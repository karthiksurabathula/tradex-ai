"""Persistent quote store -- collects and stores OHLCV data over time.

The broker builds its own historical database for backtesting,
pattern recognition, and strategy evolution.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pandas as pd
import yfinance as yf

from src.data.database import (
    dict_cursor,
    get_connection,
    get_placeholder,
    insert_ignore_sql,
    is_postgres,
    upsert_sql,
)

logger = logging.getLogger(__name__)


class QuoteStore:
    """Database-backed time-series store for OHLCV quotes."""

    def __init__(self, db_path: str = "data/quotes.db"):
        self.conn = get_connection()
        self._init_schema()

    def _init_schema(self):
        if is_postgres():
            cur = self.conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS quotes (
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open REAL, high REAL, low REAL, close REAL,
                    volume INTEGER,
                    PRIMARY KEY (symbol, timestamp, interval)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol TEXT PRIMARY KEY,
                    added_at TEXT NOT NULL,
                    added_by TEXT DEFAULT 'broker',
                    reason TEXT DEFAULT '',
                    active INTEGER DEFAULT 1
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_quotes_sym_ts ON quotes(symbol, timestamp)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_quotes_interval ON quotes(interval)")
        else:
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

    # -- Watchlist ----------------------------------------------------------------
    def add_to_watchlist(self, symbol: str, reason: str = "", added_by: str = "broker"):
        upsert = upsert_sql(
            "watchlist",
            ["symbol", "added_at", "added_by", "reason", "active"],
            "symbol",
            ["added_at", "added_by", "reason", "active"],
        )
        self.conn.execute(
            upsert,
            (symbol, datetime.now(UTC).isoformat(), added_by, reason, 1),
        )
        self.conn.commit()
        logger.info("Added %s to watchlist: %s", symbol, reason)

    def remove_from_watchlist(self, symbol: str):
        ph = get_placeholder()
        self.conn.execute(f"UPDATE watchlist SET active = 0 WHERE symbol = {ph}", (symbol,))
        self.conn.commit()

    def get_watchlist(self) -> list[dict]:
        cur = dict_cursor(self.conn)
        cur.execute("SELECT * FROM watchlist WHERE active = 1 ORDER BY added_at DESC")
        return [dict(r) for r in cur.fetchall()]

    def get_watchlist_symbols(self) -> list[str]:
        return [r["symbol"] for r in self.get_watchlist()]

    # -- Quote Collection ---------------------------------------------------------
    def collect(self, symbol: str, period: str = "5d", interval: str = "5m") -> int:
        """Fetch and store quotes for a symbol. Returns number of new bars stored."""
        try:
            hist = yf.Ticker(symbol).history(period=period, interval=interval)
            if hist.empty:
                return 0

            insert_sql = insert_ignore_sql(
                "quotes",
                ["symbol", "timestamp", "interval", "open", "high", "low", "close", "volume"],
                ["symbol", "timestamp", "interval"],
            )

            count = 0
            for idx, row in hist.iterrows():
                ts = str(idx)
                try:
                    self.conn.execute(
                        insert_sql,
                        (symbol, ts, interval, float(row["Open"]), float(row["High"]),
                         float(row["Low"]), float(row["Close"]), int(row["Volume"])),
                    )
                    count += 1
                except Exception:
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

    # -- Query --------------------------------------------------------------------
    def get_quotes(self, symbol: str, interval: str = "5m", limit: int = 1000) -> pd.DataFrame:
        """Get stored quotes as a DataFrame."""
        ph = get_placeholder()
        cur = dict_cursor(self.conn)
        cur.execute(
            f"SELECT * FROM quotes WHERE symbol = {ph} AND interval = {ph} ORDER BY timestamp DESC LIMIT {ph}",
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
        ph = get_placeholder()
        if symbol:
            cur = self.conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM quotes WHERE symbol = {ph}", (symbol,))
        else:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM quotes")
        return cur.fetchone()[0]

    def get_symbols_with_quotes(self) -> list[dict]:
        """List all symbols with quote counts."""
        cur = dict_cursor(self.conn)
        cur.execute(
            "SELECT symbol, COUNT(*) as bars, MIN(timestamp) as first, MAX(timestamp) as last FROM quotes GROUP BY symbol ORDER BY bars DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self):
        self.conn.close()
