"""FastAPI web app — tradex-ai dashboard with HTML5 UI."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yfinance as yf
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.agents.developer_agent import DeveloperAgent
from src.data.quote_store import QuoteStore
from src.execution.executor import Executor
from src.execution.fees import FeeModel
from src.execution.portfolio_store import PersistentPortfolio
from src.execution.trade_log import TradeLog
from src.feedback.metrics import compute_metrics
from src.feedback.reviewer import TradeReviewer
from src.ingestion.openbb_provider import OpenBBProvider
from src.ingestion.state_builder import StateBuilder
from src.ingestion.yfinance_news_provider import YFinanceNewsProvider
from src.reasoning.engine import ReasoningEngine
from src.reasoning.prompt_store import PromptStore
from src.scanner.market_scanner import MarketScanner
from src.state.models import SignalType, TradeSignal
from src.strategy.algorithm_lab import AlgorithmLab
from src.strategy.intraday_strategist import IntradayStrategist
from src.strategy.market_context import MarketContextProvider
from src.strategy.position_manager import PositionManager
from src.strategy.risk_manager import RiskManager

app = FastAPI(title="tradex-ai", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

# ── Components (initialized once) ───────────────────────────────────────────
fm = FeeModel()
portfolio = PersistentPortfolio(starting_cash=100_000.0, fee_model=fm)
trade_log = TradeLog()
quote_store = QuoteStore()
scanner = MarketScanner()
strategist = IntradayStrategist()
pos_mgr = PositionManager()
risk_mgr = RiskManager()
market_ctx = MarketContextProvider()
engine = ReasoningEngine()
state_builder = StateBuilder(
    OpenBBProvider(provider="yfinance", interval="5m"),
    YFinanceNewsProvider(),
)
executor = Executor(portfolio.portfolio, trade_log, max_position_pct=0.15, min_confidence=0.30)
reviewer = TradeReviewer(trade_log)
algo_lab = AlgorithmLab(quote_store)
dev_agent = DeveloperAgent()
prompt_store = PromptStore()

events: list[dict] = []
cycle_count = 0
trades_today = 0


def log_event(t: str, msg: str, sym: str = ""):
    events.append({"time": datetime.now().strftime("%H:%M:%S"), "type": t, "symbol": sym, "message": msg})
    if len(events) > 200:
        del events[:-200]


def get_prices() -> dict[str, float]:
    prices = {}
    for s in portfolio.positions:
        try:
            prices[s] = yf.Ticker(s).fast_info.get("lastPrice", 0)
        except Exception:
            prices[s] = portfolio.positions[s].avg_cost
    return prices


# ── HTML5 Page ───────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return (Path(__file__).parent / "static" / "index.html").read_text()


# ── API: Portfolio ───────────────────────────────────────────────────────────
@app.get("/api/portfolio")
async def api_portfolio():
    prices = get_prices()
    summary = portfolio.summary(prices)
    positions = []
    for sym, pos in portfolio.positions.items():
        p = prices.get(sym, pos.avg_cost)
        rule = pos_mgr.rules.get(sym)
        positions.append({
            "symbol": sym, "quantity": pos.quantity,
            "avg_cost": round(pos.avg_cost, 2), "current_price": round(p, 2),
            "pnl": round(pos.unrealized_pnl(p), 2),
            "pnl_pct": round(((p - pos.avg_cost) / pos.avg_cost) * 100, 2) if pos.avg_cost else 0,
            "is_short": pos.is_short,
            "stop_loss": round(rule.stop_loss_price, 2) if rule else None,
            "take_profit": round(rule.take_profit_price, 2) if rule else None,
            "trailing_stop": round(rule.trailing_stop_price, 2) if rule else None,
            "value": round(pos.market_value(p), 2),
        })
    return {"summary": summary, "positions": positions, "cycle_count": cycle_count, "trades_today": trades_today}


# ── API: Run Autopilot Cycle ─────────────────────────────────────────────────
@app.post("/api/autopilot/run")
async def api_autopilot_run():
    global cycle_count, trades_today
    cycle_count += 1
    results = {"scan": [], "analyzed": [], "trades": [], "exits": []}

    # Phase 1: Scan
    log_event("SCAN", "Scanning market...")
    try:
        scan_results = scanner.full_scan(top_n=12)
        results["scan"] = [{"symbol": r.symbol, "score": r.score, "category": r.category,
                            "change": r.change_pct, "reason": r.reason} for r in scan_results]
        for r in scan_results[:5]:
            log_event("FOUND", f"Score {r.score:.0f}: {r.reason}", r.symbol)
    except Exception as e:
        log_event("ERROR", str(e))
        return results

    # Phase 2: Analyze top picks
    end = datetime.now(UTC)
    start = end - timedelta(days=5)
    analyzed = {}
    for r in scan_results[:6]:
        try:
            state = state_builder.build(r.symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            signal = engine.decide(state)
            analyzed[r.symbol] = {"signal": signal, "state": state, "scan": r}
            results["analyzed"].append({
                "symbol": r.symbol, "action": signal.action.value,
                "confidence": signal.confidence, "reasoning": signal.reasoning[:200],
                "price": state.technicals.current_price, "rsi": state.technicals.rsi,
                "sentiment": state.sentiment.overall_score,
            })
            log_event("ANALYZE", f"{signal.action.value} ({signal.confidence:.0%})", r.symbol)
        except Exception as e:
            log_event("ERROR", str(e), r.symbol)

    # Phase 3: Execute
    prices = get_prices()
    prices.update({s: a["state"].technicals.current_price for s, a in analyzed.items()})
    opps = strategist.select_opportunities(scan_results, portfolio.portfolio, prices)

    for opp in opps:
        a = analyzed.get(opp.symbol)
        if a and a["signal"].action == SignalType.SELL and opp.direction == "BUY":
            log_event("VETO", "AI vetoed BUY", opp.symbol)
            continue

        fees = portfolio.buy(opp.symbol, opp.quantity, opp.price)
        if fees:
            pos_mgr.register_entry(opp.symbol, opp.price)
            trades_today += 1
            trade_log.record(
                TradeSignal(symbol=opp.symbol, action=SignalType.BUY, confidence=opp.score / 100, reasoning=opp.reason),
                price=opp.price, executed=True, quantity=opp.quantity, fees=fees,
            )
            results["trades"].append({"symbol": opp.symbol, "action": "BUY", "quantity": opp.quantity,
                                      "price": opp.price, "fees": fees["total"]})
            log_event("BOUGHT", f"{opp.quantity} @ ${opp.price:,.2f} (fees ${fees['total']:,.2f})", opp.symbol)
            portfolio.record_equity(prices)

    # Phase 4: Monitor exits
    for ex in pos_mgr.check_exits(prices):
        pos = portfolio.positions.get(ex.symbol)
        if pos:
            res = portfolio.sell(ex.symbol, pos.quantity, ex.current_price)
            if res:
                pos_mgr.remove(ex.symbol)
                trades_today += 1
                trade_log.record(
                    TradeSignal(symbol=ex.symbol, action=SignalType.SELL, confidence=0.9, reasoning=ex.reason),
                    price=ex.current_price, executed=True, quantity=pos.quantity,
                    gross_pnl=res["gross_pnl"], net_pnl=res["net_pnl"], fees=res["fees"],
                )
                results["exits"].append({"symbol": ex.symbol, "pnl": res["net_pnl"], "reason": ex.reason})
                log_event("CLOSED", f"P&L ${res['net_pnl']:+,.2f} | {ex.reason}", ex.symbol)

    return results


# ── API: Manual Analyze ──────────────────────────────────────────────────────
@app.get("/api/analyze/{symbol}")
async def api_analyze(symbol: str):
    try:
        end = datetime.now(UTC)
        start = end - timedelta(days=5)
        state = state_builder.build(symbol.upper(), start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        signal = engine.decide(state)
        return {
            "symbol": symbol.upper(), "action": signal.action.value,
            "confidence": signal.confidence, "reasoning": signal.reasoning,
            "price": state.technicals.current_price, "rsi": state.technicals.rsi,
            "rsi_label": state.technicals.rsi_label,
            "macd": state.technicals.macd_histogram,
            "bb_lower": state.technicals.bb_lower, "bb_mid": state.technicals.bb_mid,
            "bb_upper": state.technicals.bb_upper,
            "sentiment": state.sentiment.overall_score,
            "headlines": [h.get("title", "") for h in state.headlines[:5]],
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── API: Manual Buy/Sell ─────────────────────────────────────────────────────
@app.post("/api/trade")
async def api_trade(request: Request):
    global trades_today
    body = await request.json()
    symbol = body["symbol"].upper()
    action = body["action"].upper()
    quantity = int(body.get("quantity", 10))
    price = float(body.get("price", 0))

    if price == 0:
        try:
            price = yf.Ticker(symbol).fast_info.get("lastPrice", 0)
        except Exception:
            return JSONResponse({"error": "Could not get price"}, status_code=400)

    if action == "BUY":
        fees = portfolio.buy(symbol, quantity, price)
        if fees:
            pos_mgr.register_entry(symbol, price)
            trades_today += 1
            trade_log.record(TradeSignal(symbol=symbol, action=SignalType.BUY, confidence=0.8, reasoning="Manual"),
                             price=price, executed=True, quantity=quantity, fees=fees)
            return {"status": "ok", "action": "BUY", "symbol": symbol, "quantity": quantity, "price": price, "fees": fees["total"]}
        return JSONResponse({"error": "Insufficient cash"}, status_code=400)

    elif action == "SELL":
        pos = portfolio.positions.get(symbol)
        if not pos:
            return JSONResponse({"error": "No position"}, status_code=400)
        qty = min(quantity, pos.quantity)
        res = portfolio.sell(symbol, qty, price)
        if res:
            pos_mgr.remove(symbol)
            trades_today += 1
            trade_log.record(TradeSignal(symbol=symbol, action=SignalType.SELL, confidence=0.8, reasoning="Manual"),
                             price=price, executed=True, quantity=qty,
                             gross_pnl=res["gross_pnl"], net_pnl=res["net_pnl"], fees=res["fees"])
            return {"status": "ok", "action": "SELL", "symbol": symbol, "quantity": qty, "pnl": res["net_pnl"]}
        return JSONResponse({"error": "Sell failed"}, status_code=400)

    return JSONResponse({"error": "Invalid action"}, status_code=400)


# ── API: Scanner ─────────────────────────────────────────────────────────────
@app.get("/api/scanner")
async def api_scanner():
    try:
        results = scanner.full_scan(top_n=12)
        return [{"symbol": r.symbol, "score": r.score, "category": r.category,
                 "change": r.change_pct, "volume_ratio": r.volume_ratio,
                 "price": r.price, "reason": r.reason} for r in results]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── API: Trade Log ───────────────────────────────────────────────────────────
@app.get("/api/trades")
async def api_trades(symbol: str = "", limit: int = 30):
    return trade_log.recent_trades(symbol=symbol or None, limit=limit)


# ── API: Performance ─────────────────────────────────────────────────────────
@app.get("/api/performance")
async def api_performance():
    perf = trade_log.performance_summary()
    trades = trade_log.recent_trades(limit=100)
    metrics = compute_metrics(trades)
    equity = portfolio.get_equity_curve(limit=200)
    review = reviewer.review()
    return {"performance": perf, "metrics": metrics, "equity_curve": equity, "review": review}


# ── API: Events ──────────────────────────────────────────────────────────────
@app.get("/api/events")
async def api_events():
    return list(reversed(events[-50:]))


# ── API: Risk/Regime ─────────────────────────────────────────────────────────
@app.get("/api/regime")
async def api_regime():
    try:
        ctx = market_ctx.get_context()
        return {
            "regime": ctx.regime.value, "vix": ctx.vix,
            "spy_change": ctx.spy_change_pct, "dxy_change": ctx.dxy_change_pct,
            "position_multiplier": ctx.position_size_multiplier,
            "stop_multiplier": ctx.stop_loss_multiplier,
            "confidence": ctx.regime_confidence,
        }
    except Exception as e:
        return {"regime": "UNKNOWN", "error": str(e)}


@app.get("/api/risk")
async def api_risk():
    return risk_mgr.status


# ── API: Kill Switch ─────────────────────────────────────────────────────────
@app.post("/api/kill-switch/{action}")
async def api_kill_switch(action: str):
    if action == "activate":
        RiskManager.activate_kill_switch("Dashboard")
        return {"status": "activated"}
    elif action == "deactivate":
        RiskManager.deactivate_kill_switch()
        return {"status": "deactivated"}
    return JSONResponse({"error": "Invalid action"}, status_code=400)


# ── API: Reset ───────────────────────────────────────────────────────────────
@app.post("/api/reset")
async def api_reset():
    global trades_today
    portfolio.reset()
    pos_mgr.rules.clear()
    events.clear()
    trades_today = 0
    return {"status": "reset", "cash": 100_000.0}
