"""OpenBB Platform provider for OHLCV data + pandas-ta for technical indicators."""

from __future__ import annotations

import logging

import pandas as pd

try:
    import pandas_ta as ta
except ImportError:
    ta = None  # type: ignore[assignment]

from openbb import obb

from src.state.models import OHLCVData, TechnicalIndicators

logger = logging.getLogger(__name__)


class OpenBBProvider:
    """Fetches market data via OpenBB, computes technicals via pandas-ta."""

    def __init__(self, provider: str = "yfinance", interval: str = "5m"):
        self.provider = provider
        self.interval = interval

    def fetch_ohlcv(self, symbol: str, start: str, end: str, interval: str = "1d") -> OHLCVData:
        """Fetch OHLCV data for an equity symbol."""
        logger.info("Fetching OHLCV for %s (%s to %s, interval=%s)", symbol, start, end, interval)
        result = obb.equity.price.historical(
            symbol=symbol,
            start_date=start,
            end_date=end,
            provider=self.provider,
            interval=interval,
        )
        df = result.to_dataframe()
        return OHLCVData.from_dataframe(symbol, df)

    def fetch_crypto(self, symbol: str, start: str, end: str, interval: str = "1d") -> OHLCVData:
        """Fetch OHLCV data for a crypto symbol (e.g., BTC-USD)."""
        logger.info("Fetching crypto OHLCV for %s (%s to %s)", symbol, start, end)
        result = obb.crypto.price.historical(
            symbol=symbol,
            start_date=start,
            end_date=end,
            provider=self.provider,
            interval=interval,
        )
        df = result.to_dataframe()
        return OHLCVData.from_dataframe(symbol, df)

    def fetch(self, symbol: str, start: str, end: str, interval: str | None = None) -> OHLCVData:
        """Auto-detect equity vs crypto and fetch accordingly."""
        ivl = interval or self.interval
        if self._is_crypto(symbol):
            return self.fetch_crypto(symbol, start, end, ivl)
        return self.fetch_ohlcv(symbol, start, end, ivl)

    def compute_technicals(self, symbol: str, df: pd.DataFrame) -> TechnicalIndicators:
        """Compute RSI, MACD, and Bollinger Bands. Uses pandas-ta or ta library."""
        logger.info("Computing technicals for %s (%d bars)", symbol, len(df))
        close = df["close"]
        current_price = float(close.iloc[-1])

        if ta is not None:
            return self._compute_with_pandas_ta(symbol, close, current_price)
        else:
            return self._compute_with_ta_lib(symbol, close, current_price)

    def _compute_with_pandas_ta(self, symbol: str, close: pd.Series, current_price: float) -> TechnicalIndicators:
        """Compute using pandas_ta (preferred)."""
        rsi_series = ta.rsi(close, length=14)
        rsi_val = float(rsi_series.iloc[-1]) if rsi_series is not None and not rsi_series.empty else 50.0

        macd_df = ta.macd(close)
        if macd_df is not None and not macd_df.empty:
            macd_signal = float(macd_df.iloc[-1, 1])
            macd_hist = float(macd_df.iloc[-1, 2])
        else:
            macd_signal, macd_hist = 0.0, 0.0

        bb_df = ta.bbands(close)
        if bb_df is not None and not bb_df.empty:
            bb_lower, bb_mid, bb_upper = float(bb_df.iloc[-1, 0]), float(bb_df.iloc[-1, 1]), float(bb_df.iloc[-1, 2])
        else:
            bb_lower, bb_mid, bb_upper = current_price * 0.98, current_price, current_price * 1.02

        return TechnicalIndicators(symbol=symbol, rsi=rsi_val, macd_signal=macd_signal,
            macd_histogram=macd_hist, bb_upper=bb_upper, bb_lower=bb_lower, bb_mid=bb_mid, current_price=current_price)

    @staticmethod
    def _compute_with_ta_lib(symbol: str, close: pd.Series, current_price: float) -> TechnicalIndicators:
        """Fallback: compute using `ta` library (available on PyPI, Docker-friendly)."""
        from ta.momentum import RSIIndicator
        from ta.trend import MACD
        from ta.volatility import BollingerBands

        rsi = RSIIndicator(close, window=14)
        rsi_val = float(rsi.rsi().iloc[-1]) if not rsi.rsi().empty else 50.0

        macd = MACD(close)
        macd_signal = float(macd.macd_signal().iloc[-1]) if not macd.macd_signal().empty else 0.0
        macd_hist = float(macd.macd_diff().iloc[-1]) if not macd.macd_diff().empty else 0.0

        bb = BollingerBands(close)
        bb_lower = float(bb.bollinger_lband().iloc[-1]) if not bb.bollinger_lband().empty else current_price * 0.98
        bb_mid = float(bb.bollinger_mavg().iloc[-1]) if not bb.bollinger_mavg().empty else current_price
        bb_upper = float(bb.bollinger_hband().iloc[-1]) if not bb.bollinger_hband().empty else current_price * 1.02

        return TechnicalIndicators(symbol=symbol, rsi=rsi_val, macd_signal=macd_signal,
            macd_histogram=macd_hist, bb_upper=bb_upper, bb_lower=bb_lower, bb_mid=bb_mid, current_price=current_price)

    @staticmethod
    def _is_crypto(symbol: str) -> bool:
        crypto_markers = ["BTC", "ETH", "SOL", "DOGE", "ADA", "XRP", "-USD"]
        return any(m in symbol.upper() for m in crypto_markers)
