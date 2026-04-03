"""Technical Analysis Registry — all available indicators the broker can combine.

Each indicator is a function: DataFrame -> Series of signals (-1 to +1).
The broker's AlgorithmLab tests different combinations and weights.
"""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta


def _safe(series: pd.Series | None, default: float = 0.0) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype=float)
    return series.fillna(default)


# ── Momentum Indicators ──────────────────────────────────────────────────────

def signal_rsi(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """RSI → -1 (overbought) to +1 (oversold buy signal)."""
    rsi = _safe(ta.rsi(df["close"], length=length), 50)
    return ((50 - rsi) / 50).clip(-1, 1)


def signal_stoch_rsi(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Stochastic RSI → -1 to +1."""
    stoch = ta.stochrsi(df["close"], length=length)
    if stoch is None or stoch.empty:
        return pd.Series(0.0, index=df.index)
    k = stoch.iloc[:, 0].fillna(50)
    return ((50 - k) / 50).clip(-1, 1)


def signal_cci(df: pd.DataFrame, length: int = 20) -> pd.Series:
    """Commodity Channel Index → -1 to +1."""
    cci = _safe(ta.cci(df["high"], df["low"], df["close"], length=length), 0)
    return (cci / -200).clip(-1, 1)


def signal_willr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Williams %R → -1 to +1."""
    wr = _safe(ta.willr(df["high"], df["low"], df["close"], length=length), -50)
    return ((wr + 50) / 50).clip(-1, 1)


def signal_roc(df: pd.DataFrame, length: int = 10) -> pd.Series:
    """Rate of Change → -1 to +1."""
    roc = _safe(ta.roc(df["close"], length=length), 0)
    return (roc / 5).clip(-1, 1)


# ── Trend Indicators ─────────────────────────────────────────────────────────

def signal_macd(df: pd.DataFrame) -> pd.Series:
    """MACD histogram → -1 to +1."""
    macd = ta.macd(df["close"])
    if macd is None or macd.empty:
        return pd.Series(0.0, index=df.index)
    hist = macd.iloc[:, 2].fillna(0)  # MACDh
    mx = hist.abs().max()
    if mx == 0:
        return pd.Series(0.0, index=df.index)
    return (hist / mx).clip(-1, 1)


def signal_adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """ADX trend strength → 0 to +1 (strength only, no direction)."""
    adx = ta.adx(df["high"], df["low"], df["close"], length=length)
    if adx is None or adx.empty:
        return pd.Series(0.0, index=df.index)
    strength = adx.iloc[:, 0].fillna(0) / 100
    return strength.clip(0, 1)


def signal_ema_cross(df: pd.DataFrame, fast: int = 9, slow: int = 21) -> pd.Series:
    """EMA crossover → +1 (fast > slow) or -1 (fast < slow)."""
    ema_fast = _safe(ta.ema(df["close"], length=fast))
    ema_slow = _safe(ta.ema(df["close"], length=slow))
    if ema_fast.empty or ema_slow.empty:
        return pd.Series(0.0, index=df.index)
    diff = ema_fast - ema_slow
    mx = diff.abs().max()
    if mx == 0:
        return pd.Series(0.0, index=df.index)
    return (diff / mx).clip(-1, 1)


def signal_supertrend(df: pd.DataFrame, length: int = 10, multiplier: float = 3.0) -> pd.Series:
    """Supertrend → +1 (uptrend) or -1 (downtrend)."""
    st = ta.supertrend(df["high"], df["low"], df["close"], length=length, multiplier=multiplier)
    if st is None or st.empty:
        return pd.Series(0.0, index=df.index)
    direction = st.iloc[:, 1].fillna(1)  # SUPERTd
    return direction.clip(-1, 1)


# ── Volatility Indicators ────────────────────────────────────────────────────

def signal_bbands(df: pd.DataFrame, length: int = 20) -> pd.Series:
    """Bollinger Bands position → -1 (above upper) to +1 (below lower)."""
    bb = ta.bbands(df["close"], length=length)
    if bb is None or bb.empty:
        return pd.Series(0.0, index=df.index)
    lower = bb.iloc[:, 0].fillna(df["close"])
    mid = bb.iloc[:, 1].fillna(df["close"])
    upper = bb.iloc[:, 2].fillna(df["close"])
    width = upper - lower
    width = width.replace(0, 1)
    position = (mid - df["close"]) / (width / 2)
    return position.clip(-1, 1)


def signal_keltner(df: pd.DataFrame, length: int = 20) -> pd.Series:
    """Keltner Channel position → -1 to +1."""
    kc = ta.kc(df["high"], df["low"], df["close"], length=length)
    if kc is None or kc.empty:
        return pd.Series(0.0, index=df.index)
    lower = kc.iloc[:, 0].fillna(df["close"])
    mid = kc.iloc[:, 1].fillna(df["close"])
    upper = kc.iloc[:, 2].fillna(df["close"])
    width = upper - lower
    width = width.replace(0, 1)
    position = (mid - df["close"]) / (width / 2)
    return position.clip(-1, 1)


def signal_atr_regime(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """ATR regime → 0 (low vol) to 1 (high vol). Used for position sizing."""
    atr = _safe(ta.atr(df["high"], df["low"], df["close"], length=length), 0)
    if atr.empty:
        return pd.Series(0.0, index=df.index)
    normalized = atr / df["close"]
    mx = normalized.max()
    if mx == 0:
        return pd.Series(0.0, index=df.index)
    return (normalized / mx).clip(0, 1)


# ── Volume Indicators ────────────────────────────────────────────────────────

def signal_obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume trend → -1 to +1."""
    obv = _safe(ta.obv(df["close"], df["volume"]), 0)
    if obv.empty:
        return pd.Series(0.0, index=df.index)
    obv_sma = obv.rolling(20).mean().fillna(obv)
    diff = obv - obv_sma
    mx = diff.abs().max()
    if mx == 0:
        return pd.Series(0.0, index=df.index)
    return (diff / mx).clip(-1, 1)


def signal_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP deviation → +1 (price below vwap, buy) to -1 (above, sell)."""
    vwap = _safe(ta.vwap(df["high"], df["low"], df["close"], df["volume"]))
    if vwap.empty:
        return pd.Series(0.0, index=df.index)
    diff = vwap - df["close"]
    mx = diff.abs().max()
    if mx == 0:
        return pd.Series(0.0, index=df.index)
    return (diff / mx).clip(-1, 1)


def signal_mfi(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Money Flow Index → -1 (overbought) to +1 (oversold)."""
    mfi = _safe(ta.mfi(df["high"], df["low"], df["close"], df["volume"], length=length), 50)
    return ((50 - mfi) / 50).clip(-1, 1)


# ── Registry ─────────────────────────────────────────────────────────────────

INDICATOR_REGISTRY: dict[str, dict] = {
    # Momentum
    "rsi":        {"fn": signal_rsi,       "category": "momentum",   "description": "RSI(14) overbought/oversold"},
    "stoch_rsi":  {"fn": signal_stoch_rsi, "category": "momentum",   "description": "Stochastic RSI"},
    "cci":        {"fn": signal_cci,       "category": "momentum",   "description": "Commodity Channel Index"},
    "willr":      {"fn": signal_willr,     "category": "momentum",   "description": "Williams %R"},
    "roc":        {"fn": signal_roc,       "category": "momentum",   "description": "Rate of Change"},
    # Trend
    "macd":       {"fn": signal_macd,      "category": "trend",      "description": "MACD histogram"},
    "adx":        {"fn": signal_adx,       "category": "trend",      "description": "ADX trend strength"},
    "ema_cross":  {"fn": signal_ema_cross, "category": "trend",      "description": "EMA 9/21 crossover"},
    "supertrend": {"fn": signal_supertrend,"category": "trend",      "description": "Supertrend direction"},
    # Volatility
    "bbands":     {"fn": signal_bbands,    "category": "volatility",  "description": "Bollinger Bands position"},
    "keltner":    {"fn": signal_keltner,   "category": "volatility",  "description": "Keltner Channel position"},
    "atr_regime": {"fn": signal_atr_regime,"category": "volatility",  "description": "ATR volatility regime"},
    # Volume
    "obv":        {"fn": signal_obv,       "category": "volume",      "description": "On-Balance Volume trend"},
    "vwap":       {"fn": signal_vwap,      "category": "volume",      "description": "VWAP deviation"},
    "mfi":        {"fn": signal_mfi,       "category": "volume",      "description": "Money Flow Index"},
}


def get_indicator_names() -> list[str]:
    return list(INDICATOR_REGISTRY.keys())


def compute_indicator(name: str, df: pd.DataFrame) -> pd.Series:
    """Compute a single indicator signal from the registry."""
    entry = INDICATOR_REGISTRY.get(name)
    if not entry:
        raise ValueError(f"Unknown indicator: {name}")
    return entry["fn"](df)


def compute_all(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Compute all registered indicators."""
    results = {}
    for name, entry in INDICATOR_REGISTRY.items():
        try:
            results[name] = entry["fn"](df)
        except Exception:
            results[name] = pd.Series(0.0, index=df.index)
    return results
