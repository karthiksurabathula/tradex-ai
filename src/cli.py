"""CLI entry point — run a single cycle or watch mode with live refresh."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import UTC, datetime, timedelta

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text

from src.execution.executor import Executor
from src.execution.fees import FeeModel
from src.execution.portfolio import Portfolio
from src.execution.terminal_ui import TerminalUI
from src.execution.trade_log import TradeLog
from src.ingestion.openbb_provider import OpenBBProvider
from src.ingestion.state_builder import StateBuilder
from src.ingestion.yfinance_news_provider import YFinanceNewsProvider
from src.reasoning.engine import ReasoningEngine

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
console = Console()


def build_components(starting_cash: float = 100_000.0):
    fee_model = FeeModel()
    portfolio = Portfolio(cash=starting_cash, fee_model=fee_model)
    trade_log = TradeLog(db_path="data/trades.db")
    return {
        "state_builder": StateBuilder(
            OpenBBProvider(provider="yfinance", interval="5m"),
            YFinanceNewsProvider(),
        ),
        "engine": ReasoningEngine(),
        "portfolio": portfolio,
        "executor": Executor(portfolio, trade_log, max_position_pct=0.10, min_confidence=0.40),
        "ui": TerminalUI(),
        "trade_log": trade_log,
    }


def run_cycle(symbols: list[str], components: dict) -> list[dict]:
    """Run one trading cycle for all symbols. Returns results."""
    results = []
    end = datetime.now(UTC)
    start = end - timedelta(days=5)

    for symbol in symbols:
        try:
            state = components["state_builder"].build(
                symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
            )
            signal = components["engine"].decide(state)
            exec_result = components["executor"].execute(signal, state.technicals.current_price)

            results.append({
                "symbol": symbol,
                "price": state.technicals.current_price,
                "rsi": state.technicals.rsi,
                "rsi_label": state.technicals.rsi_label,
                "macd_h": state.technicals.macd_histogram,
                "bb_lower": state.technicals.bb_lower,
                "bb_upper": state.technicals.bb_upper,
                "sentiment": state.sentiment.overall_score,
                "headlines": len(state.headlines),
                "signal": signal.action.value,
                "confidence": signal.confidence,
                "reasoning": signal.reasoning,
                "executed": exec_result.get("executed", False),
                "exec_detail": exec_result,
            })
        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)})

    return results


def build_dashboard(results: list[dict], portfolio: Portfolio, cycle: int) -> Layout:
    """Build a Rich layout for the dashboard."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=8),
    )

    # Header
    header_text = Text(f"  tradex-ai  |  Cycle #{cycle}  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", style="bold white on blue")
    layout["header"].update(Panel(header_text, style="blue"))

    # Market table
    market = Table(title="Market Signals", show_header=True, header_style="bold cyan", expand=True)
    market.add_column("Symbol", style="cyan", width=8)
    market.add_column("Price", justify="right", width=10)
    market.add_column("RSI", justify="right", width=12)
    market.add_column("MACD", justify="right", width=10)
    market.add_column("Sentiment", justify="right", width=10)
    market.add_column("Signal", justify="center", width=8)
    market.add_column("Conf", justify="right", width=6)
    market.add_column("Executed", justify="center", width=10)
    market.add_column("Reasoning", width=40)

    for r in results:
        if "error" in r:
            market.add_row(r["symbol"], "ERROR", "", "", "", "", "", "", str(r["error"])[:40])
            continue

        signal_color = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(r["signal"], "white")
        rsi_color = "red" if r["rsi"] > 70 else "green" if r["rsi"] < 30 else "white"
        sent_color = "green" if r["sentiment"] > 0.3 else "red" if r["sentiment"] < -0.3 else "white"
        exec_text = "[green]YES[/]" if r["executed"] else "[dim]no[/]"

        market.add_row(
            r["symbol"],
            f"${r['price']:,.2f}",
            f"[{rsi_color}]{r['rsi']:.1f} ({r['rsi_label']})[/]",
            f"{r['macd_h']:+.4f}",
            f"[{sent_color}]{r['sentiment']:+.2f}[/]",
            f"[bold {signal_color}]{r['signal']}[/]",
            f"{r['confidence']:.0%}",
            exec_text,
            r["reasoning"][:40],
        )

    layout["body"].update(market)

    # Portfolio footer
    prices = {r["symbol"]: r["price"] for r in results if "price" in r}
    summary = portfolio.summary(prices)

    port_table = Table(show_header=True, header_style="bold", expand=True)
    port_table.add_column("Position", style="cyan")
    port_table.add_column("Qty", justify="right")
    port_table.add_column("Cost", justify="right")
    port_table.add_column("Current", justify="right")
    port_table.add_column("P&L", justify="right")

    for sym, pos in portfolio.positions.items():
        price = prices.get(sym, pos.avg_cost)
        pnl = pos.unrealized_pnl(price)
        pnl_style = "green" if pnl >= 0 else "red"
        port_table.add_row(sym, str(pos.quantity), f"${pos.avg_cost:,.2f}", f"${price:,.2f}", f"[{pnl_style}]${pnl:+,.2f}[/]")

    if not portfolio.positions:
        port_table.add_row("[dim]No positions[/]", "", "", "", "")

    footer_text = (
        f"Cash: ${summary['cash']:,.2f}  |  "
        f"Value: ${summary['total_value']:,.2f}  |  "
        f"Realized: ${summary['realized_pnl']:+,.2f}  |  "
        f"Unrealized: ${summary['unrealized_pnl']:+,.2f}  |  "
        f"Fees: ${summary['total_fees_paid']:,.2f}"
    )
    footer_layout = Layout()
    footer_layout.split_column(
        Layout(port_table, size=5),
        Layout(Panel(footer_text, style="dim"), size=3),
    )
    layout["footer"].update(footer_layout)

    return layout


def cmd_once(symbols: list[str]):
    """Run a single trading cycle and display results."""
    console.print("[bold]Running single cycle...[/]\n")
    components = build_components()
    results = run_cycle(symbols, components)

    for r in results:
        if "error" in r:
            console.print(f"[red]{r['symbol']}: {r['error']}[/]")
            continue
        components["ui"].show_divider(r["symbol"])
        console.print(f"  ${r['price']:,.2f} | RSI {r['rsi']:.1f} | Sent {r['sentiment']:+.2f}")
        if r["signal"] != "HOLD":
            color = "green" if r["signal"] == "BUY" else "red"
            console.print(f"  [{color}]{r['signal']}[/] (conf: {r['confidence']:.0%}) — {r['reasoning'][:80]}")
            if r["executed"]:
                console.print(f"  [bold]EXECUTED[/]")
        else:
            console.print(f"  [yellow]HOLD[/] — {r['reasoning'][:80]}")

    console.print()
    prices = {r["symbol"]: r["price"] for r in results if "price" in r}
    components["ui"].show_portfolio(components["portfolio"], prices)
    components["trade_log"].close()


def cmd_watch(symbols: list[str], interval: int = 300):
    """Live dashboard that refreshes every N seconds."""
    console.print(f"[bold]Starting live dashboard (refresh every {interval}s, Ctrl+C to stop)...[/]\n")
    components = build_components()
    cycle = 0

    try:
        while True:
            cycle += 1
            results = run_cycle(symbols, components)
            dashboard = build_dashboard(results, components["portfolio"], cycle)

            console.clear()
            console.print(dashboard)
            console.print(f"\n[dim]Next refresh in {interval}s... (Ctrl+C to stop)[/]")

            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[bold]Stopped.[/]")
        prices = {r["symbol"]: r["price"] for r in results if "price" in r}
        summary = components["portfolio"].summary(prices)
        console.print(f"Final value: ${summary['total_value']:,.2f} | Fees: ${summary['total_fees_paid']:,.2f}")
        components["trade_log"].close()


def cmd_status():
    """Show current portfolio and recent trades from the database."""
    log = TradeLog(db_path="data/trades.db")
    trades = log.recent_trades(limit=15)
    perf = log.performance_summary()

    console.print(Panel("[bold]Recent Trades[/]", style="cyan"))
    if trades:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Time", width=20)
        table.add_column("Symbol", width=8)
        table.add_column("Action", width=6)
        table.add_column("Qty", justify="right", width=6)
        table.add_column("Price", justify="right", width=10)
        table.add_column("Net P&L", justify="right", width=10)
        table.add_column("Fees", justify="right", width=8)
        table.add_column("Exec", justify="center", width=5)

        for t in trades:
            color = "green" if t.get("net_pnl") and t["net_pnl"] > 0 else "red" if t.get("net_pnl") and t["net_pnl"] < 0 else "white"
            pnl_str = f"[{color}]${t.get('net_pnl', 0) or 0:+,.2f}[/]"
            table.add_row(
                str(t.get("timestamp", ""))[:19],
                t.get("symbol", ""),
                t.get("action", ""),
                str(t.get("quantity", 0)),
                f"${t.get('price', 0):,.2f}",
                pnl_str,
                f"${t.get('fee_total', 0):,.2f}",
                "Y" if t.get("executed") else "N",
            )
        console.print(table)
    else:
        console.print("[dim]No trades yet.[/]")

    console.print(f"\n[bold]Performance:[/] {perf['total_trades']} trades | "
                  f"Win rate: {perf['win_rate']:.0%} | "
                  f"Net P&L: ${perf['total_pnl']:+,.2f} | "
                  f"Fees: ${perf['total_fees']:,.2f}")
    log.close()


def main():
    parser = argparse.ArgumentParser(description="tradex-ai paper trading bot")
    sub = parser.add_subparsers(dest="command", help="Command to run")

    # once
    p_once = sub.add_parser("once", help="Run a single trading cycle")
    p_once.add_argument("--symbols", nargs="+", default=["AAPL", "NVDA", "MSFT"])

    # watch
    p_watch = sub.add_parser("watch", help="Live dashboard with auto-refresh")
    p_watch.add_argument("--symbols", nargs="+", default=["AAPL", "NVDA", "MSFT"])
    p_watch.add_argument("--interval", type=int, default=300, help="Refresh interval in seconds")

    # status
    sub.add_parser("status", help="Show recent trades and performance")

    args = parser.parse_args()

    if args.command == "once":
        cmd_once(args.symbols)
    elif args.command == "watch":
        cmd_watch(args.symbols, args.interval)
    elif args.command == "status":
        cmd_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
