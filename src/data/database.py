"""Unified database connection module for tradex-ai.

Supports PostgreSQL (production) and SQLite (testing/fallback).
All modules import get_connection() from here instead of creating their own connections.

Usage:
    from src.data.database import get_connection, get_db_url, is_postgres

    conn = get_connection()
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = threading.Lock()

DEFAULT_DATABASE_URL = "postgresql://tradex:tradex@localhost:5432/tradex"


def get_db_url() -> str:
    """Return the configured database URL."""
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def is_postgres() -> bool:
    """Check if the configured database is PostgreSQL."""
    url = get_db_url()
    return url.startswith("postgresql://") or url.startswith("postgres://")


def _get_pool():
    """Get or create the psycopg2 connection pool (PostgreSQL only)."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        try:
            import psycopg2.pool

            url = get_db_url()
            _pool = psycopg2.pool.SimpleConnectionPool(minconn=1, maxconn=10, dsn=url)
            logger.info("PostgreSQL connection pool created: %s", url.split("@")[-1] if "@" in url else url)
            return _pool
        except Exception as e:
            logger.error("Failed to create PostgreSQL pool: %s", e)
            raise


def get_connection():
    """Return a database connection.

    - If DATABASE_URL points to PostgreSQL, returns a psycopg2 connection from the pool.
    - If DATABASE_URL is a sqlite:// URI or file path, returns a sqlite3 connection.
    - For testing: set DATABASE_URL=sqlite://:memory: for in-memory SQLite.
    """
    url = get_db_url()

    if url.startswith("postgresql://") or url.startswith("postgres://"):
        pool = _get_pool()
        conn = pool.getconn()
        conn.autocommit = False
        return conn

    # SQLite fallback
    if url.startswith("sqlite://"):
        db_path = url.replace("sqlite:///", "").replace("sqlite://", "")
        if not db_path or db_path == ":memory:":
            db_path = ":memory:"
    else:
        db_path = url

    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def release_connection(conn):
    """Release a connection back to the pool (PostgreSQL) or no-op (SQLite)."""
    if is_postgres():
        try:
            pool = _get_pool()
            pool.putconn(conn)
        except Exception:
            pass


def close_pool():
    """Close the connection pool. Call on application shutdown."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL connection pool closed.")


def execute_sql(conn, sql: str, params: tuple = ()) -> object:
    """Execute SQL, handling placeholder differences.

    For PostgreSQL, expects %s placeholders.
    For SQLite, expects ? placeholders.
    This function does NOT auto-convert — callers must use the correct style.
    Use get_placeholder() to get the right placeholder character.
    """
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def get_placeholder() -> str:
    """Return the correct SQL placeholder for the current database backend.

    Returns '%s' for PostgreSQL, '?' for SQLite.
    """
    return "%s" if is_postgres() else "?"


def get_serial_type() -> str:
    """Return the correct auto-increment primary key type.

    Returns 'SERIAL PRIMARY KEY' for PostgreSQL, 'INTEGER PRIMARY KEY AUTOINCREMENT' for SQLite.
    """
    return "SERIAL PRIMARY KEY" if is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"


def upsert_sql(table: str, columns: list[str], conflict_column: str, update_columns: list[str] | None = None) -> str:
    """Generate an UPSERT statement compatible with current backend.

    For PostgreSQL: INSERT ... ON CONFLICT (col) DO UPDATE SET ...
    For SQLite: INSERT OR REPLACE INTO ...
    """
    ph = get_placeholder()
    col_list = ", ".join(columns)
    val_list = ", ".join([ph] * len(columns))

    if is_postgres():
        if update_columns:
            set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_columns)
            return f"INSERT INTO {table} ({col_list}) VALUES ({val_list}) ON CONFLICT ({conflict_column}) DO UPDATE SET {set_clause}"
        else:
            # Update all non-conflict columns
            non_conflict = [c for c in columns if c != conflict_column]
            set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in non_conflict)
            return f"INSERT INTO {table} ({col_list}) VALUES ({val_list}) ON CONFLICT ({conflict_column}) DO UPDATE SET {set_clause}"
    else:
        return f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({val_list})"


def insert_ignore_sql(table: str, columns: list[str], conflict_columns: list[str] | None = None) -> str:
    """Generate an INSERT-or-ignore statement compatible with current backend.

    For PostgreSQL: INSERT ... ON CONFLICT DO NOTHING
    For SQLite: INSERT OR IGNORE INTO ...
    """
    ph = get_placeholder()
    col_list = ", ".join(columns)
    val_list = ", ".join([ph] * len(columns))

    if is_postgres():
        if conflict_columns:
            conflict = ", ".join(conflict_columns)
            return f"INSERT INTO {table} ({col_list}) VALUES ({val_list}) ON CONFLICT ({conflict}) DO NOTHING"
        return f"INSERT INTO {table} ({col_list}) VALUES ({val_list}) ON CONFLICT DO NOTHING"
    else:
        return f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({val_list})"


def dict_cursor(conn):
    """Return a cursor that returns rows as dicts.

    For PostgreSQL: uses RealDictCursor.
    For SQLite: uses row_factory (already set in get_connection).
    """
    if is_postgres():
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        return conn.cursor()


def row_to_dict(row) -> dict:
    """Convert a database row to a dict, handling both backends."""
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        # sqlite3.Row
        return dict(row)
    return dict(row)
