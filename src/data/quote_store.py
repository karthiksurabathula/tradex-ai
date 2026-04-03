"""Persistent quote store — collects and stores OHLCV data over time.

The broker builds its own historical database for backtesting,
pattern recognition, and strategy evolution.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class QuoteStore:
    """SQLite-backed time-series store for OHLCV quotes."""

    def __init__(self, db_path: str = "data/quotes.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS quotes (
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                interval TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL,
                volume INTEGER,
                PRIMARY KEY (symbol, timestamp, interval)
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY,
                added_at TEXT NOT NULL,
                added_by TEXT DEFAULT 'broker',
                reason TEXT DEFAULT '',
                active INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_quotes_sym_ts ON quotes(symbol, timestamp);
            CREATE INDEX IF NOT EXISTS idx_quotes_interval ON quotes(interval);
        """)
        self.conn.commit()

    # ── Watchlist ────────────────────────────────────────────────────────────
    def add_to_watchlist(self, symbol: str, reason: str = "", added_by: str = "broker"):
        self.conn.execute(
            "INSERT OR REPLACE INTO watchlist (symbol, added_at, added_by, reason, active) VALUES (?, ?, ?, ?, 1)",
            (symbol, datetime.now(UTC).isoformat(), added_by, reason),
        )
        self.conn.commit()
        logger.info("Added %s to watchlist: %s", symbol, reason)

    def remove_from_watchlist(self, symbol: str):
        self.conn.execute("UPDATE watchlist SET active = 0 WHERE symbol = ?", (symbol,))
        self.conn.commit()

    def get_watchlist(self) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM watchlist WHERE active = 1 ORDER BY added_at DESC")
        return [dict(r) for r in cur.fetchall()]

    def get_watchlist_symbols(self) -> list[str]:
        return [r["symbol"] for r in self.get_watchlist()]

    # ── Quote Collection ─────────────────────────────────────────────────────
    def collect(self, symbol: str, period: str = "5d", interval: str = "5m") -> int:
        """Fetch and store quotes for a symbol. Returns number of new bars stored."""
        try:
            hist = yf.Ticker(symbol).history(period=period, interval=interval)
            if hist.empty:
                return 0

            count = 0
            for idx, row in hist.iterrows():
                ts = str(idx)
                try:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO quotes (symbol, timestamp, interval, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (symbol, ts, interval, float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), int(row["Volume"])),
                    )
                    count += 1
                except sqlite3.IntegrityError:
                    pass
            self.conn.commit()
            return count
        except Exception as e:
            logger.error("Quote collection failed for %s: %s", symbol, e)
            return 0

    def collect_watchlist(self, period: str = "5d", interval: str = "5m") -> dict[str, int]:
        """Collect quotes for all watchlist symbols."""
        results = {}
        for sym in self.get_watchlist_symbols():
            results[sym] = self.collect(sym, period, interval)
        logger.info("Collected quotes for %d symbols", len(results))
        return results

    # ── Query ────────────────────────────────────────────────────────────────
    def get_quotes(self, symbol: str, interval: str = "5m", limit: int = 1000) -> pd.DataFrame:
        """Get stored quotes as a DataFrame."""
        cur = self.conn.execute(
            "SELECT * FROM quotes WHERE symbol = ? AND interval = ? ORDER BY timestamp DESC LIMIT ?",
            (symbol, interval, limit),
        )
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def get_quote_count(self, symbol: str | None = None) -> int:
        if symbol:
            cur = self.conn.execute("SELECT COUNT(*) FROM quotes WHERE symbol = ?", (symbol,))
        else:
            cur = self.conn.execute("SELECT COUNT(*) FROM quotes")
        return cur.fetchone()[0]

    def get_symbols_with_quotes(self) -> list[dict]:
        """List all symbols with quote counts."""
        cur = self.conn.execute(
            "SELECT symbol, COUNT(*) as bars, MIN(timestamp) as first, MAX(timestamp) as last FROM quotes GROUP BY symbol ORDER BY bars DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self):
        self.conn.close()
