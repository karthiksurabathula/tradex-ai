"""Streamlit visual dashboard — see the trading bot in action."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st

from src.execution.executor import Executor
from src.execution.fees import FeeModel
from src.execution.portfolio import Portfolio
from src.execution.trade_log import TradeLog
from src.ingestion.openbb_provider import OpenBBProvider
from src.ingestion.state_builder import StateBuilder
from src.ingestion.yfinance_news_provider import YFinanceNewsProvider
from src.reasoning.engine import ReasoningEngine

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="tradex-ai",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .signal-buy { background: #0e4429; color: #3fb950; padding: 8px 16px; border-radius: 8px; font-weight: bold; font-size: 1.2em; }
    .signal-sell { background: #4c1017; color: #f85149; padding: 8px 16px; border-radius: 8px; font-weight: bold; font-size: 1.2em; }
    .signal-hold { background: #3d2e00; color: #d29922; padding: 8px 16px; border-radius: 8px; font-weight: bold; font-size: 1.2em; }
    .metric-card { background: #161b22; padding: 16px; border-radius: 8px; border: 1px solid #30363d; }
    .trade-executed { border-left: 4px solid #3fb950; padding-left: 12px; margin: 8px 0; }
    .trade-skipped { border-left: 4px solid #484f58; padding-left: 12px; margin: 8px 0; }
    .data-flow { font-family: monospace; font-size: 0.85em; }
    div[data-testid="stMetric"] { background: #161b22; padding: 12px; border-radius: 8px; border: 1px solid #30363d; }
</style>
""", unsafe_allow_html=True)


# ── Session State Init ───────────────────────────────────────────────────────
def init_state():
    if "components" not in st.session_state:
        fee_model = FeeModel()
        portfolio = Portfolio(cash=100_000.0, fee_model=fee_model)
        trade_log = TradeLog(db_path="data/trades.db")
        st.session_state.components = {
            "state_builder": StateBuilder(
                OpenBBProvider(provider="yfinance", interval="5m"),
                YFinanceNewsProvider(),
            ),
            "engine": ReasoningEngine(),
            "portfolio": portfolio,
            "executor": Executor(portfolio, trade_log, max_position_pct=0.10, min_confidence=0.40),
            "trade_log": trade_log,
        }
    if "cycle_count" not in st.session_state:
        st.session_state.cycle_count = 0
    if "trade_history" not in st.session_state:
        st.session_state.trade_history = []
    if "latest_results" not in st.session_state:
        st.session_state.latest_results = []


init_state()
comp = st.session_state.components


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ tradex-ai")
    st.caption("AI Paper Trading Bot")
    st.divider()

    symbols = st.multiselect(
        "Symbols to trade",
        ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "BTC-USD", "ETH-USD"],
        default=["AAPL", "NVDA", "MSFT"],
    )

    auto_refresh = st.toggle("Auto-refresh", value=False)
    refresh_interval = st.slider("Refresh interval (sec)", 60, 600, 300, step=60)

    st.divider()
    run_button = st.button("▶ Run Trading Cycle", type="primary", use_container_width=True)

    st.divider()
    portfolio = comp["portfolio"]
    prices = {r["symbol"]: r["price"] for r in st.session_state.latest_results if "price" in r}
    summary = portfolio.summary(prices)

    st.metric("Portfolio Value", f"${summary['total_value']:,.2f}")
    st.metric("Cash", f"${summary['cash']:,.2f}")
    st.metric("Realized P&L", f"${summary['realized_pnl']:+,.2f}")
    st.metric("Fees Paid", f"${summary['total_fees_paid']:,.2f}")
    st.metric("Cycle #", st.session_state.cycle_count)


# ── Main: Run Cycle ──────────────────────────────────────────────────────────
def run_trading_cycle(symbols: list[str]):
    """Execute one full trading cycle with live progress."""
    st.session_state.cycle_count += 1
    results = []
    end = datetime.now(UTC)
    start = end - timedelta(days=5)

    # ── Data Flow Panel ──
    flow_container = st.container()
    with flow_container:
        st.subheader("🔄 Data Flow")
        progress = st.progress(0, text="Initializing...")

    for i, symbol in enumerate(symbols):
        progress.progress((i) / len(symbols), text=f"Fetching data for {symbol}...")

        try:
            # Step 1: Fetch market data
            state = comp["state_builder"].build(
                symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
            )

            progress.progress((i + 0.33) / len(symbols), text=f"Analyzing {symbol}...")

            # Step 2: Reasoning
            signal = comp["engine"].decide(state)

            progress.progress((i + 0.66) / len(symbols), text=f"Executing {symbol}...")

            # Step 3: Execute
            exec_result = comp["executor"].execute(signal, state.technicals.current_price)

            results.append({
                "symbol": symbol,
                "price": state.technicals.current_price,
                "rsi": state.technicals.rsi,
                "rsi_label": state.technicals.rsi_label,
                "macd_h": state.technicals.macd_histogram,
                "bb_lower": state.technicals.bb_lower,
                "bb_mid": state.technicals.bb_mid,
                "bb_upper": state.technicals.bb_upper,
                "sentiment": state.sentiment.overall_score,
                "sentiment_conf": state.sentiment.confidence,
                "themes": state.sentiment.top_themes[:3],
                "headlines": [h.get("title", "") for h in state.headlines[:5]],
                "signal": signal.action.value,
                "confidence": signal.confidence,
                "reasoning": signal.reasoning,
                "executed": exec_result.get("executed", False),
                "exec_detail": exec_result,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "ohlcv_bars": len(state.ohlcv.bars),
            })

            # Add to trade history
            st.session_state.trade_history.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "symbol": symbol,
                "signal": signal.action.value,
                "confidence": signal.confidence,
                "executed": exec_result.get("executed", False),
                "price": state.technicals.current_price,
                "qty": exec_result.get("quantity", 0),
                "fees": exec_result.get("fees", {}).get("total", 0) if exec_result.get("fees") else 0,
            })

        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)})

    progress.progress(1.0, text="Cycle complete!")
    st.session_state.latest_results = results
    return results


# ── Display Results ──────────────────────────────────────────────────────────
def display_results(results: list[dict]):
    # ── Signal Cards ─────────────────────────────────────────────────────
    st.subheader("📊 Market Signals")
    cols = st.columns(len(results))
    for col, r in zip(cols, results):
        with col:
            if "error" in r:
                st.error(f"{r['symbol']}: {r['error']}")
                continue

            signal_class = f"signal-{r['signal'].lower()}"
            signal_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}[r["signal"]]

            st.markdown(f'<div class="{signal_class}">{signal_emoji} {r["signal"]} {r["symbol"]}</div>', unsafe_allow_html=True)
            st.metric("Price", f"${r['price']:,.2f}")

            c1, c2 = st.columns(2)
            with c1:
                rsi_delta = "overbought" if r["rsi"] > 70 else "oversold" if r["rsi"] < 30 else "neutral"
                st.metric("RSI", f"{r['rsi']:.1f}", delta=rsi_delta, delta_color="inverse" if r["rsi"] > 70 else "normal" if r["rsi"] < 30 else "off")
            with c2:
                st.metric("Sentiment", f"{r['sentiment']:+.2f}")

            st.caption(f"Confidence: {r['confidence']:.0%} | MACD: {r['macd_h']:+.4f}")

            if r["executed"]:
                qty = r["exec_detail"].get("quantity", 0)
                fees = r["exec_detail"].get("fees", {}).get("total", 0) if r["exec_detail"].get("fees") else 0
                st.success(f"✅ Executed: {r['signal']} {qty} @ ${r['price']:,.2f} (fees: ${fees:,.2f})")
            else:
                reason = r["exec_detail"].get("reason", "signal was HOLD")
                st.info(f"⏸️ Not executed: {reason}")

    # ── Agent Reasoning ──────────────────────────────────────────────────
    st.divider()
    st.subheader("🧠 Agent Reasoning")
    for r in results:
        if "error" in r:
            continue
        with st.expander(f"{r['symbol']} — {r['signal']} ({r['confidence']:.0%} confidence)", expanded=r["executed"]):
            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown("**Decision Logic:**")
                st.text(r["reasoning"])

                st.markdown("**Technical Indicators:**")
                tech_df = pd.DataFrame([{
                    "RSI": f"{r['rsi']:.1f} ({r['rsi_label']})",
                    "MACD Hist": f"{r['macd_h']:+.4f}",
                    "BB Lower": f"${r['bb_lower']:,.2f}",
                    "BB Mid": f"${r['bb_mid']:,.2f}",
                    "BB Upper": f"${r['bb_upper']:,.2f}",
                    "Price": f"${r['price']:,.2f}",
                }])
                st.dataframe(tech_df, hide_index=True, use_container_width=True)

            with col2:
                st.markdown("**News Headlines:**")
                for h in r.get("headlines", [])[:5]:
                    if h:
                        st.caption(f"• {h[:80]}")

                if r.get("themes"):
                    st.markdown("**Themes:**")
                    for t in r["themes"]:
                        st.caption(f"🏷️ {t[:60]}")

    # ── Trade Execution Log ──────────────────────────────────────────────
    st.divider()
    st.subheader("📋 Trade Execution Log")
    history = st.session_state.trade_history
    if history:
        df = pd.DataFrame(history[-20:])  # Last 20 trades
        df["executed"] = df["executed"].map({True: "✅", False: "⏸️"})
        signal_colors = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}
        df["signal"] = df["signal"].map(lambda s: f"{signal_colors.get(s, '')} {s}")
        df["price"] = df["price"].map(lambda p: f"${p:,.2f}")
        df["fees"] = df["fees"].map(lambda f: f"${f:,.2f}")
        df["confidence"] = df["confidence"].map(lambda c: f"{c:.0%}")
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.info("No trades yet. Click **Run Trading Cycle** to start.")

    # ── Portfolio Positions ──────────────────────────────────────────────
    st.divider()
    st.subheader("💼 Portfolio Positions")
    portfolio = comp["portfolio"]
    if portfolio.positions:
        pos_data = []
        for sym, pos in portfolio.positions.items():
            price = next((r["price"] for r in results if r.get("symbol") == sym), pos.avg_cost)
            pnl = pos.unrealized_pnl(price)
            pos_data.append({
                "Symbol": sym,
                "Qty": pos.quantity,
                "Avg Cost": f"${pos.avg_cost:,.2f}",
                "Current": f"${price:,.2f}",
                "P&L": f"${pnl:+,.2f}",
                "Value": f"${pos.market_value(price):,.2f}",
            })
        st.dataframe(pd.DataFrame(pos_data), hide_index=True, use_container_width=True)
    else:
        st.info("No open positions.")

    # ── Performance from DB ──────────────────────────────────────────────
    perf = comp["trade_log"].performance_summary()
    if perf["total_trades"] > 0:
        st.divider()
        st.subheader("📈 Performance")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Trades", perf["total_trades"])
        c2.metric("Win Rate", f"{perf['win_rate']:.0%}")
        c3.metric("Net P&L", f"${perf['total_pnl']:+,.2f}")
        c4.metric("Gross P&L", f"${perf['gross_pnl']:+,.2f}")
        c5.metric("Total Fees", f"${perf['total_fees']:,.2f}")


# ── Main Logic ───────────────────────────────────────────────────────────────
if run_button and symbols:
    results = run_trading_cycle(symbols)
    display_results(results)
elif st.session_state.latest_results:
    display_results(st.session_state.latest_results)
else:
    st.title("📈 tradex-ai Dashboard")
    st.markdown("""
    ### Welcome to tradex-ai

    Select symbols in the sidebar and click **Run Trading Cycle** to start.

    The dashboard shows:
    - **Data Flow** — watch market data and news being fetched
    - **Market Signals** — live BUY/SELL/HOLD decisions with confidence scores
    - **Agent Reasoning** — see exactly why the AI made each decision
    - **Trade Execution Log** — every trade with fees and P&L
    - **Portfolio** — current positions and performance
    """)

# Auto-refresh
if auto_refresh and symbols:
    time.sleep(refresh_interval)
    st.rerun()
