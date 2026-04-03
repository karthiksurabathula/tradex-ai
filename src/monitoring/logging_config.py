"""Structured JSON logging with rotating file output.

Call setup_logging() at startup to configure console + file logging.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON with structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }

        # Add extra fields if present (e.g., trade events)
        if hasattr(record, "symbol"):
            log_entry["symbol"] = record.symbol
        if hasattr(record, "action"):
            log_entry["action"] = record.action
        if hasattr(record, "price"):
            log_entry["price"] = record.price
        if hasattr(record, "quantity"):
            log_entry["quantity"] = record.quantity
        if hasattr(record, "pnl"):
            log_entry["pnl"] = record.pnl
        if hasattr(record, "fees"):
            log_entry["fees"] = record.fees
        if hasattr(record, "extra_data"):
            log_entry["extra"] = record.extra_data

        # Include exception info if present
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console formatter."""

    FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    def __init__(self):
        super().__init__(self.FORMAT, datefmt="%Y-%m-%d %H:%M:%S")


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging to console and rotating file.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    log_dir = Path("data")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "tradex.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    # Console handler — human-readable
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # File handler — JSON structured, rotating (10MB max, 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # Capture everything to file
    file_handler.setFormatter(JSONFormatter())
    root_logger.addHandler(file_handler)

    logging.getLogger(__name__).info("Logging initialized: level=%s, file=%s", level, log_file)


def log_trade_event(
    logger: logging.Logger,
    message: str,
    symbol: str = "",
    action: str = "",
    price: float = 0.0,
    quantity: int = 0,
    pnl: float = 0.0,
    fees: float = 0.0,
) -> None:
    """Log a trade event with structured fields."""
    extra = {
        "symbol": symbol,
        "action": action,
        "price": price,
        "quantity": quantity,
        "pnl": pnl,
        "fees": fees,
    }
    logger.info(message, extra=extra)
