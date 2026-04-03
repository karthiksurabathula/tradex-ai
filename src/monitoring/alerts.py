"""Real-time alert system with pluggable backends.

Supports Slack webhook and console alerts. Fires on large losses,
daily limit hits, kill switch activation, and system errors.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class AlertBackend(ABC):
    """Base class for alert backends."""

    @abstractmethod
    def send(self, level: str, title: str, message: str, symbol: str | None = None) -> bool:
        """Send an alert. Returns True if sent successfully."""
        ...


class ConsoleAlert(AlertBackend):
    """Prints alerts to stdout — always active."""

    def send(self, level: str, title: str, message: str, symbol: str | None = None) -> bool:
        sym = f" [{symbol}]" if symbol else ""
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[ALERT {level}] {timestamp}{sym} {title}: {message}")
        return True


class SlackWebhook(AlertBackend):
    """Sends alerts to a Slack webhook URL."""

    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")

    def send(self, level: str, title: str, message: str, symbol: str | None = None) -> bool:
        if not self.webhook_url:
            logger.debug("Slack webhook URL not configured; skipping alert")
            return False

        try:
            import httpx

            emoji = {"critical": ":rotating_light:", "warning": ":warning:", "info": ":information_source:"}.get(
                level.lower(), ":bell:"
            )

            sym_text = f" `{symbol}`" if symbol else ""
            payload = {
                "text": f"{emoji} *[{level.upper()}]{sym_text} {title}*\n{message}",
            }

            response = httpx.post(self.webhook_url, json=payload, timeout=10)
            if response.status_code == 200:
                return True
            else:
                logger.warning("Slack webhook returned %d: %s", response.status_code, response.text)
                return False
        except Exception as e:
            logger.warning("Slack alert failed: %s", e)
            return False


class AlertManager:
    """Manages multiple alert backends and dispatches alerts."""

    def __init__(self):
        self.backends: list[AlertBackend] = [ConsoleAlert()]

        # Auto-configure Slack if webhook URL is available
        slack_url = os.environ.get("SLACK_WEBHOOK_URL", "")
        if slack_url:
            self.backends.append(SlackWebhook(slack_url))

    def add_backend(self, backend: AlertBackend):
        """Register an additional alert backend."""
        self.backends.append(backend)

    def send_alert(
        self,
        level: str,
        title: str,
        message: str,
        symbol: str | None = None,
    ) -> None:
        """Dispatch an alert to all registered backends.

        Args:
            level: Alert severity — "info", "warning", "critical".
            title: Short alert title.
            message: Detailed message body.
            symbol: Optional ticker symbol related to the alert.
        """
        for backend in self.backends:
            try:
                backend.send(level, title, message, symbol)
            except Exception as e:
                logger.error("Alert backend %s failed: %s", type(backend).__name__, e)

    # ── Convenience methods for common alert scenarios ────────────────────────

    def alert_large_loss(self, symbol: str, loss_pct: float, loss_amount: float):
        """Alert when a position loses more than 2%."""
        if abs(loss_pct) > 0.02:
            self.send_alert(
                "warning",
                "Large Loss Detected",
                f"Loss of {loss_pct:.1%} (${loss_amount:,.2f}) on position",
                symbol=symbol,
            )

    def alert_daily_limit(self, reason: str):
        """Alert when daily trading limit is hit."""
        self.send_alert("critical", "Daily Limit Hit", reason)

    def alert_kill_switch(self, reason: str):
        """Alert when kill switch is activated."""
        self.send_alert("critical", "Kill Switch Activated", reason)

    def alert_system_error(self, error: str, module: str = ""):
        """Alert on system errors."""
        self.send_alert("critical", f"System Error in {module}" if module else "System Error", error)
