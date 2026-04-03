"""Append-only audit trail for every decision the system makes.

Every scan, entry, exit, and skip is recorded to data/audit.db.
Rows are NEVER updated or deleted — append only.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class AuditTrail:
    """Append-only decision log backed by SQLite."""

    def __init__(self, db_path: str = "data/audit.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                symbol TEXT,
                action TEXT,
                technicals_snapshot TEXT,
                sentiment_snapshot TEXT,
                reasoning TEXT,
                signal REAL,
                confidence REAL,
                executed INTEGER DEFAULT 0,
                portfolio_state_json TEXT
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON decisions(symbol)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(timestamp)"
        )
        self._conn.commit()

    def log_decision(
        self,
        event_type: str,
        symbol: str | None = None,
        action: str | None = None,
        technicals_snapshot: dict | None = None,
        sentiment_snapshot: dict | None = None,
        reasoning: str = "",
        signal: float = 0.0,
        confidence: float = 0.0,
        executed: bool = False,
        portfolio_state: dict | None = None,
    ) -> None:
        """Append a decision record. Never updates or deletes."""
        self._conn.execute(
            """INSERT INTO decisions
            (timestamp, event_type, symbol, action, technicals_snapshot,
             sentiment_snapshot, reasoning, signal, confidence, executed,
             portfolio_state_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(UTC).isoformat(),
                event_type,
                symbol,
                action,
                json.dumps(technicals_snapshot, default=str) if technicals_snapshot else None,
                json.dumps(sentiment_snapshot, default=str) if sentiment_snapshot else None,
                reasoning[:5000],
                signal,
                confidence,
                1 if executed else 0,
                json.dumps(portfolio_state, default=str) if portfolio_state else None,
            ),
        )
        self._conn.commit()

    def get_audit_trail(
        self,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve recent audit entries. Optionally filter by symbol."""
        if symbol:
            cur = self._conn.execute(
                "SELECT * FROM decisions WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                (symbol, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM decisions ORDER BY id DESC LIMIT ?",
                (limit,),
            )

        rows = [dict(r) for r in cur.fetchall()]
        # Parse JSON fields back to dicts for convenience
        for row in rows:
            for field in ("technicals_snapshot", "sentiment_snapshot", "portfolio_state_json"):
                if row.get(field):
                    try:
                        row[field] = json.loads(row[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
        return rows[::-1]  # Return in chronological order

    def close(self):
        self._conn.close()
