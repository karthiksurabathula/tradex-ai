"""Unified Streamlit dashboard — autopilot + monitoring + trades in one UI."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st
import yfinance as yf

from src.execution.executor import Executor
from src.execution.fees import FeeModel
from src.execution.portfolio import Portfolio
from src.execution.trade_log import TradeLog
from src.ingestion.openbb_provider import OpenBBProvider
from src.ingestion.state_builder import StateBuilder
from src.ingestion.yfinance_news_provider import YFinanceNewsProvider
from src.reasoning.engine import ReasoningEngine
from src.scanner.market_scanner import MarketScanner, ScanResult
from src.state.models import SignalType, TradeSignal
from src.strategy.intraday_strategist import IntradayStrategist
from src.strategy.position_manager import PositionManager

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="tradex-ai", page_icon="tradex", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    div[data-testid="stMetric"] {
        background: #0e1117; padding: 10px; border-radius: 8px;
        border: 1px solid #262730;
    }
    .buy-signal { color: #3fb950; font-weight: bold; }
    .sell-signal { color: #f85149; font-weight: bold; }
    .hold-signal { color: #d29922; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# ── Session State ────────────────────────────────────────────────────────────
def init_session():
    if "initialized" not in st.session_state:
        fee_model = FeeModel()
        portfolio = Portfolio(cash=100_000.0, fee_model=fee_model)
        trade_log = TradeLog(db_path="data/trades.db")

        st.session_state.portfolio = portfolio
        st.session_state.trade_log = trade_log
        st.session_state.scanner = MarketScanner()
        st.session_state.strategist = IntradayStrategist()
        st.session_state.position_mgr = PositionManager()
        st.session_state.engine = ReasoningEngine()
        st.session_state.state_builder = StateBuilder(
            OpenBBProvider(provider="yfinance", interval="5m"),
            YFinanceNewsProvider(),
        )
        st.session_state.executor = Executor(portfolio, trade_log, max_position_pct=0.15, min_confidence=0.30)

        st.session_state.events = []
        st.session_state.scan_results = []
        st.session_state.cycle_count = 0
        st.session_state.trades_today = 0
        st.session_state.analyzed_symbols = {}  # symbol -> analysis dict
        st.session_state.running = False
        st.session_state.initialized = True


init_session()


def log_event(etype: str, msg: str, symbol: str = ""):
    st.session_state.events.append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "type": etype,
        "symbol": symbol,
        "message": msg,
    })
    if len(st.session_state.events) > 100:
        st.session_state.events = st.session_state.events[-100:]


def get_prices() -> dict[str, float]:
    prices = {}
    for sym in st.session_state.portfolio.positions:
        try:
            prices[sym] = yf.Ticker(sym).fast_info.get("lastPrice", 0)
        except Exception:
            prices[sym] = st.session_state.portfolio.positions[sym].avg_cost
    return prices


# ── Phase 1: SCAN ────────────────────────────────────────────────────────────
def phase_scan(status_area):
    status_area.info("Phase 1/4: Scanning market for opportunities...")
    log_event("SCAN", "Scanning 50+ stocks for momentum, volume, sectors...")

    try:
        results = st.session_state.scanner.full_scan(top_n=12)
        st.session_state.scan_results = results
        log_event("SCAN", f"Found {len(results)} opportunities")
        return results
    except Exception as e:
        log_event("ERROR", f"Scan failed: {e}")
        return []


# ── Phase 2: ANALYZE ─────────────────────────────────────────────────────────
def phase_analyze(scan_results: list[ScanResult], status_area):
    status_area.info("Phase 2/4: AI analyzing top opportunities...")
    analyzed = {}
    end = datetime.now(UTC)
    start = end - timedelta(days=5)

    for r in scan_results[:8]:
        try:
            log_event("ANALYZE", f"Reasoning engine evaluating...", r.symbol)
            state = st.session_state.state_builder.build(
                r.symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
            )
            signal = st.session_state.engine.decide(state)

            analyzed[r.symbol] = {
                "scan": r,
                "state": state,
                "signal": signal,
                "price": state.technicals.current_price,
                "rsi": state.technicals.rsi,
                "rsi_label": state.technicals.rsi_label,
                "macd_h": state.technicals.macd_histogram,
                "bb_lower": state.technicals.bb_lower,
                "bb_mid": state.technicals.bb_mid,
                "bb_upper": state.technicals.bb_upper,
                "sentiment": state.sentiment.overall_score,
                "headlines": [h.get("title", "") for h in state.headlines[:5]],
                "themes": state.sentiment.top_themes[:3],
            }
            log_event("ANALYZE", f"{signal.action.value} (conf: {signal.confidence:.0%}) — {signal.reasoning[:60]}", r.symbol)
        except Exception as e:
            log_event("ERROR", f"Analysis failed: {e}", r.symbol)

    st.session_state.analyzed_symbols = analyzed
    return analyzed


# ── Phase 3: TRADE ───────────────────────────────────────────────────────────
def phase_trade(scan_results: list[ScanResult], analyzed: dict, status_area):
    status_area.info("Phase 3/4: Executing trades...")
    portfolio = st.session_state.portfolio
    prices = {sym: a["price"] for sym, a in analyzed.items()}
    prices.update(get_prices())

    # Check emergency
    if st.session_state.strategist.should_exit_all(portfolio, prices):
        log_event("EMERGENCY", "Portfolio loss > 5%! Exiting all.")
        for sym in list(portfolio.positions.keys()):
            pos = portfolio.positions[sym]
            p = prices.get(sym, pos.avg_cost)
            result = portfolio.sell(sym, pos.quantity, p)
            if result:
                st.session_state.position_mgr.remove(sym)
                log_event("CLOSED", f"Emergency exit {pos.quantity} @ ${p:,.2f} | P&L: ${result['net_pnl']:+,.2f}", sym)
        return

    # Select opportunities
    opportunities = st.session_state.strategist.select_opportunities(scan_results, portfolio, prices)

    for opp in opportunities:
        # Check if reasoning engine agrees
        analysis = analyzed.get(opp.symbol)
        if analysis and analysis["signal"].action == SignalType.SELL and opp.direction == "BUY":
            log_event("VETO", f"AI vetoed BUY (reasoning says SELL)", opp.symbol)
            continue

        fees = portfolio.buy(opp.symbol, opp.quantity, opp.price)
        if fees:
            st.session_state.position_mgr.register_entry(opp.symbol, opp.price)
            st.session_state.trades_today += 1
            st.session_state.trade_log.record(
                TradeSignal(symbol=opp.symbol, action=SignalType.BUY, confidence=opp.score / 100, reasoning=opp.reason),
                price=opp.price, executed=True, quantity=opp.quantity, fees=fees,
            )
            log_event("BOUGHT", f"{opp.quantity} shares @ ${opp.price:,.2f} (fees: ${fees['total']:,.2f}) — {opp.reason[:50]}", opp.symbol)
        else:
            log_event("SKIP", f"Insufficient cash for {opp.quantity} shares", opp.symbol)


# ── Phase 4: MONITOR ─────────────────────────────────────────────────────────
def phase_monitor(status_area):
    status_area.info("Phase 4/4: Monitoring positions...")
    portfolio = st.session_state.portfolio
    if not portfolio.positions:
        return

    prices = get_prices()
    exits = st.session_state.position_mgr.check_exits(prices)

    for ex in exits:
        pos = portfolio.positions.get(ex.symbol)
        if pos:
            result = portfolio.sell(ex.symbol, pos.quantity, ex.current_price)
            if result:
                st.session_state.position_mgr.remove(ex.symbol)
                st.session_state.trades_today += 1
                tag = "PROFIT" if result["net_pnl"] > 0 else "LOSS"
                st.session_state.trade_log.record(
                    TradeSignal(symbol=ex.symbol, action=SignalType.SELL, confidence=0.9, reasoning=ex.reason),
                    price=ex.current_price, executed=True, quantity=pos.quantity,
                    gross_pnl=result["gross_pnl"], net_pnl=result["net_pnl"], fees=result["fees"],
                )
                log_event(tag, f"Sold {pos.quantity} @ ${ex.current_price:,.2f} | P&L: ${result['net_pnl']:+,.2f} | {ex.reason}", ex.symbol)


# ── Full Cycle ───────────────────────────────────────────────────────────────
def run_full_cycle():
    st.session_state.cycle_count += 1
    status = st.empty()

    scan_results = phase_scan(status)
    if not scan_results:
        status.warning("No opportunities found in this scan.")
        return

    analyzed = phase_analyze(scan_results, status)
    phase_trade(scan_results, analyzed, status)
    phase_monitor(status)
    status.success(f"Cycle #{st.session_state.cycle_count} complete! ({datetime.now().strftime('%H:%M:%S')})")


# ═══════════════════════════════════════════════════════════════════════════════
#  LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

# ── Header ───────────────────────────────────────────────────────────────────
col_title, col_controls = st.columns([3, 1])
with col_title:
    st.title("tradex-ai")
    st.caption("Fully autonomous AI paper trading")
with col_controls:
    auto = st.toggle("Auto-pilot", value=False, help="Auto-run every N seconds")
    interval = st.number_input("Interval (sec)", min_value=30, max_value=600, value=120, step=30)

# ── Portfolio Bar ────────────────────────────────────────────────────────────
prices = get_prices()
summary = st.session_state.portfolio.summary(prices)
starting = 100_000.0
total_return = ((summary["total_value"] - starting) / starting) * 100

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Portfolio Value", f"${summary['total_value']:,.2f}", f"{total_return:+.2f}%")
m2.metric("Cash", f"${summary['cash']:,.2f}")
m3.metric("Realized P&L", f"${summary['realized_pnl']:+,.2f}")
m4.metric("Unrealized P&L", f"${summary['unrealized_pnl']:+,.2f}")
m5.metric("Fees Paid", f"${summary['total_fees_paid']:,.2f}")
m6.metric("Trades Today", st.session_state.trades_today)

# ── Run Button ───────────────────────────────────────────────────────────────
run = st.button("Run Trading Cycle", type="primary", use_container_width=True)

if run:
    run_full_cycle()

st.divider()

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_positions, tab_scanner, tab_analysis, tab_trades, tab_events = st.tabs(
    ["Open Positions", "Market Scanner", "AI Analysis", "Trade Log", "Event Feed"]
)

# ── Tab 1: Open Positions ────────────────────────────────────────────────────
with tab_positions:
    portfolio = st.session_state.portfolio
    if portfolio.positions:
        pos_data = []
        for sym, pos in portfolio.positions.items():
            price = prices.get(sym, pos.avg_cost)
            pnl = pos.unrealized_pnl(price)
            pnl_pct = ((price - pos.avg_cost) / pos.avg_cost) * 100
            rule = st.session_state.position_mgr.rules.get(sym)

            pos_data.append({
                "Symbol": sym,
                "Qty": pos.quantity,
                "Entry": f"${pos.avg_cost:,.2f}",
                "Current": f"${price:,.2f}",
                "P&L": f"${pnl:+,.2f}",
                "P&L %": f"{pnl_pct:+.2f}%",
                "Stop-Loss": f"${rule.stop_loss_price:,.2f}" if rule else "N/A",
                "Take-Profit": f"${rule.take_profit_price:,.2f}" if rule else "N/A",
                "Trail Stop": f"${rule.trailing_stop_price:,.2f}" if rule else "N/A",
                "Value": f"${pos.market_value(price):,.2f}",
            })

        df = pd.DataFrame(pos_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No open positions. Click **Run Trading Cycle** to start scanning and trading.")

# ── Tab 2: Scanner Results ───────────────────────────────────────────────────
with tab_scanner:
    results = st.session_state.scan_results
    if results:
        scan_data = []
        for r in results:
            scan_data.append({
                "Symbol": r.symbol,
                "Score": f"{r.score:.0f}",
                "Category": r.category.upper(),
                "Change": f"{r.change_pct:+.1f}%",
                "Vol Ratio": f"{r.volume_ratio:.1f}x" if r.volume_ratio > 0 else "-",
                "Price": f"${r.price:,.2f}" if r.price > 0 else "-",
                "Reason": r.reason,
            })
        st.dataframe(pd.DataFrame(scan_data), use_container_width=True, hide_index=True)
    else:
        st.info("No scan results yet. Run a cycle to scan the market.")

# ── Tab 3: AI Analysis ──────────────────────────────────────────────────────
with tab_analysis:
    analyzed = st.session_state.analyzed_symbols
    if analyzed:
        for sym, data in analyzed.items():
            signal = data["signal"]
            color_class = f"{signal.action.value.lower()}-signal"
            icon = {"BUY": "+", "SELL": "-", "HOLD": "="}[signal.action.value]

            with st.expander(
                f"[{icon}] {sym} — {signal.action.value} ({signal.confidence:.0%}) | "
                f"${data['price']:,.2f} | RSI {data['rsi']:.1f}",
                expanded=(signal.action.value != "HOLD"),
            ):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown("**Technical Indicators**")
                    st.write(f"- RSI: {data['rsi']:.1f} ({data['rsi_label']})")
                    st.write(f"- MACD Hist: {data['macd_h']:+.4f}")
                    st.write(f"- BB: ${data['bb_lower']:,.2f} / ${data['bb_mid']:,.2f} / ${data['bb_upper']:,.2f}")
                    st.write(f"- Price: ${data['price']:,.2f}")
                with c2:
                    st.markdown("**Sentiment**")
                    st.write(f"- Score: {data['sentiment']:+.2f}")
                    if data["themes"]:
                        for t in data["themes"]:
                            st.caption(f"- {t[:60]}")
                with c3:
                    st.markdown("**Headlines**")
                    for h in data["headlines"][:4]:
                        if h:
                            st.caption(f"- {h[:70]}")

                st.markdown("**Agent Reasoning:**")
                st.code(signal.reasoning, language=None)

                # Scanner context
                scan = data["scan"]
                st.caption(f"Scanner: {scan.category} | Score: {scan.score:.0f} | {scan.reason}")
    else:
        st.info("No analysis yet. Run a cycle to see AI reasoning.")

# ── Tab 4: Trade Log ─────────────────────────────────────────────────────────
with tab_trades:
    trades = st.session_state.trade_log.recent_trades(limit=30)
    if trades:
        trade_data = []
        for t in trades:
            net = t.get("net_pnl") or 0
            trade_data.append({
                "Time": str(t.get("timestamp", ""))[:19],
                "Symbol": t.get("symbol", ""),
                "Action": t.get("action", ""),
                "Qty": t.get("quantity", 0),
                "Price": f"${t.get('price', 0):,.2f}",
                "Net P&L": f"${net:+,.2f}" if net else "-",
                "Fees": f"${t.get('fee_total', 0):,.2f}",
                "Executed": "Yes" if t.get("executed") else "No",
                "Reasoning": (t.get("reasoning") or "")[:50],
            })
        st.dataframe(pd.DataFrame(trade_data), use_container_width=True, hide_index=True)

        # Performance summary
        perf = st.session_state.trade_log.performance_summary()
        if perf["total_trades"] > 0:
            st.divider()
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Total Trades", perf["total_trades"])
            p2.metric("Win Rate", f"{perf['win_rate']:.0%}")
            p3.metric("Net P&L", f"${perf['total_pnl']:+,.2f}")
            p4.metric("Total Fees", f"${perf['total_fees']:,.2f}")
    else:
        st.info("No trades yet.")

# ── Tab 5: Event Feed ────────────────────────────────────────────────────────
with tab_events:
    events = st.session_state.events
    if events:
        icons = {
            "SCAN": "[>>]", "ANALYZE": "[AI]", "BOUGHT": "[BUY]", "SOLD": "[SELL]",
            "PROFIT": "[$$]", "LOSS": "[--]", "VETO": "[NO]", "SKIP": "[..]",
            "ERROR": "[!!]", "EMERGENCY": "[!!]", "CLOSED": "[OK]",
        }
        event_data = []
        for e in reversed(events[-50:]):
            event_data.append({
                "Time": e["time"],
                "Type": icons.get(e["type"], "[--]") + " " + e["type"],
                "Symbol": e["symbol"],
                "Details": e["message"],
            })
        st.dataframe(pd.DataFrame(event_data), use_container_width=True, hide_index=True)
    else:
        st.info("No events yet. Run a cycle to see the AI in action.")


# ── Auto-pilot ───────────────────────────────────────────────────────────────
if auto:
    time.sleep(interval)
    run_full_cycle()
    st.rerun()
