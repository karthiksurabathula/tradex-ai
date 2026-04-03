"""Main entry point — APScheduler-based orchestration loop for the AI paper trading bot."""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler

from src.execution.executor import Executor
from src.execution.fees import FeeModel
from src.execution.portfolio import Portfolio
from src.execution.terminal_ui import TerminalUI
from src.execution.trade_log import TradeLog
from src.feedback.prompt_tuner import PromptTuner
from src.feedback.reviewer import TradeReviewer
from src.ingestion.gdelt_provider import GdeltProvider
from src.ingestion.openbb_provider import OpenBBProvider
from src.ingestion.state_builder import StateBuilder
from src.ingestion.worldmonitor_provider import WorldMonitorProvider
from src.reasoning.engine import ReasoningEngine
from src.reasoning.prompt_store import PromptStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    """Load config.yaml with environment variable substitution."""
    raw = Path(path).read_text()
    # Substitute ${ENV_VAR} patterns
    for key, value in os.environ.items():
        raw = raw.replace(f"${{{key}}}", value)
    return yaml.safe_load(raw)


def build_components(config: dict) -> dict:
    """Wire up all system components from config."""
    fee_model = FeeModel.from_config(config)
    portfolio = Portfolio(cash=config.get("starting_cash", 100_000), fee_model=fee_model)
    trade_log = TradeLog()
    prompt_store = PromptStore()

    openbb = OpenBBProvider(
        provider=config.get("data_provider", "yfinance"),
        interval=config.get("data_interval", "5m"),
    )

    # Sentiment provider: use GDELT (free, no key) unless WorldMonitor is configured
    wm_key = config.get("worldmonitor_key", "")
    if wm_key and wm_key != "${WORLDMONITOR_API_KEY}":
        logger.info("Using WorldMonitor for sentiment (API key configured)")
        sentiment_provider = WorldMonitorProvider(
            api_base=config.get("worldmonitor_api", ""),
            api_key=wm_key,
        )
    else:
        logger.info("Using GDELT for sentiment (free, no API key required)")
        sentiment_provider = GdeltProvider()

    engine = ReasoningEngine(
        llm_provider=config.get("llm_provider", "anthropic"),
        deep_think_model=config.get("deep_think_model", "claude-sonnet-4-6"),
        quick_think_model=config.get("quick_think_model", "claude-sonnet-4-6"),
        prompt_store=prompt_store,
    )

    return {
        "config": config,
        "state_builder": StateBuilder(openbb, sentiment_provider),
        "engine": engine,
        "portfolio": portfolio,
        "executor": Executor(
            portfolio,
            trade_log,
            max_position_pct=config.get("max_position_pct", 0.10),
            min_confidence=config.get("min_confidence", 0.60),
        ),
        "ui": TerminalUI(),
        "trade_log": trade_log,
        "reviewer": TradeReviewer(trade_log),
        "tuner": PromptTuner(prompt_store),
        "prompt_store": prompt_store,
    }


def run_trading_cycle(symbol: str, components: dict):
    """Single trading cycle for one symbol."""
    ui: TerminalUI = components["ui"]
    ui.show_divider(f"Trading Cycle: {symbol}")

    try:
        config = components["config"]
        lookback = config.get("data_lookback_days", 5)
        end = datetime.now(UTC)
        start = end - timedelta(days=lookback)

        state = components["state_builder"].build(
            symbol,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
        )

        signal = components["engine"].decide(state)
        ui.show_signal(signal)

        result = components["executor"].execute(signal, state.technicals.current_price)
        ui.show_execution(result)

        prices = {symbol: state.technicals.current_price}
        ui.show_portfolio(components["portfolio"], prices)

    except Exception:
        logger.exception("Trading cycle failed for %s", symbol)


def run_feedback_cycle(symbols: list[str], components: dict):
    """Nightly feedback loop — reviews trades and tunes prompts."""
    ui: TerminalUI = components["ui"]
    ui.show_divider("Nightly Feedback Cycle")

    min_trades = components["config"].get("min_trades_for_feedback", 10)

    for symbol in symbols:
        try:
            review = components["reviewer"].review(symbol)
            perf = review["performance"]

            logger.info(
                "%s: %d trades, win rate %.1f%%, net P&L $%.2f, fees $%.2f",
                symbol,
                perf["total_trades"],
                perf["win_rate"] * 100,
                perf["total_pnl"],
                perf["total_fees"],
            )

            if perf["total_trades"] >= min_trades:
                logger.info("Triggering prompt refinement for %s", symbol)
                components["tuner"].refine(review)
            else:
                logger.info(
                    "Skipping prompt tuning for %s (%d/%d trades)",
                    symbol, perf["total_trades"], min_trades,
                )
        except Exception:
            logger.exception("Feedback cycle failed for %s", symbol)


def main():
    """Main entry point."""
    config = load_config()
    symbols = config.get("symbols", ["AAPL"])
    schedule = config.get("schedule", {})

    logger.info("Starting AI Paper Trader with symbols: %s", symbols)

    components = build_components(config)

    scheduler = BlockingScheduler()

    # Trading cycles during market hours
    interval = schedule.get("trading_interval_minutes", 30)
    market_start = schedule.get("market_hours_start", 9)
    market_end = schedule.get("market_hours_end", 16)

    for symbol in symbols:
        scheduler.add_job(
            run_trading_cycle,
            "cron",
            args=[symbol, components],
            day_of_week="mon-fri",
            hour=f"{market_start}-{market_end}",
            minute=f"*/{interval}",
            id=f"trade_{symbol}",
        )

    # Nightly feedback cycle
    feedback_hour = schedule.get("feedback_hour", 20)
    scheduler.add_job(
        run_feedback_cycle,
        "cron",
        args=[symbols, components],
        hour=feedback_hour,
        minute=0,
        id="feedback_cycle",
    )

    logger.info(
        "Scheduler configured: trading every %dmin (%d:00-%d:00 M-F), feedback at %d:00",
        interval, market_start, market_end, feedback_hour,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down gracefully...")
        components["trade_log"].close()
        sys.exit(0)


if __name__ == "__main__":
    main()
