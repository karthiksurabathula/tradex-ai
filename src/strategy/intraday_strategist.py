"""Intraday strategist — capital allocation, opportunity ranking, portfolio-level decisions.

This is the "AI brain" that decides:
- Which opportunities to take from the scanner
- How much capital to allocate to each
- When to scale in/out
- Overall portfolio risk management
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.execution.portfolio import Portfolio
from src.scanner.market_scanner import ScanResult

logger = logging.getLogger(__name__)


@dataclass
class TradeOpportunity:
    """A ranked, sized trading opportunity ready for execution."""
    symbol: str
    direction: str  # "BUY" or "SELL"
    allocation_pct: float  # % of portfolio to allocate
    quantity: int
    price: float
    score: float
    reason: str
    category: str


class IntradayStrategist:
    """Decides what to trade, how much, and when — fully autonomous."""

    def __init__(
        self,
        max_open_positions: int = 5,
        max_single_position_pct: float = 0.15,  # 15% of portfolio per position
        min_cash_reserve_pct: float = 0.20,      # Keep 20% cash always
        min_score_threshold: float = 25.0,        # Minimum scanner score to trade
        prefer_momentum: bool = True,
    ):
        self.max_open_positions = max_open_positions
        self.max_single_position_pct = max_single_position_pct
        self.min_cash_reserve_pct = min_cash_reserve_pct
        self.min_score_threshold = min_score_threshold
        self.prefer_momentum = prefer_momentum

    def select_opportunities(
        self,
        scan_results: list[ScanResult],
        portfolio: Portfolio,
        current_prices: dict[str, float],
    ) -> list[TradeOpportunity]:
        """From scanner results, select and size the best opportunities.

        This is where the AI acts as a portfolio manager:
        1. Filter by score threshold
        2. Avoid already-held positions
        3. Respect position limits
        4. Size positions based on conviction (score)
        5. Reserve cash for risk management
        """
        portfolio_value = portfolio.total_value(current_prices)
        available_cash = portfolio.cash
        cash_reserve = portfolio_value * self.min_cash_reserve_pct
        tradeable_cash = max(0, available_cash - cash_reserve)
        open_slots = self.max_open_positions - len(portfolio.positions)

        if open_slots <= 0:
            logger.info("All %d position slots filled. No new entries.", self.max_open_positions)
            return []

        if tradeable_cash < 100:
            logger.info("Insufficient tradeable cash ($%.2f). Skipping.", tradeable_cash)
            return []

        # Filter and rank
        candidates = [
            r for r in scan_results
            if r.score >= self.min_score_threshold
            and r.symbol not in portfolio.positions
            and r.price > 0
        ]

        if not candidates:
            logger.info("No candidates above score threshold (%.1f)", self.min_score_threshold)
            return []

        # Sort: momentum first if preferred, then by score
        if self.prefer_momentum:
            candidates.sort(key=lambda x: (x.category == "momentum", x.score), reverse=True)
        else:
            candidates.sort(key=lambda x: x.score, reverse=True)

        # Take top N for available slots
        selected = candidates[:open_slots]

        # Size positions — proportional to score, capped at max single position
        total_score = sum(c.score for c in selected)
        opportunities = []

        for candidate in selected:
            # Allocation: proportional to score, capped
            if total_score > 0:
                score_weight = candidate.score / total_score
            else:
                score_weight = 1.0 / len(selected)

            raw_allocation = tradeable_cash * score_weight
            max_allocation = portfolio_value * self.max_single_position_pct
            allocation = min(raw_allocation, max_allocation)

            quantity = int(allocation / candidate.price)
            if quantity <= 0:
                continue

            # Determine direction
            direction = "BUY"
            if candidate.change_pct < -2 and candidate.category == "sector":
                direction = "SELL"  # Short weak sectors (if supported)

            opportunities.append(TradeOpportunity(
                symbol=candidate.symbol,
                direction=direction,
                allocation_pct=round((quantity * candidate.price) / portfolio_value * 100, 1),
                quantity=quantity,
                price=candidate.price,
                score=candidate.score,
                reason=candidate.reason,
                category=candidate.category,
            ))

            tradeable_cash -= quantity * candidate.price

        logger.info(
            "Selected %d opportunities from %d candidates (tradeable cash: $%.2f)",
            len(opportunities), len(candidates), tradeable_cash,
        )
        return opportunities

    def should_exit_all(self, portfolio: Portfolio, current_prices: dict[str, float]) -> bool:
        """Emergency check — exit everything if portfolio is tanking."""
        if not portfolio.positions:
            return False

        total_unrealized = portfolio.total_unrealized_pnl(current_prices)
        portfolio_value = portfolio.total_value(current_prices)

        # Exit all if unrealized loss exceeds 5% of portfolio
        if portfolio_value > 0 and (total_unrealized / portfolio_value) < -0.05:
            logger.warning(
                "EMERGENCY: Unrealized loss %.1f%% exceeds 5%% threshold. Recommending full exit.",
                (total_unrealized / portfolio_value) * 100,
            )
            return True
        return False
