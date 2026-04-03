"""OpenBB Platform provider for OHLCV data and technical indicators."""

from __future__ import annotations

import logging

import pandas as pd
from openbb import obb

from src.state.models import OHLCVData, TechnicalIndicators

logger = logging.getLogger(__name__)


class OpenBBProvider:
    """Fetches market data and computes technicals via OpenBB Platform v4."""

    def __init__(self, provider: str = "yfinance", interval: str = "5m"):
        self.provider = provider
        self.interval = interval

    def fetch_ohlcv(self, symbol: str, start: str, end: str, interval: str = "1d") -> OHLCVData:
        """Fetch OHLCV data for an equity symbol."""
        logger.info("Fetching OHLCV for %s (%s to %s)", symbol, start, end)
        result = obb.equity.price.historical(
            symbol=symbol,
            start_date=start,
            end_date=end,
            provider=self.provider,
            interval=interval,
        )
        df = result.to_dataframe()
        return OHLCVData.from_dataframe(symbol, df)

    def fetch_crypto(self, symbol: str, start: str, end: str, interval: str = "1d") -> OHLCVData:
        """Fetch OHLCV data for a crypto symbol (e.g., BTC-USD)."""
        logger.info("Fetching crypto OHLCV for %s (%s to %s)", symbol, start, end)
        result = obb.crypto.price.historical(
            symbol=symbol,
            start_date=start,
            end_date=end,
            provider=self.provider,
            interval=interval,
        )
        df = result.to_dataframe()
        return OHLCVData.from_dataframe(symbol, df)

    def fetch(self, symbol: str, start: str, end: str, interval: str | None = None) -> OHLCVData:
        """Auto-detect equity vs crypto and fetch accordingly."""
        ivl = interval or self.interval
        if self._is_crypto(symbol):
            return self.fetch_crypto(symbol, start, end, ivl)
        return self.fetch_ohlcv(symbol, start, end, ivl)

    def compute_technicals(self, symbol: str, df: pd.DataFrame) -> TechnicalIndicators:
        """Compute RSI, MACD, and Bollinger Bands from OHLCV DataFrame."""
        logger.info("Computing technicals for %s", symbol)

        rsi_result = obb.technical.rsi(data=df, target="close", length=14)
        rsi_df = rsi_result.to_dataframe()

        macd_result = obb.technical.macd(data=df, target="close")
        macd_df = macd_result.to_dataframe()

        bbands_result = obb.technical.bbands(data=df, target="close")
        bbands_df = bbands_result.to_dataframe()

        current_price = float(df["close"].iloc[-1])

        return TechnicalIndicators(
            symbol=symbol,
            rsi=float(rsi_df.iloc[-1].filter(like="RSI").iloc[0]),
            macd_signal=float(macd_df.iloc[-1].filter(like="MACDs").iloc[0]),
            macd_histogram=float(macd_df.iloc[-1].filter(like="MACDh").iloc[0]),
            bb_upper=float(bbands_df.iloc[-1].filter(like="BBU").iloc[0]),
            bb_lower=float(bbands_df.iloc[-1].filter(like="BBL").iloc[0]),
            bb_mid=float(bbands_df.iloc[-1].filter(like="BBM").iloc[0]),
            current_price=current_price,
        )

    @staticmethod
    def _is_crypto(symbol: str) -> bool:
        crypto_markers = ["BTC", "ETH", "SOL", "DOGE", "ADA", "XRP", "-USD"]
        return any(m in symbol.upper() for m in crypto_markers)
