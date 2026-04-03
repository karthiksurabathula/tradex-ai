"""Pydantic state models — single source of truth for all data flowing through the system."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

import pandas as pd
from pydantic import BaseModel, Field


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OHLCVBar(BaseModel):
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class OHLCVData(BaseModel):
    symbol: str
    bars: list[OHLCVBar]
    interval: str = "1d"

    @classmethod
    def from_dataframe(cls, symbol: str, df: pd.DataFrame) -> OHLCVData:
        records = df.reset_index().to_dict("records")
        bars = []
        for row in records:
            bars.append(
                OHLCVBar(
                    date=row.get("date", row.get("Date", row.get("index", datetime.now()))),
                    open=float(row.get("open", row.get("Open", 0))),
                    high=float(row.get("high", row.get("High", 0))),
                    low=float(row.get("low", row.get("Low", 0))),
                    close=float(row.get("close", row.get("Close", 0))),
                    volume=int(row.get("volume", row.get("Volume", 0))),
                )
            )
        return cls(symbol=symbol, bars=bars)

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([b.model_dump() for b in self.bars])

    @property
    def latest_close(self) -> float:
        if not self.bars:
            return 0.0
        return self.bars[-1].close


class TechnicalIndicators(BaseModel):
    symbol: str
    rsi: float
    macd_signal: float
    macd_histogram: float
    bb_upper: float
    bb_lower: float
    bb_mid: float
    current_price: float

    @property
    def rsi_label(self) -> str:
        if self.rsi > 70:
            return "overbought"
        elif self.rsi < 30:
            return "oversold"
        return "neutral"


class NewsSentiment(BaseModel):
    overall_score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    top_themes: list[str] = Field(default_factory=list)
    instability_index: float | None = None
    headline_count: int = 0
    source: str = "worldmonitor"


class MarketState(BaseModel):
    """Unified state object — single source of truth for the reasoning engine."""

    symbol: str
    timestamp: datetime
    ohlcv: OHLCVData
    technicals: TechnicalIndicators
    sentiment: NewsSentiment
    headlines: list[dict] = Field(default_factory=list)
    macro_events: list[dict] = Field(default_factory=list)


class TradeSignal(BaseModel):
    symbol: str
    action: SignalType
    confidence: float = Field(ge=0.0, le=1.0)
    quantity: int = 0
    reasoning: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
