"""Ensemble signal — runs multiple strategies and only trades on consensus.

Combines the AlgorithmLab active strategy, rule-based fallback engine,
and a simple momentum indicator. Requires 2+ agreement to trade.
"""

from __future__ import annotations

import logging
import math

import pandas as pd

from src.strategy.ta_registry import compute_indicator

logger = logging.getLogger(__name__)


def _algo_lab_signal(symbol: str, df: pd.DataFrame) -> float:
    """Get signal from the active AlgorithmLab strategy (if available)."""
    try:
        from src.data.quote_store import QuoteStore
        from src.strategy.algorithm_lab import AlgorithmLab

        qs = QuoteStore()
        lab = AlgorithmLab(qs)
        sig = lab.get_signal(symbol, df)
        lab.close()
        qs.close()
        return float(sig)
    except Exception as e:
        logger.debug("AlgorithmLab signal unavailable: %s", e)
        return 0.0


def _rule_based_signal(df: pd.DataFrame) -> float:
    """Simple rule-based engine combining RSI, MACD, and Bollinger Bands."""
    if df.empty or len(df) < 30:
        return 0.0

    score = 0.0
    try:
        rsi_sig = compute_indicator("rsi", df)
        if not rsi_sig.empty:
            score += float(rsi_sig.iloc[-1]) * 0.4
    except Exception:
        pass

    try:
        macd_sig = compute_indicator("macd", df)
        if not macd_sig.empty:
            score += float(macd_sig.iloc[-1]) * 0.35
    except Exception:
        pass

    try:
        bb_sig = compute_indicator("bbands", df)
        if not bb_sig.empty:
            score += float(bb_sig.iloc[-1]) * 0.25
    except Exception:
        pass

    return max(-1.0, min(1.0, score))


def _momentum_signal(df: pd.DataFrame) -> float:
    """Simple momentum: rate-of-change over last 10 bars + EMA crossover."""
    if df.empty or len(df) < 25:
        return 0.0

    score = 0.0
    try:
        roc_sig = compute_indicator("roc", df)
        if not roc_sig.empty:
            score += float(roc_sig.iloc[-1]) * 0.5
    except Exception:
        pass

    try:
        ema_sig = compute_indicator("ema_cross", df)
        if not ema_sig.empty:
            score += float(ema_sig.iloc[-1]) * 0.5
    except Exception:
        pass

    return max(-1.0, min(1.0, score))


def get_ensemble_signal(
    symbol: str, df: pd.DataFrame
) -> tuple[float, float, float]:
    """Run 3 strategies and return consensus signal.

    Returns:
        (signal, confidence, disagreement)
        signal: -1 to +1 averaged from agreeing strategies
        confidence: 0 to 1, higher when strategies agree strongly
        disagreement: 0 = full consensus, 1 = total disagreement
    """
    signals = [
        ("algo_lab", _algo_lab_signal(symbol, df)),
        ("rule_based", _rule_based_signal(df)),
        ("momentum", _momentum_signal(df)),
    ]

    values = [s[1] for s in signals]
    directions = [1 if v > 0.05 else (-1 if v < -0.05 else 0) for v in values]

    # Disagreement: standard deviation of signals normalized to [0, 1]
    mean_val = sum(values) / len(values)
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
    std = math.sqrt(variance)
    disagreement = min(1.0, std)  # std of [-1,1] range, max ~1.15

    # Consensus: count how many agree on direction
    bullish = sum(1 for d in directions if d > 0)
    bearish = sum(1 for d in directions if d < 0)

    if bullish >= 2:
        # Consensus bullish — average the bullish signals
        agreeing = [v for v, d in zip(values, directions) if d > 0]
        signal = sum(agreeing) / len(agreeing)
        confidence = min(1.0, bullish / 3.0 * (1.0 - disagreement))
    elif bearish >= 2:
        # Consensus bearish
        agreeing = [v for v, d in zip(values, directions) if d < 0]
        signal = sum(agreeing) / len(agreeing)
        confidence = min(1.0, bearish / 3.0 * (1.0 - disagreement))
    else:
        # No consensus — no trade
        signal = 0.0
        confidence = 0.0

    logger.info(
        "Ensemble [%s]: algo=%.2f, rules=%.2f, momentum=%.2f -> signal=%.2f, conf=%.2f, disagree=%.2f",
        symbol, values[0], values[1], values[2], signal, confidence, disagreement,
    )

    return (
        round(signal, 4),
        round(confidence, 4),
        round(disagreement, 4),
    )
