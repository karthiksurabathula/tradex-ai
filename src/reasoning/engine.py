"""Reasoning engine — orchestrates TradingAgents with supplementary OpenBB/WorldMonitor context."""

from __future__ import annotations

import logging
import re

from src.reasoning.agent_config import build_config
from src.reasoning.prompt_store import PromptStore
from src.state.models import MarketState, SignalType, TradeSignal

logger = logging.getLogger(__name__)


class ReasoningEngine:
    """Wraps TradingAgents graph execution with injected MarketState context."""

    def __init__(
        self,
        llm_provider: str = "anthropic",
        deep_think_model: str = "claude-sonnet-4-6",
        quick_think_model: str = "claude-sonnet-4-6",
        prompt_store: PromptStore | None = None,
    ):
        self.config = build_config(llm_provider, deep_think_model, quick_think_model)
        self.prompt_store = prompt_store or PromptStore()
        self._graph = None

    @property
    def graph(self):
        """Lazy-load TradingAgentsGraph (heavy import)."""
        if self._graph is None:
            try:
                from tradingagents.graph.trading_graph import TradingAgentsGraph

                self._graph = TradingAgentsGraph(debug=True, config=self.config)
            except ImportError:
                logger.warning(
                    "TradingAgents not installed. Using fallback reasoning."
                )
        return self._graph

    def decide(self, state: MarketState) -> TradeSignal:
        """Run TradingAgents reasoning pipeline with supplementary context.

        TradingAgents runs its own analyst pipeline natively.
        We SUPPLEMENT (not replace) by injecting OpenBB technicals and
        WorldMonitor sentiment as extra context into the Senior Trader prompt.
        """
        context = self._build_context_prompt(state)

        if self.graph is not None:
            return self._decide_with_tradingagents(state, context)
        else:
            return self._decide_fallback(state, context)

    def _decide_with_tradingagents(
        self, state: MarketState, context: str
    ) -> TradeSignal:
        """Use the full TradingAgents multi-agent pipeline."""
        self.graph.config["senior_trader_context"] = context

        _, decision = self.graph.propagate(
            state.symbol, state.timestamp.strftime("%Y-%m-%d")
        )

        return self._parse_decision(state.symbol, decision)

    def _decide_fallback(self, state: MarketState, context: str) -> TradeSignal:
        """Rule-based fallback when TradingAgents is not available."""
        logger.info("Using rule-based fallback for %s", state.symbol)

        rsi = state.technicals.rsi
        macd_h = state.technicals.macd_histogram
        sentiment = state.sentiment.overall_score

        score = 0.0
        reasons = []

        # Technical signals (weight: 60%)
        if rsi < 30:
            score += 0.3
            reasons.append(f"RSI oversold ({rsi:.1f})")
        elif rsi > 70:
            score -= 0.3
            reasons.append(f"RSI overbought ({rsi:.1f})")

        if macd_h > 0:
            score += 0.15
            reasons.append("MACD histogram positive")
        else:
            score -= 0.15
            reasons.append("MACD histogram negative")

        price = state.technicals.current_price
        if price < state.technicals.bb_lower:
            score += 0.15
            reasons.append("Price below lower Bollinger Band")
        elif price > state.technicals.bb_upper:
            score -= 0.15
            reasons.append("Price above upper Bollinger Band")

        # Sentiment signals (weight: 40%)
        score += sentiment * 0.4
        if abs(sentiment) > 0.3:
            label = "bullish" if sentiment > 0 else "bearish"
            reasons.append(f"WorldMonitor sentiment {label} ({sentiment:.2f})")

        # Map score to signal
        confidence = min(abs(score), 1.0)
        if score > 0.2:
            action = SignalType.BUY
        elif score < -0.2:
            action = SignalType.SELL
        else:
            action = SignalType.HOLD
            confidence = 1.0 - confidence

        return TradeSignal(
            symbol=state.symbol,
            action=action,
            confidence=round(confidence, 2),
            reasoning="; ".join(reasons),
        )

    def _build_context_prompt(self, state: MarketState) -> str:
        """Build supplementary context for the Senior Trader from our state."""
        headlines_text = "\n".join(
            f'- {h.get("title", "N/A")}' for h in state.headlines[:5]
        )

        return f"""
SUPPLEMENTARY MARKET INTELLIGENCE (from external systems):

## Technical Indicators (OpenBB)
- RSI(14): {state.technicals.rsi:.1f} ({state.technicals.rsi_label})
- MACD Histogram: {state.technicals.macd_histogram:.4f}
- Bollinger Bands: Lower={state.technicals.bb_lower:.2f} | Mid={state.technicals.bb_mid:.2f} | Upper={state.technicals.bb_upper:.2f}
- Current Price: ${state.technicals.current_price:.2f}

## Macro Sentiment (WorldMonitor)
- Overall Sentiment: {state.sentiment.overall_score:.2f} (-1=bearish, +1=bullish)
- Confidence: {state.sentiment.confidence:.0%}
- Key Themes: {', '.join(state.sentiment.top_themes[:5]) or 'N/A'}
- Global Instability Index: {state.sentiment.instability_index or 'N/A'}
- Active Macro Events: {len(state.macro_events)}

## Top Headlines
{headlines_text or '- No headlines available'}

Weight these external signals alongside your own analysis. If external sentiment
strongly contradicts your technical read, flag the divergence in your reasoning.
"""

    def _parse_decision(self, symbol: str, decision: str) -> TradeSignal:
        """Parse TradingAgents text decision into structured TradeSignal."""
        decision_lower = decision.lower()

        # Try to extract structured fields
        action = SignalType.HOLD
        if "buy" in decision_lower or "overweight" in decision_lower:
            action = SignalType.BUY
        elif "sell" in decision_lower or "underweight" in decision_lower:
            action = SignalType.SELL

        # Try to extract confidence from CONFIDENCE: line
        confidence = 0.5
        conf_match = re.search(r"confidence[:\s]+([0-9.]+)", decision_lower)
        if conf_match:
            try:
                confidence = float(conf_match.group(1))
                confidence = max(0.0, min(1.0, confidence))
            except ValueError:
                pass

        return TradeSignal(
            symbol=symbol,
            action=action,
            confidence=confidence,
            reasoning=decision[:2000],
        )
