"""Health checks and heartbeat for the trading system.

Monitors: yfinance connectivity, SQLite writability, data freshness, scheduler heartbeat.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

HEARTBEAT_FILE = Path("data/.heartbeat")


def _check_yfinance() -> dict:
    """Check if yfinance is responding by fetching SPY price."""
    try:
        import yfinance as yf

        ticker = yf.Ticker("SPY")
        hist = ticker.history(period="1d")
        if hist.empty:
            return {"name": "yfinance", "status": "degraded", "message": "SPY returned empty data"}
        price = float(hist["Close"].iloc[-1])
        return {"name": "yfinance", "status": "ok", "message": f"SPY last close: ${price:.2f}"}
    except Exception as e:
        return {"name": "yfinance", "status": "error", "message": str(e)}


def _check_sqlite() -> dict:
    """Check if SQLite is writable with a test row."""
    db_path = Path("data/health_check.db")
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE IF NOT EXISTS health (ts TEXT, val TEXT)")
        now = datetime.now(UTC).isoformat()
        conn.execute("INSERT INTO health VALUES (?, ?)", (now, "ok"))
        conn.commit()
        cur = conn.execute("SELECT val FROM health ORDER BY ts DESC LIMIT 1")
        row = cur.fetchone()
        conn.execute("DELETE FROM health")
        conn.commit()
        conn.close()
        if row and row[0] == "ok":
            return {"name": "sqlite", "status": "ok", "message": "Read/write successful"}
        return {"name": "sqlite", "status": "error", "message": "Read-back mismatch"}
    except Exception as e:
        return {"name": "sqlite", "status": "error", "message": str(e)}


def _check_data_freshness() -> dict:
    """Check if last quote data is stale (> 30 minutes old)."""
    try:
        db_path = Path("data/quotes.db")
        if not db_path.exists():
            return {"name": "data_freshness", "status": "warning", "message": "No quotes database found"}

        conn = sqlite3.connect(str(db_path))
        cur = conn.execute("SELECT MAX(timestamp) FROM quotes")
        row = cur.fetchone()
        conn.close()

        if not row or not row[0]:
            return {"name": "data_freshness", "status": "warning", "message": "No quotes in database"}

        from dateutil.parser import parse as parse_dt

        last_ts = parse_dt(row[0])
        if last_ts.tzinfo is None:
            from datetime import timezone
            last_ts = last_ts.replace(tzinfo=timezone.utc)

        age_minutes = (datetime.now(UTC) - last_ts).total_seconds() / 60

        if age_minutes > 30:
            return {
                "name": "data_freshness",
                "status": "stale",
                "message": f"Last quote is {age_minutes:.0f} min old (> 30 min threshold)",
            }
        return {
            "name": "data_freshness",
            "status": "ok",
            "message": f"Last quote is {age_minutes:.0f} min old",
        }
    except Exception as e:
        return {"name": "data_freshness", "status": "error", "message": str(e)}


def _check_heartbeat() -> dict:
    """Check if the scheduler heartbeat file is recent."""
    try:
        if not HEARTBEAT_FILE.exists():
            return {"name": "heartbeat", "status": "warning", "message": "No heartbeat file found"}

        content = HEARTBEAT_FILE.read_text().strip()
        try:
            from dateutil.parser import parse as parse_dt

            last_beat = parse_dt(content)
            if last_beat.tzinfo is None:
                from datetime import timezone
                last_beat = last_beat.replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(UTC) - last_beat).total_seconds()
        except Exception:
            mtime = HEARTBEAT_FILE.stat().st_mtime
            age_seconds = time.time() - mtime

        if age_seconds > 600:  # 10 minutes
            return {
                "name": "heartbeat",
                "status": "stale",
                "message": f"Last heartbeat {age_seconds:.0f}s ago (> 600s threshold)",
            }
        return {
            "name": "heartbeat",
            "status": "ok",
            "message": f"Last heartbeat {age_seconds:.0f}s ago",
        }
    except Exception as e:
        return {"name": "heartbeat", "status": "error", "message": str(e)}


def write_heartbeat():
    """Write current timestamp to the heartbeat file. Call on every cycle."""
    HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_FILE.write_text(datetime.now(UTC).isoformat())


def run_health_check() -> list[dict]:
    """Run all health checks and return results.

    Returns:
        List of dicts with keys: name, status, message.
        status is one of: ok, warning, degraded, stale, error.
    """
    results = [
        _check_yfinance(),
        _check_sqlite(),
        _check_data_freshness(),
        _check_heartbeat(),
    ]

    for r in results:
        level = logging.INFO if r["status"] == "ok" else logging.WARNING
        logger.log(level, "Health [%s]: %s — %s", r["name"], r["status"], r["message"])

    return results
