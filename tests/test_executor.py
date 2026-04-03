"""Tests for the trade executor."""

import os
import tempfile

import pytest

from src.execution.executor import Executor
from src.execution.fees import FeeModel
from src.execution.portfolio import Portfolio
from src.execution.trade_log import TradeLog
from src.state.models import SignalType, TradeSignal


@pytest.fixture
def components():
    """Create executor with portfolio and temp trade log."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    portfolio = Portfolio(cash=100_000.0, fee_model=FeeModel())
    trade_log = TradeLog(db_path=path)
    executor = Executor(portfolio, trade_log, max_position_pct=0.10, min_confidence=0.60)
    yield {"executor": executor, "portfolio": portfolio, "log": trade_log, "db_path": path}
    trade_log.close()
    os.unlink(path)


def _make_signal(
    symbol: str = "AAPL",
    action: SignalType = SignalType.BUY,
    confidence: float = 0.8,
) -> TradeSignal:
    return TradeSignal(symbol=symbol, action=action, confidence=confidence, reasoning="test")


class TestExecutor:
    def test_hold_not_executed(self, components):
        signal = _make_signal(action=SignalType.HOLD)
        result = components["executor"].execute(signal, 150.0)
        assert not result["executed"]
        assert result["action"] == "HOLD"

    def test_low_confidence_rejected(self, components):
        signal = _make_signal(confidence=0.3)  # Below 0.60 threshold
        result = components["executor"].execute(signal, 150.0)
        assert not result["executed"]
        assert result["reason"] == "low confidence"

    def test_buy_executed(self, components):
        signal = _make_signal(action=SignalType.BUY, confidence=0.8)
        result = components["executor"].execute(signal, 150.0)
        assert result["executed"]
        assert result["action"] == "BUY"
        assert result["quantity"] > 0
        assert "fees" in result

    def test_buy_tracked_in_portfolio(self, components):
        signal = _make_signal(action=SignalType.BUY, confidence=0.8)
        components["executor"].execute(signal, 150.0)
        assert "AAPL" in components["portfolio"].positions

    def test_sell_with_no_position(self, components):
        signal = _make_signal(action=SignalType.SELL, confidence=0.8)
        result = components["executor"].execute(signal, 150.0)
        assert not result["executed"]

    def test_sell_after_buy(self, components):
        buy = _make_signal(action=SignalType.BUY, confidence=0.8)
        components["executor"].execute(buy, 150.0)

        sell = _make_signal(action=SignalType.SELL, confidence=0.8)
        result = components["executor"].execute(sell, 160.0)
        assert result["executed"]
        assert "net_pnl" in result

    def test_trades_logged(self, components):
        signal = _make_signal(action=SignalType.BUY, confidence=0.8)
        components["executor"].execute(signal, 150.0)

        trades = components["log"].recent_trades("AAPL")
        assert len(trades) == 1
        assert trades[0]["executed"]
