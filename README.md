# tradex-ai

Autonomous paper-trading system for scanning markets, generating trade signals, executing paper orders, managing intraday risk, and evolving technical strategies over time.

## What Is In This Repo

The codebase has one shared trading pipeline and multiple entrypoints built on top of it.

Core pipeline:

1. `MarketScanner` finds opportunities across a fixed equity and crypto universe.
2. `StateBuilder` merges price history, technical indicators, headlines, and sentiment into a `MarketState`.
3. `ReasoningEngine` produces `BUY`, `SELL`, or `HOLD` with confidence.
4. `Executor` and portfolio classes apply paper trades with fees.
5. `PositionManager` and `RiskManager` handle exits, halts, cooldowns, and kill switch logic.
6. `QuoteStore`, `TradeLog`, `AlgorithmLab`, and feedback modules persist history and analysis.

## Entry Points

This repo currently exposes five runnable surfaces.

| Surface | Command | Notes |
|---|---|---|
| FastAPI dashboard | `uvicorn src.web.app:app --port 8000` | Serves the HTML dashboard at `/` and JSON API endpoints under `/api/*` |
| Streamlit dashboard | `streamlit run src/dashboard.py` | Separate dashboard implementation with 14 pages |
| Terminal autopilot | `python -m src.autopilot` | Rich terminal UI with autonomous scan, entry, and exit loop |
| CLI | `python -m src.cli once --symbols AAPL NVDA` | Single-cycle and watch/status commands |
| Scheduler loop | `python -m src.main` | APScheduler-driven periodic trading and nightly feedback |

## Which Interface To Use

- Use the FastAPI app if you want the HTML dashboard and HTTP API.
- Use the Streamlit app if you want the richer exploratory dashboard pages.
- Use the terminal autopilot if you want the bot to run continuously in a console.
- Use the CLI for quick checks.
- Use the scheduler loop if you want cron-style orchestration from `config.yaml`.

## Quick Start

### Option 1: FastAPI dashboard

```bash
pip install -e ".[dev]"
DATABASE_URL=sqlite:///data/tradex.db uvicorn src.web.app:app --port 8000
```

Open `http://localhost:8000`.

### Option 2: Streamlit dashboard

```bash
pip install -e ".[dev]"
streamlit run src/dashboard.py
```

Open `http://localhost:8501`.

### Option 3: Terminal autopilot

```bash
pip install -e ".[dev]"
python -m src.autopilot
```

Aggressive mode:

```bash
python -m src.autopilot --aggressive --cash 50000
```

### Option 4: CLI

```bash
python -m src.cli once --symbols AAPL NVDA MSFT
python -m src.cli watch --symbols AAPL NVDA --interval 300
python -m src.cli status
```

### Option 5: Scheduler loop

```bash
python -m src.main
```

This uses `config.yaml` for symbols, intervals, and nightly feedback settings.

## Docker

The repo includes Docker assets and defaults to PostgreSQL when `DATABASE_URL` is not set.

```bash
docker compose up -d
```

The default database URL in code is:

```text
postgresql://tradex:tradex@localhost:5432/tradex
```

If PostgreSQL is unavailable, most modules fall back to SQLite when configured with a `sqlite:///...` URL.

## Runtime Architecture

```text
scanner -> state builder -> reasoning -> execution -> risk/exits -> persistence/feedback
```

Main components:

| Layer | Modules | Responsibility |
|---|---|---|
| Scanning | `src/scanner/market_scanner.py` | Trending, momentum, volume breakout, sector rotation scans |
| Ingestion | `src/ingestion/openbb_provider.py`, `src/ingestion/state_builder.py`, `src/ingestion/yfinance_news_provider.py` | Price data, technicals, headlines, sentiment |
| Reasoning | `src/reasoning/engine.py` | TradingAgents when installed, otherwise rule-based fallback |
| Execution | `src/execution/executor.py`, `src/execution/portfolio.py`, `src/execution/portfolio_store.py`, `src/execution/trade_log.py` | Order sizing, paper fills, persistence, fee-aware PnL |
| Risk | `src/strategy/risk_manager.py`, `src/strategy/position_manager.py`, `src/strategy/market_context.py` | Kill switch, daily loss limit, sector/correlation checks, exits, market regime |
| Research | `src/strategy/algorithm_lab.py`, `src/strategy/ta_registry.py` | Indicator registry, backtesting, genetic strategy evolution |
| Feedback | `src/feedback/reviewer.py`, `src/feedback/metrics.py`, `src/feedback/prompt_tuner.py` | Trade review, metrics, prompt refinement |
| Agents | `src/agents/developer_agent.py` | Generates custom TA indicators into `data/custom_algorithms/` |

## FastAPI Surface

The FastAPI app in `src/web/app.py` serves the static HTML dashboard and these endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | HTML dashboard |
| GET | `/api/portfolio` | Portfolio summary and open positions |
| POST | `/api/autopilot/run` | Run one scan/analyze/trade/monitor cycle |
| GET | `/api/analyze/{symbol}` | Analyze one symbol |
| GET | `/api/analyze-batch` | Parallel symbol analysis |
| POST | `/api/trade` | Manual buy or sell |
| GET | `/api/scanner` | Run market scan |
| GET | `/api/trades` | Recent trades |
| GET | `/api/performance` | Performance, metrics, equity curve, review |
| GET | `/api/events` | Recent event feed |
| GET | `/api/regime` | Market regime snapshot |
| GET | `/api/risk` | Risk manager status |
| POST | `/api/kill-switch/{action}` | Activate or deactivate kill switch |
| POST | `/api/reset` | Reset persistent portfolio state |

## Streamlit Surface

The Streamlit dashboard in `src/dashboard.py` currently exposes these pages:

1. Autopilot
2. Manual Trade
3. Positions
4. Market Scanner
5. AI Analysis
6. Trade Log
7. Performance
8. Algorithm Lab
9. Developer Agent
10. Risk & Regime
11. Quote Store
12. Event Feed
13. Settings
14. Help

## Persistence Model

The repository has a shared database helper in `src/data/database.py` used by:

- `TradeLog`
- `PersistentPortfolio`
- `QuoteStore`
- `AlgorithmLab`
- `AuditTrail`
- monitoring health checks

Important runtime distinction:

- `src/autopilot.py`, `src/web/app.py`, and `src/dashboard.py` use `PersistentPortfolio`.
- `src/cli.py` and `src/main.py` currently build the plain in-memory `Portfolio` class.

That means not every entrypoint shares identical persistence behavior.

## Data Providers And AI Behavior

- Price and technical data are fetched through `OpenBBProvider` configured to use `yfinance` in the active runtime paths.
- The common default sentiment provider is `YFinanceNewsProvider`.
- `src/main.py` can switch to `WorldMonitorProvider` when configured.
- `ReasoningEngine` uses TradingAgents only if the optional dependency is installed.
- Without TradingAgents, the fallback path uses weighted RSI, MACD histogram, Bollinger Band position, and sentiment.

## Risk Controls Implemented

- Daily loss limit halt
- Max drawdown halt
- Kill switch file at `data/.kill_switch`
- Max trades per day
- Cooldown after large loss
- Sector concentration checks
- Correlation checks
- Pattern day trader tracking helpers
- Stop-loss, take-profit, trailing stop, and max-hold exits

## Configuration

Primary runtime settings live in `config.yaml`, including:

- symbols
- starting cash
- data interval and lookback
- LLM model configuration
- schedule settings for `src.main`
- risk limits
- fee model
- algorithm lab defaults

## Project Structure

```text
src/
  autopilot.py
  cli.py
  dashboard.py
  main.py
  agents/
  data/
  execution/
  feedback/
  ingestion/
  monitoring/
  reasoning/
  scanner/
  state/
  strategy/
  web/
tests/
data/
```

## Tests

```bash
pytest -v
```

## Notes On Current State

The repo is functional, but the documentation previously drifted from the code in a few places:

- Both FastAPI and Streamlit dashboards exist.
- The scheduler path and CLI do not use the same persistent portfolio wrapper as the dashboard/autopilot paths.
- The docs previously mixed intended architecture with currently wired runtime behavior.

This README now describes the code as it exists today.

## Disclaimer

This is a paper-trading project for research and educational use. It does not place real brokerage orders.