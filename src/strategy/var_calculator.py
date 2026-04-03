"""Value-at-Risk (VaR) calculations for portfolio risk assessment.

Provides historical VaR, parametric VaR, and portfolio-level VaR.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _get_historical_returns(symbols: list[str], period: str = "3mo") -> pd.DataFrame:
    """Fetch historical daily returns for a list of symbols."""
    data = {}
    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(period=period, interval="1d")
            if not hist.empty and len(hist) > 5:
                data[sym] = hist["Close"].pct_change().dropna()
        except Exception as e:
            logger.warning("Could not fetch returns for %s: %s", sym, e)
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data).dropna()


def _historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Historical VaR: percentile of actual return distribution."""
    if returns.empty or len(returns) < 5:
        return 0.0
    quantile = 1.0 - confidence
    return float(-returns.quantile(quantile))


def _parametric_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Parametric VaR: assumes normal distribution (mean/std based)."""
    if returns.empty or len(returns) < 5:
        return 0.0

    from scipy import stats

    mean = float(returns.mean())
    std = float(returns.std())
    if std == 0:
        return 0.0

    z_score = stats.norm.ppf(1 - confidence)
    return float(-(mean + z_score * std))


def _parametric_var_simple(returns: pd.Series, confidence: float = 0.95) -> float:
    """Parametric VaR without scipy — uses hardcoded z-scores."""
    if returns.empty or len(returns) < 5:
        return 0.0

    z_scores = {0.90: 1.282, 0.95: 1.645, 0.99: 2.326}
    z = z_scores.get(confidence, 1.645)

    mean = float(returns.mean())
    std = float(returns.std())
    if std == 0:
        return 0.0

    return float(-(mean - z * std))


def calculate_var(
    portfolio: object,
    prices: dict[str, float],
    confidence: float = 0.95,
) -> dict:
    """Calculate VaR metrics for the current portfolio.

    Args:
        portfolio: Portfolio object with .positions and .cash attributes.
        prices: Current prices dict {symbol: price}.
        confidence: Confidence level (default 0.95 for 95% VaR).

    Returns:
        Dict with historical_var, parametric_var, portfolio_var (all as dollar amounts),
        plus var_pct (as percentage of portfolio value).
    """
    positions = getattr(portfolio, "positions", {})
    if not positions:
        return {
            "historical_var": 0.0,
            "parametric_var": 0.0,
            "portfolio_var": 0.0,
            "var_pct": 0.0,
            "confidence": confidence,
            "note": "No open positions",
        }

    symbols = list(positions.keys())
    returns_df = _get_historical_returns(symbols)

    if returns_df.empty:
        return {
            "historical_var": 0.0,
            "parametric_var": 0.0,
            "portfolio_var": 0.0,
            "var_pct": 0.0,
            "confidence": confidence,
            "note": "Insufficient historical data",
        }

    # Calculate portfolio weights
    total_value = sum(
        positions[s].quantity * prices.get(s, positions[s].avg_cost)
        for s in symbols
        if s in returns_df.columns
    )

    if total_value <= 0:
        return {
            "historical_var": 0.0,
            "parametric_var": 0.0,
            "portfolio_var": 0.0,
            "var_pct": 0.0,
            "confidence": confidence,
            "note": "Zero portfolio value",
        }

    # Portfolio returns: weighted sum of individual returns
    portfolio_returns = pd.Series(0.0, index=returns_df.index)
    weights = {}
    for sym in symbols:
        if sym in returns_df.columns:
            pos = positions[sym]
            weight = (pos.quantity * prices.get(sym, pos.avg_cost)) / total_value
            weights[sym] = weight
            portfolio_returns += returns_df[sym] * weight

    # Calculate VaR metrics
    hist_var_pct = _historical_var(portfolio_returns, confidence)

    try:
        param_var_pct = _parametric_var(portfolio_returns, confidence)
    except ImportError:
        param_var_pct = _parametric_var_simple(portfolio_returns, confidence)

    # Portfolio-level VaR in dollars
    cash = getattr(portfolio, "cash", 0.0)
    full_portfolio_value = total_value + cash
    portfolio_var_dollars = hist_var_pct * total_value

    result = {
        "historical_var": round(hist_var_pct * total_value, 2),
        "parametric_var": round(param_var_pct * total_value, 2),
        "portfolio_var": round(portfolio_var_dollars, 2),
        "var_pct": round(hist_var_pct * 100, 4),
        "confidence": confidence,
        "portfolio_value": round(full_portfolio_value, 2),
        "weights": {k: round(v, 4) for k, v in weights.items()},
    }

    logger.info(
        "VaR (%.0f%%): Historical=$%.2f, Parametric=$%.2f, Portfolio=$%.2f",
        confidence * 100,
        result["historical_var"],
        result["parametric_var"],
        result["portfolio_var"],
    )

    return result
