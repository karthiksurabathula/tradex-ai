"""Tests for the fee model."""

from src.execution.fees import FeeModel


class TestFeeModel:
    def test_buy_equity_fees(self):
        fm = FeeModel()
        fees = fm.calculate("BUY", "AAPL", 100, 150.0)

        assert fees["commission"] == 4.95
        assert fees["spread"] > 0  # 0.02% of 15000 = 3.0
        assert fees["slippage"] > 0  # 0.10% of 15000 = 15.0
        assert fees["sec_fee"] == 0  # No SEC fee on buys
        assert fees["total"] == fees["commission"] + fees["spread"] + fees["slippage"]
        assert fees["effective_price"] > 150.0  # Buy price + fees

    def test_sell_equity_includes_sec_fee(self):
        fm = FeeModel()
        fees = fm.calculate("SELL", "AAPL", 100, 150.0)

        assert fees["sec_fee"] > 0  # SEC fee applies on sells
        assert fees["total"] > fees["commission"] + fees["spread"] + fees["slippage"]

    def test_crypto_higher_spread(self):
        fm = FeeModel()
        equity_fees = fm.calculate("BUY", "AAPL", 10, 100.0)
        crypto_fees = fm.calculate("BUY", "BTC-USD", 10, 100.0)

        # Same notional, but crypto spread is 15x higher (0.3% vs 0.02%)
        assert crypto_fees["spread"] > equity_fees["spread"]

    def test_zero_quantity_returns_zero_fees(self):
        fm = FeeModel()
        fees = fm.calculate("BUY", "AAPL", 0, 150.0)
        assert fees["total"] == 0.0

    def test_effective_price_buy_vs_sell(self):
        fm = FeeModel()
        buy_fees = fm.calculate("BUY", "AAPL", 100, 150.0)
        sell_fees = fm.calculate("SELL", "AAPL", 100, 150.0)

        # Buy effective price is higher (you pay more)
        assert buy_fees["effective_price"] > 150.0
        # Sell effective price is lower (you receive less)
        assert sell_fees["effective_price"] < 150.0

    def test_from_config(self):
        config = {
            "fees": {
                "commission_per_trade": 0.0,
                "spread_pct_equity": 0.001,
                "slippage_pct": 0.0,
            }
        }
        fm = FeeModel.from_config(config)
        assert fm.commission_per_trade == 0.0
        assert fm.spread_pct_equity == 0.001
        assert fm.slippage_pct == 0.0
        # Unspecified fields get defaults
        assert fm.sec_fee_per_million == 8.00

    def test_is_crypto_detection(self):
        assert FeeModel._is_crypto("BTC-USD")
        assert FeeModel._is_crypto("ETH-USD")
        assert FeeModel._is_crypto("DOGE")
        assert not FeeModel._is_crypto("AAPL")
        assert not FeeModel._is_crypto("MSFT")
