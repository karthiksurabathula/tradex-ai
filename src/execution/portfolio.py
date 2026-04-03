"""Paper portfolio with position management and fee-aware PnL tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.execution.fees import FeeModel


@dataclass
class Position:
    symbol: str
    quantity: int
    avg_cost: float
    entry_fees: float = 0.0
    opened_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    is_short: bool = False

    def unrealized_pnl(self, current_price: float) -> float:
        """Unrealized PnL based on effective cost basis (includes entry fees)."""
        if self.is_short:
            return (self.avg_cost - current_price) * self.quantity
        return (current_price - self.avg_cost) * self.quantity

    def market_value(self, current_price: float) -> float:
        if self.is_short:
            # Short position value: margin posted minus unrealized loss/gain
            return self.avg_cost * self.quantity + self.unrealized_pnl(current_price)
        return current_price * self.quantity


@dataclass
class Portfolio:
    cash: float = 100_000.0
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    total_fees_paid: float = 0.0
    fee_model: FeeModel = field(default_factory=FeeModel)

    def buy(self, symbol: str, quantity: int, price: float) -> dict | None:
        """Execute a paper buy. Returns fee breakdown or None if insufficient cash."""
        if quantity <= 0:
            return None

        fees = self.fee_model.calculate("BUY", symbol, quantity, price)
        total_cost = (quantity * price) + fees["total"]

        if total_cost > self.cash:
            return None

        self.cash -= total_cost
        self.total_fees_paid += fees["total"]

        effective_price = fees["effective_price"]

        if symbol in self.positions:
            pos = self.positions[symbol]
            total_qty = pos.quantity + quantity
            pos.avg_cost = (
                (pos.avg_cost * pos.quantity) + (effective_price * quantity)
            ) / total_qty
            pos.entry_fees += fees["total"]
            pos.quantity = total_qty
        else:
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                avg_cost=effective_price,
                entry_fees=fees["total"],
            )

        return fees

    def sell(self, symbol: str, quantity: int, price: float) -> dict | None:
        """Execute a paper sell. Returns PnL breakdown or None if insufficient position."""
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        if pos.quantity < quantity or quantity <= 0:
            return None

        fees = self.fee_model.calculate("SELL", symbol, quantity, price)
        proceeds = (quantity * price) - fees["total"]
        gross_pnl = (price - pos.avg_cost) * quantity
        net_pnl = gross_pnl - fees["total"]

        self.realized_pnl += net_pnl
        self.cash += proceeds
        self.total_fees_paid += fees["total"]

        pos.quantity -= quantity
        if pos.quantity == 0:
            del self.positions[symbol]

        return {
            "net_pnl": round(net_pnl, 4),
            "gross_pnl": round(gross_pnl, 4),
            "fees": fees,
            "proceeds": round(proceeds, 4),
        }

    def short(self, symbol: str, quantity: int, price: float) -> dict | None:
        """Open a short position. Returns fee breakdown or None on failure."""
        if quantity <= 0:
            return None

        fees = self.fee_model.calculate("SELL", symbol, quantity, price)
        # Shorting: receive proceeds minus fees, but must post margin (cash as collateral)
        margin_required = quantity * price  # 100% margin for paper trading
        if margin_required + fees["total"] > self.cash:
            return None

        self.cash -= fees["total"]  # Only deduct fees; margin stays as collateral
        self.total_fees_paid += fees["total"]

        if symbol in self.positions and self.positions[symbol].is_short:
            pos = self.positions[symbol]
            total_qty = pos.quantity + quantity
            pos.avg_cost = (
                (pos.avg_cost * pos.quantity) + (price * quantity)
            ) / total_qty
            pos.entry_fees += fees["total"]
            pos.quantity = total_qty
        else:
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                avg_cost=price,
                entry_fees=fees["total"],
                is_short=True,
            )

        return fees

    def cover(self, symbol: str, quantity: int, price: float) -> dict | None:
        """Close a short position (cover). Returns PnL breakdown or None."""
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        if not pos.is_short or pos.quantity < quantity or quantity <= 0:
            return None

        fees = self.fee_model.calculate("BUY", symbol, quantity, price)
        # Short P&L = (entry_price - exit_price) * quantity - fees
        gross_pnl = (pos.avg_cost - price) * quantity
        net_pnl = gross_pnl - fees["total"]

        self.realized_pnl += net_pnl
        self.cash += net_pnl  # Return P&L (can be negative)
        self.total_fees_paid += fees["total"]

        pos.quantity -= quantity
        if pos.quantity == 0:
            del self.positions[symbol]

        return {
            "net_pnl": round(net_pnl, 4),
            "gross_pnl": round(gross_pnl, 4),
            "fees": fees,
        }

    def total_value(self, prices: dict[str, float]) -> float:
        """Total portfolio value = cash + long positions + short position P&L."""
        position_value = 0.0
        for pos in self.positions.values():
            current_price = prices.get(pos.symbol, pos.avg_cost)
            if pos.is_short:
                # Short position contributes its unrealized P&L
                position_value += pos.unrealized_pnl(current_price)
            else:
                position_value += pos.market_value(current_price)
        return self.cash + position_value

    def total_unrealized_pnl(self, prices: dict[str, float]) -> float:
        return sum(
            pos.unrealized_pnl(prices.get(pos.symbol, pos.avg_cost))
            for pos in self.positions.values()
        )

    def summary(self, prices: dict[str, float]) -> dict:
        """Full portfolio summary for display."""
        long_count = sum(1 for p in self.positions.values() if not p.is_short)
        short_count = sum(1 for p in self.positions.values() if p.is_short)
        return {
            "cash": round(self.cash, 2),
            "positions": len(self.positions),
            "long_positions": long_count,
            "short_positions": short_count,
            "total_value": round(self.total_value(prices), 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(self.total_unrealized_pnl(prices), 2),
            "total_fees_paid": round(self.total_fees_paid, 2),
        }
