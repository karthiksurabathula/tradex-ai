"""Unified web dashboard — everything in one place.

Combines: autopilot scanner, manual trading, portfolio, AI analysis,
trade log, performance analytics, feedback loop, and settings.

Run: streamlit run src/dashboard.py
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st
import yfinance as yf

from src.agents.developer_agent import DeveloperAgent
from src.data.quote_store import QuoteStore
from src.execution.executor import Executor
from src.execution.fees import FeeModel
from src.execution.portfolio import Portfolio
from src.execution.portfolio_store import PersistentPortfolio
from src.execution.trade_log import TradeLog
from src.feedback.metrics import compute_metrics
from src.feedback.reviewer import TradeReviewer
from src.ingestion.openbb_provider import OpenBBProvider
from src.ingestion.state_builder import StateBuilder
from src.ingestion.yfinance_news_provider import YFinanceNewsProvider
from src.reasoning.engine import ReasoningEngine
from src.reasoning.prompt_store import PromptStore
from src.scanner.market_scanner import MarketScanner, ScanResult
from src.state.models import SignalType, TradeSignal
from src.strategy.algorithm_lab import AlgorithmLab
from src.strategy.intraday_strategist import IntradayStrategist
from src.strategy.market_context import MarketContextProvider
from src.strategy.position_manager import PositionManager
from src.strategy.risk_manager import RiskManager

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="tradex-ai", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 0.5rem; }
    div[data-testid="stMetric"] {
        background: #0e1117; padding: 8px; border-radius: 6px; border: 1px solid #262730;
    }
    .help-tip { font-size: 0.85em; color: #888; background: #1a1a2e; padding: 8px 12px;
                border-radius: 6px; border-left: 3px solid #4a6cf7; margin: 4px 0 12px 0; }
</style>
""", unsafe_allow_html=True)


# ── Help Texts ───────────────────────────────────────────────────────────────
HELP = {
    "portfolio_value": "Total value of your paper portfolio: cash + value of all open positions (long and short). Starts at $100,000.",
    "cash": "Available cash for new trades. Reduced by purchases + fees. Increases when you sell.",
    "realized_pnl": "Profit/loss from closed trades (after fees). Only counts positions you've exited.",
    "unrealized_pnl": "Paper profit/loss on positions you still hold. Changes with live prices.",
    "fees": "Total broker fees paid across all trades: commission ($4.95) + spread + slippage + SEC fee.",
    "trades_today": "Number of trades executed in the current session.",

    "autopilot": "The AI autonomously scans 50+ stocks, picks the best opportunities, confirms with its reasoning engine, executes trades, and monitors positions with stop-loss/take-profit. Click 'Run Cycle' or enable 'Auto-run' to let it trade continuously.",
    "run_cycle": "Runs one full trading cycle: (1) Scan market for movers, (2) AI analyzes top picks, (3) Execute trades that pass all filters, (4) Check existing positions for exits. Takes 30-60 seconds.",
    "auto_run": "When enabled, the bot runs cycles automatically at the interval you set. It will keep scanning, trading, and monitoring without any human input.",

    "manual_trade": "Type stock symbols (comma-separated) to analyze them. The AI evaluates technicals (RSI, MACD, Bollinger Bands), news sentiment, and gives a BUY/SELL/HOLD recommendation. You can then manually execute trades with the buttons.",
    "analyze_btn": "Fetches live price data, computes 15+ technical indicators, and runs the AI reasoning engine to produce a trading signal for each symbol.",

    "positions": "Shows all open positions (long and short) with entry price, current price, P&L, and risk levels. Stop-loss automatically sells if price drops too far. Take-profit locks in gains. Trailing stop follows the price up.",
    "stop_loss": "Automatic sell trigger if price drops below this level. Protects against large losses. Adjusted by volatility (ATR) — wider in volatile markets.",
    "take_profit": "Automatic sell trigger when price reaches this target. Locks in profits at a predefined level (default: 4% gain).",
    "trailing_stop": "Follows the price upward. If the stock rises 5% then drops 1.5% from the peak, it sells — locking in most of the gain.",

    "scanner": "Scans 50+ stocks across S&P 500 and crypto for: momentum (price + volume spikes), volume breakouts (unusual trading activity), and sector rotation (strongest/weakest sectors). Each opportunity gets a score from 0-100.",
    "scanner_score": "Higher = better opportunity. Combines momentum strength, volume ratio, and price change. Scores above 25 are considered tradeable.",

    "ai_analysis": "The AI reasoning engine evaluates each stock using: RSI (overbought/oversold), MACD (trend), Bollinger Bands (volatility), and news sentiment. It produces a BUY/SELL/HOLD signal with confidence level and written reasoning.",

    "trade_log": "Every trade ever executed, with full details: price, quantity, fees, P&L, and the AI's reasoning for the decision. Filter by symbol to see history for a specific stock.",

    "performance": "Historical performance metrics: win rate, Sharpe ratio (risk-adjusted return), max drawdown (worst peak-to-trough loss), and profit factor (gross wins / gross losses). The equity curve shows portfolio value over time.",
    "sharpe": "Risk-adjusted return metric. > 1.0 is good, > 2.0 is excellent, < 0 means losing money. Measures return per unit of risk.",
    "max_drawdown": "Largest peak-to-trough decline. If portfolio went from $105k to $98k, drawdown is $7k. Lower is better.",
    "profit_factor": "Gross winning trades / gross losing trades. > 1.0 means profitable. > 2.0 is very good.",

    "algo_lab": "The AI evolves its own trading strategies using a genetic algorithm: (1) Generate random indicator combinations, (2) Backtest on historical data, (3) Breed the winners, (4) Promote the best to production. Each generation gets smarter.",
    "evolve": "Starts a strategy evolution cycle. Creates random strategies, tests them on historical data (with fees and walk-forward validation), breeds the top performers, and promotes the winner.",

    "dev_agent": "An AI sub-agent that writes new technical analysis algorithms on demand. Describe what you want in plain English (e.g., 'detect mean reversion') and it generates, validates, and registers the Python code automatically.",

    "risk_regime": "Shows current market conditions: VIX (fear gauge), market regime (BULL/BEAR/VOLATILE/SIDEWAYS), and how the AI adjusts its behavior. In volatile markets, position sizes are reduced and stops are widened.",
    "kill_switch": "Emergency halt — immediately stops ALL trading. Use if something goes wrong. Trading stays halted until you deactivate it. Can also be triggered automatically by the daily loss limit.",

    "quote_store": "Persistent database of price history. The AI collects quotes for stocks it watches, building a local dataset for backtesting and strategy evolution. More data = better strategies.",

    "settings": "Adjust risk parameters (stop-loss %, take-profit %, max positions), view fee model details, and reset the portfolio to start fresh.",
}


def info(key: str):
    """Show an info tooltip for a help key."""
    text = HELP.get(key, "")
    if text:
        st.markdown(f'<div class="help-tip">&#9432; {text}</div>', unsafe_allow_html=True)


def help_icon(key: str) -> str:
    """Return help text for use in Streamlit's help= parameter."""
    return HELP.get(key, "")


# ── Onboarding Wizard ────────────────────────────────────────────────────────
def show_onboarding():
    """Step-by-step guide for first-time users."""
    if "onboarding_done" in st.session_state:
        return

    with st.expander("Welcome to tradex-ai! Click here for a quick setup guide", expanded=True):
        st.markdown("""
### Getting Started in 4 Steps

**Step 1: Understand your portfolio**
> You start with **$100,000 in paper money**. This is simulated — no real money is involved.
> The top bar shows your portfolio value, cash, P&L, and fees at all times.

**Step 2: Let the AI trade for you (Autopilot)**
> Go to the **Autopilot** tab and click **"Run Cycle"**. The AI will:
> 1. Scan 50+ stocks for momentum, volume spikes, and sector moves
> 2. Analyze the best opportunities with technical indicators + news sentiment
> 3. Execute trades that pass all safety filters (earnings, correlation, risk limits)
> 4. Monitor existing positions and exit when stop-loss/take-profit triggers
>
> Enable **"Auto-run"** to let it trade continuously without you clicking anything.

**Step 3: Or trade manually (Manual Trade)**
> Go to **Manual Trade**, type stock symbols (e.g., `AAPL, NVDA, TSLA`), click **Analyze**.
> The AI shows its recommendation. Click **BUY** or **SELL** to execute.

**Step 4: Monitor and learn**
> - **Positions** — see your open trades with stop-loss/take-profit levels
> - **Performance** — track win rate, Sharpe ratio, equity curve over time
> - **AI Analysis** — read exactly why the AI made each decision
> - **Algorithm Lab** — watch the AI evolve its own strategies
> - **Risk & Regime** — see market conditions and safety controls

### Key Concepts
| Term | What it means |
|------|--------------|
| **Stop-Loss** | Auto-sells if price drops 2% below entry — limits your losses |
| **Take-Profit** | Auto-sells when price rises 4% above entry — locks in gains |
| **Trailing Stop** | Follows price up, sells if it drops 1.5% from peak — captures gains |
| **Kill Switch** | Emergency halt — stops ALL trading instantly |
| **Market Regime** | BULL/BEAR/VOLATILE/SIDEWAYS — AI adjusts strategy per regime |
| **Scanner Score** | 0-100 opportunity ranking — higher is better |

### Tips
- Start with **Autopilot** to see the AI in action
- Check **Performance** after a few cycles to see how it's doing
- Use **Algorithm Lab** to let the AI discover better strategies
- The **Event Feed** shows everything the AI does in real-time
        """)

        if st.button("Got it! Start trading", type="primary"):
            st.session_state.onboarding_done = True
            st.rerun()


# ── Session State ────────────────────────────────────────────────────────────
def init_session():
    if "init" in st.session_state:
        return
    fm = FeeModel()
    pp = PersistentPortfolio(starting_cash=100_000.0, fee_model=fm)
    tl = TradeLog(db_path="data/trades.db")
    ps = PromptStore()
    qs = QuoteStore()

    st.session_state.update({
        "init": True,
        "portfolio": pp,
        "trade_log": tl,
        "prompt_store": ps,
        "quote_store": qs,
        "scanner": MarketScanner(),
        "strategist": IntradayStrategist(),
        "pos_mgr": PositionManager(),
        "risk_mgr": RiskManager(),
        "market_ctx": MarketContextProvider(),
        "engine": ReasoningEngine(),
        "state_builder": StateBuilder(
            OpenBBProvider(provider="yfinance", interval="5m"),
            YFinanceNewsProvider(),
        ),
        "executor": Executor(pp.portfolio, tl, max_position_pct=0.15, min_confidence=0.30),
        "reviewer": TradeReviewer(tl),
        "algo_lab": AlgorithmLab(qs),
        "dev_agent": DeveloperAgent(),
        "events": [],
        "scan_results": [],
        "analyzed": {},
        "manual_results": [],
        "cycle_count": 0,
        "trades_today": 0,
    })

init_session()

# Shortcuts
portfolio = st.session_state.portfolio
trade_log = st.session_state.trade_log
pos_mgr = st.session_state.pos_mgr


def log_event(t: str, msg: str, sym: str = ""):
    st.session_state.events.append({"time": datetime.now().strftime("%H:%M:%S"), "type": t, "symbol": sym, "message": msg})
    if len(st.session_state.events) > 200:
        st.session_state.events = st.session_state.events[-200:]


def get_prices() -> dict[str, float]:
    prices = {}
    for s in portfolio.positions:
        try:
            prices[s] = yf.Ticker(s).fast_info.get("lastPrice", 0)
        except Exception:
            prices[s] = portfolio.positions[s].avg_cost
    return prices


# ── Autopilot Phases ─────────────────────────────────────────────────────────
def autopilot_scan():
    log_event("SCAN", "Scanning 50+ stocks...")
    try:
        r = st.session_state.scanner.full_scan(top_n=12)
        st.session_state.scan_results = r
        for x in r[:5]:
            log_event("FOUND", f"Score {x.score:.0f}: {x.reason}", x.symbol)
        return r
    except Exception as e:
        log_event("ERROR", str(e))
        return []


def autopilot_analyze(scan_results):
    analyzed = {}
    end = datetime.now(UTC)
    start = end - timedelta(days=5)
    for r in scan_results[:8]:
        try:
            state = st.session_state.state_builder.build(r.symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            signal = st.session_state.engine.decide(state)
            analyzed[r.symbol] = {
                "scan": r, "state": state, "signal": signal,
                "price": state.technicals.current_price,
                "rsi": state.technicals.rsi, "rsi_label": state.technicals.rsi_label,
                "macd_h": state.technicals.macd_histogram,
                "bb_lower": state.technicals.bb_lower, "bb_mid": state.technicals.bb_mid, "bb_upper": state.technicals.bb_upper,
                "sentiment": state.sentiment.overall_score,
                "headlines": [h.get("title", "") for h in state.headlines[:5]],
                "themes": state.sentiment.top_themes[:3],
            }
            log_event("ANALYZE", f"{signal.action.value} ({signal.confidence:.0%})", r.symbol)
        except Exception as e:
            log_event("ERROR", str(e), r.symbol)
    st.session_state.analyzed = analyzed
    return analyzed


def autopilot_trade(scan_results, analyzed):
    prices = {s: a["price"] for s, a in analyzed.items()}
    prices.update(get_prices())

    if st.session_state.strategist.should_exit_all(portfolio, prices):
        log_event("EMERGENCY", "Exiting all positions!")
        for s in list(portfolio.positions):
            pos = portfolio.positions[s]
            pr = prices.get(s, pos.avg_cost)
            res = portfolio.sell(s, pos.quantity, pr)
            if res:
                pos_mgr.remove(s)
                log_event("CLOSED", f"Emergency exit P&L: ${res['net_pnl']:+,.2f}", s)
        return

    opps = st.session_state.strategist.select_opportunities(scan_results, portfolio, prices)
    for opp in opps:
        a = analyzed.get(opp.symbol)
        if a and a["signal"].action == SignalType.SELL and opp.direction == "BUY":
            log_event("VETO", "AI vetoed BUY", opp.symbol)
            continue
        fees = portfolio.buy(opp.symbol, opp.quantity, opp.price)
        if fees:
            pos_mgr.register_entry(opp.symbol, opp.price)
            st.session_state.trades_today += 1
            trade_log.record(
                TradeSignal(symbol=opp.symbol, action=SignalType.BUY, confidence=opp.score / 100, reasoning=opp.reason),
                price=opp.price, executed=True, quantity=opp.quantity, fees=fees,
            )
            log_event("BOUGHT", f"{opp.quantity} @ ${opp.price:,.2f} (fees ${fees['total']:,.2f})", opp.symbol)


def autopilot_monitor():
    if not portfolio.positions:
        return
    prices = get_prices()
    for ex in pos_mgr.check_exits(prices):
        pos = portfolio.positions.get(ex.symbol)
        if not pos:
            continue
        res = portfolio.sell(ex.symbol, pos.quantity, ex.current_price)
        if res:
            pos_mgr.remove(ex.symbol)
            st.session_state.trades_today += 1
            tag = "PROFIT" if res["net_pnl"] > 0 else "LOSS"
            trade_log.record(
                TradeSignal(symbol=ex.symbol, action=SignalType.SELL, confidence=0.9, reasoning=ex.reason),
                price=ex.current_price, executed=True, quantity=pos.quantity,
                gross_pnl=res["gross_pnl"], net_pnl=res["net_pnl"], fees=res["fees"],
            )
            log_event(tag, f"Sold {pos.quantity} @ ${ex.current_price:,.2f} | P&L ${res['net_pnl']:+,.2f} | {ex.reason}", ex.symbol)


def run_autopilot_cycle(progress_bar):
    st.session_state.cycle_count += 1
    progress_bar.progress(10, "Scanning market...")
    scan = autopilot_scan()
    if not scan:
        progress_bar.progress(100, "No opportunities found.")
        return
    progress_bar.progress(30, "AI analyzing...")
    analyzed = autopilot_analyze(scan)
    progress_bar.progress(60, "Executing trades...")
    autopilot_trade(scan, analyzed)
    progress_bar.progress(80, "Monitoring positions...")
    autopilot_monitor()
    progress_bar.progress(100, f"Cycle #{st.session_state.cycle_count} complete!")


# ── Manual Trading ───────────────────────────────────────────────────────────
def manual_analyze(symbols: list[str]):
    results = []
    end = datetime.now(UTC)
    start = end - timedelta(days=5)
    for sym in symbols:
        try:
            state = st.session_state.state_builder.build(sym, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            signal = st.session_state.engine.decide(state)
            results.append({
                "symbol": sym, "signal": signal, "state": state,
                "price": state.technicals.current_price,
                "rsi": state.technicals.rsi, "rsi_label": state.technicals.rsi_label,
                "macd_h": state.technicals.macd_histogram,
                "bb_lower": state.technicals.bb_lower, "bb_mid": state.technicals.bb_mid, "bb_upper": state.technicals.bb_upper,
                "sentiment": state.sentiment.overall_score,
                "headlines": [h.get("title", "") for h in state.headlines[:5]],
            })
            log_event("MANUAL", f"{signal.action.value} ({signal.confidence:.0%})", sym)
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})
    st.session_state.manual_results = results
    return results


def manual_execute(symbol: str, action: str, quantity: int, price: float):
    if action == "BUY":
        fees = portfolio.buy(symbol, quantity, price)
        if fees:
            pos_mgr.register_entry(symbol, price)
            st.session_state.trades_today += 1
            trade_log.record(
                TradeSignal(symbol=symbol, action=SignalType.BUY, confidence=0.8, reasoning="Manual trade"),
                price=price, executed=True, quantity=quantity, fees=fees,
            )
            log_event("BOUGHT", f"Manual: {quantity} @ ${price:,.2f}", symbol)
            return True
    elif action == "SELL":
        pos = portfolio.positions.get(symbol)
        if pos:
            qty = min(quantity, pos.quantity)
            res = portfolio.sell(symbol, qty, price)
            if res:
                pos_mgr.remove(symbol)
                st.session_state.trades_today += 1
                trade_log.record(
                    TradeSignal(symbol=symbol, action=SignalType.SELL, confidence=0.8, reasoning="Manual trade"),
                    price=price, executed=True, quantity=qty,
                    gross_pnl=res["gross_pnl"], net_pnl=res["net_pnl"], fees=res["fees"],
                )
                log_event("SOLD", f"Manual: {qty} @ ${price:,.2f} | P&L ${res['net_pnl']:+,.2f}", symbol)
                return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
#  LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

# ── Onboarding ───────────────────────────────────────────────────────────────
show_onboarding()

# ── Header ───────────────────────────────────────────────────────────────────
prices = get_prices()
summary = portfolio.summary(prices)
ret_pct = ((summary["total_value"] - 100_000) / 100_000) * 100

hc1, hc2 = st.columns([4, 1])
with hc1:
    st.title("tradex-ai")
with hc2:
    st.caption(f"Cycle #{st.session_state.cycle_count} | {datetime.now().strftime('%H:%M:%S')}")

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Portfolio", f"${summary['total_value']:,.2f}", f"{ret_pct:+.2f}%", help=help_icon("portfolio_value"))
m2.metric("Cash", f"${summary['cash']:,.2f}", help=help_icon("cash"))
m3.metric("Realized", f"${summary['realized_pnl']:+,.2f}", help=help_icon("realized_pnl"))
m4.metric("Unrealized", f"${summary['unrealized_pnl']:+,.2f}", help=help_icon("unrealized_pnl"))
m5.metric("Fees", f"${summary['total_fees_paid']:,.2f}", help=help_icon("fees"))
m6.metric("Trades", st.session_state.trades_today, help=help_icon("trades_today"))

st.divider()

# ── Navigation ───────────────────────────────────────────────────────────────
page = st.radio(
    "Mode",
    ["Autopilot", "Manual Trade", "Positions", "Market Scanner", "AI Analysis",
     "Trade Log", "Performance", "Algorithm Lab", "Developer Agent", "Risk & Regime",
     "Quote Store", "Event Feed", "Settings", "Help"],
    horizontal=True,
    label_visibility="collapsed",
)


# ── PAGE: Autopilot ─────────────────────────────────────────────────────────
if page == "Autopilot":
    st.subheader("Autopilot")
    info("autopilot")

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        run_btn = st.button("Run Cycle", type="primary", use_container_width=True, help=help_icon("run_cycle"))
    with c2:
        auto = st.toggle("Auto-run", value=False, help=help_icon("auto_run"))
    with c3:
        interval = st.slider("Interval (sec)", 60, 600, 120, step=30, label_visibility="collapsed", help="How often the AI runs a full trading cycle when Auto-run is enabled.")

    if run_btn:
        pb = st.progress(0)
        run_autopilot_cycle(pb)

    # Show latest scan + positions side by side
    col_scan, col_pos = st.columns(2)
    with col_scan:
        st.markdown("**Latest Scanner Hits**")
        if st.session_state.scan_results:
            for r in st.session_state.scan_results[:8]:
                score_bar = "=" * int(r.score / 5)
                st.text(f"{r.symbol:<6} [{score_bar:<12}] {r.score:>4.0f}  {r.category:<10}  {r.reason[:40]}")
        else:
            st.info("No scans yet.")

    with col_pos:
        st.markdown("**Open Positions**")
        if portfolio.positions:
            for sym, pos in portfolio.positions.items():
                p = prices.get(sym, pos.avg_cost)
                pnl = pos.unrealized_pnl(p)
                rule = pos_mgr.rules.get(sym)
                color = "green" if pnl >= 0 else "red"
                st.markdown(f"**{sym}** {pos.quantity} shares @ ${pos.avg_cost:,.2f} -> ${p:,.2f} "
                           f"(:{color}[${pnl:+,.2f}])")
                if rule:
                    st.caption(f"  SL: ${rule.stop_loss_price:,.2f} | TP: ${rule.take_profit_price:,.2f} | Trail: ${rule.trailing_stop_price:,.2f}")
        else:
            st.info("No positions. Click Run Cycle.")

    # Recent events
    st.markdown("**Recent Activity**")
    for e in reversed(st.session_state.events[-10:]):
        icons = {"BOUGHT": "+", "SOLD": "-", "PROFIT": "$", "LOSS": "X", "SCAN": ">", "FOUND": "!", "ANALYZE": "?", "VETO": "N", "ERROR": "!", "EMERGENCY": "!"}
        ic = icons.get(e["type"], "-")
        st.text(f"  {e['time']}  [{ic}] {e['type']:<10} {e['symbol']:<6}  {e['message'][:60]}")

    if auto:
        time.sleep(interval)
        pb = st.progress(0)
        run_autopilot_cycle(pb)
        st.rerun()


# ── PAGE: Manual Trade ───────────────────────────────────────────────────────
elif page == "Manual Trade":
    st.subheader("Manual Trade")
    info("manual_trade")

    c1, c2 = st.columns([3, 1])
    with c1:
        symbols_input = st.text_input("Symbols (comma-separated)", "AAPL, NVDA, TSLA, MSFT")
    with c2:
        analyze_btn = st.button("Analyze", type="primary", use_container_width=True, help=help_icon("analyze_btn"))

    if analyze_btn:
        syms = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]
        with st.spinner(f"Analyzing {len(syms)} symbols..."):
            results = manual_analyze(syms)

    # Show results
    for r in st.session_state.manual_results:
        if "error" in r:
            st.error(f"{r['symbol']}: {r['error']}")
            continue

        sig = r["signal"]
        color = {"BUY": "green", "SELL": "red", "HOLD": "orange"}[sig.action.value]

        with st.expander(f":{color}[**{sig.action.value}**] {r['symbol']} @ ${r['price']:,.2f} | RSI {r['rsi']:.1f} | Conf {sig.confidence:.0%}", expanded=(sig.action.value != "HOLD")):
            tc1, tc2, tc3 = st.columns(3)
            with tc1:
                st.markdown("**Technicals**")
                st.write(f"RSI: {r['rsi']:.1f} ({r['rsi_label']})")
                st.write(f"MACD: {r['macd_h']:+.4f}")
                st.write(f"BB: ${r['bb_lower']:,.2f} / ${r['bb_mid']:,.2f} / ${r['bb_upper']:,.2f}")
            with tc2:
                st.markdown("**Sentiment:** {:.2f}".format(r["sentiment"]))
                for h in r["headlines"][:3]:
                    if h:
                        st.caption(f"- {h[:60]}")
            with tc3:
                st.markdown("**Reasoning:**")
                st.code(sig.reasoning, language=None)

            # Trade buttons
            bc1, bc2, bc3 = st.columns([1, 1, 2])
            with bc1:
                qty = st.number_input(f"Qty ({r['symbol']})", min_value=1, value=10, key=f"qty_{r['symbol']}")
            with bc2:
                if st.button(f"BUY {r['symbol']}", key=f"buy_{r['symbol']}", type="primary"):
                    if manual_execute(r["symbol"], "BUY", qty, r["price"]):
                        st.success(f"Bought {qty} {r['symbol']}")
                        st.rerun()
                if r["symbol"] in portfolio.positions:
                    if st.button(f"SELL {r['symbol']}", key=f"sell_{r['symbol']}"):
                        if manual_execute(r["symbol"], "SELL", qty, r["price"]):
                            st.success(f"Sold {qty} {r['symbol']}")
                            st.rerun()


# ── PAGE: Positions ──────────────────────────────────────────────────────────
elif page == "Positions":
    st.subheader("Open Positions")
    info("positions")

    if portfolio.positions:
        rows = []
        for sym, pos in portfolio.positions.items():
            p = prices.get(sym, pos.avg_cost)
            pnl = pos.unrealized_pnl(p)
            pnl_pct = ((p - pos.avg_cost) / pos.avg_cost) * 100
            rule = pos_mgr.rules.get(sym)
            mins = rule.minutes_held if hasattr(rule, "minutes_held") else (datetime.now(UTC) - rule.entry_time).total_seconds() / 60 if rule else 0

            rows.append({
                "Symbol": sym, "Qty": pos.quantity,
                "Entry": f"${pos.avg_cost:,.2f}", "Current": f"${p:,.2f}",
                "P&L": f"${pnl:+,.2f}", "P&L %": f"{pnl_pct:+.1f}%",
                "Stop-Loss": f"${rule.stop_loss_price:,.2f}" if rule else "-",
                "Take-Profit": f"${rule.take_profit_price:,.2f}" if rule else "-",
                "Trail Stop": f"${rule.trailing_stop_price:,.2f}" if rule else "-",
                "Hold (min)": f"{mins:.0f}",
                "Value": f"${pos.market_value(p):,.2f}",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # Close all button
        if st.button("Close All Positions", type="secondary"):
            for sym in list(portfolio.positions):
                pos = portfolio.positions[sym]
                p = prices.get(sym, pos.avg_cost)
                res = portfolio.sell(sym, pos.quantity, p)
                if res:
                    pos_mgr.remove(sym)
                    log_event("CLOSED", f"Manual close P&L ${res['net_pnl']:+,.2f}", sym)
            st.rerun()
    else:
        st.info("No open positions.")


# ── PAGE: Market Scanner ─────────────────────────────────────────────────────
elif page == "Market Scanner":
    st.subheader("Market Scanner")
    info("scanner")

    sc1, sc2 = st.columns([1, 3])
    with sc1:
        if st.button("Scan Now", type="primary", help="Scans 50+ stocks for momentum, volume breakouts, and sector rotation. Takes ~15 seconds."):
            with st.spinner("Scanning..."):
                autopilot_scan()

    if st.session_state.scan_results:
        rows = []
        for r in st.session_state.scan_results:
            rows.append({
                "Symbol": r.symbol, "Score": f"{r.score:.0f}",
                "Category": r.category.upper(),
                "Change": f"{r.change_pct:+.1f}%",
                "Volume": f"{r.volume_ratio:.1f}x" if r.volume_ratio else "-",
                "Price": f"${r.price:,.2f}" if r.price else "-",
                "Reason": r.reason,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Click Scan Now to discover opportunities.")


# ── PAGE: AI Analysis ────────────────────────────────────────────────────────
elif page == "AI Analysis":
    st.subheader("AI Analysis")
    info("ai_analysis")

    analyzed = st.session_state.analyzed
    if analyzed:
        for sym, d in analyzed.items():
            sig = d["signal"]
            color = {"BUY": "green", "SELL": "red", "HOLD": "orange"}[sig.action.value]
            with st.expander(f":{color}[**{sig.action.value}**] {sym} | ${d['price']:,.2f} | RSI {d['rsi']:.1f} | Score {d['scan'].score:.0f}", expanded=(sig.action.value != "HOLD")):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**RSI:** {d['rsi']:.1f} ({d['rsi_label']})")
                    st.write(f"**MACD:** {d['macd_h']:+.4f}")
                    st.write(f"**BB:** ${d['bb_lower']:,.2f} / ${d['bb_mid']:,.2f} / ${d['bb_upper']:,.2f}")
                    st.write(f"**Sentiment:** {d['sentiment']:+.2f}")
                with c2:
                    for h in d["headlines"][:4]:
                        if h:
                            st.caption(f"- {h[:70]}")
                st.markdown("**Reasoning:**")
                st.code(sig.reasoning, language=None)
                st.caption(f"Scanner: {d['scan'].category} | Score {d['scan'].score:.0f} | {d['scan'].reason}")
    else:
        st.info("Run an Autopilot cycle or Manual Analysis to see AI reasoning.")


# ── PAGE: Trade Log ──────────────────────────────────────────────────────────
elif page == "Trade Log":
    st.subheader("Trade Log")
    info("trade_log")

    filter_sym = st.text_input("Filter by symbol (blank = all)", "")
    trades = trade_log.recent_trades(symbol=filter_sym or None, limit=50)

    if trades:
        rows = []
        for t in trades:
            net = t.get("net_pnl") or 0
            rows.append({
                "Time": str(t.get("timestamp", ""))[:19],
                "Symbol": t.get("symbol", ""),
                "Action": t.get("action", ""),
                "Qty": t.get("quantity", 0),
                "Price": f"${t.get('price', 0):,.2f}",
                "Net P&L": f"${net:+,.2f}" if net else "-",
                "Fees": f"${t.get('fee_total', 0):,.2f}",
                "Exec": "Y" if t.get("executed") else "N",
                "Reasoning": (t.get("reasoning") or "")[:50],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No trades recorded yet.")


# ── PAGE: Performance ────────────────────────────────────────────────────────
elif page == "Performance":
    st.subheader("Performance Analytics")
    info("performance")

    perf = trade_log.performance_summary()
    trades = trade_log.recent_trades(limit=100)
    metrics = compute_metrics(trades)

    # Summary cards
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("Total Trades", perf["total_trades"])
    p2.metric("Win Rate", f"{perf['win_rate']:.0%}")
    p3.metric("Net P&L", f"${perf['total_pnl']:+,.2f}")
    p4.metric("Gross P&L", f"${perf['gross_pnl']:+,.2f}")
    p5.metric("Total Fees", f"${perf['total_fees']:,.2f}")

    st.divider()

    # Metrics
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Sharpe Ratio", f"{metrics['sharpe_ratio']:.2f}", help=help_icon("sharpe"))
    mc2.metric("Max Drawdown", f"${metrics['max_drawdown']:,.2f}", help=help_icon("max_drawdown"))
    mc3.metric("Profit Factor", f"{metrics['profit_factor']:.2f}", help=help_icon("profit_factor"))
    mc4.metric("Max Consec. Losses", metrics["max_consecutive_losses"], help="Most consecutive losing trades in a row. If > 5, the system pauses to reassess.")

    a1, a2 = st.columns(2)
    with a1:
        st.metric("Avg Win", f"${metrics['avg_win']:+,.2f}")
    with a2:
        st.metric("Avg Loss", f"${metrics['avg_loss']:+,.2f}")

    # P&L chart
    executed = [t for t in trades if t.get("executed") and t.get("net_pnl") is not None]
    if executed:
        st.divider()
        st.markdown("**Cumulative P&L**")
        cum_pnl = []
        running = 0
        for t in reversed(executed):
            running += t["net_pnl"]
            cum_pnl.append({"Trade #": len(cum_pnl) + 1, "Cumulative P&L": running})
        st.line_chart(pd.DataFrame(cum_pnl).set_index("Trade #"))

    # Feedback / loss patterns
    st.divider()
    st.markdown("**Feedback Analysis**")
    review = st.session_state.reviewer.review()
    if review["loss_patterns"]:
        st.warning("Loss patterns detected:")
        for p in review["loss_patterns"]:
            st.write(f"- {p}")
    st.info(f"Recommendation: {review['recommendation']}")

    # Equity curve from persistent store
    equity_data = st.session_state.portfolio.get_equity_curve(limit=500)
    if equity_data:
        st.divider()
        st.markdown("**Equity Curve (Time-Series)**")
        eq_df = pd.DataFrame(equity_data)
        eq_df["timestamp"] = pd.to_datetime(eq_df["timestamp"], utc=True)
        st.line_chart(eq_df.set_index("timestamp")["total_value"])

    # Prompt versions
    versions = st.session_state.prompt_store.list_versions()
    if versions:
        st.divider()
        st.markdown(f"**Prompt Versions:** {len(versions)} saved")
        for v in versions[:5]:
            st.caption(f"v_{v}")


# ── PAGE: Event Feed ─────────────────────────────────────────────────────────
elif page == "Event Feed":
    st.subheader("Event Feed")

    if st.session_state.events:
        icons = {
            "SCAN": ">>", "FOUND": "!!", "BOUGHT": "BUY", "SOLD": "SELL",
            "PROFIT": "$$", "LOSS": "--", "VETO": "NO", "ERROR": "XX",
            "ANALYZE": "AI", "MANUAL": ">>", "EMERGENCY": "!!", "CLOSED": "OK", "SKIP": "..",
        }
        rows = []
        for e in reversed(st.session_state.events[-80:]):
            rows.append({
                "Time": e["time"],
                "Event": f"[{icons.get(e['type'], '--')}] {e['type']}",
                "Symbol": e["symbol"],
                "Details": e["message"],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=600)
    else:
        st.info("No events yet.")


# ── PAGE: Algorithm Lab ──────────────────────────────────────────────────────
elif page == "Algorithm Lab":
    st.subheader("Algorithm Lab")
    info("algo_lab")

    lab = st.session_state.algo_lab
    qs = st.session_state.quote_store

    c1, c2, c3 = st.columns(3)
    with c1:
        pop_size = st.number_input("Population size", 5, 50, 15)
    with c2:
        gens = st.number_input("Generations", 1, 10, 3)
    with c3:
        evolve_syms = st.text_input("Symbols to test on", "AAPL, NVDA, TSLA")

    if st.button("Evolve Strategies", type="primary", help=help_icon("evolve")):
        syms = [s.strip().upper() for s in evolve_syms.split(",") if s.strip()]
        with st.spinner(f"Collecting quotes and evolving {pop_size} strategies over {gens} generations..."):
            for s in syms:
                qs.add_to_watchlist(s, "algo lab")
                qs.collect(s, period="1mo", interval="1d")
            best = lab.evolve(symbols=syms, population_size=pop_size, generations=gens)
        st.success(f"Winner: {best.strategy_id} (gen {best.generation})")
        st.json(best.indicators)

    # Leaderboard
    st.markdown("**Strategy Leaderboard**")
    leaders = lab.get_leaderboard(10)
    if leaders:
        rows = []
        for e in leaders:
            active = "Yes" if e["is_active"] else ""
            rows.append({
                "Strategy": e["strategy_id"],
                "Gen": e.get("generation", "?"),
                "Avg Sharpe": f"{e['avg_sharpe']:.4f}",
                "Win Rate": f"{e['avg_winrate']:.0%}",
                "Trades": e["total_trades"],
                "Active": active,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No strategies tested yet. Click Evolve to start.")

    # Active strategy detail
    active = lab.active_strategy
    if active:
        st.markdown(f"**Active Strategy:** `{active.strategy_id}` (gen {active.generation})")
        st.write(f"Buy threshold: {active.buy_threshold}, Sell threshold: {active.sell_threshold}")
        st.write("Indicators:")
        for name, weight in sorted(active.indicators.items(), key=lambda x: abs(x[1]), reverse=True):
            bar = "+" * int(abs(weight) * 20)
            sign = "+" if weight > 0 else "-"
            st.text(f"  {name:<15} {sign}{abs(weight):.3f}  [{bar}]")


# ── PAGE: Developer Agent ────────────────────────────────────────────────────
elif page == "Developer Agent":
    st.subheader("Developer Agent")
    info("dev_agent")

    dev = st.session_state.dev_agent

    desc = st.text_area("Describe the indicator you want", placeholder="e.g., Detect mean reversion using z-score of price vs 20-day SMA")
    name = st.text_input("Indicator name (optional)", placeholder="mean_rev")

    if st.button("Create Indicator", type="primary") and desc:
        with st.spinner("Developer agent writing and validating code..."):
            result = dev.create_indicator(desc, name or None)
        if result["status"] == "success":
            st.success(result["message"])
            st.code(result["code"], language="python")
        else:
            st.error(result["message"])
            if result.get("code"):
                st.code(result["code"], language="python")

    # Delegate arbitrary task
    st.divider()
    task = st.text_input("Or delegate a task", placeholder="e.g., Build a volatility squeeze detector")
    if st.button("Delegate") and task:
        with st.spinner("Working..."):
            result = dev.delegate(task)
        st.json(result)

    # List custom algorithms
    st.divider()
    st.markdown("**Custom Algorithms**")
    algos = dev.list_custom_algorithms()
    if algos:
        st.dataframe(pd.DataFrame(algos), use_container_width=True, hide_index=True)
    else:
        st.info("No custom algorithms yet.")

    # Task log
    if dev.task_log:
        st.divider()
        st.markdown("**Agent Task Log**")
        for t in reversed(dev.task_log[-10:]):
            st.text(f"  {t['time'][:19]}  [{t['type']}]  {t['message'][:80]}")


# ── PAGE: Risk & Regime ──────────────────────────────────────────────────────
elif page == "Risk & Regime":
    st.subheader("Risk Management & Market Regime")
    info("risk_regime")

    # Market regime
    st.markdown("**Current Market Regime**")
    try:
        ctx = st.session_state.market_ctx.get_context()
        rc1, rc2, rc3, rc4 = st.columns(4)
        regime_colors = {"BULL": "green", "BEAR": "red", "VOLATILE": "orange", "SIDEWAYS": "gray"}
        rc1.metric("Regime", ctx.regime.value)
        rc2.metric("VIX", f"{ctx.vix:.1f}")
        rc3.metric("SPY", f"{ctx.spy_change_pct:+.1f}%")
        rc4.metric("Position Size Mult.", f"{ctx.position_size_multiplier:.1f}x")

        st.caption(f"Stop-loss multiplier: {ctx.stop_loss_multiplier:.1f}x | Confidence: {ctx.regime_confidence:.0%}")
    except Exception as e:
        st.warning(f"Could not fetch market context: {e}")

    st.divider()

    # Risk manager status
    st.markdown("**Risk Controls**")
    risk = st.session_state.risk_mgr
    status = risk.status
    rs1, rs2, rs3 = st.columns(3)
    rs1.metric("Halted", "YES" if status["halted"] else "No")
    rs2.metric("Kill Switch", "ACTIVE" if status["kill_switch"] else "Off")
    rs3.metric("Trades Today", status["trades_today"])

    if status["halted"]:
        st.error(f"Trading halted: {status['halt_reason']}")

    # Kill switch controls
    st.divider()
    st.markdown("**Kill Switch**")
    info("kill_switch")
    ks1, ks2 = st.columns(2)
    with ks1:
        if st.button("ACTIVATE Kill Switch", type="secondary", help="Immediately halts ALL trading. Use in emergencies."):
            RiskManager.activate_kill_switch("Manual activation from dashboard")
            st.error("Kill switch activated! All trading halted.")
            st.rerun()
    with ks2:
        if st.button("Deactivate Kill Switch"):
            RiskManager.deactivate_kill_switch()
            st.success("Kill switch deactivated.")
            st.rerun()


# ── PAGE: Quote Store ────────────────────────────────────────────────────────
elif page == "Quote Store":
    st.subheader("Quote Store")
    info("quote_store")

    qs = st.session_state.quote_store

    # Watchlist
    st.markdown("**Watchlist**")
    wl = qs.get_watchlist()
    if wl:
        st.dataframe(pd.DataFrame(wl), use_container_width=True, hide_index=True)
    else:
        st.info("Watchlist empty.")

    # Add to watchlist
    qc1, qc2 = st.columns([3, 1])
    with qc1:
        new_sym = st.text_input("Add symbol", placeholder="AAPL")
    with qc2:
        if st.button("Add") and new_sym:
            qs.add_to_watchlist(new_sym.strip().upper(), "manual add")
            st.rerun()

    # Collect quotes
    st.divider()
    if st.button("Collect Quotes for Watchlist", type="primary"):
        with st.spinner("Collecting..."):
            results = qs.collect_watchlist(period="1mo", interval="1d")
        st.success(f"Collected for {len(results)} symbols: {results}")

    # Quote inventory
    st.divider()
    st.markdown("**Stored Quotes**")
    syms = qs.get_symbols_with_quotes()
    if syms:
        st.dataframe(pd.DataFrame(syms), use_container_width=True, hide_index=True)
        st.metric("Total Quotes", qs.get_quote_count())
    else:
        st.info("No quotes stored yet.")


# ── PAGE: Settings ───────────────────────────────────────────────────────────
elif page == "Settings":
    st.subheader("Settings")

    st.markdown("**Risk Management**")
    sc1, sc2 = st.columns(2)
    with sc1:
        new_sl = st.slider("Stop-Loss %", 0.5, 10.0, pos_mgr.stop_loss_pct * 100, 0.5)
        new_tp = st.slider("Take-Profit %", 1.0, 20.0, pos_mgr.take_profit_pct * 100, 0.5)
        new_trail = st.slider("Trailing Stop %", 0.5, 5.0, pos_mgr.trailing_stop_pct * 100, 0.25)
    with sc2:
        new_max_hold = st.slider("Max Hold (min)", 30, 480, pos_mgr.max_hold_minutes, 30)
        new_max_pos = st.slider("Max Positions", 1, 15, st.session_state.strategist.max_open_positions)
        new_min_score = st.slider("Min Scanner Score", 5.0, 50.0, st.session_state.strategist.min_score_threshold, 5.0)

    if st.button("Apply Settings"):
        pos_mgr.stop_loss_pct = new_sl / 100
        pos_mgr.take_profit_pct = new_tp / 100
        pos_mgr.trailing_stop_pct = new_trail / 100
        pos_mgr.max_hold_minutes = new_max_hold
        st.session_state.strategist.max_open_positions = new_max_pos
        st.session_state.strategist.min_score_threshold = new_min_score
        st.success("Settings applied!")

    st.divider()
    st.markdown("**Fee Model**")
    fm = portfolio.fee_model
    st.write(f"Commission: ${fm.commission_per_trade} | Equity spread: {fm.spread_pct_equity:.4%} | Crypto spread: {fm.spread_pct_crypto:.4%}")
    st.write(f"Slippage: {fm.slippage_pct:.4%} | SEC fee: ${fm.sec_fee_per_million}/M")

    st.divider()
    st.markdown("**Scanner Universe**")
    from src.scanner.market_scanner import SP500_SAMPLE, CRYPTO_SAMPLE
    st.write(f"Stocks: {len(SP500_SAMPLE)} | Crypto: {len(CRYPTO_SAMPLE)}")
    st.caption(", ".join(SP500_SAMPLE[:20]) + "...")

    st.divider()
    if st.button("Reset Portfolio", type="secondary", help="Resets cash to $100,000, closes all positions, and clears trade history for this session."):
        portfolio.cash = 100_000.0
        portfolio.positions.clear()
        portfolio.realized_pnl = 0.0
        portfolio.total_fees_paid = 0.0
        st.session_state.trades_today = 0
        st.session_state.events.clear()
        pos_mgr.rules.clear()
        st.success("Portfolio reset to $100,000.")
        st.rerun()


# ── PAGE: Help ───────────────────────────────────────────────────────────────
elif page == "Help":
    st.subheader("Help & User Guide")

    st.markdown("""
    ### Quick Start
    1. Click **Autopilot** tab > **Run Cycle** to let the AI trade automatically
    2. Or click **Manual Trade** > type symbols > **Analyze** > **BUY/SELL**
    3. Check **Positions** to see your open trades
    4. Check **Performance** to see how you're doing
    """)

    st.divider()

    st.markdown("### Page Guide")

    with st.expander("Autopilot — Let the AI trade for you"):
        st.markdown("""
**What it does:** Scans 50+ stocks, picks opportunities, confirms with AI reasoning, executes trades, and monitors positions — all automatically.

**How to use:**
1. Click **Run Cycle** to run one scan-analyze-trade-monitor cycle
2. Toggle **Auto-run** to repeat automatically every N seconds
3. Watch the event log at the bottom for real-time activity

**What happens in each cycle:**
- **SCAN:** Checks 50+ stocks for momentum, volume spikes, sector rotation
- **ANALYZE:** AI evaluates top picks with 15+ technical indicators + news
- **FILTER:** Checks earnings calendar, sector concentration, correlation, risk limits
- **EXECUTE:** Buys stocks that pass all filters (with fees)
- **MONITOR:** Checks existing positions for stop-loss, take-profit, trailing stop exits

**Safety features active:**
- Daily loss limit: trading halts if portfolio drops > 1.5% in a day
- Max 30% in any single sector
- No buying stocks with earnings in next 3 days
- Rejects trades correlated > 70% with existing positions
- Market regime adjusts position sizes (smaller in volatile markets)
        """)

    with st.expander("Manual Trade — Analyze and trade specific stocks"):
        st.markdown("""
**What it does:** You pick the stocks, the AI analyzes them, you decide whether to trade.

**How to use:**
1. Type stock symbols separated by commas (e.g., `AAPL, NVDA, TSLA`)
2. Click **Analyze** — the AI fetches live data and runs its reasoning engine
3. Each stock gets a **BUY / SELL / HOLD** recommendation with confidence %
4. Expand a stock to see full technicals, news, and reasoning
5. Use the **BUY** or **SELL** buttons to execute manually

**What the AI looks at:**
- RSI (overbought > 70, oversold < 30)
- MACD histogram (positive = bullish, negative = bearish)
- Bollinger Bands (price position relative to bands)
- News sentiment from recent headlines
        """)

    with st.expander("Positions — Monitor your open trades"):
        st.markdown("""
**Columns explained:**
- **Entry:** Your purchase price (including fees baked into cost basis)
- **Current:** Live market price
- **P&L:** Unrealized profit/loss (hasn't been sold yet)
- **Stop-Loss:** If price drops below this, position is automatically closed
- **Take-Profit:** If price reaches this target, position is automatically closed
- **Trail Stop:** Follows price upward. If price drops 1.5% from its highest point, sells

**Close All Positions:** Emergency button to sell everything immediately.
        """)

    with st.expander("Market Scanner — Discover opportunities"):
        st.markdown("""
**Scans for:**
- **Momentum:** Stocks with strong recent price + volume trends
- **Volume breakouts:** Unusual volume (> 2x average) suggesting big moves
- **Sector rotation:** Which sectors are leading or lagging today

**Score column:** 0-100 opportunity ranking. Higher = stronger signal.
- 50+: Very strong move (e.g., stock down 5%)
- 25-50: Solid opportunity
- < 25: Weak signal, usually filtered out
        """)

    with st.expander("AI Analysis — See the AI's reasoning"):
        st.markdown("""
Each stock analyzed gets a detailed breakdown:
- **Technical indicators:** RSI, MACD, Bollinger Bands with specific values
- **Sentiment:** Score from -1 (bearish) to +1 (bullish) based on news
- **Headlines:** Recent news articles the AI considered
- **Reasoning:** Plain-English explanation of why BUY/SELL/HOLD
- **Scanner context:** What triggered the scanner to pick this stock
        """)

    with st.expander("Performance — Track your results"):
        st.markdown("""
**Key metrics:**
- **Win Rate:** % of closed trades that were profitable
- **Sharpe Ratio:** Return per unit of risk. > 1.0 is good, > 2.0 is excellent
- **Max Drawdown:** Worst peak-to-trough decline. Lower is better
- **Profit Factor:** Total wins / total losses. > 1.0 = profitable
- **Equity Curve:** Portfolio value plotted over time

**Feedback Analysis:** The AI identifies patterns in losing trades and suggests improvements.
        """)

    with st.expander("Algorithm Lab — Self-evolving strategies"):
        st.markdown("""
**How it works:**
1. Generates random strategies (different indicator combinations + weights)
2. Backtests each on historical data (with fees, walk-forward testing)
3. Tests statistical significance (Monte Carlo permutation)
4. Breeds the top performers (genetic crossover + mutation)
5. Promotes the winner to production

**Parameters:**
- **Population:** How many random strategies to test (more = slower but better)
- **Generations:** How many breed cycles (more = more evolved)
- **Symbols:** Which stocks to test on (use diverse set for robustness)
        """)

    with st.expander("Developer Agent — Create custom indicators"):
        st.markdown("""
**What it does:** An AI sub-agent that writes Python code for new technical indicators.

**How to use:**
1. Describe what you want in plain English
2. Click **Create Indicator**
3. The agent writes code, validates it on sample data, and registers it
4. New indicators are automatically available for the Algorithm Lab

**Example prompts:**
- "Detect mean reversion using z-score of price vs 20-day SMA"
- "Build a volatility squeeze detector using Bollinger + Keltner"
- "Create a multi-timeframe momentum indicator using 7/14/28 RSI"
        """)

    with st.expander("Risk & Regime — Safety controls"):
        st.markdown("""
**Market Regime:**
- **BULL:** Low volatility, uptrend — full position sizes
- **BEAR:** High volatility, downtrend — 30% position sizes
- **VOLATILE:** High VIX, no clear direction — 50% position sizes
- **SIDEWAYS:** Low volatility, flat — 80% position sizes

**Risk Controls:**
- Daily loss limit halts trading after -1.5% daily loss
- Kill switch immediately stops ALL trading
- 30-min cooldown after any trade loses > 2%
- Max 50 trades per day (prevents overtrading)

**Kill Switch:** File-based emergency halt. Activate from dashboard or create `data/.kill_switch` file.
        """)

    with st.expander("Quote Store — Historical data"):
        st.markdown("""
The AI builds its own database of price history over time.

**Watchlist:** Symbols the AI is tracking. Add manually or let the autopilot add them.
**Collect Quotes:** Downloads recent price data and stores it locally.
**Used by:** Algorithm Lab for backtesting strategies on historical data.

More historical data = better strategy evolution.
        """)

    with st.expander("Settings — Adjust parameters"):
        st.markdown("""
**Risk parameters:**
- Stop-Loss %: How far price can drop before auto-sell (default: 2%)
- Take-Profit %: Target gain to lock in (default: 4%)
- Trailing Stop %: Distance from peak before selling (default: 1.5%)
- Max Hold: Force-close after this many minutes (default: 180)
- Max Positions: How many stocks to hold at once (default: 5)
- Min Scanner Score: Minimum quality threshold for opportunities (default: 25)

**Fee Model:** Shows the broker fee structure being simulated.
**Reset Portfolio:** Starts fresh with $100,000.
        """)
