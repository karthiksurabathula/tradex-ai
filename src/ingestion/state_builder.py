"""Builds a unified MarketState from OpenBB market data + news/sentiment provider."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from src.ingestion.openbb_provider import OpenBBProvider
from src.state.models import MarketState, NewsSentiment

logger = logging.getLogger(__name__)


class SentimentProvider(Protocol):
    """Protocol for any sentiment provider (WorldMonitor, GDELT, etc.)."""

    def fetch_headlines(self, **kwargs) -> list[dict]: ...
    def fetch_sentiment(self, **kwargs) -> NewsSentiment: ...
    def fetch_macro_events(self, **kwargs) -> list[dict]: ...


class StateBuilder:
    """Merges OpenBB and a sentiment provider into a single MarketState object."""

    def __init__(self, openbb: OpenBBProvider, sentiment_provider: SentimentProvider):
        self.openbb = openbb
        self.sp = sentiment_provider

    def build(self, symbol: str, start: str, end: str) -> MarketState:
        """Build a complete MarketState for a given symbol and date range."""
        logger.info("Building state for %s (%s to %s)", symbol, start, end)

        # Fetch market data (auto-detects equity vs crypto)
        ohlcv = self.openbb.fetch(symbol, start, end)
        df = ohlcv.to_dataframe()
        technicals = self.openbb.compute_technicals(symbol, df)

        # Fetch news/sentiment — try symbol-specific first, fall back to general
        headlines = self._fetch_headlines(symbol)
        sentiment = self._fetch_sentiment(symbol)
        macro_events = self._fetch_macro_events()

        return MarketState(
            symbol=symbol,
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
            technicals=technicals,
            sentiment=sentiment,
            headlines=headlines[:10],
            macro_events=macro_events,
        )

    def _fetch_headlines(self, symbol: str) -> list[dict]:
        """Fetch headlines — symbol-specific if provider supports it."""
        if hasattr(self.sp, "fetch_symbol_headlines"):
            return self.sp.fetch_symbol_headlines(symbol)
        return self.sp.fetch_headlines()

    def _fetch_sentiment(self, symbol: str) -> NewsSentiment:
        """Fetch sentiment — symbol-specific if provider supports it."""
        if hasattr(self.sp, "fetch_symbol_sentiment"):
            return self.sp.fetch_symbol_sentiment(symbol)
        return self.sp.fetch_sentiment()

    def _fetch_macro_events(self) -> list[dict]:
        return self.sp.fetch_macro_events()
