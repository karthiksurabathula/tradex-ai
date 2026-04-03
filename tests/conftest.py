"""Shared test configuration.

Sets DATABASE_URL to SQLite in-memory for all tests unless PostgreSQL is explicitly available.
"""

import os


def _postgres_available() -> bool:
    """Check if PostgreSQL is reachable at the configured URL."""
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql://") and not url.startswith("postgres://"):
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(url)
        conn.close()
        return True
    except Exception:
        return False


# Default to SQLite in-memory for tests unless PG is explicitly set and reachable
if not _postgres_available():
    os.environ["DATABASE_URL"] = "sqlite://:memory:"
