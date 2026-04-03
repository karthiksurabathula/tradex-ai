"""Health checks and heartbeat for the trading system.

Monitors: yfinance connectivity, database writability, data freshness, scheduler heartbeat.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from src.data.database import get_connection, get_placeholder, is_postgres

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


def _check_database() -> dict:
    """Check if the database is writable with a test row."""
    try:
        conn = get_connection()
        ph = get_placeholder()
        conn.execute("CREATE TABLE IF NOT EXISTS health (ts TEXT, val TEXT)")
        now = datetime.now(UTC).isoformat()
        conn.execute(f"INSERT INTO health VALUES ({ph}, {ph})", (now, "ok"))
        conn.commit()
        cur = conn.cursor()
        cur.execute("SELECT val FROM health ORDER BY ts DESC LIMIT 1")
        row = cur.fetchone()
        conn.execute("DELETE FROM health")
        conn.commit()

        db_type = "PostgreSQL" if is_postgres() else "SQLite"
        if row and (row[0] if not isinstance(row, dict) else row.get("val")) == "ok":
            return {"name": "database", "status": "ok", "message": f"{db_type} read/write successful"}
        return {"name": "database", "status": "error", "message": f"{db_type} read-back mismatch"}
    except Exception as e:
        return {"name": "database", "status": "error", "message": str(e)}


def _check_data_freshness() -> dict:
    """Check if last quote data is stale (> 30 minutes old)."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT MAX(timestamp) FROM quotes")
            row = cur.fetchone()
        except Exception:
            return {"name": "data_freshness", "status": "warning", "message": "No quotes table found"}

        if not row or not (row[0] if not isinstance(row, dict) else row.get("max")):
            return {"name": "data_freshness", "status": "warning", "message": "No quotes in database"}

        last_val = row[0] if not isinstance(row, dict) else row.get("max")

        from dateutil.parser import parse as parse_dt

        last_ts = parse_dt(last_val)
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
        _check_database(),
        _check_data_freshness(),
        _check_heartbeat(),
    ]

    for r in results:
        level = logging.INFO if r["status"] == "ok" else logging.WARNING
        logger.log(level, "Health [%s]: %s -- %s", r["name"], r["status"], r["message"])

    return results
