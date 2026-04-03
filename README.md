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
  <img src="https://img.shields.io/badge/tests-54%20passing-brightgreen?style=flat-square" alt="Tests">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
</p>

---

## What is this?

**tradex-ai** is an automated paper-trading system that combines institutional-grade market data, global news sentiment, and LLM-powered multi-agent reasoning to make trading decisions — then learns from its own mistakes overnight.

It doesn't just backtest. It runs live against real market data, simulates trades with realistic broker fees, and refines its own decision-making prompts based on performance.

```
┌─────────────────────────────────────────────────────┐
│                 tradex-ai pipeline                   │
│                                                     │
│   Market Data ──┐                                   │
│   (OpenBB)      ├──▶ MarketState ──▶ Multi-Agent ──▶ Paper Trade ──▶ Feedback  │
│   News/Sentiment┘    (unified)      Reasoning       (fee-aware)     Loop       │
│   (WorldMonitor)                    (TradingAgents)                 (nightly)  │
└─────────────────────────────────────────────────────┘
```

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

### Dual Data Streams → Unified State
- **[OpenBB Platform](https://github.com/OpenBB-finance/OpenBB)** fetches OHLCV data + technical indicators for equities and crypto
- **[WorldMonitor](https://www.worldmonitor.app/)** streams real-time news headlines, macro-sentiment scores, and geopolitical instability data
- Both streams normalize into a single `MarketState` Pydantic object — one clean input to the reasoning engine

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
│   ├── worldmonitor_provider.py  # News headlines + macro sentiment
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

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/karthiksurabathula/tradex-ai.git
cd tradex-ai
pip install -e ".[dev]"
```

### 2. Configure API Keys

```bash
cp .env.example .env
# Edit .env with your keys:
#   ANTHROPIC_API_KEY=sk-ant-...
#   WORLDMONITOR_API_KEY=...
```

### 3. Choose Your Tickers

Edit `config.yaml`:

```yaml
symbols:
  - AAPL
  - NVDA
  - MSFT
  - BTC-USD

starting_cash: 100000.0
```

### 4. Run

```bash
python -m src.main
```

The bot will:
- Trade every **30 minutes** during market hours (9 AM – 4 PM, Mon–Fri)
- Run a **feedback cycle** at 8 PM nightly
- Display a live terminal dashboard with portfolio, signals, and P&L

---

## Configuration

All settings live in `config.yaml`:

```yaml
# Risk limits
max_position_pct: 0.10        # Max 10% of portfolio per position
min_confidence: 0.60           # Skip trades below 60% confidence
min_trades_for_feedback: 10    # Minimum sample before prompt tuning

# Fee model
fees:
  commission_per_trade: 4.95
  spread_pct_equity: 0.0002
  spread_pct_crypto: 0.003
  sec_fee_per_million: 8.00
  slippage_pct: 0.001

# LLM
llm_provider: anthropic        # or openai, google, ollama
deep_think_model: claude-sonnet-4-6
quick_think_model: claude-sonnet-4-6
```

---

## How the Reasoning Works

tradex-ai uses a **supplement, don't replace** strategy:

1. **TradingAgents** runs its full multi-agent analyst pipeline (technical, sentiment, news, fundamental analysis + bull/bear debate)
2. **OpenBB** technicals and **WorldMonitor** sentiment are injected as **supplementary context** into the Senior Trader's prompt — a "second opinion"
3. The Senior Trader synthesizes everything into a structured decision:

```
SIGNAL: BUY
CONFIDENCE: 0.82
QUANTITY: 45
REASONING: RSI at 28 (oversold) with positive MACD crossover.
           WorldMonitor sentiment bullish (0.65) with low instability.
           Entering with reduced size due to elevated macro event count.
```

If TradingAgents is not installed, the fallback engine uses a weighted scoring model:

| Signal Source | Weight | Indicators |
|---------------|--------|------------|
| Technical | 60% | RSI (<30 buy / >70 sell), MACD histogram, Bollinger Band position |
| Sentiment | 40% | WorldMonitor overall score (-1 to +1) |

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
tests/test_fees.py           ✓✓✓✓✓✓✓     7 passed
tests/test_portfolio.py      ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓  15 passed
tests/test_trade_log.py      ✓✓✓✓✓✓       6 passed
tests/test_executor.py       ✓✓✓✓✓✓✓     7 passed
tests/test_metrics.py        ✓✓✓✓✓✓       6 passed
tests/test_reasoning.py      ✓✓✓✓✓✓       6 passed
tests/test_state_models.py   ✓✓✓✓✓✓✓     7 passed
─────────────────────────────────────────────
                             54 passed in 0.5s
```

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Market Data | [OpenBB Platform](https://github.com/OpenBB-finance/OpenBB) | OHLCV, technicals, 100+ data providers |
| News & Sentiment | [WorldMonitor](https://www.worldmonitor.app/) | 435+ feeds, macro-sentiment, instability index |
| Reasoning | [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Multi-agent LLM trading desk simulation |
| LLM | [Claude](https://www.anthropic.com/) (Anthropic) | Senior Trader decisions + prompt tuning |
| Data Models | [Pydantic](https://docs.pydantic.dev/) | Type-safe state management |
| Scheduling | [APScheduler](https://apscheduler.readthedocs.io/) | Cron-based trading + feedback cycles |
| Terminal UI | [Rich](https://github.com/Textualize/rich) | Bloomberg-style portfolio display |
| Trade Storage | SQLite | Zero-config trade journal |

---

## Disclaimer

This is a **paper trading** system for research and educational purposes. It does not execute real trades or manage real money. Past performance of paper trades does not indicate future results. Always do your own research before making investment decisions.

---

## License

MIT
