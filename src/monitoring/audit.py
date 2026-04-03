"""Append-only audit trail for every decision the system makes.

Every scan, entry, exit, and skip is recorded.
Rows are NEVER updated or deleted -- append only.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from src.data.database import (
    dict_cursor,
    get_connection,
    get_placeholder,
    get_serial_type,
    is_postgres,
)

logger = logging.getLogger(__name__)


class AuditTrail:
    """Append-only decision log backed by the database."""

    def __init__(self, db_path: str = "data/audit.db"):
        self._conn = get_connection()
        self._init_schema()

    def _init_schema(self):
        serial = get_serial_type()
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS decisions (
                id {serial},
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
        ph = get_placeholder()
        self._conn.execute(
            f"""INSERT INTO decisions
            (timestamp, event_type, symbol, action, technicals_snapshot,
             sentiment_snapshot, reasoning, signal, confidence, executed,
             portfolio_state_json)
            VALUES ({', '.join([ph] * 11)})""",
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
        ph = get_placeholder()
        cur = dict_cursor(self._conn)
        if symbol:
            cur.execute(
                f"SELECT * FROM decisions WHERE symbol = {ph} ORDER BY id DESC LIMIT {ph}",
                (symbol, limit),
            )
        else:
            cur.execute(
                f"SELECT * FROM decisions ORDER BY id DESC LIMIT {ph}",
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
