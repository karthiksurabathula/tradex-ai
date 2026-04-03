"""Tests for the reasoning engine (fallback mode without TradingAgents)."""

from datetime import UTC, datetime

from src.reasoning.engine import ReasoningEngine
from src.state.models import (
    MarketState,
    NewsSentiment,
    OHLCVBar,
    OHLCVData,
    SignalType,
    TechnicalIndicators,
)


def _make_state(
    rsi: float = 50.0,
    macd_h: float = 0.0,
    price: float = 150.0,
    bb_lower: float = 140.0,
    bb_mid: float = 150.0,
    bb_upper: float = 160.0,
    sentiment: float = 0.0,
) -> MarketState:
    return MarketState(
        symbol="AAPL",
        timestamp=datetime.now(UTC),
        ohlcv=OHLCVData(
            symbol="AAPL",
            bars=[OHLCVBar(date=datetime.now(UTC), open=149, high=152, low=148, close=price, volume=1000)],
        ),
        technicals=TechnicalIndicators(
            symbol="AAPL",
            rsi=rsi,
            macd_signal=0.0,
            macd_histogram=macd_h,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            bb_mid=bb_mid,
            current_price=price,
        ),
        sentiment=NewsSentiment(overall_score=sentiment, confidence=0.7),
    )


class TestReasoningEngine:
    def setup_method(self):
        self.engine = ReasoningEngine()

    def test_bullish_signals_produce_buy(self):
        state = _make_state(rsi=25, macd_h=0.5, price=139.0, sentiment=0.6)
        signal = self.engine.decide(state)
        assert signal.action == SignalType.BUY

    def test_bearish_signals_produce_sell(self):
        state = _make_state(rsi=75, macd_h=-0.5, price=161.0, sentiment=-0.6)
        signal = self.engine.decide(state)
        assert signal.action == SignalType.SELL

    def test_mixed_signals_produce_hold(self):
        state = _make_state(rsi=50, macd_h=0.01, price=150.0, sentiment=0.0)
        signal = self.engine.decide(state)
        assert signal.action == SignalType.HOLD

    def test_signal_has_reasoning(self):
        state = _make_state(rsi=25, sentiment=0.5)
        signal = self.engine.decide(state)
        assert len(signal.reasoning) > 0

    def test_confidence_bounded(self):
        state = _make_state(rsi=10, macd_h=1.0, sentiment=0.9)
        signal = self.engine.decide(state)
        assert 0.0 <= signal.confidence <= 1.0

    def test_context_prompt_built(self):
        state = _make_state(rsi=45, sentiment=0.3)
        context = self.engine._build_context_prompt(state)
        assert "RSI(14)" in context
        assert "WorldMonitor" in context
        assert "Bollinger Bands" in context
