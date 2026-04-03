"""Maps trade signals to paper portfolio operations."""

from __future__ import annotations

import logging

from src.execution.portfolio import Portfolio
from src.execution.trade_log import TradeLog
from src.state.models import SignalType, TradeSignal

logger = logging.getLogger(__name__)


class Executor:
    """Executes trade signals against the paper portfolio with position sizing."""

    def __init__(
        self,
        portfolio: Portfolio,
        trade_log: TradeLog,
        max_position_pct: float = 0.10,
        min_confidence: float = 0.60,
    ):
        self.portfolio = portfolio
        self.log = trade_log
        self.max_position_pct = max_position_pct
        self.min_confidence = min_confidence

    def execute(self, signal: TradeSignal, current_price: float) -> dict:
        """Execute a trade signal. Returns execution result dict."""
        if signal.action == SignalType.HOLD:
            self.log.record(signal, current_price, executed=False, reason="HOLD signal")
            return {"action": "HOLD", "executed": False}

        if signal.confidence < self.min_confidence:
            self.log.record(
                signal,
                current_price,
                executed=False,
                reason=f"Confidence {signal.confidence:.2f} below threshold {self.min_confidence}",
            )
            return {
                "action": signal.action.value,
                "executed": False,
                "reason": "low confidence",
            }

        # Position sizing: allocate based on confidence within max position limit
        portfolio_value = self._estimate_portfolio_value(current_price)
        max_allocation = portfolio_value * self.max_position_pct
        quantity = int((max_allocation * signal.confidence) / current_price)

        if quantity == 0:
            self.log.record(signal, current_price, executed=False, reason="quantity=0")
            return {
                "action": signal.action.value,
                "executed": False,
                "reason": "insufficient size",
            }

        if signal.action == SignalType.BUY:
            return self._execute_buy(signal, quantity, current_price)
        elif signal.action == SignalType.SELL:
            return self._execute_sell(signal, quantity, current_price)

        return {"action": signal.action.value, "executed": False}

    def _execute_buy(self, signal: TradeSignal, quantity: int, price: float) -> dict:
        fees = self.portfolio.buy(signal.symbol, quantity, price)
        if fees is None:
            self.log.record(signal, price, executed=False, reason="insufficient cash")
            return {"action": "BUY", "executed": False, "reason": "insufficient cash"}

        self.log.record(
            signal,
            price,
            executed=True,
            quantity=quantity,
            fees=fees,
        )
        logger.info("BUY %d %s @ $%.2f (fees: $%.2f)", quantity, signal.symbol, price, fees["total"])
        return {
            "action": "BUY",
            "executed": True,
            "quantity": quantity,
            "price": price,
            "fees": fees,
        }

    def _execute_sell(self, signal: TradeSignal, quantity: int, price: float) -> dict:
        # Adjust quantity to available position
        pos = self.portfolio.positions.get(signal.symbol)
        if pos is None:
            self.log.record(signal, price, executed=False, reason="no position to sell")
            return {"action": "SELL", "executed": False, "reason": "no position"}

        sell_qty = min(quantity, pos.quantity)
        result = self.portfolio.sell(signal.symbol, sell_qty, price)
        if result is None:
            self.log.record(signal, price, executed=False, reason="sell failed")
            return {"action": "SELL", "executed": False, "reason": "sell failed"}

        self.log.record(
            signal,
            price,
            executed=True,
            quantity=sell_qty,
            gross_pnl=result["gross_pnl"],
            net_pnl=result["net_pnl"],
            fees=result["fees"],
        )
        logger.info(
            "SELL %d %s @ $%.2f (net P&L: $%.2f, fees: $%.2f)",
            sell_qty, signal.symbol, price, result["net_pnl"], result["fees"]["total"],
        )
        return {
            "action": "SELL",
            "executed": True,
            "quantity": sell_qty,
            "price": price,
            "net_pnl": result["net_pnl"],
            "gross_pnl": result["gross_pnl"],
            "fees": result["fees"],
        }

    def _estimate_portfolio_value(self, fallback_price: float) -> float:
        """Rough portfolio value estimate for position sizing."""
        position_value = sum(
            p.quantity * fallback_price for p in self.portfolio.positions.values()
        )
        return self.portfolio.cash + position_value
