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

from src.execution.executor import Executor
from src.execution.fees import FeeModel
from src.execution.portfolio import Portfolio
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
from src.strategy.intraday_strategist import IntradayStrategist
from src.strategy.position_manager import PositionManager

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="tradex-ai", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 0.5rem; }
    div[data-testid="stMetric"] {
        background: #0e1117; padding: 8px; border-radius: 6px; border: 1px solid #262730;
    }
</style>
""", unsafe_allow_html=True)


# ── Session State ────────────────────────────────────────────────────────────
def init_session():
    if "init" in st.session_state:
        return
    fm = FeeModel()
    p = Portfolio(cash=100_000.0, fee_model=fm)
    tl = TradeLog(db_path="data/trades.db")
    ps = PromptStore()

    st.session_state.update({
        "init": True,
        "portfolio": p,
        "trade_log": tl,
        "prompt_store": ps,
        "scanner": MarketScanner(),
        "strategist": IntradayStrategist(),
        "pos_mgr": PositionManager(),
        "engine": ReasoningEngine(),
        "state_builder": StateBuilder(
            OpenBBProvider(provider="yfinance", interval="5m"),
            YFinanceNewsProvider(),
        ),
        "executor": Executor(p, tl, max_position_pct=0.15, min_confidence=0.30),
        "reviewer": TradeReviewer(tl),
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
m1.metric("Portfolio", f"${summary['total_value']:,.2f}", f"{ret_pct:+.2f}%")
m2.metric("Cash", f"${summary['cash']:,.2f}")
m3.metric("Realized", f"${summary['realized_pnl']:+,.2f}")
m4.metric("Unrealized", f"${summary['unrealized_pnl']:+,.2f}")
m5.metric("Fees", f"${summary['total_fees_paid']:,.2f}")
m6.metric("Trades", st.session_state.trades_today)

st.divider()

# ── Navigation ───────────────────────────────────────────────────────────────
page = st.radio(
    "Mode",
    ["Autopilot", "Manual Trade", "Positions", "Market Scanner", "AI Analysis", "Trade Log", "Performance", "Event Feed", "Settings"],
    horizontal=True,
    label_visibility="collapsed",
)


# ── PAGE: Autopilot ─────────────────────────────────────────────────────────
if page == "Autopilot":
    st.subheader("Autopilot")
    st.caption("AI scans the market, picks stocks, trades, and manages positions autonomously.")

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        run_btn = st.button("Run Cycle", type="primary", use_container_width=True)
    with c2:
        auto = st.toggle("Auto-run", value=False)
    with c3:
        interval = st.slider("Interval (sec)", 60, 600, 120, step=30, label_visibility="collapsed")

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
    st.caption("Pick specific symbols to analyze and trade.")

    c1, c2 = st.columns([3, 1])
    with c1:
        symbols_input = st.text_input("Symbols (comma-separated)", "AAPL, NVDA, TSLA, MSFT")
    with c2:
        analyze_btn = st.button("Analyze", type="primary", use_container_width=True)

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

    sc1, sc2 = st.columns([1, 3])
    with sc1:
        if st.button("Scan Now", type="primary"):
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
    mc1.metric("Sharpe Ratio", f"{metrics['sharpe_ratio']:.2f}")
    mc2.metric("Max Drawdown", f"${metrics['max_drawdown']:,.2f}")
    mc3.metric("Profit Factor", f"{metrics['profit_factor']:.2f}")
    mc4.metric("Max Consec. Losses", metrics["max_consecutive_losses"])

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
    if st.button("Reset Portfolio", type="secondary"):
        portfolio.cash = 100_000.0
        portfolio.positions.clear()
        portfolio.realized_pnl = 0.0
        portfolio.total_fees_paid = 0.0
        st.session_state.trades_today = 0
        st.session_state.events.clear()
        pos_mgr.rules.clear()
        st.success("Portfolio reset to $100,000.")
        st.rerun()
