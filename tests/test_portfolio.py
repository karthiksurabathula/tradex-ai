"""Tests for the portfolio and position management with fee integration."""

from src.execution.fees import FeeModel
from src.execution.portfolio import Portfolio, Position


class TestPosition:
    def test_unrealized_pnl_profit(self):
        pos = Position(symbol="AAPL", quantity=10, avg_cost=150.0)
        assert pos.unrealized_pnl(160.0) == 100.0

    def test_unrealized_pnl_loss(self):
        pos = Position(symbol="AAPL", quantity=10, avg_cost=150.0)
        assert pos.unrealized_pnl(140.0) == -100.0

    def test_market_value(self):
        pos = Position(symbol="AAPL", quantity=10, avg_cost=150.0)
        assert pos.market_value(160.0) == 1600.0


class TestPortfolio:
    def _make_portfolio(self, cash: float = 100_000.0) -> Portfolio:
        return Portfolio(cash=cash, fee_model=FeeModel())

    def test_buy_deducts_cash_and_fees(self):
        p = self._make_portfolio()
        initial_cash = p.cash
        fees = p.buy("AAPL", 10, 150.0)

        assert fees is not None
        assert p.cash < initial_cash
        # Cash reduced by notional + fees
        expected_cost = (10 * 150.0) + fees["total"]
        assert abs(p.cash - (initial_cash - expected_cost)) < 0.01

    def test_buy_creates_position(self):
        p = self._make_portfolio()
        p.buy("AAPL", 10, 150.0)

        assert "AAPL" in p.positions
        assert p.positions["AAPL"].quantity == 10
        assert p.positions["AAPL"].avg_cost > 150.0  # Includes fees

    def test_buy_insufficient_cash(self):
        p = self._make_portfolio(cash=100.0)
        result = p.buy("AAPL", 10, 150.0)  # Costs $1500+fees
        assert result is None
        assert len(p.positions) == 0

    def test_buy_adds_to_existing_position(self):
        p = self._make_portfolio()
        p.buy("AAPL", 10, 150.0)
        p.buy("AAPL", 5, 160.0)

        assert p.positions["AAPL"].quantity == 15

    def test_sell_returns_pnl_breakdown(self):
        p = self._make_portfolio()
        p.buy("AAPL", 10, 100.0)

        result = p.sell("AAPL", 10, 120.0)
        assert result is not None
        assert "net_pnl" in result
        assert "gross_pnl" in result
        assert "fees" in result
        # Gross PnL should be positive (bought at ~100, sold at 120)
        assert result["gross_pnl"] > 0
        # Net PnL accounts for sell fees
        assert result["net_pnl"] < result["gross_pnl"]

    def test_sell_insufficient_quantity(self):
        p = self._make_portfolio()
        p.buy("AAPL", 10, 100.0)
        result = p.sell("AAPL", 20, 120.0)
        assert result is None

    def test_sell_no_position(self):
        p = self._make_portfolio()
        result = p.sell("AAPL", 10, 120.0)
        assert result is None

    def test_sell_removes_empty_position(self):
        p = self._make_portfolio()
        p.buy("AAPL", 10, 100.0)
        p.sell("AAPL", 10, 120.0)
        assert "AAPL" not in p.positions

    def test_sell_partial(self):
        p = self._make_portfolio()
        p.buy("AAPL", 10, 100.0)
        p.sell("AAPL", 5, 120.0)
        assert p.positions["AAPL"].quantity == 5

    def test_total_fees_tracked(self):
        p = self._make_portfolio()
        p.buy("AAPL", 10, 100.0)
        p.sell("AAPL", 10, 120.0)
        assert p.total_fees_paid > 0

    def test_total_value(self):
        p = self._make_portfolio(cash=50_000.0)
        p.buy("AAPL", 10, 100.0)
        prices = {"AAPL": 110.0}
        val = p.total_value(prices)
        # Value = remaining cash + 10 shares * $110
        assert val > 0

    def test_summary(self):
        p = self._make_portfolio()
        p.buy("AAPL", 10, 150.0)
        summary = p.summary({"AAPL": 155.0})
        assert "cash" in summary
        assert "positions" in summary
        assert "total_value" in summary
        assert "realized_pnl" in summary
        assert "unrealized_pnl" in summary
        assert "total_fees_paid" in summary
