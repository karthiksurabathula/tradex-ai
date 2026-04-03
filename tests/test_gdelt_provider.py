"""Tests for the GDELT sentiment provider."""

from unittest.mock import MagicMock, patch

from src.ingestion.gdelt_provider import GdeltProvider


class TestGdeltProvider:
    def setup_method(self):
        self.provider = GdeltProvider()

    def test_fetch_headlines_returns_list(self):
        # Live test against GDELT (free, no key)
        headlines = self.provider.fetch_headlines(query="stock market", limit=5)
        assert isinstance(headlines, list)
        # GDELT may return 0 results if no recent matches, that's ok
        if headlines:
            assert "title" in headlines[0]

    def test_fetch_sentiment_returns_model(self):
        sentiment = self.provider.fetch_sentiment(query="economy")
        assert -1.0 <= sentiment.overall_score <= 1.0
        assert 0.0 <= sentiment.confidence <= 1.0
        assert sentiment.source in ("gdelt", "gdelt_fallback")

    def test_fetch_symbol_sentiment(self):
        sentiment = self.provider.fetch_symbol_sentiment("AAPL")
        assert -1.0 <= sentiment.overall_score <= 1.0

    def test_fetch_macro_events_returns_list(self):
        events = self.provider.fetch_macro_events()
        assert isinstance(events, list)

    def test_fetch_symbol_headlines(self):
        headlines = self.provider.fetch_symbol_headlines("NVDA", limit=3)
        assert isinstance(headlines, list)

    def test_handles_network_error_gracefully(self):
        """Provider should return empty/neutral on network failure, not crash."""
        provider = GdeltProvider(timeout=0.001)  # Impossibly short timeout
        headlines = provider.fetch_headlines()
        assert headlines == []

        sentiment = provider.fetch_sentiment()
        assert sentiment.overall_score == 0.0
        assert sentiment.source == "gdelt_fallback"
