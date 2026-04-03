"""Persistent portfolio state — survives restarts, crash-safe.

Wraps Portfolio with SQLite persistence and thread-safe operations.
Every buy/sell is atomically saved. On startup, state is restored.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from src.execution.fees import FeeModel
from src.execution.portfolio import Portfolio, Position

logger = logging.getLogger(__name__)


class PersistentPortfolio:
    """Thread-safe, crash-recoverable portfolio backed by SQLite."""

    def __init__(self, db_path: str = "data/portfolio.db", starting_cash: float = 100_000.0, fee_model: FeeModel | None = None):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._fee_model = fee_model or FeeModel()
        self._starting_cash = starting_cash
        self._init_schema()
        self.portfolio = self._load_or_create()

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS portfolio_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                quantity INTEGER NOT NULL,
                avg_cost REAL NOT NULL,
                entry_fees REAL DEFAULT 0,
                opened_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS equity_curve (
                timestamp TEXT PRIMARY KEY,
                total_value REAL,
                cash REAL,
                realized_pnl REAL,
                unrealized_pnl REAL,
                total_fees REAL,
                position_count INTEGER
            );
        """)
        self._conn.commit()

    def _load_or_create(self) -> Portfolio:
        """Load portfolio from DB or create fresh."""
        cur = self._conn.execute("SELECT key, value FROM portfolio_state")
        state = {r["key"]: r["value"] for r in cur.fetchall()}

        if state:
            cash = float(state.get("cash", self._starting_cash))
            realized_pnl = float(state.get("realized_pnl", 0))
            total_fees = float(state.get("total_fees_paid", 0))

            # Load positions
            positions = {}
            for row in self._conn.execute("SELECT * FROM positions"):
                positions[row["symbol"]] = Position(
                    symbol=row["symbol"],
                    quantity=row["quantity"],
                    avg_cost=row["avg_cost"],
                    entry_fees=row["entry_fees"],
                )

            p = Portfolio(cash=cash, fee_model=self._fee_model, realized_pnl=realized_pnl, total_fees_paid=total_fees)
            p.positions = positions
            logger.info("Restored portfolio: $%.2f cash, %d positions, $%.2f realized P&L",
                        cash, len(positions), realized_pnl)
            return p
        else:
            logger.info("Creating fresh portfolio with $%.2f", self._starting_cash)
            return Portfolio(cash=self._starting_cash, fee_model=self._fee_model)

    def _save_state(self):
        """Persist current portfolio state to SQLite."""
        now = datetime.now(UTC).isoformat()
        p = self.portfolio

        self._conn.execute("INSERT OR REPLACE INTO portfolio_state VALUES (?, ?, ?)", ("cash", str(p.cash), now))
        self._conn.execute("INSERT OR REPLACE INTO portfolio_state VALUES (?, ?, ?)", ("realized_pnl", str(p.realized_pnl), now))
        self._conn.execute("INSERT OR REPLACE INTO portfolio_state VALUES (?, ?, ?)", ("total_fees_paid", str(p.total_fees_paid), now))

        # Sync positions
        self._conn.execute("DELETE FROM positions")
        for sym, pos in p.positions.items():
            self._conn.execute(
                "INSERT INTO positions VALUES (?, ?, ?, ?, ?)",
                (sym, pos.quantity, pos.avg_cost, pos.entry_fees, pos.opened_at.isoformat() if hasattr(pos.opened_at, 'isoformat') else str(pos.opened_at)),
            )
        self._conn.commit()

    def buy(self, symbol: str, quantity: int, price: float) -> dict | None:
        """Thread-safe buy with persistence."""
        with self._lock:
            result = self.portfolio.buy(symbol, quantity, price)
            if result:
                self._save_state()
            return result

    def sell(self, symbol: str, quantity: int, price: float) -> dict | None:
        """Thread-safe sell with persistence."""
        with self._lock:
            result = self.portfolio.sell(symbol, quantity, price)
            if result:
                self._save_state()
            return result

    def record_equity(self, prices: dict[str, float]):
        """Record a point on the equity curve for charting."""
        with self._lock:
            p = self.portfolio
            total_value = p.total_value(prices)
            unrealized = p.total_unrealized_pnl(prices)
            self._conn.execute(
                "INSERT OR REPLACE INTO equity_curve VALUES (?, ?, ?, ?, ?, ?, ?)",
                (datetime.now(UTC).isoformat(), total_value, p.cash, p.realized_pnl,
                 unrealized, p.total_fees_paid, len(p.positions)),
            )
            self._conn.commit()

    def get_equity_curve(self, limit: int = 500) -> list[dict]:
        """Get equity curve data for charting."""
        cur = self._conn.execute(
            "SELECT * FROM equity_curve ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cur.fetchall()][::-1]

    def reset(self, starting_cash: float | None = None):
        """Reset portfolio to fresh state."""
        with self._lock:
            cash = starting_cash or self._starting_cash
            self.portfolio = Portfolio(cash=cash, fee_model=self._fee_model)
            self._conn.execute("DELETE FROM portfolio_state")
            self._conn.execute("DELETE FROM positions")
            self._conn.execute("DELETE FROM equity_curve")
            self._conn.commit()
            self._save_state()
            logger.info("Portfolio reset to $%.2f", cash)

    # Delegate common properties
    @property
    def cash(self) -> float:
        return self.portfolio.cash

    @property
    def positions(self) -> dict:
        return self.portfolio.positions

    @property
    def realized_pnl(self) -> float:
        return self.portfolio.realized_pnl

    @property
    def total_fees_paid(self) -> float:
        return self.portfolio.total_fees_paid

    @property
    def fee_model(self) -> FeeModel:
        return self.portfolio.fee_model

    def total_value(self, prices: dict) -> float:
        return self.portfolio.total_value(prices)

    def total_unrealized_pnl(self, prices: dict) -> float:
        return self.portfolio.total_unrealized_pnl(prices)

    def summary(self, prices: dict) -> dict:
        return self.portfolio.summary(prices)

    def close(self):
        self._save_state()
        self._conn.close()
