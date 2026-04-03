"""Trade reviewer — analyzes recent trades to identify patterns in wins and losses."""

from __future__ import annotations

import logging
from collections import Counter

from src.execution.trade_log import TradeLog
from src.feedback.metrics import compute_metrics

logger = logging.getLogger(__name__)


class TradeReviewer:
    """Analyzes trade outcomes and identifies systematic patterns."""

    def __init__(self, trade_log: TradeLog):
        self.log = trade_log

    def review(self, symbol: str | None = None) -> dict:
        """Full review of recent trades for a symbol (or all symbols)."""
        trades = self.log.recent_trades(symbol, limit=50)
        perf = self.log.performance_summary(symbol)
        metrics = compute_metrics(trades)
        loss_patterns = self._analyze_losses(trades)

        return {
            "performance": perf,
            "metrics": metrics,
            "loss_patterns": loss_patterns,
            "recommendation": self._generate_recommendation(perf, metrics, loss_patterns),
        }

    def _analyze_losses(self, trades: list[dict]) -> list[str]:
        """Find common patterns in losing trades' reasoning."""
        losses = [t for t in trades if (t.get("net_pnl") or 0) < 0]
        if not losses:
            return []

        patterns: list[str] = []
        pattern_counts: Counter[str] = Counter()

        for t in losses:
            reasoning = (t.get("reasoning") or "").lower()

            if "sentiment" in reasoning and "bullish" in reasoning:
                pattern = "over-weighted bullish sentiment on losing trade"
                pattern_counts[pattern] += 1

            if "rsi" in reasoning and "oversold" in reasoning:
                pattern = "caught falling knife on RSI oversold signal"
                pattern_counts[pattern] += 1

            if "macd" in reasoning and ("cross" in reasoning or "positive" in reasoning):
                pattern = "false MACD crossover signal"
                pattern_counts[pattern] += 1

            if "bollinger" in reasoning and "lower" in reasoning:
                pattern = "premature Bollinger Band bounce entry"
                pattern_counts[pattern] += 1

            if "hold" not in reasoning and (t.get("fee_total") or 0) > abs(t.get("net_pnl") or 1):
                pattern = "fees exceeded trade PnL (overtrading)"
                pattern_counts[pattern] += 1

        # Return patterns sorted by frequency
        for pattern, count in pattern_counts.most_common():
            patterns.append(f"{pattern} ({count}x)")

        return patterns

    def _generate_recommendation(
        self, perf: dict, metrics: dict, patterns: list[str]
    ) -> str:
        """Generate actionable recommendation based on review."""
        recommendations = []

        win_rate = perf.get("win_rate", 0)
        if win_rate < 0.4 and perf.get("total_trades", 0) >= 10:
            recommendations.append(
                "URGENT: Win rate below 40%. Increase HOLD threshold, tighten stop-losses."
            )

        if metrics.get("max_consecutive_losses", 0) >= 5:
            recommendations.append(
                "WARNING: 5+ consecutive losses detected. Consider pausing and reviewing strategy."
            )

        if metrics.get("profit_factor", 0) < 1.0 and perf.get("total_trades", 0) >= 10:
            recommendations.append(
                "ALERT: Profit factor below 1.0 — system is losing money net of fees."
            )

        fee_ratio = perf.get("total_fees", 0) / max(abs(perf.get("gross_pnl", 1)), 1)
        if fee_ratio > 0.5:
            recommendations.append(
                f"COST: Fees are {fee_ratio:.0%} of gross PnL. Reduce trade frequency or increase position sizes."
            )

        # Pattern-specific advice
        pattern_str = " ".join(patterns)
        if "bullish sentiment" in pattern_str:
            recommendations.append(
                "ADJUST: Reduce sentiment weight from 30% to 20%, increase technical weight."
            )
        if "falling knife" in pattern_str:
            recommendations.append(
                "ADJUST: Add RSI trend confirmation — require RSI to be rising, not just < 30."
            )
        if "overtrading" in pattern_str:
            recommendations.append(
                "ADJUST: Increase minimum confidence threshold to reduce fee drag."
            )

        if not recommendations:
            recommendations.append("STABLE: No major adjustments needed.")

        return " | ".join(recommendations)
