"""Tests for the performance metrics module."""

from src.feedback.metrics import compute_metrics


class TestMetrics:
    def test_empty_trades(self):
        result = compute_metrics([])
        assert result["total_trades"] == 0
        assert result["sharpe_ratio"] == 0.0

    def test_all_winners(self):
        trades = [
            {"executed": True, "net_pnl": 100.0},
            {"executed": True, "net_pnl": 50.0},
            {"executed": True, "net_pnl": 75.0},
        ]
        result = compute_metrics(trades)
        assert result["total_trades"] == 3
        assert result["avg_win"] > 0
        assert result["avg_loss"] == 0
        assert result["max_consecutive_losses"] == 0
        assert result["max_drawdown"] == 0.0

    def test_all_losers(self):
        trades = [
            {"executed": True, "net_pnl": -50.0},
            {"executed": True, "net_pnl": -30.0},
            {"executed": True, "net_pnl": -20.0},
        ]
        result = compute_metrics(trades)
        assert result["avg_loss"] < 0
        assert result["avg_win"] == 0
        assert result["max_consecutive_losses"] == 3

    def test_mixed_trades(self):
        trades = [
            {"executed": True, "net_pnl": 100.0},
            {"executed": True, "net_pnl": -50.0},
            {"executed": True, "net_pnl": 80.0},
            {"executed": True, "net_pnl": -30.0},
            {"executed": True, "net_pnl": -20.0},
        ]
        result = compute_metrics(trades)
        assert result["total_trades"] == 5
        assert result["profit_factor"] > 0
        assert result["max_consecutive_losses"] == 2
        assert result["max_drawdown"] > 0

    def test_sharpe_ratio(self):
        # Consistent positive returns → high Sharpe
        trades = [{"executed": True, "net_pnl": 10.0} for _ in range(20)]
        result = compute_metrics(trades)
        # All same returns → std = 0 → sharpe = 0 (degenerate case)
        # Let's test with some variance
        trades2 = [
            {"executed": True, "net_pnl": 10.0 + (i % 3) * 5} for i in range(20)
        ]
        result2 = compute_metrics(trades2)
        assert result2["sharpe_ratio"] > 0

    def test_non_executed_trades_excluded(self):
        trades = [
            {"executed": True, "net_pnl": 100.0},
            {"executed": False, "net_pnl": None},
            {"executed": True, "net_pnl": -50.0},
        ]
        result = compute_metrics(trades)
        assert result["total_trades"] == 2
