"""Developer Agent — AI sub-agent that writes and tests new TA algorithms.

The broker can delegate tasks to this agent:
- "Write me an indicator that detects mean reversion"
- "Create a volatility breakout algorithm"
- "Build a multi-timeframe momentum indicator"

The agent writes Python code, validates it, registers it in the TA registry.
"""

from __future__ import annotations

import importlib
import logging
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Where custom algorithms are stored
CUSTOM_ALGO_DIR = Path("data/custom_algorithms")
CUSTOM_ALGO_DIR.mkdir(parents=True, exist_ok=True)


class DeveloperAgent:
    """AI agent that writes, validates, and deploys new TA indicators.

    Works with or without an LLM — has built-in templates for common patterns.
    When an LLM is available (Anthropic), it generates truly custom algorithms.
    """

    def __init__(self):
        self._client = None
        self.task_log: list[dict] = []

    @property
    def client(self):
        if self._client is None:
            try:
                from anthropic import Anthropic
                self._client = Anthropic()
            except Exception:
                logger.warning("Anthropic not available. Using template-based generation only.")
        return self._client

    def create_indicator(self, description: str, name: str | None = None) -> dict:
        """Create a new indicator from a natural language description.

        Returns: {"name": str, "code": str, "status": "success"|"error", "message": str}
        """
        name = name or f"custom_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
        self._log_task("create", f"Creating indicator '{name}': {description}")

        # Try LLM-generated code first
        if self.client:
            return self._create_with_llm(name, description)
        else:
            return self._create_from_template(name, description)

    def _create_with_llm(self, name: str, description: str) -> dict:
        """Use Claude to write a custom indicator."""
        prompt = f"""Write a Python function that implements a trading indicator.

REQUIREMENTS:
- Function name: signal_{name}
- Input: df (pandas DataFrame with columns: open, high, low, close, volume)
- Output: pandas Series with values from -1.0 (bearish) to +1.0 (bullish)
- Use pandas_ta library for any technical analysis computations
- Handle edge cases (empty data, NaN values)
- Keep it simple and efficient

DESCRIPTION OF WHAT THE INDICATOR SHOULD DO:
{description}

OUTPUT FORMAT:
Return ONLY the Python code. No explanations, no markdown fences.
The function must start with:
import pandas as pd
import pandas_ta as ta

def signal_{name}(df: pd.DataFrame) -> pd.Series:
"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            code = response.content[0].text.strip()

            # Clean up code
            if "```" in code:
                lines = code.split("\n")
                code = "\n".join(l for l in lines if not l.strip().startswith("```"))

            return self._validate_and_save(name, code, description)

        except Exception as e:
            self._log_task("error", f"LLM generation failed: {e}")
            return self._create_from_template(name, description)

    def _create_from_template(self, name: str, description: str) -> dict:
        """Generate indicator from built-in templates based on keywords."""
        desc_lower = description.lower()

        if "mean reversion" in desc_lower or "revert" in desc_lower:
            code = self._template_mean_reversion(name)
        elif "breakout" in desc_lower:
            code = self._template_breakout(name)
        elif "momentum" in desc_lower and "multi" in desc_lower:
            code = self._template_multi_timeframe_momentum(name)
        elif "squeeze" in desc_lower:
            code = self._template_squeeze(name)
        elif "divergence" in desc_lower:
            code = self._template_divergence(name)
        elif "volume" in desc_lower and "price" in desc_lower:
            code = self._template_volume_price(name)
        else:
            code = self._template_composite(name)

        return self._validate_and_save(name, code, description)

    def _validate_and_save(self, name: str, code: str, description: str) -> dict:
        """Validate generated code by running it on sample data, then save."""
        # Write to temp file and try importing
        try:
            # Create sample data for testing
            sample_df = pd.DataFrame({
                "open": [100 + i * 0.1 for i in range(100)],
                "high": [101 + i * 0.1 for i in range(100)],
                "low": [99 + i * 0.1 for i in range(100)],
                "close": [100.5 + i * 0.1 for i in range(100)],
                "volume": [1000000 + i * 1000 for i in range(100)],
            })

            # Execute the code
            import pandas_ta as ta_lib
            local_ns = {}
            exec(code, {"pd": pd, "ta": ta_lib, "__builtins__": __builtins__}, local_ns)

            # Find the signal function
            fn_name = f"signal_{name}"
            if fn_name not in local_ns:
                # Try to find any signal_ function
                fn_name = next((k for k in local_ns if k.startswith("signal_")), None)
                if not fn_name:
                    return {"name": name, "code": code, "status": "error", "message": "No signal_ function found in code"}

            fn = local_ns[fn_name]
            result = fn(sample_df)

            # Validate output
            if not isinstance(result, pd.Series):
                return {"name": name, "code": code, "status": "error", "message": f"Function returned {type(result)}, expected pd.Series"}

            if result.empty:
                return {"name": name, "code": code, "status": "error", "message": "Function returned empty Series"}

            # Check bounds
            if result.max() > 1.01 or result.min() < -1.01:
                return {"name": name, "code": code, "status": "error", "message": f"Signal out of bounds: [{result.min():.2f}, {result.max():.2f}]"}

            # Save the code
            path = CUSTOM_ALGO_DIR / f"{name}.py"
            path.write_text(f'"""{description}"""\n\n{code}\n')

            # Register in the TA registry
            from src.strategy.ta_registry import INDICATOR_REGISTRY
            INDICATOR_REGISTRY[name] = {
                "fn": fn,
                "category": "custom",
                "description": f"[Custom] {description[:60]}",
            }

            self._log_task("success", f"Created and registered '{name}' ({len(result)} signals validated)")

            return {
                "name": name,
                "code": code,
                "status": "success",
                "message": f"Indicator '{name}' validated and registered. {len(result)} signals, range [{result.min():.2f}, {result.max():.2f}]",
            }

        except Exception as e:
            tb = traceback.format_exc()
            self._log_task("error", f"Validation failed: {e}")
            return {"name": name, "code": code, "status": "error", "message": f"Validation failed: {e}\n{tb}"}

    # ── Built-in Templates ───────────────────────────────────────────────────
    def _template_mean_reversion(self, name: str) -> str:
        return f'''import pandas as pd
import pandas_ta as ta

def signal_{name}(df: pd.DataFrame) -> pd.Series:
    """Mean reversion: buy when price deviates far below SMA, sell when above."""
    sma = ta.sma(df["close"], length=20)
    if sma is None:
        return pd.Series(0.0, index=df.index)
    std = df["close"].rolling(20).std().fillna(1)
    zscore = (sma - df["close"]) / std
    return zscore.clip(-1, 1).fillna(0)
'''

    def _template_breakout(self, name: str) -> str:
        return f'''import pandas as pd
import pandas_ta as ta

def signal_{name}(df: pd.DataFrame) -> pd.Series:
    """Breakout: detect price breaking out of N-period range with volume confirmation."""
    high_20 = df["high"].rolling(20).max()
    low_20 = df["low"].rolling(20).min()
    vol_avg = df["volume"].rolling(20).mean()
    vol_ratio = df["volume"] / vol_avg.replace(0, 1)
    breakout_up = ((df["close"] > high_20.shift(1)) & (vol_ratio > 1.5)).astype(float)
    breakout_dn = ((df["close"] < low_20.shift(1)) & (vol_ratio > 1.5)).astype(float)
    signal = breakout_up - breakout_dn
    return signal.clip(-1, 1).fillna(0)
'''

    def _template_multi_timeframe_momentum(self, name: str) -> str:
        return f'''import pandas as pd
import pandas_ta as ta

def signal_{name}(df: pd.DataFrame) -> pd.Series:
    """Multi-timeframe momentum: combine short, medium, long RSI."""
    rsi_7 = ta.rsi(df["close"], length=7)
    rsi_14 = ta.rsi(df["close"], length=14)
    rsi_28 = ta.rsi(df["close"], length=28)
    if rsi_7 is None or rsi_14 is None or rsi_28 is None:
        return pd.Series(0.0, index=df.index)
    combined = (rsi_7 * 0.5 + rsi_14 * 0.3 + rsi_28 * 0.2).fillna(50)
    return ((50 - combined) / 50).clip(-1, 1)
'''

    def _template_squeeze(self, name: str) -> str:
        return f'''import pandas as pd
import pandas_ta as ta

def signal_{name}(df: pd.DataFrame) -> pd.Series:
    """Squeeze: BB inside Keltner = compression, breakout imminent."""
    bb = ta.bbands(df["close"], length=20)
    kc = ta.kc(df["high"], df["low"], df["close"], length=20)
    if bb is None or kc is None or bb.empty or kc.empty:
        return pd.Series(0.0, index=df.index)
    bb_lower, bb_upper = bb.iloc[:, 0], bb.iloc[:, 2]
    kc_lower, kc_upper = kc.iloc[:, 0], kc.iloc[:, 2]
    squeeze = ((bb_lower > kc_lower) & (bb_upper < kc_upper)).astype(float)
    mom = ta.mom(df["close"], length=12)
    if mom is None:
        return pd.Series(0.0, index=df.index)
    mom_norm = mom / mom.abs().max().clip(lower=0.001)
    return (squeeze * mom_norm).clip(-1, 1).fillna(0)
'''

    def _template_divergence(self, name: str) -> str:
        return f'''import pandas as pd
import pandas_ta as ta

def signal_{name}(df: pd.DataFrame) -> pd.Series:
    """RSI-price divergence: price makes new low but RSI doesn't (bullish)."""
    rsi = ta.rsi(df["close"], length=14)
    if rsi is None:
        return pd.Series(0.0, index=df.index)
    price_low = df["close"].rolling(14).min()
    rsi_low = rsi.rolling(14).min()
    price_making_low = (df["close"] <= price_low * 1.001)
    rsi_not_low = (rsi > rsi_low * 1.05)
    bull_div = (price_making_low & rsi_not_low).astype(float) * 0.8
    price_high = df["close"].rolling(14).max()
    rsi_high = rsi.rolling(14).max()
    price_making_high = (df["close"] >= price_high * 0.999)
    rsi_not_high = (rsi < rsi_high * 0.95)
    bear_div = (price_making_high & rsi_not_high).astype(float) * -0.8
    return (bull_div + bear_div).clip(-1, 1).fillna(0)
'''

    def _template_volume_price(self, name: str) -> str:
        return f'''import pandas as pd
import pandas_ta as ta

def signal_{name}(df: pd.DataFrame) -> pd.Series:
    """Volume-price trend: rising price + rising volume = bullish."""
    price_change = df["close"].pct_change(5).fillna(0)
    vol_change = df["volume"].pct_change(5).fillna(0)
    agreement = (price_change * vol_change).clip(-0.1, 0.1) * 10
    return agreement.clip(-1, 1).fillna(0)
'''

    def _template_composite(self, name: str) -> str:
        return f'''import pandas as pd
import pandas_ta as ta

def signal_{name}(df: pd.DataFrame) -> pd.Series:
    """Composite: RSI + MACD + OBV weighted signal."""
    rsi = ta.rsi(df["close"], length=14)
    macd = ta.macd(df["close"])
    obv = ta.obv(df["close"], df["volume"])
    if rsi is None or macd is None or obv is None:
        return pd.Series(0.0, index=df.index)
    rsi_sig = ((50 - rsi) / 50).fillna(0)
    macd_h = macd.iloc[:, 2].fillna(0)
    macd_mx = macd_h.abs().max()
    macd_sig = (macd_h / macd_mx if macd_mx > 0 else macd_h)
    obv_sma = obv.rolling(20).mean().fillna(obv)
    obv_diff = obv - obv_sma
    obv_mx = obv_diff.abs().max()
    obv_sig = (obv_diff / obv_mx if obv_mx > 0 else obv_diff)
    combined = rsi_sig * 0.4 + macd_sig * 0.35 + obv_sig * 0.25
    return combined.clip(-1, 1).fillna(0)
'''

    # ── Task Delegation ──────────────────────────────────────────────────────
    def delegate(self, task: str) -> dict:
        """High-level task delegation — broker tells developer what to build.

        Examples:
        - "Create an indicator that detects mean reversion opportunities"
        - "Build a momentum indicator using multiple timeframes"
        - "Write a volume breakout detector"
        """
        self._log_task("delegate", f"Received task: {task}")

        # Parse task type
        task_lower = task.lower()
        if "indicator" in task_lower or "signal" in task_lower or "algorithm" in task_lower:
            return self.create_indicator(task)
        elif "optimize" in task_lower or "tune" in task_lower:
            return {"status": "info", "message": "Use AlgorithmLab.evolve() for strategy optimization."}
        elif "backtest" in task_lower:
            return {"status": "info", "message": "Use AlgorithmLab.backtest() for backtesting."}
        else:
            return self.create_indicator(task)

    def list_custom_algorithms(self) -> list[dict]:
        """List all custom algorithms created by this agent."""
        algos = []
        for path in CUSTOM_ALGO_DIR.glob("*.py"):
            code = path.read_text()
            first_line = code.split("\n")[0].strip('"').strip("'")
            algos.append({
                "name": path.stem,
                "description": first_line[:80],
                "path": str(path),
                "size": len(code),
            })
        return algos

    def _log_task(self, task_type: str, message: str):
        self.task_log.append({
            "time": datetime.now(UTC).isoformat(),
            "type": task_type,
            "message": message,
        })
        logger.info("[DevAgent] %s: %s", task_type, message)
