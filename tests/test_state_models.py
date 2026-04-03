"""Tests for the Pydantic state models."""

import pandas as pd

from src.state.models import (
    MarketState,
    NewsSentiment,
    OHLCVBar,
    OHLCVData,
    SignalType,
    TechnicalIndicators,
    TradeSignal,
)


class TestOHLCVData:
    def test_from_dataframe(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=3),
                "open": [100.0, 101.0, 102.0],
                "high": [105.0, 106.0, 107.0],
                "low": [99.0, 100.0, 101.0],
                "close": [103.0, 104.0, 105.0],
                "volume": [1000, 1100, 1200],
            }
        )
        data = OHLCVData.from_dataframe("AAPL", df)
        assert data.symbol == "AAPL"
        assert len(data.bars) == 3
        assert data.latest_close == 105.0

    def test_to_dataframe_roundtrip(self):
        bars = [
            OHLCVBar(
                date=pd.Timestamp("2024-01-01"), open=100, high=105, low=99, close=103, volume=1000
            ),
        ]
        data = OHLCVData(symbol="AAPL", bars=bars)
        df = data.to_dataframe()
        assert "close" in df.columns
        assert len(df) == 1

    def test_latest_close_empty(self):
        data = OHLCVData(symbol="AAPL", bars=[])
        assert data.latest_close == 0.0


class TestTechnicalIndicators:
    def test_rsi_labels(self):
        ti = TechnicalIndicators(
            symbol="X", rsi=75, macd_signal=0, macd_histogram=0,
            bb_upper=0, bb_lower=0, bb_mid=0, current_price=100,
        )
        assert ti.rsi_label == "overbought"

        ti.rsi = 25
        assert ti.rsi_label == "oversold"

        ti.rsi = 50
        assert ti.rsi_label == "neutral"


class TestNewsSentiment:
    def test_bounds(self):
        s = NewsSentiment(overall_score=0.5, confidence=0.8)
        assert -1.0 <= s.overall_score <= 1.0
        assert 0.0 <= s.confidence <= 1.0


class TestTradeSignal:
    def test_signal_types(self):
        assert SignalType.BUY.value == "BUY"
        assert SignalType.SELL.value == "SELL"
        assert SignalType.HOLD.value == "HOLD"

    def test_signal_creation(self):
        signal = TradeSignal(
            symbol="AAPL", action=SignalType.BUY, confidence=0.85, reasoning="test"
        )
        assert signal.symbol == "AAPL"
        assert signal.action == SignalType.BUY
        assert signal.confidence == 0.85
