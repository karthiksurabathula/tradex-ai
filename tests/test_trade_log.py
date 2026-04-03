"""Tests for the SQLite trade log."""

import os
import tempfile

import pytest

from src.execution.trade_log import TradeLog
from src.state.models import SignalType, TradeSignal


@pytest.fixture
def trade_log():
    """Create a trade log with a temporary database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    log = TradeLog(db_path=path)
    yield log
    log.close()
    os.unlink(path)


def _make_signal(symbol: str = "AAPL", action: SignalType = SignalType.BUY) -> TradeSignal:
    return TradeSignal(symbol=symbol, action=action, confidence=0.8, reasoning="test reason")


class TestTradeLog:
    def test_record_and_retrieve(self, trade_log: TradeLog):
        signal = _make_signal()
        trade_log.record(signal, price=150.0, executed=True, quantity=10)

        trades = trade_log.recent_trades("AAPL")
        assert len(trades) == 1
        assert trades[0]["symbol"] == "AAPL"
        assert trades[0]["quantity"] == 10
        assert trades[0]["executed"]

    def test_record_with_fees(self, trade_log: TradeLog):
        signal = _make_signal()
        fees = {"commission": 4.95, "spread": 3.0, "slippage": 15.0, "sec_fee": 0, "total": 22.95}
        trade_log.record(
            signal, price=150.0, executed=True, quantity=10,
            fees=fees, net_pnl=100.0, gross_pnl=122.95,
        )

        trades = trade_log.recent_trades("AAPL")
        assert trades[0]["fee_total"] == 22.95
        assert trades[0]["fee_commission"] == 4.95
        assert trades[0]["net_pnl"] == 100.0

    def test_performance_summary(self, trade_log: TradeLog):
        # Record some winning and losing trades
        for i in range(5):
            signal = _make_signal()
            trade_log.record(signal, price=100.0, executed=True, quantity=10, net_pnl=50.0)
        for i in range(3):
            signal = _make_signal(action=SignalType.SELL)
            trade_log.record(signal, price=100.0, executed=True, quantity=10, net_pnl=-30.0)

        perf = trade_log.performance_summary("AAPL")
        assert perf["total_trades"] == 8
        assert perf["wins"] == 5
        assert perf["losses"] == 3
        assert perf["win_rate"] == 5 / 8

    def test_performance_summary_empty(self, trade_log: TradeLog):
        perf = trade_log.performance_summary("AAPL")
        assert perf["total_trades"] == 0
        assert perf["win_rate"] == 0

    def test_recent_trades_all_symbols(self, trade_log: TradeLog):
        trade_log.record(_make_signal("AAPL"), 150.0, True, 10)
        trade_log.record(_make_signal("NVDA"), 200.0, True, 5)

        all_trades = trade_log.recent_trades(symbol=None)
        assert len(all_trades) == 2

    def test_non_executed_trades(self, trade_log: TradeLog):
        signal = _make_signal()
        trade_log.record(signal, price=150.0, executed=False, reason="HOLD signal")

        trades = trade_log.recent_trades("AAPL")
        assert len(trades) == 1
        assert not trades[0]["executed"]
        assert trades[0]["reason"] == "HOLD signal"
