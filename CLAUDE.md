# AI Paper Trader

## Project Overview
Automated AI paper-trading bot combining OpenBB market data, WorldMonitor news sentiment,
TradingAgents multi-agent reasoning, and an in-house terminal-based paper trading execution layer.

## Architecture
- **Data Ingestion**: OpenBB (OHLCV + technicals) + WorldMonitor (news + sentiment) → MarketState
- **Reasoning**: TradingAgents runs its own analyst pipeline natively; OpenBB/WorldMonitor supplement via prompt injection
- **Execution**: In-house paper portfolio with full traditional fee model (commission + spread + slippage + SEC)
- **Feedback**: Nightly review cycle with LLM-driven prompt refinement

## Commands
- Run: `python -m src.main`
- Tests: `pytest`
- Format: `black src/ tests/`
- Lint: `ruff check src/ tests/`

## Key Conventions
- All state flows through Pydantic models in `src/state/models.py`
- Fees are always applied — never bypass `FeeModel` in portfolio operations
- Trade log is SQLite at `data/trades.db`
- Prompt versions stored as JSON in `data/prompt_versions/`
