"""Algorithm Lab — the broker discovers its own best TA combinations.

Tests different indicator combos + weights on historical data,
tracks which work, evolves the strategy over time.

How it works:
1. Generates random "strategies" (combos of indicators + weights)
2. Backtests each on stored quote data
3. Ranks by Sharpe ratio / win rate
4. Breeds top strategies (genetic algorithm style)
5. Promotes the best to production
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.data.quote_store import QuoteStore
from src.strategy.ta_registry import INDICATOR_REGISTRY, compute_indicator

logger = logging.getLogger(__name__)


@dataclass
class Strategy:
    """A combination of indicators with weights — the broker's 'algorithm'."""
    strategy_id: str
    indicators: dict[str, float]  # {indicator_name: weight}
    buy_threshold: float = 0.2
    sell_threshold: float = -0.2
    generation: int = 0

    def compute_signal(self, df: pd.DataFrame) -> pd.Series:
        """Compute combined signal from weighted indicators."""
        combined = pd.Series(0.0, index=df.index)
        total_weight = sum(abs(w) for w in self.indicators.values())
        if total_weight == 0:
            return combined

        for name, weight in self.indicators.items():
            try:
                sig = compute_indicator(name, df)
                if not sig.empty:
                    combined += sig * (weight / total_weight)
            except Exception:
                continue

        return combined.clip(-1, 1)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "indicators": self.indicators,
            "buy_threshold": self.buy_threshold,
            "sell_threshold": self.sell_threshold,
            "generation": self.generation,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Strategy:
        return cls(**d)


@dataclass
class BacktestResult:
    strategy_id: str
    symbol: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    tested_at: str = ""


class AlgorithmLab:
    """Tests, evolves, and promotes TA strategies autonomously."""

    def __init__(self, quote_store: QuoteStore, db_path: str = "data/algorithm_lab.db"):
        self.quote_store = quote_store
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._active_strategy: Strategy | None = None

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS strategies (
                strategy_id TEXT PRIMARY KEY,
                config TEXT NOT NULL,
                generation INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                total_trades INTEGER, wins INTEGER, losses INTEGER,
                total_pnl REAL, sharpe REAL, max_drawdown REAL, win_rate REAL,
                tested_at TEXT NOT NULL
            );
        """)
        self.conn.commit()

    # ── Strategy Generation ──────────────────────────────────────────────────
    def generate_random_strategy(self, n_indicators: int = 4) -> Strategy:
        """Create a random strategy with N indicators and random weights."""
        available = list(INDICATOR_REGISTRY.keys())
        chosen = random.sample(available, min(n_indicators, len(available)))
        weights = {name: round(random.uniform(-1, 1), 3) for name in chosen}
        buy_t = round(random.uniform(0.1, 0.4), 2)
        sell_t = round(random.uniform(-0.4, -0.1), 2)

        sid = f"gen0_{datetime.now(UTC).strftime('%H%M%S')}_{random.randint(100, 999)}"
        strategy = Strategy(
            strategy_id=sid, indicators=weights,
            buy_threshold=buy_t, sell_threshold=sell_t, generation=0,
        )
        self._save_strategy(strategy)
        return strategy

    def breed(self, parent_a: Strategy, parent_b: Strategy) -> Strategy:
        """Breed two strategies — crossover indicators + mutate weights."""
        all_indicators = set(parent_a.indicators) | set(parent_b.indicators)
        child_indicators = {}

        for name in all_indicators:
            wa = parent_a.indicators.get(name, 0)
            wb = parent_b.indicators.get(name, 0)
            # Crossover: average + small mutation
            w = (wa + wb) / 2 + random.gauss(0, 0.1)
            if abs(w) > 0.05:  # Drop near-zero weights
                child_indicators[name] = round(w, 3)

        # Possibly add a new random indicator
        if random.random() < 0.2:
            available = set(INDICATOR_REGISTRY.keys()) - set(child_indicators)
            if available:
                new = random.choice(list(available))
                child_indicators[new] = round(random.uniform(-0.5, 0.5), 3)

        gen = max(parent_a.generation, parent_b.generation) + 1
        sid = f"gen{gen}_{datetime.now(UTC).strftime('%H%M%S')}_{random.randint(100, 999)}"

        child = Strategy(
            strategy_id=sid, indicators=child_indicators,
            buy_threshold=round((parent_a.buy_threshold + parent_b.buy_threshold) / 2, 2),
            sell_threshold=round((parent_a.sell_threshold + parent_b.sell_threshold) / 2, 2),
            generation=gen,
        )
        self._save_strategy(child)
        return child

    # ── Backtesting ──────────────────────────────────────────────────────────
    def backtest(self, strategy: Strategy, symbol: str, interval: str = "5m") -> BacktestResult:
        """Backtest a strategy on stored quote data."""
        df = self.quote_store.get_quotes(symbol, interval=interval, limit=5000)
        if df.empty or len(df) < 50:
            return BacktestResult(strategy_id=strategy.strategy_id, symbol=symbol)

        signals = strategy.compute_signal(df)
        close = df["close"]

        # Simulate trades
        position = 0  # 0 = flat, 1 = long
        entry_price = 0.0
        pnls = []

        for i in range(1, len(signals)):
            sig = signals.iloc[i]
            price = close.iloc[i]

            if position == 0 and sig > strategy.buy_threshold:
                position = 1
                entry_price = price
            elif position == 1 and sig < strategy.sell_threshold:
                pnl = (price - entry_price) / entry_price
                pnls.append(pnl)
                position = 0

        # Close any open position
        if position == 1:
            pnl = (close.iloc[-1] - entry_price) / entry_price
            pnls.append(pnl)

        if not pnls:
            return BacktestResult(strategy_id=strategy.strategy_id, symbol=symbol)

        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        total_pnl = sum(pnls)

        # Sharpe
        import math
        mean = total_pnl / len(pnls)
        if len(pnls) > 1:
            var = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
            std = math.sqrt(var)
            sharpe = (mean / std) if std > 0 else 0
        else:
            sharpe = 0

        # Max drawdown
        cumulative = []
        running = 0
        for p in pnls:
            running += p
            cumulative.append(running)
        peak = cumulative[0]
        max_dd = 0
        for v in cumulative:
            if v > peak:
                peak = v
            dd = peak - v
            if dd > max_dd:
                max_dd = dd

        result = BacktestResult(
            strategy_id=strategy.strategy_id, symbol=symbol,
            total_trades=len(pnls), wins=wins, losses=losses,
            total_pnl=round(total_pnl * 100, 2),
            sharpe=round(sharpe, 4),
            max_drawdown=round(max_dd * 100, 2),
            win_rate=round(wins / len(pnls), 4) if pnls else 0,
            tested_at=datetime.now(UTC).isoformat(),
        )

        # Save result
        self.conn.execute(
            "INSERT INTO backtest_results (strategy_id, symbol, total_trades, wins, losses, total_pnl, sharpe, max_drawdown, win_rate, tested_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (result.strategy_id, result.symbol, result.total_trades, result.wins, result.losses, result.total_pnl, result.sharpe, result.max_drawdown, result.win_rate, result.tested_at),
        )
        self.conn.commit()
        return result

    # ── Evolution Cycle ──────────────────────────────────────────────────────
    def evolve(self, symbols: list[str], population_size: int = 20, generations: int = 3) -> Strategy:
        """Run a full evolution cycle: generate, test, breed, promote.

        Returns the best strategy found.
        """
        logger.info("Starting evolution: %d population, %d generations, %d symbols",
                     population_size, generations, len(symbols))

        # Generate initial population
        population = [self.generate_random_strategy() for _ in range(population_size)]

        for gen in range(generations):
            # Backtest all strategies on all symbols
            scores: list[tuple[Strategy, float]] = []
            for strat in population:
                total_sharpe = 0
                for sym in symbols:
                    result = self.backtest(strat, sym)
                    total_sharpe += result.sharpe
                avg_sharpe = total_sharpe / len(symbols) if symbols else 0
                scores.append((strat, avg_sharpe))

            # Rank by average Sharpe
            scores.sort(key=lambda x: x[1], reverse=True)
            top_half = [s[0] for s in scores[:len(scores) // 2]]

            logger.info("Gen %d: Best Sharpe=%.4f (%s), Worst=%.4f",
                        gen, scores[0][1], scores[0][0].strategy_id, scores[-1][1])

            # Breed next generation
            if gen < generations - 1:
                children = []
                for _ in range(population_size):
                    a, b = random.sample(top_half, 2)
                    children.append(self.breed(a, b))
                population = children

        # Promote the best
        best = scores[0][0]
        self.promote(best)
        return best

    # ── Promotion & Active Strategy ──────────────────────────────────────────
    def promote(self, strategy: Strategy):
        """Promote a strategy to active production use."""
        self.conn.execute("UPDATE strategies SET is_active = 0")
        self.conn.execute("UPDATE strategies SET is_active = 1 WHERE strategy_id = ?", (strategy.strategy_id,))
        self.conn.commit()
        self._active_strategy = strategy
        logger.info("Promoted strategy %s (gen %d, %d indicators)",
                    strategy.strategy_id, strategy.generation, len(strategy.indicators))

    @property
    def active_strategy(self) -> Strategy | None:
        if self._active_strategy:
            return self._active_strategy
        cur = self.conn.execute("SELECT config FROM strategies WHERE is_active = 1")
        row = cur.fetchone()
        if row:
            self._active_strategy = Strategy.from_dict(json.loads(row["config"]))
        return self._active_strategy

    def get_signal(self, symbol: str, df: pd.DataFrame) -> float:
        """Get the active strategy's signal for a symbol. Returns -1 to +1."""
        strat = self.active_strategy
        if not strat:
            return 0.0
        signals = strat.compute_signal(df)
        return float(signals.iloc[-1]) if not signals.empty else 0.0

    # ── Persistence ──────────────────────────────────────────────────────────
    def _save_strategy(self, strategy: Strategy):
        self.conn.execute(
            "INSERT OR REPLACE INTO strategies (strategy_id, config, generation, created_at, is_active) VALUES (?, ?, ?, ?, 0)",
            (strategy.strategy_id, json.dumps(strategy.to_dict()), strategy.generation, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def get_leaderboard(self, limit: int = 10) -> list[dict]:
        """Top strategies by average Sharpe ratio."""
        cur = self.conn.execute("""
            SELECT s.strategy_id, s.generation, s.is_active, s.config,
                   AVG(b.sharpe) as avg_sharpe, AVG(b.win_rate) as avg_winrate,
                   SUM(b.total_trades) as total_trades
            FROM strategies s
            JOIN backtest_results b ON s.strategy_id = b.strategy_id
            GROUP BY s.strategy_id
            ORDER BY avg_sharpe DESC
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]

    def close(self):
        self.conn.close()
