"""Fundamental data filters using yfinance Ticker.info.

Checks P/E ratio, forward P/E, revenue growth, profit margins before entry.
"""

from __future__ import annotations

import logging

import yfinance as yf

logger = logging.getLogger(__name__)


def is_fundamentally_sound(symbol: str) -> tuple[bool, str]:
    """Check if a symbol passes fundamental quality filters.

    Returns:
        (passed, reason) — True if fundamentals are acceptable.
    """
    try:
        info = yf.Ticker(symbol).info
    except Exception as e:
        logger.warning("Could not fetch fundamentals for %s: %s", symbol, e)
        # Allow trade if we can't check — don't block on data failure
        return True, "Fundamental data unavailable; proceeding with caution"

    if not info:
        return True, "No fundamental data available"

    reasons: list[str] = []

    # P/E ratio check
    pe = info.get("trailingPE")
    if pe is not None:
        try:
            pe = float(pe)
            if pe > 100:
                reasons.append(f"Trailing P/E too high ({pe:.1f} > 100)")
        except (TypeError, ValueError):
            pass

    # Forward P/E check
    forward_pe = info.get("forwardPE")
    if forward_pe is not None:
        try:
            forward_pe = float(forward_pe)
            if forward_pe > 100:
                reasons.append(f"Forward P/E too high ({forward_pe:.1f} > 100)")
        except (TypeError, ValueError):
            pass

    # Profit margins check
    profit_margin = info.get("profitMargins")
    if profit_margin is not None:
        try:
            profit_margin = float(profit_margin)
            if profit_margin < 0:
                reasons.append(f"Negative profit margins ({profit_margin:.1%})")
        except (TypeError, ValueError):
            pass

    # Revenue growth check
    revenue_growth = info.get("revenueGrowth")
    if revenue_growth is not None:
        try:
            revenue_growth = float(revenue_growth)
            if revenue_growth < -0.20:
                reasons.append(f"Revenue declining > 20% ({revenue_growth:.1%})")
        except (TypeError, ValueError):
            pass

    if reasons:
        combined = "; ".join(reasons)
        logger.info("Fundamentals REJECT %s: %s", symbol, combined)
        return False, combined

    logger.debug("Fundamentals OK for %s", symbol)
    return True, "Fundamentals acceptable"


def get_fundamentals(symbol: str) -> dict:
    """Get a summary of key fundamental metrics for a symbol."""
    try:
        info = yf.Ticker(symbol).info
    except Exception:
        return {}

    if not info:
        return {}

    return {
        "symbol": symbol,
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "profit_margins": info.get("profitMargins"),
        "revenue_growth": info.get("revenueGrowth"),
        "market_cap": info.get("marketCap"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
    }
