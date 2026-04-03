"""GDELT provider — free, no API key required, real-time global news with sentiment/tone."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx

from src.state.models import NewsSentiment

logger = logging.getLogger(__name__)

# GDELT DOC 2.0 API — free, no authentication, no rate limits
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_GEO_API = "https://api.gdeltproject.org/api/v2/geo/geo"


class GdeltProvider:
    """Fetches news headlines and sentiment from GDELT (free, no API key).

    GDELT's "tone" field ranges from -100 (extremely negative) to +100 (extremely positive).
    We normalize to -1.0 to +1.0 to match the NewsSentiment model.
    """

    def __init__(self, timeout: float = 30.0, request_delay: float = 1.0):
        self.client = httpx.Client(timeout=timeout)
        self.request_delay = request_delay  # Seconds between GDELT calls to avoid 429
        self._last_request: float = 0.0

    def _throttled_get(self, url: str, params: dict) -> httpx.Response:
        """Rate-limited GET request to avoid GDELT 429 errors."""
        elapsed = time.time() - self._last_request
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        resp = self.client.get(url, params=params)
        self._last_request = time.time()
        return resp

    def fetch_headlines(self, query: str = "stock market OR trading", limit: int = 20) -> list[dict]:
        """Fetch latest headlines matching a query from GDELT DOC API."""
        logger.info("Fetching GDELT headlines: %s", query)
        try:
            resp = self._throttled_get(
                GDELT_DOC_API,
                params={
                    "query": query,
                    "mode": "ArtList",
                    "maxrecords": str(limit),
                    "format": "json",
                    "sort": "DateDesc",
                    "timespan": "60min",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("articles", [])
            return [
                {
                    "title": a.get("title", ""),
                    "url": a.get("url", ""),
                    "source": a.get("domain", ""),
                    "date": a.get("seendate", ""),
                    "tone": a.get("tone", 0),
                    "language": a.get("language", "English"),
                }
                for a in articles
            ]
        except (httpx.HTTPError, Exception) as e:
            logger.error("GDELT headlines fetch failed: %s", e)
            return []

    def fetch_sentiment(self, query: str = "stock market OR economy OR trading") -> NewsSentiment:
        """Compute aggregated sentiment from recent GDELT articles' tone scores."""
        logger.info("Fetching GDELT sentiment for: %s", query)
        try:
            resp = self._throttled_get(
                GDELT_DOC_API,
                params={
                    "query": query,
                    "mode": "ToneChart",
                    "format": "json",
                    "timespan": "60min",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # ToneChart returns time-bucketed tone averages
            tone_data = data.get("tonechart", [])
            if tone_data:
                avg_tone = sum(t.get("tone", 0) for t in tone_data) / len(tone_data)
                # Normalize GDELT tone (-100 to +100) → (-1.0 to +1.0)
                normalized = max(-1.0, min(1.0, avg_tone / 10.0))
                confidence = min(1.0, len(tone_data) / 50.0)
            else:
                normalized = 0.0
                confidence = 0.0

            # Fetch top themes via a separate call
            themes = self._fetch_themes(query)

            return NewsSentiment(
                overall_score=round(normalized, 4),
                confidence=round(confidence, 4),
                top_themes=themes,
                instability_index=None,
                headline_count=len(tone_data),
                source="gdelt",
            )
        except (httpx.HTTPError, Exception) as e:
            logger.error("GDELT sentiment fetch failed: %s", e)
            return NewsSentiment(
                overall_score=0.0, confidence=0.0, source="gdelt_fallback"
            )

    def _fetch_themes(self, query: str) -> list[str]:
        """Fetch top themes/topics from GDELT for context."""
        try:
            resp = self._throttled_get(
                GDELT_DOC_API,
                params={
                    "query": query,
                    "mode": "ThemeList",
                    "format": "json",
                    "timespan": "60min",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            themes_raw = data.get("themes", [])
            # Return top 5 theme names
            return [t.get("theme", "") for t in themes_raw[:5] if t.get("theme")]
        except (httpx.HTTPError, Exception):
            return []

    def fetch_macro_events(self, query: str = "geopolitical OR conflict OR sanctions") -> list[dict]:
        """Fetch recent macro/geopolitical events from GDELT."""
        logger.info("Fetching GDELT macro events")
        try:
            resp = self._throttled_get(
                GDELT_DOC_API,
                params={
                    "query": query,
                    "mode": "ArtList",
                    "maxrecords": "10",
                    "format": "json",
                    "sort": "ToneDesc",
                    "timespan": "24hours",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "title": a.get("title", ""),
                    "source": a.get("domain", ""),
                    "tone": a.get("tone", 0),
                    "date": a.get("seendate", ""),
                }
                for a in data.get("articles", [])
            ]
        except (httpx.HTTPError, Exception) as e:
            logger.error("GDELT macro events fetch failed: %s", e)
            return []

    def fetch_symbol_sentiment(self, symbol: str) -> NewsSentiment:
        """Fetch sentiment for a specific stock/crypto symbol."""
        # Strip common suffixes for search
        clean = symbol.replace("-USD", "").replace(".X", "")
        query = f"{clean} stock OR {clean} price OR {clean} trading"
        return self.fetch_sentiment(query)

    def fetch_symbol_headlines(self, symbol: str, limit: int = 10) -> list[dict]:
        """Fetch headlines for a specific symbol."""
        clean = symbol.replace("-USD", "").replace(".X", "")
        query = f"{clean} stock OR {clean} price"
        return self.fetch_headlines(query, limit)

    def close(self):
        self.client.close()
