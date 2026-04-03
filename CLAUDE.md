# tradex-ai

## Overview
Autonomous AI paper-trading bot. Scans markets, picks stocks, trades intraday, manages risk, and evolves its own strategies — no human intervention needed.

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

## Layers

| Layer | Modules | Purpose |
|-------|---------|---------|
| **Ingestion** | `openbb_provider`, `yfinance_news_provider`, `fundamental_provider`, `state_builder` | Fetch OHLCV, technicals, news, sentiment, fundamentals |
| **Reasoning** | `engine`, `senior_trader`, `ensemble` | Multi-agent or rule-based BUY/SELL/HOLD signals |
| **Strategy** | `algorithm_lab`, `ta_registry`, `intraday_strategist`, `market_context`, `var_calculator` | Self-evolving strategies, position sizing, regime detection |
| **Execution** | `portfolio`, `portfolio_store`, `executor`, `fees`, `trade_log` | Paper trades with fees, persistent state, SQLite journal |
| **Risk** | `risk_manager`, `position_manager` | Stop-loss, take-profit, trailing stop, PDT, daily limits, kill switch, sector/correlation checks |
| **Feedback** | `reviewer`, `metrics`, `prompt_tuner`, `prompt_store` | Nightly review, loss pattern detection, LLM prompt refinement |
| **Monitoring** | `alerts`, `audit`, `health`, `logging_config` | Slack alerts, append-only audit trail, health checks, structured logging |
| **Agents** | `developer_agent` | AI writes and validates new TA indicators |
| **Scanner** | `market_scanner` | Scans 50+ stocks for momentum, volume, sector rotation |

## Commands
```bash
streamlit run src/dashboard.py      # Web dashboard (everything)
python -m src.autopilot             # Terminal autopilot
python -m src.autopilot --aggressive # More positions, wider stops
python -m src.cli once              # Single trading cycle
python -m src.cli status            # Show trade history
```

## Key Design Decisions
- **Supplement, don't replace**: TradingAgents runs its own analysts; we inject extra context
- **Fees always applied**: Every paper trade deducts commission + spread + slippage + SEC
- **Persistent state**: Portfolio survives restarts (SQLite-backed)
- **Self-evolving**: AlgorithmLab breeds strategies via genetic algorithm
- **Walk-forward testing**: Backtest uses 70/30 train/test split with fees
- **Statistical significance**: Monte Carlo permutation tests before promoting strategies

## Data Files (gitignored)
- `data/trades.db` — Trade journal
- `data/portfolio.db` — Persistent portfolio state
- `data/quotes.db` — Historical quote store
- `data/algorithm_lab.db` — Strategy evolution results
- `data/audit.db` — Append-only decision audit trail
- `data/prompt_versions/` — Versioned Senior Trader prompts
- `data/custom_algorithms/` — Developer Agent created indicators
