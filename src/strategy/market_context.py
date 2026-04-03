"""Market context — regime detection, earnings calendar, VIX, macro signals.

Provides the big-picture context that strategies need to adapt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class MarketRegime(str, Enum):
    BULL = "BULL"           # Low vol, trending up
    BEAR = "BEAR"           # High vol, trending down
    VOLATILE = "VOLATILE"   # High vol, no clear direction
    SIDEWAYS = "SIDEWAYS"   # Low vol, no trend


@dataclass
class MarketContext:
    """Snapshot of current market conditions."""
    regime: MarketRegime
    vix: float
    spy_change_pct: float
    dxy_change_pct: float     # Dollar index
    tlt_change_pct: float     # Bond proxy (20yr treasury)
    regime_confidence: float
    timestamp: datetime

    @property
    def is_defensive(self) -> bool:
        return self.regime in (MarketRegime.BEAR, MarketRegime.VOLATILE)

    @property
    def position_size_multiplier(self) -> float:
        """Reduce position sizes in volatile/bear regimes."""
        if self.regime == MarketRegime.BULL:
            return 1.0
        elif self.regime == MarketRegime.SIDEWAYS:
            return 0.8
        elif self.regime == MarketRegime.VOLATILE:
            return 0.5
        else:  # BEAR
            return 0.3

    @property
    def stop_loss_multiplier(self) -> float:
        """Widen stops in volatile markets, tighten in calm."""
        if self.vix > 30:
            return 2.0
        elif self.vix > 20:
            return 1.5
        elif self.vix > 15:
            return 1.0
        return 0.8


class MarketContextProvider:
    """Fetches and classifies current market regime."""

    def get_context(self) -> MarketContext:
        """Get current market context including regime classification."""
        vix = self._get_vix()
        spy = self._get_change("SPY")
        dxy = self._get_change("UUP")   # Dollar bull ETF as DXY proxy
        tlt = self._get_change("TLT")   # 20yr treasury bond ETF

        regime = self._classify_regime(vix, spy)

        return MarketContext(
            regime=regime,
            vix=vix,
            spy_change_pct=spy,
            dxy_change_pct=dxy,
            tlt_change_pct=tlt,
            regime_confidence=self._regime_confidence(vix, spy),
            timestamp=datetime.now(UTC),
        )

    def _classify_regime(self, vix: float, spy_change: float) -> MarketRegime:
        """Simple but effective regime classification."""
        if vix > 25 and spy_change < -1:
            return MarketRegime.BEAR
        elif vix > 25:
            return MarketRegime.VOLATILE
        elif spy_change > 0.5:
            return MarketRegime.BULL
        elif abs(spy_change) < 0.3:
            return MarketRegime.SIDEWAYS
        elif spy_change < -0.5:
            return MarketRegime.BEAR
        return MarketRegime.SIDEWAYS

    def _regime_confidence(self, vix: float, spy_change: float) -> float:
        """How confident are we in the regime classification?"""
        # Strong signals = high confidence
        if vix > 30 or abs(spy_change) > 2:
            return 0.9
        elif vix > 20 or abs(spy_change) > 1:
            return 0.7
        return 0.5

    def _get_vix(self) -> float:
        try:
            hist = yf.Ticker("^VIX").history(period="2d", interval="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return 20.0  # Default neutral

    def _get_change(self, symbol: str) -> float:
        try:
            hist = yf.Ticker(symbol).history(period="5d", interval="1d")
            if len(hist) >= 2:
                return ((hist["Close"].iloc[-1] / hist["Close"].iloc[-2]) - 1) * 100
        except Exception:
            pass
        return 0.0


class EarningsCalendar:
    """Check if a symbol has earnings coming up."""

    def has_upcoming_earnings(self, symbol: str, days_ahead: int = 3) -> tuple[bool, str]:
        """Check if symbol has earnings within N days."""
        try:
            ticker = yf.Ticker(symbol)
            cal = ticker.calendar
            if cal is None or (isinstance(cal, pd.DataFrame) and cal.empty):
                return False, ""

            # yfinance calendar can be a dict or DataFrame
            if isinstance(cal, dict):
                earn_date = cal.get("Earnings Date")
                if earn_date:
                    if isinstance(earn_date, list):
                        earn_date = earn_date[0]
                    if hasattr(earn_date, 'date'):
                        days_until = (earn_date.date() - datetime.now(UTC).date()).days
                    else:
                        return False, ""
                    if 0 <= days_until <= days_ahead:
                        return True, f"Earnings in {days_until} day(s)"
            elif isinstance(cal, pd.DataFrame):
                if "Earnings Date" in cal.index:
                    dates = cal.loc["Earnings Date"]
                    for d in (dates if hasattr(dates, '__iter__') else [dates]):
                        if hasattr(d, 'date'):
                            days_until = (d.date() - datetime.now(UTC).date()).days
                            if 0 <= days_until <= days_ahead:
                                return True, f"Earnings in {days_until} day(s)"
        except Exception as e:
            logger.debug("Earnings check failed for %s: %s", symbol, e)

        return False, ""


class VolatilityAdjuster:
    """Adjust position sizing and stops based on per-stock volatility (ATR)."""

    def get_atr(self, symbol: str, period: int = 14) -> float:
        """Get Average True Range for a symbol."""
        try:
            hist = yf.Ticker(symbol).history(period="1mo", interval="1d")
            if len(hist) < period + 1:
                return 0.0
            # Try pandas_ta first, then ta library
            try:
                import pandas_ta as pta
                atr = pta.atr(hist["High"], hist["Low"], hist["Close"], length=period)
            except ImportError:
                from ta.volatility import AverageTrueRange
                atr_ind = AverageTrueRange(hist["High"], hist["Low"], hist["Close"], window=period)
                atr = atr_ind.average_true_range()
            if atr is not None and not atr.empty:
                return float(atr.iloc[-1])
        except Exception:
            pass
        return 0.0

    def adjusted_stop_loss(self, symbol: str, entry_price: float, base_pct: float = 0.02, atr_multiplier: float = 1.5) -> float:
        """Calculate volatility-adjusted stop-loss price."""
        atr = self.get_atr(symbol)
        if atr > 0:
            atr_stop = entry_price - (atr * atr_multiplier)
            pct_stop = entry_price * (1 - base_pct)
            # Use the wider of ATR-based and fixed-pct stop
            return min(atr_stop, pct_stop)
        return entry_price * (1 - base_pct)

    def adjusted_quantity(self, symbol: str, price: float, risk_amount: float) -> int:
        """Position size based on risk amount / ATR (risk per share)."""
        atr = self.get_atr(symbol)
        if atr > 0 and atr < price:
            # Risk $risk_amount per trade, ATR defines risk per share
            qty = int(risk_amount / (atr * 1.5))
            return max(1, qty)
        # Fallback: risk_amount / price
        return max(1, int(risk_amount / price))
