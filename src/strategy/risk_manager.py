"""Risk Manager — circuit breakers, daily limits, kill switch, rate limiting.

Independent safety layer that can halt trading regardless of strategy signals.
"""

from __future__ import annotations

import logging
import time
import threading
from datetime import UTC, datetime
from pathlib import Path

import yfinance as yf

logger = logging.getLogger(__name__)

KILL_SWITCH_FILE = Path("data/.kill_switch")


class RiskManager:
    """Portfolio-level risk controls and circuit breakers."""

    def __init__(
        self,
        daily_loss_limit_pct: float = 0.015,    # Halt after -1.5% daily loss
        max_drawdown_pct: float = 0.05,          # Emergency exit at -5% drawdown
        max_trades_per_day: int = 50,             # Prevent overtrading
        cooldown_after_loss_min: int = 30,        # Wait 30min after big loss
        max_sector_pct: float = 0.30,             # Max 30% in any sector
    ):
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_trades_per_day = max_trades_per_day
        self.cooldown_after_loss_min = cooldown_after_loss_min
        self.max_sector_pct = max_sector_pct

        self._daily_starting_value: float | None = None
        self._trades_today: int = 0
        self._last_big_loss_time: datetime | None = None
        self._halted: bool = False
        self._halt_reason: str = ""
        self._day: str = ""

        # PDT tracking: list of (symbol, action, timestamp) for round-trip detection
        self._trade_history: list[tuple[str, str, datetime]] = []

    def reset_daily(self, portfolio_value: float):
        """Call at start of each trading day."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if self._day != today:
            self._daily_starting_value = portfolio_value
            self._trades_today = 0
            self._halted = False
            self._halt_reason = ""
            self._day = today
            logger.info("Risk manager reset for %s. Starting value: $%.2f", today, portfolio_value)

    def record_trade(self):
        self._trades_today += 1

    def record_loss(self, loss_pct: float):
        """Record a significant loss for cooldown tracking."""
        if loss_pct < -0.02:  # Loss > 2%
            self._last_big_loss_time = datetime.now(UTC)
            logger.warning("Big loss recorded: %.1f%%. Cooldown started.", loss_pct * 100)

    # ── Checks ───────────────────────────────────────────────────────────────

    def can_trade(self, portfolio_value: float) -> tuple[bool, str]:
        """Check all risk conditions. Returns (allowed, reason)."""
        # Kill switch file
        if KILL_SWITCH_FILE.exists():
            return False, "KILL SWITCH ACTIVE (delete data/.kill_switch to resume)"

        if self._halted:
            return False, f"HALTED: {self._halt_reason}"

        # Daily loss limit
        if self._daily_starting_value and self._daily_starting_value > 0:
            daily_return = (portfolio_value - self._daily_starting_value) / self._daily_starting_value
            if daily_return < -self.daily_loss_limit_pct:
                self._halted = True
                self._halt_reason = f"Daily loss limit hit ({daily_return:.1%} < -{self.daily_loss_limit_pct:.1%})"
                return False, self._halt_reason

        # Max drawdown
        if self._daily_starting_value and self._daily_starting_value > 0:
            drawdown = (portfolio_value - self._daily_starting_value) / self._daily_starting_value
            if drawdown < -self.max_drawdown_pct:
                self._halted = True
                self._halt_reason = f"Max drawdown hit ({drawdown:.1%})"
                return False, self._halt_reason

        # Trade count limit
        if self._trades_today >= self.max_trades_per_day:
            return False, f"Max trades/day reached ({self._trades_today}/{self.max_trades_per_day})"

        # Cooldown after big loss
        if self._last_big_loss_time:
            elapsed = (datetime.now(UTC) - self._last_big_loss_time).total_seconds() / 60
            if elapsed < self.cooldown_after_loss_min:
                return False, f"Cooldown active ({self.cooldown_after_loss_min - elapsed:.0f}min remaining)"

        return True, "OK"

    def check_sector_exposure(self, new_symbol: str, positions: dict, prices: dict, portfolio_value: float) -> tuple[bool, str]:
        """Check if adding new_symbol would exceed sector concentration limits."""
        sector_map = self._get_sectors([new_symbol] + list(positions.keys()))
        new_sector = sector_map.get(new_symbol, "Unknown")

        # Calculate current sector exposure
        sector_values: dict[str, float] = {}
        for sym, pos in positions.items():
            sector = sector_map.get(sym, "Unknown")
            price = prices.get(sym, pos.avg_cost)
            sector_values[sector] = sector_values.get(sector, 0) + (pos.quantity * price)

        current_exposure = sector_values.get(new_sector, 0)
        exposure_pct = current_exposure / portfolio_value if portfolio_value > 0 else 0

        if exposure_pct >= self.max_sector_pct:
            return False, f"Sector '{new_sector}' already at {exposure_pct:.0%} (max {self.max_sector_pct:.0%})"

        return True, "OK"

    def check_correlation(self, new_symbol: str, existing_symbols: list[str], threshold: float = 0.7) -> tuple[bool, str]:
        """Check if new symbol is too correlated with existing positions."""
        if not existing_symbols:
            return True, "OK"

        try:
            all_syms = [new_symbol] + existing_symbols[:5]  # Limit to avoid slow fetches
            data = {}
            for sym in all_syms:
                hist = yf.Ticker(sym).history(period="1mo", interval="1d")
                if not hist.empty:
                    data[sym] = hist["Close"].pct_change().dropna()

            if new_symbol not in data:
                return True, "OK"

            import pandas as pd
            df = pd.DataFrame(data).dropna()
            if df.empty or len(df) < 10:
                return True, "OK"

            for sym in existing_symbols:
                if sym in df.columns:
                    corr = df[new_symbol].corr(df[sym])
                    if abs(corr) > threshold:
                        return False, f"High correlation with {sym}: {corr:.2f} (threshold: {threshold})"

        except Exception as e:
            logger.warning("Correlation check failed: %s", e)

        return True, "OK"

    # ── PDT Rule Tracking ─────────────────────────────────────────────────────

    def record_trade_for_pdt(self, symbol: str, action: str):
        """Record a trade for PDT tracking. Call after every buy/sell execution."""
        self._trade_history.append((symbol, action.upper(), datetime.now(UTC)))

    def _count_day_trades(self, window_days: int = 5) -> int:
        """Count round-trip day trades in the rolling window.

        A round trip = buy + sell of the same symbol on the same calendar day.
        """
        from collections import defaultdict
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=window_days)
        recent = [(s, a, t) for s, a, t in self._trade_history if t >= cutoff]

        # Group by (symbol, date)
        day_trades: dict[tuple[str, str], list[str]] = defaultdict(list)
        for symbol, action, ts in recent:
            day_key = (symbol, ts.strftime("%Y-%m-%d"))
            day_trades[day_key].append(action)

        # Count round trips: a day with both BUY and SELL for same symbol
        count = 0
        for key, actions in day_trades.items():
            buys = sum(1 for a in actions if a == "BUY")
            sells = sum(1 for a in actions if a == "SELL")
            count += min(buys, sells)

        return count

    def check_pdt(self, symbol: str, portfolio_value: float) -> tuple[bool, str]:
        """Check Pattern Day Trader rule compliance.

        If account < $25,000 and approaching 3 day trades in 5 days, warn/block.

        Returns:
            (allowed, reason) — True if the trade is allowed.
        """
        if portfolio_value >= 25_000:
            return True, "Account >= $25,000; PDT rule does not apply"

        day_trade_count = self._count_day_trades()

        if day_trade_count >= 3:
            return False, (
                f"PDT BLOCKED: {day_trade_count} day trades in 5 days "
                f"(account ${portfolio_value:,.2f} < $25,000)"
            )

        if day_trade_count == 2:
            return True, (
                f"PDT WARNING: {day_trade_count}/3 day trades used. "
                f"Next round-trip will trigger PDT restriction."
            )

        return True, f"PDT OK: {day_trade_count}/3 day trades in rolling 5 days"

    # ── Kill Switch ──────────────────────────────────────────────────────────

    @staticmethod
    def activate_kill_switch(reason: str = "Manual halt"):
        KILL_SWITCH_FILE.write_text(f"{reason}\n{datetime.now(UTC).isoformat()}")
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

    @staticmethod
    def deactivate_kill_switch():
        if KILL_SWITCH_FILE.exists():
            KILL_SWITCH_FILE.unlink()
            logger.info("Kill switch deactivated.")

    @staticmethod
    def is_kill_switch_active() -> bool:
        return KILL_SWITCH_FILE.exists()

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _get_sectors(symbols: list[str]) -> dict[str, str]:
        """Get sector for each symbol. Cached and best-effort."""
        sector_map = {}
        for sym in symbols:
            try:
                info = yf.Ticker(sym).info
                sector_map[sym] = info.get("sector", "Unknown")
            except Exception:
                sector_map[sym] = "Unknown"
        return sector_map

    @property
    def status(self) -> dict:
        return {
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "kill_switch": self.is_kill_switch_active(),
            "trades_today": self._trades_today,
            "daily_starting_value": self._daily_starting_value,
            "day": self._day,
        }


class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, calls_per_second: float = 2.0):
        self._min_interval = 1.0 / calls_per_second
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self):
        """Block until rate limit allows next call."""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.time()


# Global rate limiter for yfinance
yf_rate_limiter = RateLimiter(calls_per_second=2.0)
