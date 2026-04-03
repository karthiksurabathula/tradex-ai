"""Market scanner — discovers tradeable stocks by scanning the broader market.

Finds opportunities via:
1. Trending tickers (most active, most volume)
2. Gap scanners (pre-market movers)
3. Momentum breakouts (unusual volume + price action)
4. Sector leaders/laggards
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Universe pools to scan
SP500_SAMPLE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "MA", "HD", "PG", "JNJ", "COST", "ABBV", "MRK",
    "CRM", "AVGO", "AMD", "NFLX", "PEP", "KO", "TMO", "ORCL", "ADBE",
    "WMT", "BAC", "DIS", "CSCO", "ACN", "INTC", "QCOM", "AMAT", "PANW",
    "NOW", "UBER", "SHOP", "COIN", "PLTR", "SNOW", "CRWD", "NET",
    "DDOG", "MDB", "ABNB",
]

CRYPTO_SAMPLE = ["BTC-USD", "ETH-USD", "SOL-USD"]

SECTOR_ETFS = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Energy": "XLE",
    "Consumer": "XLY",
    "Industrials": "XLI",
    "Real Estate": "XLRE",
}


@dataclass
class ScanResult:
    symbol: str
    score: float  # 0-100, higher = better opportunity
    reason: str
    category: str  # "momentum", "volume", "gap", "trending", "news"
    price: float = 0.0
    volume_ratio: float = 0.0  # Current vol / avg vol
    change_pct: float = 0.0
    scanned_at: datetime = field(default_factory=datetime.now)


class MarketScanner:
    """Scans the market to discover intraday trading opportunities."""

    def __init__(self, universe: list[str] | None = None, max_workers: int = 8):
        self.universe = universe or SP500_SAMPLE + CRYPTO_SAMPLE
        self.max_workers = max_workers

    def full_scan(self, top_n: int = 10) -> list[ScanResult]:
        """Run all scanners and return top N opportunities ranked by score."""
        logger.info("Starting full market scan across %d symbols...", len(self.universe))

        all_results: list[ScanResult] = []

        # Run scanners
        all_results.extend(self._scan_trending())
        all_results.extend(self._scan_momentum())
        all_results.extend(self._scan_volume_breakouts())
        all_results.extend(self._scan_sector_rotation())

        # Deduplicate by symbol, keep highest score
        best = {}
        for r in all_results:
            if r.symbol not in best or r.score > best[r.symbol].score:
                best[r.symbol] = r

        # Sort by score descending
        ranked = sorted(best.values(), key=lambda x: x.score, reverse=True)
        logger.info("Scan complete: %d opportunities found, returning top %d", len(ranked), top_n)
        return ranked[:top_n]

    def _scan_trending(self) -> list[ScanResult]:
        """Find trending/most active tickers via yfinance (parallel)."""
        results = []

        def _check_trending(symbol: str) -> ScanResult | None:
            try:
                info = yf.Ticker(symbol).fast_info
                price = info.get("lastPrice", 0)
                prev_close = info.get("previousClose", price)
                if prev_close and prev_close > 0:
                    change_pct = ((price - prev_close) / prev_close) * 100
                else:
                    return None
                score = min(abs(change_pct) * 10, 50)
                if abs(change_pct) > 2:
                    return ScanResult(symbol=symbol, score=score,
                        reason=f"Moving {change_pct:+.1f}% today",
                        category="trending", price=price, change_pct=change_pct)
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(_check_trending, sym): sym for sym in self.universe[:20]}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)

        return results

    def _scan_momentum(self) -> list[ScanResult]:
        """Find stocks with strong intraday momentum using parallel fetches."""
        results = []

        def check_momentum(symbol: str) -> ScanResult | None:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d", interval="1h")
                if hist.empty or len(hist) < 10:
                    return None

                close = hist["Close"]
                volume = hist["Volume"]

                # RSI-like momentum (simplified)
                returns = close.pct_change().dropna()
                recent_returns = returns.tail(5)
                momentum = recent_returns.mean() * 100

                # Volume spike
                avg_vol = volume.mean()
                recent_vol = volume.tail(3).mean()
                vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0

                # Score: momentum strength + volume confirmation
                score = 0.0
                reasons = []

                if abs(momentum) > 0.3:
                    score += min(abs(momentum) * 20, 40)
                    direction = "bullish" if momentum > 0 else "bearish"
                    reasons.append(f"{direction} momentum ({momentum:+.2f}%/hr)")

                if vol_ratio > 1.5:
                    score += min((vol_ratio - 1) * 20, 30)
                    reasons.append(f"volume {vol_ratio:.1f}x avg")

                if score > 20 and reasons:
                    return ScanResult(
                        symbol=symbol,
                        score=score,
                        reason="; ".join(reasons),
                        category="momentum",
                        price=float(close.iloc[-1]),
                        volume_ratio=vol_ratio,
                        change_pct=momentum,
                    )
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(check_momentum, sym): sym for sym in self.universe}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)

        return results

    def _scan_volume_breakouts(self) -> list[ScanResult]:
        """Find stocks with unusual volume spikes (potential breakouts)."""
        results = []

        def check_volume(symbol: str) -> ScanResult | None:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d", interval="1d")
                if hist.empty or len(hist) < 3:
                    return None

                vol_today = hist["Volume"].iloc[-1]
                vol_avg = hist["Volume"].iloc[:-1].mean()
                if vol_avg == 0:
                    return None

                vol_ratio = vol_today / vol_avg
                price = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                change_pct = ((price - prev) / prev) * 100

                if vol_ratio > 2.0:
                    score = min(vol_ratio * 15, 60)
                    return ScanResult(
                        symbol=symbol,
                        score=score,
                        reason=f"Volume spike {vol_ratio:.1f}x avg, price {change_pct:+.1f}%",
                        category="volume",
                        price=price,
                        volume_ratio=vol_ratio,
                        change_pct=change_pct,
                    )
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(check_volume, sym): sym for sym in self.universe}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)

        return results

    def _scan_sector_rotation(self) -> list[ScanResult]:
        """Identify strongest/weakest sectors for rotation trades."""
        results = []
        try:
            sector_perf = {}
            for sector, etf in SECTOR_ETFS.items():
                try:
                    hist = yf.Ticker(etf).history(period="5d", interval="1d")
                    if len(hist) >= 2:
                        change = ((hist["Close"].iloc[-1] / hist["Close"].iloc[-2]) - 1) * 100
                        sector_perf[sector] = {"etf": etf, "change": change, "price": float(hist["Close"].iloc[-1])}
                except Exception:
                    continue

            if sector_perf:
                # Best performing sector
                best = max(sector_perf.items(), key=lambda x: x[1]["change"])
                worst = min(sector_perf.items(), key=lambda x: x[1]["change"])

                results.append(ScanResult(
                    symbol=best[1]["etf"],
                    score=min(abs(best[1]["change"]) * 10, 40),
                    reason=f"Strongest sector: {best[0]} ({best[1]['change']:+.1f}%)",
                    category="sector",
                    price=best[1]["price"],
                    change_pct=best[1]["change"],
                ))

                if worst[1]["change"] < -1:
                    results.append(ScanResult(
                        symbol=worst[1]["etf"],
                        score=min(abs(worst[1]["change"]) * 8, 30),
                        reason=f"Weakest sector: {worst[0]} ({worst[1]['change']:+.1f}%) — potential short",
                        category="sector",
                        price=worst[1]["price"],
                        change_pct=worst[1]["change"],
                    ))
        except Exception as e:
            logger.error("Sector scan failed: %s", e)

        return results

    def quick_scan(self, top_n: int = 5) -> list[ScanResult]:
        """Faster scan using only trending + volume (skips momentum for speed)."""
        logger.info("Running quick scan...")
        results = []
        results.extend(self._scan_trending())
        results.extend(self._scan_sector_rotation())

        best = {}
        for r in results:
            if r.symbol not in best or r.score > best[r.symbol].score:
                best[r.symbol] = r

        ranked = sorted(best.values(), key=lambda x: x.score, reverse=True)
        return ranked[:top_n]
