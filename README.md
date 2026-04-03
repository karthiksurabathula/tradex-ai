<p align="center">
  <h1 align="center">tradex-ai</h1>
  <p align="center">
    <strong>An AI-powered paper-trading bot that thinks like a hedge fund.</strong>
  </p>
  <p align="center">
    Multi-agent reasoning &bull; Real-time sentiment &bull; Fee-realistic execution &bull; Self-improving
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/tests-60%20passing-brightgreen?style=flat-square" alt="Tests">
  <img src="https://img.shields.io/badge/API%20keys-zero%20required-orange?style=flat-square" alt="Zero keys required">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
</p>

---

## What is this?

**tradex-ai** is an automated paper-trading system that combines institutional-grade market data, global news sentiment, and LLM-powered multi-agent reasoning to make trading decisions — then learns from its own mistakes overnight.

It doesn't just backtest. It runs live against real market data, simulates trades with realistic broker fees, and refines its own decision-making prompts based on performance.

**Works out of the box with zero API keys.** All data sources (yfinance, GDELT) are free and keyless. Add an Anthropic key to unlock the full LLM-powered multi-agent reasoning.

```
┌──────────────────────────────────────────────────────────┐
│                    tradex-ai pipeline                     │
│                                                          │
│   Market Data ──┐                                        │
│   (yfinance)    ├──▶ MarketState ──▶ Multi-Agent ──▶ Paper Trade ──▶ Feedback │
│   News/Sentiment┘    (unified)      Reasoning       (fee-aware)     Loop      │
│   (GDELT)                           (TradingAgents)                 (nightly) │
└──────────────────────────────────────────────────────────┘
```

---

## Zero-Config Quick Start

```bash
git clone https://github.com/karthiksurabathula/tradex-ai.git
cd tradex-ai
pip install -e ".[dev]"
python -m src.main
```

That's it. No API keys, no signup, no `.env` file needed for the base system.

| What you get | API key needed? |
|---|---|
| Live price data (equities + crypto) | No — yfinance via OpenBB |
| Technical indicators (RSI, MACD, Bollinger) | No — OpenBB |
| News headlines & sentiment | No — GDELT (free, 435+ sources) |
| Paper portfolio with realistic fees | No — local SQLite |
| Terminal dashboard | No — Rich |
| **LLM multi-agent reasoning** | **Optional** — Anthropic key |
| **Nightly prompt self-tuning** | **Optional** — Anthropic key |

> Without an Anthropic key, the system uses a built-in **rule-based fallback engine** (RSI + MACD + Bollinger + GDELT sentiment scoring). Add `ANTHROPIC_API_KEY` to `.env` to unlock the full multi-agent AI pipeline.

---

## Key Features

### Multi-Agent Reasoning Engine
Integrates with [TradingAgents](https://github.com/TauricResearch/TradingAgents) — a framework that simulates a full trading desk with specialized AI agents:

- **Technical Analyst** — RSI, MACD, Bollinger Bands, price action
- **Sentiment Analyst** — market mood from social and news signals
- **News Analyst** — macroeconomic event interpretation
- **Fundamental Analyst** — financial metrics and valuations
- **Bull/Bear Researchers** — structured debate mechanism
- **Senior Trader** — final synthesis and decision
- **Risk Manager** — portfolio-level guardrails

When TradingAgents isn't installed, a built-in rule-based fallback engine takes over with configurable technical/sentiment weighting (60/40 split).

### Dual Data Streams, Zero Keys
- **[OpenBB Platform](https://github.com/OpenBB-finance/OpenBB)** via yfinance — OHLCV data + technical indicators for equities and crypto. Supports intraday intervals (1m, 5m, 15m, 30m, 1h, 1d). Free, no key.
- **[GDELT](https://www.gdeltproject.org/)** — real-time global news from 435+ sources with tone/sentiment scoring. Updates every 15 minutes. Free, no key, no rate limits.
- **[WorldMonitor](https://www.worldmonitor.app/)** — optional upgrade for richer sentiment analysis if you have an API key. The system auto-detects and uses GDELT when no WorldMonitor key is configured.
- Both streams normalize into a single `MarketState` Pydantic object — one clean input to the reasoning engine

### High-Frequency Ready
Default config runs **6 trades per hour** per symbol with 5-minute candles:

```yaml
schedule:
  trading_interval_minutes: 10    # Every 10 minutes
data_interval: 5m                 # 5-minute OHLCV candles
data_lookback_days: 5             # 5 days of intraday history
```

### Fee-Realistic Paper Trading
Paper trading without realistic costs is fiction. tradex-ai simulates **full traditional broker fees** on every trade:

| Cost Component | Rate | Applied On |
|----------------|------|------------|
| Commission | $4.95 / trade | All trades |
| Bid-Ask Spread | 0.02% equity, 0.30% crypto | All trades |
| Slippage | 0.10% | All trades |
| SEC Fee | $8 / $1M notional | Sells only |

Every trade logs `gross_pnl` and `net_pnl` separately. The terminal always shows cumulative fees so you never lose sight of cost drag.

### Self-Correcting Feedback Loop
Every night at 8 PM, the system:
1. Reviews all trades from the day — win rate, P&L, Sharpe ratio, max drawdown
2. Identifies **loss patterns** (e.g., "caught falling knife on RSI oversold signal — 5 occurrences")
3. Uses Claude to suggest **targeted prompt refinements** for the Senior Trader agent
4. Saves versioned prompts to disk — fully auditable, git-trackable, rollback-ready

---

## Architecture

```
src/
├── state/
│   └── models.py              # Pydantic models: MarketState, TradeSignal, etc.
│
├── ingestion/
│   ├── openbb_provider.py     # OHLCV + technicals (equities & crypto)
│   ├── gdelt_provider.py      # News + sentiment (free, no API key)
│   ├── worldmonitor_provider.py  # News + sentiment (optional, needs key)
│   └── state_builder.py       # Merges both streams → MarketState
│
├── reasoning/
│   ├── engine.py              # TradingAgents orchestration + fallback
│   ├── senior_trader.py       # Senior Trader prompt template
│   ├── agent_config.py        # LLM provider configuration
│   └── prompt_store.py        # Versioned prompt management
│
├── execution/
│   ├── fees.py                # Full traditional broker fee model
│   ├── portfolio.py           # Paper portfolio with fee-aware PnL
│   ├── executor.py            # Signal → trade mapping + position sizing
│   ├── trade_log.py           # SQLite trade journal
│   └── terminal_ui.py         # Rich terminal dashboard
│
├── feedback/
│   ├── reviewer.py            # Trade outcome pattern analysis
│   ├── metrics.py             # Sharpe, drawdown, profit factor, win rate
│   └── prompt_tuner.py        # LLM-driven prompt refinement
│
└── main.py                    # APScheduler orchestration loop
```

---

## Setup Options

### Option A: Zero keys (rule-based engine)

```bash
git clone https://github.com/karthiksurabathula/tradex-ai.git
cd tradex-ai
pip install -e ".[dev]"
python -m src.main
```

Uses yfinance for prices, GDELT for sentiment, rule-based signals. Fully functional.

### Option B: With AI reasoning (recommended)

```bash
pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
```

```bash
pip install tradingagents    # Optional: enables full multi-agent pipeline
python -m src.main
```

### Option C: Full stack (all providers)

```
ANTHROPIC_API_KEY=sk-ant-...
WORLDMONITOR_API_BASE=https://api.worldmonitor.app
WORLDMONITOR_API_KEY=wm-...
```

When a WorldMonitor key is present, the system automatically switches from GDELT to WorldMonitor for richer sentiment data.

---

## Configuration

All settings live in `config.yaml`:

```yaml
# Tickers
symbols: [AAPL, NVDA, MSFT, BTC-USD]
starting_cash: 100000.0

# Data
data_provider: yfinance            # Free, no key
data_interval: 5m                  # 1m, 5m, 15m, 30m, 1h, 1d
data_lookback_days: 5

# Schedule
schedule:
  trading_interval_minutes: 10     # 6 trades/hour per symbol
  market_hours_start: 9
  market_hours_end: 16
  feedback_hour: 20

# Risk limits
max_position_pct: 0.10            # Max 10% of portfolio per position
min_confidence: 0.60              # Skip trades below 60% confidence

# Fee model (full traditional broker)
fees:
  commission_per_trade: 4.95
  spread_pct_equity: 0.0002       # 0.02%
  spread_pct_crypto: 0.003        # 0.30%
  sec_fee_per_million: 8.00
  slippage_pct: 0.001             # 0.10%

# LLM (only needed for AI reasoning)
llm_provider: anthropic
deep_think_model: claude-sonnet-4-6
quick_think_model: claude-sonnet-4-6
```

---

## How the Reasoning Works

tradex-ai uses a **supplement, don't replace** strategy:

1. **TradingAgents** runs its full multi-agent analyst pipeline (technical, sentiment, news, fundamental analysis + bull/bear debate)
2. **OpenBB** technicals and **GDELT** sentiment are injected as **supplementary context** into the Senior Trader's prompt — a "second opinion"
3. The Senior Trader synthesizes everything into a structured decision:

```
SIGNAL: BUY
CONFIDENCE: 0.82
QUANTITY: 45
REASONING: RSI at 28 (oversold) with positive MACD crossover.
           GDELT sentiment bullish (0.65) across 42 recent articles.
           Entering with reduced size due to elevated macro event count.
```

If TradingAgents is not installed, the fallback engine uses a weighted scoring model:

| Signal Source | Weight | Indicators |
|---------------|--------|------------|
| Technical | 60% | RSI (<30 buy / >70 sell), MACD histogram, Bollinger Band position |
| Sentiment | 40% | GDELT tone score (-1 to +1) |

Score > 0.2 → **BUY** &nbsp;|&nbsp; Score < -0.2 → **SELL** &nbsp;|&nbsp; Otherwise → **HOLD**

---

## Feedback & Self-Correction

The nightly feedback loop detects patterns like:

| Pattern | Action |
|---------|--------|
| Win rate < 40% | Increase HOLD threshold, tighten stop-losses |
| 5+ consecutive losses | Pause and review strategy |
| Profit factor < 1.0 | System losing money — needs recalibration |
| Fees > 50% of gross P&L | Reduce trade frequency or increase position sizes |
| Over-weighted bullish sentiment | Reduce sentiment weight from 30% → 20% |
| RSI "falling knife" entries | Add trend confirmation requirement |

Refined prompts are saved as versioned JSON files in `data/prompt_versions/`, making every change auditable and reversible.

---

## Tests

```bash
pytest -v
```

```
tests/test_fees.py             ✓✓✓✓✓✓✓       7 passed
tests/test_gdelt_provider.py   ✓✓✓✓✓✓         6 passed
tests/test_portfolio.py        ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓  15 passed
tests/test_trade_log.py        ✓✓✓✓✓✓         6 passed
tests/test_executor.py         ✓✓✓✓✓✓✓       7 passed
tests/test_metrics.py          ✓✓✓✓✓✓         6 passed
tests/test_reasoning.py        ✓✓✓✓✓✓         6 passed
tests/test_state_models.py     ✓✓✓✓✓✓✓       7 passed
──────────────────────────────────────────────
                               60 passed in 1.1s
```

---

## Tech Stack

| Component | Technology | API Key? | Purpose |
|-----------|------------|----------|---------|
| Market Data | [OpenBB](https://github.com/OpenBB-finance/OpenBB) + yfinance | No | OHLCV, technicals, intraday to daily |
| News & Sentiment | [GDELT](https://www.gdeltproject.org/) | No | 435+ global news sources, tone scoring |
| News & Sentiment | [WorldMonitor](https://www.worldmonitor.app/) | Optional | Richer sentiment, instability index |
| Reasoning | [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Optional | Multi-agent LLM trading desk |
| LLM | [Claude](https://www.anthropic.com/) (Anthropic) | Optional | Senior Trader decisions + prompt tuning |
| Data Models | [Pydantic](https://docs.pydantic.dev/) | No | Type-safe state management |
| Scheduling | [APScheduler](https://apscheduler.readthedocs.io/) | No | Cron-based trading + feedback cycles |
| Terminal UI | [Rich](https://github.com/Textualize/rich) | No | Bloomberg-style portfolio display |
| Trade Storage | SQLite | No | Zero-config trade journal |

---

## Disclaimer

This is a **paper trading** system for research and educational purposes. It does not execute real trades or manage real money. Past performance of paper trades does not indicate future results. Always do your own research before making investment decisions.

---

## License

MIT
