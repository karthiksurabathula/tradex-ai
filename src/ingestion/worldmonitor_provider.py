"""WorldMonitor API provider for real-time news and macro-sentiment analysis."""

from __future__ import annotations

import logging

import httpx

from src.state.models import NewsSentiment

logger = logging.getLogger(__name__)


class WorldMonitorProvider:
    """Fetches news headlines, sentiment scores, and macro events from WorldMonitor."""

    def __init__(self, api_base: str, api_key: str, timeout: float = 30.0):
        self.client = httpx.Client(
            base_url=api_base,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def fetch_headlines(self, category: str = "markets", limit: int = 20) -> list[dict]:
        """Fetch latest headlines from WorldMonitor REST API."""
        logger.info("Fetching %d headlines (category=%s)", limit, category)
        try:
            resp = self.client.get(
                "/v1/news/headlines", params={"category": category, "limit": limit}
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("articles", data.get("headlines", []))
        except httpx.HTTPError as e:
            logger.error("WorldMonitor headlines fetch failed: %s", e)
            return []

    def fetch_sentiment(self, region: str = "global") -> NewsSentiment:
        """Fetch aggregated sentiment scores."""
        logger.info("Fetching sentiment (region=%s)", region)
        try:
            resp = self.client.get("/v1/sentiment/aggregate", params={"region": region})
            resp.raise_for_status()
            data = resp.json()
            return NewsSentiment(
                overall_score=data.get("sentiment_score", 0.0),
                confidence=data.get("confidence", 0.0),
                top_themes=data.get("themes", []),
                instability_index=data.get("country_instability_index"),
                headline_count=data.get("article_count", 0),
                source="worldmonitor",
            )
        except httpx.HTTPError as e:
            logger.error("WorldMonitor sentiment fetch failed: %s", e)
            return NewsSentiment(
                overall_score=0.0, confidence=0.0, source="worldmonitor_fallback"
            )

    def fetch_macro_events(self, window: str = "7d") -> list[dict]:
        """Fetch conflict/macro events (ACLED, GDELT sourced)."""
        logger.info("Fetching macro events (window=%s)", window)
        try:
            resp = self.client.get("/v1/events/macro", params={"window": window})
            resp.raise_for_status()
            data = resp.json()
            return data.get("events", [])
        except httpx.HTTPError as e:
            logger.error("WorldMonitor macro events fetch failed: %s", e)
            return []

    def close(self):
        self.client.close()
