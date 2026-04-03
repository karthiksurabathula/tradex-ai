"""TradingAgents configuration overrides."""

from __future__ import annotations


def build_config(
    llm_provider: str = "anthropic",
    deep_think_model: str = "claude-sonnet-4-6",
    quick_think_model: str = "claude-sonnet-4-6",
) -> dict:
    """Build a TradingAgents config dict with our preferred settings."""
    try:
        from tradingagents.default_config import DEFAULT_CONFIG

        config = DEFAULT_CONFIG.copy()
    except ImportError:
        config = {}

    config["llm_provider"] = llm_provider
    config["deep_think_model"] = deep_think_model
    config["quick_think_model"] = quick_think_model

    return config
