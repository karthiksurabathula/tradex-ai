"""Builds a unified MarketState from OpenBB market data + WorldMonitor sentiment."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.ingestion.openbb_provider import OpenBBProvider
from src.ingestion.worldmonitor_provider import WorldMonitorProvider
from src.state.models import MarketState

logger = logging.getLogger(__name__)


class StateBuilder:
    """Merges OpenBB and WorldMonitor data streams into a single MarketState object."""

    def __init__(self, openbb: OpenBBProvider, worldmonitor: WorldMonitorProvider):
        self.openbb = openbb
        self.wm = worldmonitor

    def build(self, symbol: str, start: str, end: str) -> MarketState:
        """Build a complete MarketState for a given symbol and date range."""
        logger.info("Building state for %s (%s to %s)", symbol, start, end)

        # Fetch market data (auto-detects equity vs crypto)
        ohlcv = self.openbb.fetch(symbol, start, end)
        df = ohlcv.to_dataframe()
        technicals = self.openbb.compute_technicals(symbol, df)

        # Fetch news/sentiment
        headlines = self.wm.fetch_headlines(category="markets")
        sentiment = self.wm.fetch_sentiment()
        macro_events = self.wm.fetch_macro_events()

        return MarketState(
            symbol=symbol,
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
            technicals=technicals,
            sentiment=sentiment,
            headlines=headlines[:10],
            macro_events=macro_events,
        )
