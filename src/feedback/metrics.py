"""Performance metrics — Sharpe ratio, max drawdown, win rate, etc."""

from __future__ import annotations

import math


def compute_metrics(trades: list[dict]) -> dict:
    """Compute performance metrics from a list of trade dicts."""
    executed = [t for t in trades if t.get("executed") and t.get("net_pnl") is not None]

    if not executed:
        return {
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "max_consecutive_losses": 0,
            "total_trades": 0,
        }

    pnls = [t["net_pnl"] for t in executed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    # Sharpe ratio (simplified: mean / std of trade returns)
    mean_pnl = sum(pnls) / len(pnls)
    if len(pnls) > 1:
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
        std_pnl = math.sqrt(variance)
        sharpe = (mean_pnl / std_pnl) if std_pnl > 0 else 0.0
    else:
        sharpe = 0.0

    # Max drawdown (cumulative PnL series)
    cumulative = []
    running = 0.0
    for p in pnls:
        running += p
        cumulative.append(running)

    peak = cumulative[0]
    max_dd = 0.0
    for val in cumulative:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd

    # Profit factor
    total_wins = sum(wins) if wins else 0.0
    total_losses = abs(sum(losses)) if losses else 0.0
    profit_factor = (total_wins / total_losses) if total_losses > 0 else float("inf")

    # Max consecutive losses
    max_consec = 0
    current_consec = 0
    for p in pnls:
        if p < 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0

    return {
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        "max_consecutive_losses": max_consec,
        "total_trades": len(executed),
    }
