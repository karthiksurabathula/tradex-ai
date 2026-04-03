"""Persistent portfolio state -- survives restarts, crash-safe.

Wraps Portfolio with database persistence and thread-safe operations.
Every buy/sell is atomically saved. On startup, state is restored.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime

from src.data.database import (
    dict_cursor,
    get_connection,
    get_placeholder,
    is_postgres,
    upsert_sql,
)
from src.execution.fees import FeeModel
from src.execution.portfolio import Portfolio, Position

logger = logging.getLogger(__name__)


class PersistentPortfolio:
    """Thread-safe, crash-recoverable portfolio backed by the database."""

    def __init__(self, db_path: str = "data/portfolio.db", starting_cash: float = 100_000.0, fee_model: FeeModel | None = None):
        self._conn = get_connection()
        self._lock = threading.Lock()
        self._fee_model = fee_model or FeeModel()
        self._starting_cash = starting_cash
        self._init_schema()
        self.portfolio = self._load_or_create()

    def _init_schema(self):
        cur = self._conn.cursor()
        if is_postgres():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL,
                    avg_cost REAL NOT NULL,
                    entry_fees REAL DEFAULT 0,
                    opened_at TEXT NOT NULL,
                    is_short INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS equity_curve (
                    timestamp TEXT PRIMARY KEY,
                    total_value REAL,
                    cash REAL,
                    realized_pnl REAL,
                    unrealized_pnl REAL,
                    total_fees REAL,
                    position_count INTEGER
                )
            """)
        else:
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
                    opened_at TEXT NOT NULL,
                    is_short INTEGER DEFAULT 0
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
        cur = dict_cursor(self._conn)
        cur.execute("SELECT key, value FROM portfolio_state")
        state = {r["key"]: r["value"] for r in cur.fetchall()}

        if state:
            cash = float(state.get("cash", self._starting_cash))
            realized_pnl = float(state.get("realized_pnl", 0))
            total_fees = float(state.get("total_fees_paid", 0))

            # Load positions
            positions = {}
            cur2 = dict_cursor(self._conn)
            cur2.execute("SELECT * FROM positions")
            for row in cur2.fetchall():
                row = dict(row)
                positions[row["symbol"]] = Position(
                    symbol=row["symbol"],
                    quantity=row["quantity"],
                    avg_cost=row["avg_cost"],
                    entry_fees=row["entry_fees"],
                    is_short=bool(row["is_short"]) if "is_short" in row else False,
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
        """Persist current portfolio state to database."""
        now = datetime.now(UTC).isoformat()
        p = self.portfolio
        ph = get_placeholder()

        upsert = upsert_sql("portfolio_state", ["key", "value", "updated_at"], "key", ["value", "updated_at"])
        self._conn.execute(upsert, ("cash", str(p.cash), now))
        self._conn.execute(upsert, ("realized_pnl", str(p.realized_pnl), now))
        self._conn.execute(upsert, ("total_fees_paid", str(p.total_fees_paid), now))

        # Sync positions
        self._conn.execute("DELETE FROM positions")
        for sym, pos in p.positions.items():
            self._conn.execute(
                f"INSERT INTO positions VALUES ({', '.join([ph] * 6)})",
                (sym, pos.quantity, pos.avg_cost, pos.entry_fees,
                 pos.opened_at.isoformat() if hasattr(pos.opened_at, 'isoformat') else str(pos.opened_at),
                 1 if pos.is_short else 0),
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

    def short(self, symbol: str, quantity: int, price: float) -> dict | None:
        """Thread-safe short with persistence."""
        with self._lock:
            result = self.portfolio.short(symbol, quantity, price)
            if result:
                self._save_state()
            return result

    def cover(self, symbol: str, quantity: int, price: float) -> dict | None:
        """Thread-safe cover with persistence."""
        with self._lock:
            result = self.portfolio.cover(symbol, quantity, price)
            if result:
                self._save_state()
            return result

    def record_equity(self, prices: dict[str, float]):
        """Record a point on the equity curve for charting."""
        ph = get_placeholder()
        with self._lock:
            p = self.portfolio
            total_value = p.total_value(prices)
            unrealized = p.total_unrealized_pnl(prices)
            upsert = upsert_sql(
                "equity_curve",
                ["timestamp", "total_value", "cash", "realized_pnl", "unrealized_pnl", "total_fees", "position_count"],
                "timestamp",
            )
            self._conn.execute(
                upsert,
                (datetime.now(UTC).isoformat(), total_value, p.cash, p.realized_pnl,
                 unrealized, p.total_fees_paid, len(p.positions)),
            )
            self._conn.commit()

    def get_equity_curve(self, limit: int = 500) -> list[dict]:
        """Get equity curve data for charting."""
        ph = get_placeholder()
        cur = dict_cursor(self._conn)
        cur.execute(
            f"SELECT * FROM equity_curve ORDER BY timestamp DESC LIMIT {ph}", (limit,)
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
