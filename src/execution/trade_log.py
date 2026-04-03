"""SQLite-backed trade journal for logging every signal and execution."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from src.state.models import TradeSignal


class TradeLog:
    def __init__(self, db_path: str = "data/trades.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                price REAL DEFAULT 0,
                effective_price REAL DEFAULT 0,
                gross_pnl REAL,
                net_pnl REAL,
                fee_commission REAL DEFAULT 0,
                fee_spread REAL DEFAULT 0,
                fee_slippage REAL DEFAULT 0,
                fee_sec REAL DEFAULT 0,
                fee_total REAL DEFAULT 0,
                confidence REAL DEFAULT 0,
                reasoning TEXT DEFAULT '',
                executed BOOLEAN DEFAULT 0,
                reason TEXT DEFAULT ''
            )
        """)
        self.conn.commit()

    def record(
        self,
        signal: TradeSignal,
        price: float,
        executed: bool,
        quantity: int = 0,
        gross_pnl: float | None = None,
        net_pnl: float | None = None,
        fees: dict | None = None,
        reason: str = "",
    ):
        """Record a trade (executed or not) with full fee breakdown."""
        fees = fees or {}
        effective_price = fees.get("effective_price", price)

        self.conn.execute(
            """INSERT INTO trades
            (timestamp, symbol, action, quantity, price, effective_price,
             gross_pnl, net_pnl, fee_commission, fee_spread, fee_slippage,
             fee_sec, fee_total, confidence, reasoning, executed, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(UTC).isoformat(),
                signal.symbol,
                signal.action.value,
                quantity,
                price,
                effective_price,
                gross_pnl,
                net_pnl,
                fees.get("commission", 0),
                fees.get("spread", 0),
                fees.get("slippage", 0),
                fees.get("sec_fee", 0),
                fees.get("total", 0),
                signal.confidence,
                signal.reasoning[:2000],
                executed,
                reason,
            ),
        )
        self.conn.commit()

    def recent_trades(self, symbol: str | None = None, limit: int = 20) -> list[dict]:
        if symbol:
            cur = self.conn.execute(
                "SELECT * FROM trades WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                (symbol, limit),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
        return [dict(row) for row in cur.fetchall()]

    def performance_summary(self, symbol: str | None = None) -> dict:
        """Win rate, avg PnL, total trades, total fees for feedback loop."""
        where = "WHERE executed = 1 AND net_pnl IS NOT NULL"
        params: tuple = ()
        if symbol:
            where += " AND symbol = ?"
            params = (symbol,)

        cur = self.conn.execute(
            f"""
            SELECT
                COUNT(*) as total,
                COALESCE(SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END), 0) as wins,
                COALESCE(SUM(CASE WHEN net_pnl < 0 THEN 1 ELSE 0 END), 0) as losses,
                COALESCE(AVG(net_pnl), 0) as avg_pnl,
                COALESCE(SUM(net_pnl), 0) as total_pnl,
                COALESCE(SUM(fee_total), 0) as total_fees,
                COALESCE(SUM(gross_pnl), 0) as gross_pnl
            FROM trades {where}
            """,
            params,
        )
        row = cur.fetchone()
        total = row[0] or 0
        return {
            "total_trades": total,
            "wins": row[1],
            "losses": row[2],
            "avg_pnl": round(row[3], 4),
            "total_pnl": round(row[4], 4),
            "total_fees": round(row[5], 4),
            "gross_pnl": round(row[6], 4),
            "win_rate": round(row[1] / total, 4) if total > 0 else 0,
        }

    def close(self):
        self.conn.close()
