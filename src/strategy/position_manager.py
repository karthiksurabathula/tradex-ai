"""Position manager — stop-loss, take-profit, trailing stops, exit logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class PositionRule:
    """Rules for managing an open position."""
    symbol: str
    entry_price: float
    entry_time: datetime
    stop_loss_pct: float = 0.02       # 2% stop-loss
    take_profit_pct: float = 0.04     # 4% take-profit (2:1 reward/risk)
    trailing_stop_pct: float = 0.015  # 1.5% trailing stop
    max_hold_minutes: int = 180       # Force exit after 3 hours
    high_water_mark: float = 0.0      # Track highest price for trailing stop

    def __post_init__(self):
        self.high_water_mark = self.entry_price

    @property
    def stop_loss_price(self) -> float:
        return self.entry_price * (1 - self.stop_loss_pct)

    @property
    def take_profit_price(self) -> float:
        return self.entry_price * (1 + self.take_profit_pct)

    @property
    def trailing_stop_price(self) -> float:
        return self.high_water_mark * (1 - self.trailing_stop_pct)


@dataclass
class ExitSignal:
    symbol: str
    reason: str
    urgency: str  # "immediate", "normal"
    current_price: float
    pnl_pct: float


class PositionManager:
    """Monitors open positions and generates exit signals."""

    def __init__(
        self,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.04,
        trailing_stop_pct: float = 0.015,
        max_hold_minutes: int = 180,
    ):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.max_hold_minutes = max_hold_minutes
        self.rules: dict[str, PositionRule] = {}

    def register_entry(self, symbol: str, price: float):
        """Register a new position for monitoring."""
        self.rules[symbol] = PositionRule(
            symbol=symbol,
            entry_price=price,
            entry_time=datetime.now(UTC),
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
            trailing_stop_pct=self.trailing_stop_pct,
            max_hold_minutes=self.max_hold_minutes,
        )
        logger.info(
            "Registered %s @ $%.2f — SL: $%.2f, TP: $%.2f",
            symbol, price,
            self.rules[symbol].stop_loss_price,
            self.rules[symbol].take_profit_price,
        )

    def remove(self, symbol: str):
        self.rules.pop(symbol, None)

    def check_exits(self, prices: dict[str, float]) -> list[ExitSignal]:
        """Check all positions for exit conditions. Returns signals for positions to close."""
        exits = []

        for symbol, rule in list(self.rules.items()):
            price = prices.get(symbol)
            if price is None:
                continue

            # Update high water mark
            if price > rule.high_water_mark:
                rule.high_water_mark = price

            pnl_pct = (price - rule.entry_price) / rule.entry_price
            minutes_held = (datetime.now(UTC) - rule.entry_time).total_seconds() / 60

            # Check exit conditions (priority order)
            if price <= rule.stop_loss_price:
                exits.append(ExitSignal(
                    symbol=symbol,
                    reason=f"STOP-LOSS hit at ${price:.2f} ({pnl_pct:+.1%})",
                    urgency="immediate",
                    current_price=price,
                    pnl_pct=pnl_pct,
                ))

            elif price >= rule.take_profit_price:
                exits.append(ExitSignal(
                    symbol=symbol,
                    reason=f"TAKE-PROFIT hit at ${price:.2f} ({pnl_pct:+.1%})",
                    urgency="immediate",
                    current_price=price,
                    pnl_pct=pnl_pct,
                ))

            elif price <= rule.trailing_stop_price and pnl_pct > 0:
                exits.append(ExitSignal(
                    symbol=symbol,
                    reason=f"TRAILING-STOP at ${price:.2f} (high: ${rule.high_water_mark:.2f}, {pnl_pct:+.1%})",
                    urgency="immediate",
                    current_price=price,
                    pnl_pct=pnl_pct,
                ))

            elif minutes_held >= rule.max_hold_minutes:
                exits.append(ExitSignal(
                    symbol=symbol,
                    reason=f"MAX-HOLD {minutes_held:.0f}min exceeded ({pnl_pct:+.1%})",
                    urgency="normal",
                    current_price=price,
                    pnl_pct=pnl_pct,
                ))

        return exits

    def status(self) -> list[dict]:
        """Current status of all monitored positions."""
        return [
            {
                "symbol": r.symbol,
                "entry": r.entry_price,
                "stop_loss": round(r.stop_loss_price, 2),
                "take_profit": round(r.take_profit_price, 2),
                "trailing_stop": round(r.trailing_stop_price, 2),
                "high_water": round(r.high_water_mark, 2),
                "minutes_held": (datetime.now(UTC) - r.entry_time).total_seconds() / 60,
            }
            for r in self.rules.values()
        ]
