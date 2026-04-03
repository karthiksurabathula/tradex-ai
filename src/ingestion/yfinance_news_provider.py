"""yfinance news provider — free, no API key, no rate limits."""

from __future__ import annotations

import logging

import yfinance as yf

from src.state.models import NewsSentiment

logger = logging.getLogger(__name__)

# Simple keyword sentiment scoring (no external API needed)
BULLISH_WORDS = {
    "surge", "soar", "rally", "gain", "jump", "rise", "boost", "upgrade",
    "beat", "record", "high", "growth", "profit", "bullish", "outperform",
    "buy", "strong", "positive", "boom", "breakout", "upbeat",
}
BEARISH_WORDS = {
    "drop", "fall", "crash", "plunge", "decline", "loss", "miss", "cut",
    "downgrade", "low", "sell", "weak", "negative", "bearish", "underperform",
    "recession", "fear", "risk", "warning", "slump", "layoff",
}


class YFinanceNewsProvider:
    """Fetches news and computes sentiment from yfinance — zero config, zero keys."""

    def fetch_headlines(self, **kwargs) -> list[dict]:
        """Not used directly — use fetch_symbol_headlines instead."""
        return []

    def fetch_symbol_headlines(self, symbol: str, limit: int = 10) -> list[dict]:
        """Fetch recent news for a symbol via yfinance."""
        logger.info("Fetching yfinance news for %s", symbol)
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news or []
            results = []
            for item in news[:limit]:
                # yfinance v2: content is nested under item["content"]
                content = item.get("content", item)
                provider = content.get("provider", {})
                results.append({
                    "title": content.get("title", ""),
                    "url": content.get("canonicalUrl", {}).get("url", ""),
                    "source": provider.get("displayName", ""),
                    "date": content.get("pubDate", ""),
                })
            return results
        except Exception as e:
            logger.error("yfinance news fetch failed for %s: %s", symbol, e)
            return []

    def fetch_sentiment(self, **kwargs) -> NewsSentiment:
        """General market sentiment — aggregate from major tickers."""
        all_headlines = []
        for sym in ["SPY", "QQQ"]:
            all_headlines.extend(self.fetch_symbol_headlines(sym, limit=5))
        return self._score_headlines(all_headlines)

    def fetch_symbol_sentiment(self, symbol: str) -> NewsSentiment:
        """Compute sentiment for a specific symbol from its news headlines."""
        headlines = self.fetch_symbol_headlines(symbol, limit=10)
        return self._score_headlines(headlines)

    def fetch_macro_events(self, **kwargs) -> list[dict]:
        """Macro events from broad market news."""
        return self.fetch_symbol_headlines("SPY", limit=5)

    def _score_headlines(self, headlines: list[dict]) -> NewsSentiment:
        """Score sentiment from headlines using keyword matching."""
        if not headlines:
            return NewsSentiment(
                overall_score=0.0, confidence=0.0, source="yfinance_news"
            )

        bullish_count = 0
        bearish_count = 0
        themes = []

        for h in headlines:
            title = h.get("title", "").lower()
            words = set(title.split())

            bull_hits = words & BULLISH_WORDS
            bear_hits = words & BEARISH_WORDS

            bullish_count += len(bull_hits)
            bearish_count += len(bear_hits)

            # Extract themes from first few headlines
            if len(themes) < 5 and h.get("title"):
                themes.append(h["title"][:60])

        total = bullish_count + bearish_count
        if total == 0:
            score = 0.0
            confidence = 0.1
        else:
            score = (bullish_count - bearish_count) / total
            confidence = min(1.0, total / 20.0)

        return NewsSentiment(
            overall_score=round(max(-1.0, min(1.0, score)), 4),
            confidence=round(confidence, 4),
            top_themes=themes,
            headline_count=len(headlines),
            source="yfinance_news",
        )
