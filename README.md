<p align="center">
  <h1 align="center">tradex-ai</h1>
  <p align="center">
    <strong>Autonomous AI paper-trading bot that scans markets, picks stocks, trades, and evolves — no human needed.</strong>
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/tests-60%20passing-brightgreen?style=flat-square" alt="Tests">
  <img src="https://img.shields.io/badge/API%20keys-zero%20required-orange?style=flat-square" alt="Zero keys required">
  <img src="https://img.shields.io/badge/version-1.0.0-purple?style=flat-square" alt="v1.0.0">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
</p>

---

## What is this?

**tradex-ai** is a fully autonomous paper-trading system. Give it $100k in simulated money and it will:

1. **Scan** 50+ stocks for momentum, volume breakouts, and sector rotation
2. **Analyze** each opportunity with 15+ technical indicators and news sentiment
3. **Decide** BUY/SELL/HOLD using AI multi-agent reasoning
4. **Execute** trades with realistic broker fees ($4.95 + spread + slippage + SEC)
5. **Monitor** positions with stop-loss, take-profit, and trailing stops
6. **Learn** from mistakes and evolve better strategies overnight

**Zero API keys required.** All data sources are free. Add an Anthropic key to unlock the full AI reasoning engine.

---

## Quick Start

```bash
git clone https://github.com/karthiksurabathula/tradex-ai.git
cd tradex-ai
pip install -e ".[dev]"
streamlit run src/dashboard.py
```

Open **http://localhost:8501** and click **Run Trading Cycle**.

---

## Three Ways to Run

| Mode | Command | Description |
|------|---------|-------------|
| **Web Dashboard** | `streamlit run src/dashboard.py` | Full visual UI with 14 pages |
| **Autopilot (terminal)** | `python -m src.autopilot` | Autonomous trading in terminal |
| **CLI** | `python -m src.cli once` | Quick single-cycle check |

---

## Architecture

```
  Market Data ──┐                              ┌── Stop-Loss / Take-Profit
  (yfinance)    │                              │── Trailing Stops
                ├──▶ Scanner ──▶ AI Reasoning ──▶ Paper Execution ──▶ Feedback Loop
  News/Sentiment│    (50+ stocks) (multi-agent)  (fee-realistic)     (self-improving)
  (yfinance)    │                              │── Risk Manager
  Fundamentals ─┘                              └── Regime Detection
```

### Module Map

| Layer | Modules | What it does |
|-------|---------|-------------|
| **Data Ingestion** | `openbb_provider`, `yfinance_news_provider`, `fundamental_provider` | OHLCV, technicals, news sentiment, P/E ratios |
| **Market Scanner** | `market_scanner` | Scans 50+ stocks for momentum, volume, sectors |
| **AI Reasoning** | `engine`, `senior_trader`, `ensemble` | Multi-agent or rule-based signals with consensus voting |
| **Strategy** | `algorithm_lab`, `ta_registry`, `intraday_strategist` | 15+ indicators, genetic evolution, position sizing |
| **Execution** | `portfolio`, `portfolio_store`, `executor`, `fees` | Paper trades with full broker fees, persistent state |
| **Risk Management** | `risk_manager`, `position_manager`, `market_context` | Circuit breakers, PDT rules, VaR, sector limits |
| **Feedback** | `reviewer`, `metrics`, `prompt_tuner` | Nightly review, pattern detection, prompt refinement |
| **Monitoring** | `alerts`, `audit`, `health`, `logging_config` | Alerts, audit trail, health checks, structured logs |
| **Agents** | `developer_agent` | AI writes custom indicators on demand |

---

## Key Features

### Autonomous Trading (Autopilot)
The bot runs fully independently — scans, decides, trades, monitors, exits:
- Scans 50+ S&P 500 stocks + crypto every 5 minutes
- AI confirms each trade before execution (scanner + reasoning must agree)
- Manages positions with automatic stop-loss, take-profit, trailing stops
- Force-exits after 3 hours (intraday only)

### Self-Evolving Strategies (Algorithm Lab)
The AI discovers its own best indicator combinations through genetic evolution:
- 15 built-in indicators: RSI, MACD, ADX, EMA Cross, Supertrend, Bollinger Bands, Keltner, ATR, OBV, VWAP, MFI, StochRSI, CCI, Williams %R, ROC
- Generates random strategies, backtests with fees + walk-forward testing
- Tests statistical significance (Monte Carlo, p < 0.05)
- Breeds winners, promotes the best to production

### Developer Agent
An AI sub-agent that writes new technical analysis code on demand:
```
"Create a mean reversion indicator using z-score" → Python code → validated → registered
```

### Risk Management
| Control | What it does |
|---------|-------------|
| Daily loss limit | Halts trading after -1.5% daily loss |
| Kill switch | One-click emergency halt (file-based) |
| Sector cap | Max 30% portfolio in any single sector |
| Correlation filter | Rejects trades >0.7 correlated with holdings |
| Earnings avoidance | Skips stocks with earnings in 3 days |
| PDT compliance | Tracks round-trip day trades (pattern day trader rule) |
| VaR calculation | Historical + parametric Value-at-Risk |
| Cooldown | 30-min pause after any >2% loss trade |
| Max trades/day | Hard limit of 50 trades (prevents overtrading) |

### Market Regime Detection
| Regime | VIX | Position Size | Description |
|--------|-----|---------------|-------------|
| BULL | < 15 | 100% | Low vol, uptrend |
| SIDEWAYS | 15-20 | 80% | No clear direction |
| VOLATILE | 20-25 | 50% | High vol, choppy |
| BEAR | > 25 | 30% | Downtrend, defensive |

### Fee-Realistic Paper Trading
| Cost | Rate | Applied On |
|------|------|-----------|
| Commission | $4.95/trade | All trades |
| Spread | 0.02% equity, 0.30% crypto | All trades |
| Slippage | 0.10% | All trades |
| SEC Fee | $8/$1M notional | Sells only |

### Short Selling
Portfolio supports both long and short positions with proper margin calculation and P&L tracking.

### Persistent State
Portfolio state survives restarts (SQLite-backed), including positions, cash, fees, and equity curve history.

### Monitoring & Observability
- **Structured logging** — JSON logs with rotating files
- **Slack alerts** — large losses, kill switch, system errors
- **Health checks** — yfinance connectivity, SQLite health, data freshness
- **Audit trail** — append-only decision log with full context

---

## Web Dashboard (14 Pages)

| Page | Description |
|------|-------------|
| **Autopilot** | AI scans, trades, and monitors — with auto-run toggle |
| **Manual Trade** | Pick symbols, see AI analysis, click BUY/SELL |
| **Positions** | Open holdings with SL/TP/trailing stop + close-all |
| **Market Scanner** | On-demand scan with scores, categories, reasons |
| **AI Analysis** | Full reasoning per symbol — technicals, news, decision logic |
| **Trade Log** | Every trade with fees, P&L, reasoning — filterable |
| **Performance** | Win rate, Sharpe, drawdown, profit factor, equity curve |
| **Algorithm Lab** | Evolve strategies, leaderboard, active strategy detail |
| **Developer Agent** | Create custom indicators, delegate tasks |
| **Risk & Regime** | VIX, market regime, risk status, kill switch |
| **Quote Store** | Watchlist, quote collection, data inventory |
| **Event Feed** | Real-time timeline of all system activity |
| **Settings** | Adjust risk params, view fees, reset portfolio |
| **Help** | Step-by-step guide, onboarding wizard, full documentation |

First-time users see an **onboarding wizard** with a 4-step getting started guide. Every button and metric has an info tooltip explaining what it does.

---

## Configuration

All settings in `config.yaml` with inline documentation:

```yaml
symbols: [AAPL, NVDA, MSFT, BTC-USD]
starting_cash: 100000.0
data_interval: 5m                   # 1m, 5m, 15m, 30m, 1h, 1d
max_position_pct: 0.10              # Max 10% per position
stop_loss_pct: 0.02                 # 2% auto-sell
take_profit_pct: 0.04               # 4% target
daily_loss_limit_pct: 0.015         # Halt at -1.5% daily
max_sector_pct: 0.30                # Max 30% per sector
```

See `config.yaml` for full documented options.

---

## Tech Stack

| Component | Technology | Key? |
|-----------|------------|------|
| Price Data | yfinance via OpenBB | No |
| Technicals | pandas-ta (15+ indicators) | No |
| News Sentiment | yfinance headlines | No |
| Fundamentals | yfinance Ticker.info | No |
| AI Reasoning | Claude (Anthropic) | Optional |
| Multi-Agent | TradingAgents | Optional |
| Data Models | Pydantic | No |
| Scheduling | APScheduler | No |
| Web UI | Streamlit | No |
| Terminal UI | Rich | No |
| Trade Storage | SQLite | No |
| Strategy Evolution | Custom genetic algorithm | No |

---

## Project Structure

```
src/
├── main.py                    # APScheduler orchestration loop
├── autopilot.py               # Fully autonomous trading bot
├── cli.py                     # CLI (once, watch, status)
├── dashboard.py               # Streamlit web dashboard (14 pages)
│
├── state/models.py            # Pydantic data models
├── ingestion/                 # Data providers
│   ├── openbb_provider.py     # OHLCV + technicals
│   ├── yfinance_news_provider.py  # News + sentiment
│   ├── fundamental_provider.py    # P/E, margins, revenue
│   └── state_builder.py      # Merges all data → MarketState
│
├── reasoning/                 # AI decision engine
│   ├── engine.py              # TradingAgents + fallback
│   ├── senior_trader.py       # Senior Trader prompt
│   └── prompt_store.py        # Versioned prompts
│
├── scanner/market_scanner.py  # 50+ stock momentum/volume scanner
│
├── strategy/                  # Strategy evolution + risk
│   ├── algorithm_lab.py       # Genetic algorithm strategy evolution
│   ├── ta_registry.py         # 15 built-in TA indicators
│   ├── ensemble.py            # Multi-model consensus voting
│   ├── intraday_strategist.py # Position sizing + capital allocation
│   ├── position_manager.py    # SL/TP/trailing stop management
│   ├── risk_manager.py        # Circuit breakers, PDT, sector limits
│   ├── market_context.py      # VIX regime, earnings, ATR sizing
│   └── var_calculator.py      # Value-at-Risk (historical + parametric)
│
├── execution/                 # Trade execution
│   ├── portfolio.py           # Paper portfolio (long + short)
│   ├── portfolio_store.py     # Persistent state (SQLite + thread-safe)
│   ├── executor.py            # Signal → trade mapping
│   ├── fees.py                # Full broker fee model
│   └── trade_log.py           # SQLite trade journal
│
├── feedback/                  # Self-improvement
│   ├── reviewer.py            # Trade outcome analysis
│   ├── metrics.py             # Sharpe, drawdown, profit factor
│   └── prompt_tuner.py        # LLM-driven prompt refinement
│
├── monitoring/                # Observability
│   ├── alerts.py              # Slack + console alerts
│   ├── audit.py               # Append-only decision log
│   ├── health.py              # System health checks
│   └── logging_config.py      # Structured JSON logging
│
├── agents/developer_agent.py  # AI code-writing sub-agent
└── data/quote_store.py        # Persistent quote history
```

---

## Tests

```bash
pytest -v     # 60 tests, all passing
```

---

## Disclaimer

This is a **paper trading** system for research and educational purposes. It does not execute real trades or manage real money. Past performance of paper trades does not indicate future results. Always do your own research before making investment decisions.

---

## License

MIT
