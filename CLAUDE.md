# tradex-ai

## Overview
Autonomous AI paper-trading bot. Scans markets, picks stocks, trades intraday, manages risk, and evolves its own strategies — no human intervention needed. PostgreSQL (Docker) or SQLite (local) backend.

## How to Run
```bash
# Docker (recommended — includes PostgreSQL)
docker compose up -d
# Open http://localhost:8000

# Local (SQLite fallback)
DATABASE_URL=sqlite:///data/tradex.db uvicorn src.web.app:app --port 8000

# Terminal autopilot (no web UI)
python -m src.autopilot [--aggressive] [--cash 50000]

# CLI quick check
python -m src.cli once --symbols AAPL NVDA
python -m src.cli status
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐
│  INGESTION   │────▶│  REASONING   │────▶│  EXECUTION   │────▶│  FEEDBACK  │
│              │     │              │     │              │     │            │
│ OpenBB/yf   │     │ TradingAgents│     │ Portfolio    │     │ Reviewer   │
│ yf News     │     │ OR fallback  │     │ Executor     │     │ PromptTuner│
│ Fundamentals│     │ Ensemble     │     │ TradeLog     │     │ AlgoLab    │
└─────────────┘     └──────────────┘     └──────────────┘     └────────────┘
       │                    │                    │                    │
       └────────────────────┴────────────────────┴────────────────────┘
                                    │
                          ┌─────────┴─────────┐
                          │   SAFETY LAYER     │
                          │ RiskManager        │
                          │ PositionManager    │
                          │ MarketContext      │
                          │ EarningsCalendar   │
                          └────────────────────┘
```

## Data Flow (Autopilot Cycle)

```
1. Scanner.full_scan()          → 4 parallel scans (trending, momentum, volume, sector)
   └── 50+ stocks scanned       → returns list[ScanResult] ranked by score

2. StateBuilder.build(symbol)   → parallel for top 6 picks
   ├── OpenBBProvider.fetch()   → OHLCV data (yfinance)
   ├── OpenBBProvider.compute_technicals() → RSI, MACD, BB (pandas-ta or ta lib)
   └── YFinanceNewsProvider     → headlines + keyword sentiment
   └── returns MarketState (Pydantic model)

3. ReasoningEngine.decide()     → parallel for each MarketState
   ├── TradingAgents.propagate() if installed
   └── OR fallback rule-based: RSI(60%) + sentiment(40%) weighted score
   └── returns TradeSignal (BUY/SELL/HOLD + confidence)

4. Safety checks (sequential, per opportunity):
   ├── RiskManager.can_trade()     → daily loss limit, max trades, cooldown
   ├── EarningsCalendar            → skip if earnings in 3 days
   ├── RiskManager.check_sector()  → max 30% per sector
   ├── RiskManager.check_correlation() → reject if >0.7 correlated
   └── MarketContext.regime        → adjust position size by VIX regime

5. Executor.execute()           → sequential (cash depends on prior trade)
   ├── Portfolio.buy()/sell()   → deducts fees, updates positions
   ├── TradeLog.record()        → persists to PostgreSQL/SQLite
   └── PositionManager.register_entry() → sets SL/TP/trailing stop

6. PositionManager.check_exits() → checks all open positions
   ├── Stop-loss (2%, ATR-adjusted)
   ├── Take-profit (4%)
   ├── Trailing stop (1.5% from peak)
   └── Max hold time (3 hours)

7. Feedback (nightly):
   ├── TradeReviewer.review()    → win rate, loss patterns
   └── PromptTuner.refine()     → LLM adjusts Senior Trader prompt
```

## Key Files

| File | Purpose | Entry points |
|------|---------|-------------|
| `src/web/app.py` | FastAPI web app, all API endpoints | `uvicorn src.web.app:app` |
| `src/web/static/index.html` | HTML5/CSS/JS dashboard (single file) | Served at `/` |
| `src/autopilot.py` | Terminal-based autonomous trading loop | `python -m src.autopilot` |
| `src/cli.py` | CLI commands (once, watch, status) | `python -m src.cli` |
| `src/main.py` | APScheduler-based cron loop | `python -m src.main` |
| `src/state/models.py` | All Pydantic data models | Imported everywhere |
| `src/data/database.py` | Unified DB layer (PostgreSQL + SQLite) | `get_connection()` |
| `src/data/quote_store.py` | Persistent OHLCV time-series | Used by AlgorithmLab |
| `src/scanner/market_scanner.py` | Scans 50+ stocks in parallel | `full_scan()` |
| `src/reasoning/engine.py` | AI decision engine + fallback | `decide(MarketState)` |
| `src/strategy/algorithm_lab.py` | Genetic strategy evolution | `evolve()`, `backtest()` |
| `src/strategy/ta_registry.py` | 15 TA indicators, all pluggable | `INDICATOR_REGISTRY` |
| `src/strategy/risk_manager.py` | Circuit breakers, PDT, sector limits | `can_trade()`, `check_pdt()` |
| `src/strategy/market_context.py` | VIX regime, earnings, ATR sizing | `get_context()` |
| `src/execution/portfolio.py` | Paper portfolio (long + short) | `buy()`, `sell()`, `short()`, `cover()` |
| `src/execution/portfolio_store.py` | Persistent + thread-safe wrapper | `PersistentPortfolio` |
| `src/execution/fees.py` | Full broker fee model | `FeeModel.calculate()` |
| `src/agents/developer_agent.py` | AI writes custom TA indicators | `create_indicator()`, `delegate()` |

## API Endpoints (FastAPI at port 8000)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | HTML5 dashboard |
| GET | `/api/portfolio` | Portfolio summary + positions |
| POST | `/api/autopilot/run` | Run full scan → analyze → trade → monitor cycle |
| GET | `/api/analyze/{symbol}` | AI analysis for one symbol |
| GET | `/api/analyze-batch?symbols=AAPL,NVDA` | Parallel analysis for multiple symbols |
| POST | `/api/trade` | Manual buy/sell `{symbol, action, quantity}` |
| GET | `/api/scanner` | Run market scanner |
| GET | `/api/trades?symbol=&limit=30` | Trade history |
| GET | `/api/performance` | Metrics + equity curve + feedback |
| GET | `/api/events` | Event timeline |
| GET | `/api/regime` | Market regime + VIX |
| GET | `/api/risk` | Risk manager status |
| POST | `/api/kill-switch/{activate\|deactivate}` | Emergency halt |
| POST | `/api/reset` | Reset portfolio to $100k |

## Database Tables

**trades** — Every trade executed (trade_log.py)
`id, timestamp, symbol, action, quantity, price, effective_price, gross_pnl, net_pnl, fee_commission, fee_spread, fee_slippage, fee_sec, fee_total, confidence, reasoning, executed, reason`

**portfolio_state** — Key-value store for cash, realized_pnl, total_fees (portfolio_store.py)
`key, value, updated_at`

**positions** — Open positions (portfolio_store.py)
`symbol, quantity, avg_cost, entry_fees, opened_at, is_short`

**equity_curve** — Portfolio value over time (portfolio_store.py)
`timestamp, total_value, cash, realized_pnl, unrealized_pnl, total_fees, position_count`

**quotes** — Historical OHLCV data (quote_store.py)
`symbol, timestamp, interval, open, high, low, close, volume`

**watchlist** — Symbols the bot tracks (quote_store.py)
`symbol, added_at, added_by, reason, active`

**strategies** — Evolved strategies from AlgorithmLab
`strategy_id, config (JSON), generation, created_at, is_active`

**backtest_results** — Backtest metrics per strategy
`id, strategy_id, symbol, total_trades, wins, losses, total_pnl, sharpe, max_drawdown, win_rate, tested_at`

**audit_log** — Append-only decision trail (audit.py)
`id, timestamp, event_type, symbol, action, technicals_json, sentiment_json, reasoning, signal, confidence, executed, portfolio_state_json`

## How to Extend

**Add a new data source:**
1. Create `src/ingestion/my_provider.py` with methods: `fetch_headlines()`, `fetch_sentiment()`, `fetch_macro_events()`
2. It should return data compatible with `NewsSentiment` model
3. Wire it in `src/web/app.py` or `src/main.py` as the sentiment_provider

**Add a new technical indicator:**
1. Add a function to `src/strategy/ta_registry.py`: `def signal_myindicator(df) -> pd.Series` (returns -1 to +1)
2. Register it in `INDICATOR_REGISTRY` dict at the bottom
3. It's automatically available to AlgorithmLab for evolution

**Add a new risk check:**
1. Add method to `src/strategy/risk_manager.py`: `def check_myrule() -> tuple[bool, str]`
2. Call it in `src/autopilot.py` in the `scan_and_enter()` method before trade execution

**Add a new API endpoint:**
1. Add route in `src/web/app.py`
2. Add corresponding JS function and UI section in `src/web/static/index.html`

## Key Design Decisions
- **Supplement, don't replace**: TradingAgents runs its own analysts; we inject extra context via prompt
- **Fees always applied**: Every trade deducts commission ($4.95) + spread + slippage + SEC fee
- **Persistent state**: Portfolio survives restarts (PostgreSQL/SQLite)
- **Self-evolving**: AlgorithmLab breeds strategies via genetic algorithm with walk-forward + Monte Carlo significance
- **Parallel by default**: Scanner, analysis, price fetching all use ThreadPoolExecutor
- **Dual TA library**: Uses pandas-ta when available, falls back to `ta` library (Docker-friendly)
- **Dual DB**: PostgreSQL in Docker, SQLite for local dev/testing — same code, auto-detected via DATABASE_URL

## Data Files (gitignored)
- `data/trades.db` / PostgreSQL `trades` table — Trade journal
- `data/portfolio.db` / PostgreSQL `portfolio_state` + `positions` — Persistent state
- `data/quotes.db` / PostgreSQL `quotes` + `watchlist` — Quote history
- `data/algorithm_lab.db` / PostgreSQL `strategies` + `backtest_results` — Evolution data
- `data/audit.db` / PostgreSQL `audit_log` — Decision audit trail
- `data/prompt_versions/` — Versioned Senior Trader prompts (JSON files)
- `data/custom_algorithms/` — Developer Agent generated indicators (Python files)
- `data/.kill_switch` — If this file exists, all trading is halted
- `data/.heartbeat` — Updated each cycle for health monitoring
