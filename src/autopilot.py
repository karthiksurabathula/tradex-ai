"""Autopilot — fully autonomous AI trading bot.

Give it money, it scans the market, picks stocks, trades intraday,
manages risk, and evolves. No human involvement.

Usage:
    python -m src.autopilot
    python -m src.autopilot --cash 50000 --aggressive
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import UTC, datetime, timedelta

import yfinance as yf
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.columns import Columns

from src.execution.executor import Executor
from src.execution.fees import FeeModel
from src.execution.portfolio import Portfolio
from src.execution.trade_log import TradeLog
from src.ingestion.openbb_provider import OpenBBProvider
from src.ingestion.state_builder import StateBuilder
from src.ingestion.yfinance_news_provider import YFinanceNewsProvider
from src.reasoning.engine import ReasoningEngine
from src.scanner.market_scanner import MarketScanner
from src.strategy.intraday_strategist import IntradayStrategist
from src.strategy.position_manager import PositionManager

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)
console = Console(force_terminal=True, color_system="auto")


class Autopilot:
    """Fully autonomous intraday trading bot."""

    def __init__(
        self,
        starting_cash: float = 100_000.0,
        aggressive: bool = False,
        scan_interval: int = 300,     # Scan market every 5 min
        monitor_interval: int = 60,   # Check positions every 1 min
    ):
        self.scan_interval = scan_interval
        self.monitor_interval = monitor_interval

        # Core components
        fee_model = FeeModel()
        self.portfolio = Portfolio(cash=starting_cash, fee_model=fee_model)
        self.trade_log = TradeLog(db_path="data/trades.db")

        # Scanner
        self.scanner = MarketScanner()

        # Strategist
        self.strategist = IntradayStrategist(
            max_open_positions=8 if aggressive else 5,
            max_single_position_pct=0.20 if aggressive else 0.15,
            min_cash_reserve_pct=0.10 if aggressive else 0.20,
            min_score_threshold=15.0 if aggressive else 25.0,
        )

        # Position manager (stop-loss, take-profit, trailing stops)
        self.position_manager = PositionManager(
            stop_loss_pct=0.03 if aggressive else 0.02,
            take_profit_pct=0.06 if aggressive else 0.04,
            trailing_stop_pct=0.02 if aggressive else 0.015,
            max_hold_minutes=240 if aggressive else 180,
        )

        # Reasoning engine for trade confirmation
        self.engine = ReasoningEngine()
        self.state_builder = StateBuilder(
            OpenBBProvider(provider="yfinance", interval="5m"),
            YFinanceNewsProvider(),
        )

        # Executor
        self.executor = Executor(
            self.portfolio, self.trade_log,
            max_position_pct=0.20 if aggressive else 0.15,
            min_confidence=0.30 if aggressive else 0.40,
        )

        # Stats
        self.cycle_count = 0
        self.trades_today = 0
        self.events: list[dict] = []  # Event log for display

    def log_event(self, event_type: str, message: str, symbol: str = ""):
        """Log an event for the live display."""
        self.events.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "type": event_type,
            "symbol": symbol,
            "message": message,
        })
        # Keep last 50 events
        if len(self.events) > 50:
            self.events = self.events[-50:]

    def scan_and_enter(self):
        """Phase 1: Scan market for opportunities and enter positions."""
        self.log_event("SCAN", "Scanning market for opportunities...")

        try:
            scan_results = self.scanner.full_scan(top_n=15)
        except Exception as e:
            self.log_event("ERROR", f"Scan failed: {e}")
            return

        if not scan_results:
            self.log_event("SCAN", "No opportunities found.")
            return

        # Log top opportunities
        for r in scan_results[:5]:
            self.log_event("FOUND", f"Score {r.score:.0f}: {r.reason}", r.symbol)

        # Get current prices for portfolio valuation
        current_prices = self._get_current_prices()

        # Check emergency exit first
        if self.strategist.should_exit_all(self.portfolio, current_prices):
            self.log_event("EMERGENCY", "Portfolio loss > 5%! Exiting all positions.")
            self._exit_all_positions(current_prices)
            return

        # Select and size opportunities
        opportunities = self.strategist.select_opportunities(
            scan_results, self.portfolio, current_prices
        )

        if not opportunities:
            self.log_event("STRATEGY", "No actionable opportunities after filtering.")
            return

        # Execute entries
        for opp in opportunities:
            self.log_event("ENTRY", f"Entering {opp.direction} {opp.quantity} shares (score: {opp.score:.0f}, {opp.reason})", opp.symbol)

            # Quick confirmation via reasoning engine
            try:
                end = datetime.now(UTC)
                start = end - timedelta(days=5)
                state = self.state_builder.build(opp.symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
                signal = self.engine.decide(state)

                # Only enter if reasoning agrees with scanner
                if signal.action.value == "SELL" and opp.direction == "BUY":
                    self.log_event("VETO", f"Reasoning engine vetoed BUY (says SELL)", opp.symbol)
                    continue

                fees = self.portfolio.buy(opp.symbol, opp.quantity, opp.price)
                if fees:
                    self.position_manager.register_entry(opp.symbol, opp.price)
                    self.trades_today += 1
                    self.log_event("EXECUTED", f"BOUGHT {opp.quantity} @ ${opp.price:,.2f} (fees: ${fees['total']:,.2f})", opp.symbol)

                    # Log to trade log
                    from src.state.models import TradeSignal, SignalType
                    self.trade_log.record(
                        TradeSignal(symbol=opp.symbol, action=SignalType.BUY, confidence=opp.score / 100, reasoning=opp.reason),
                        price=opp.price, executed=True, quantity=opp.quantity, fees=fees,
                    )
                else:
                    self.log_event("FAILED", f"Insufficient cash for {opp.quantity} shares", opp.symbol)

            except Exception as e:
                self.log_event("ERROR", f"Entry failed: {e}", opp.symbol)

    def monitor_and_exit(self):
        """Phase 2: Monitor positions and exit when conditions are met."""
        if not self.portfolio.positions:
            return

        current_prices = self._get_current_prices()

        # Check exit conditions
        exit_signals = self.position_manager.check_exits(current_prices)

        for exit_sig in exit_signals:
            self.log_event("EXIT", f"{exit_sig.reason}", exit_sig.symbol)

            pos = self.portfolio.positions.get(exit_sig.symbol)
            if pos:
                result = self.portfolio.sell(exit_sig.symbol, pos.quantity, exit_sig.current_price)
                if result:
                    self.position_manager.remove(exit_sig.symbol)
                    self.trades_today += 1
                    color = "profit" if result["net_pnl"] > 0 else "loss"
                    self.log_event(
                        "CLOSED",
                        f"SOLD {pos.quantity} @ ${exit_sig.current_price:,.2f} | "
                        f"P&L: ${result['net_pnl']:+,.2f} ({color})",
                        exit_sig.symbol,
                    )

                    # Log to trade log
                    from src.state.models import TradeSignal, SignalType
                    self.trade_log.record(
                        TradeSignal(symbol=exit_sig.symbol, action=SignalType.SELL, confidence=0.9, reasoning=exit_sig.reason),
                        price=exit_sig.current_price, executed=True, quantity=pos.quantity,
                        gross_pnl=result["gross_pnl"], net_pnl=result["net_pnl"], fees=result["fees"],
                    )

    def _exit_all_positions(self, prices: dict[str, float]):
        """Emergency exit all positions."""
        for symbol in list(self.portfolio.positions.keys()):
            pos = self.portfolio.positions[symbol]
            price = prices.get(symbol, pos.avg_cost)
            result = self.portfolio.sell(symbol, pos.quantity, price)
            if result:
                self.position_manager.remove(symbol)
                self.log_event("EMERGENCY_EXIT", f"Closed {pos.quantity} @ ${price:,.2f} | P&L: ${result['net_pnl']:+,.2f}", symbol)

    def _get_current_prices(self) -> dict[str, float]:
        """Get current prices for all held positions."""
        prices = {}
        symbols = list(self.portfolio.positions.keys())
        if not symbols:
            return prices

        try:
            tickers = yf.Tickers(" ".join(symbols))
            for symbol in symbols:
                try:
                    info = yf.Ticker(symbol).fast_info
                    prices[symbol] = info.get("lastPrice", 0) or info.get("regularMarketPrice", 0)
                except Exception:
                    pos = self.portfolio.positions.get(symbol)
                    if pos:
                        prices[symbol] = pos.avg_cost
        except Exception:
            pass

        return prices

    def build_display(self) -> str:
        """Build the live terminal display."""
        prices = self._get_current_prices()
        summary = self.portfolio.summary(prices)

        lines = []
        lines.append("")
        lines.append("=" * 80)
        lines.append("  TRADEX-AI AUTOPILOT  |  Cycle #{:<4}  |  {}  |  Trades Today: {}".format(
            self.cycle_count, datetime.now().strftime("%H:%M:%S"), self.trades_today
        ))
        lines.append("=" * 80)

        # Portfolio summary
        lines.append("")
        lines.append(f"  Cash: ${summary['cash']:>12,.2f}  |  Value: ${summary['total_value']:>12,.2f}  |  "
                     f"P&L: ${summary['realized_pnl']:>+10,.2f}  |  Fees: ${summary['total_fees_paid']:>8,.2f}")
        lines.append("-" * 80)

        # Open positions
        if self.portfolio.positions:
            lines.append("  OPEN POSITIONS:")
            lines.append(f"  {'Symbol':<8} {'Qty':>6} {'Entry':>10} {'Current':>10} {'P&L':>12} {'Stop':>10} {'Target':>10}")
            for sym, pos in self.portfolio.positions.items():
                price = prices.get(sym, pos.avg_cost)
                pnl = pos.unrealized_pnl(price)
                rule = self.position_manager.rules.get(sym)
                sl = f"${rule.stop_loss_price:,.2f}" if rule else "N/A"
                tp = f"${rule.take_profit_price:,.2f}" if rule else "N/A"
                pnl_marker = "+" if pnl >= 0 else ""
                lines.append(f"  {sym:<8} {pos.quantity:>6} ${pos.avg_cost:>9,.2f} ${price:>9,.2f} {pnl_marker}${pnl:>10,.2f} {sl:>10} {tp:>10}")
        else:
            lines.append("  No open positions — scanning for opportunities...")

        lines.append("-" * 80)

        # Recent events
        lines.append("  EVENT LOG:")
        for event in self.events[-15:]:
            emoji = {
                "SCAN": "[>>]", "FOUND": "[!!]", "ENTRY": "[->]", "EXECUTED": "[OK]",
                "EXIT": "[<-]", "CLOSED": "[$$]", "VETO": "[NO]", "ERROR": "[XX]",
                "STRATEGY": "[AI]", "EMERGENCY": "[!!]", "FAILED": "[??]",
                "MONITOR": "[..]", "EMERGENCY_EXIT": "[!!]",
            }.get(event["type"], "[--]")
            sym = f"[{event['symbol']}]" if event["symbol"] else ""
            lines.append(f"  {event['time']}  {emoji} {event['type']:<12} {sym:<8} {event['message']}")

        lines.append("=" * 80)
        lines.append("  Ctrl+C to stop  |  Scanning every {}s  |  Monitoring every {}s".format(
            self.scan_interval, self.monitor_interval
        ))
        lines.append("")

        return "\n".join(lines)

    def run(self):
        """Main loop — fully autonomous, runs until stopped."""
        console.print(Panel(
            "[bold]TRADEX-AI AUTOPILOT[/]\n\n"
            f"Starting cash: ${self.portfolio.cash:,.2f}\n"
            f"Scan interval: {self.scan_interval}s | Monitor interval: {self.monitor_interval}s\n"
            f"Max positions: {self.strategist.max_open_positions} | "
            f"Stop-loss: {self.position_manager.stop_loss_pct:.0%} | "
            f"Take-profit: {self.position_manager.take_profit_pct:.0%}\n\n"
            "[dim]Ctrl+C to stop[/]",
            title="[AI] Starting Up",
            border_style="green",
        ))

        last_scan = 0
        last_monitor = 0

        try:
            while True:
                now = time.time()
                self.cycle_count += 1

                # Phase 1: Scan for new opportunities (every scan_interval)
                if now - last_scan >= self.scan_interval:
                    self.scan_and_enter()
                    last_scan = now

                # Phase 2: Monitor existing positions (every monitor_interval)
                if now - last_monitor >= self.monitor_interval:
                    self.monitor_and_exit()
                    last_monitor = now

                # Display
                console.clear()
                console.print(self.build_display())

                # Sleep until next action needed
                next_scan = last_scan + self.scan_interval - now
                next_monitor = last_monitor + self.monitor_interval - now
                sleep_time = max(5, min(next_scan, next_monitor, 30))
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            console.print("\n[bold yellow]Shutting down...[/]")

            # Final summary
            prices = self._get_current_prices()
            summary = self.portfolio.summary(prices)
            perf = self.trade_log.performance_summary()

            console.print(Panel(
                f"[bold]Final Portfolio[/]\n\n"
                f"Cash: ${summary['cash']:,.2f}\n"
                f"Total Value: ${summary['total_value']:,.2f}\n"
                f"Realized P&L: ${summary['realized_pnl']:+,.2f}\n"
                f"Unrealized P&L: ${summary['unrealized_pnl']:+,.2f}\n"
                f"Total Fees: ${summary['total_fees_paid']:,.2f}\n\n"
                f"Trades Today: {self.trades_today}\n"
                f"Win Rate: {perf['win_rate']:.0%}\n"
                f"Open Positions: {len(self.portfolio.positions)}",
                title="Session Summary",
                border_style="cyan",
            ))

            self.trade_log.close()


def main():
    parser = argparse.ArgumentParser(description="tradex-ai Autopilot — fully autonomous AI trader")
    parser.add_argument("--cash", type=float, default=100_000, help="Starting cash (default: $100,000)")
    parser.add_argument("--aggressive", action="store_true", help="Aggressive mode (more positions, wider stops)")
    parser.add_argument("--scan-interval", type=int, default=300, help="Market scan interval in seconds (default: 300)")
    parser.add_argument("--monitor-interval", type=int, default=60, help="Position monitor interval in seconds (default: 60)")
    args = parser.parse_args()

    autopilot = Autopilot(
        starting_cash=args.cash,
        aggressive=args.aggressive,
        scan_interval=args.scan_interval,
        monitor_interval=args.monitor_interval,
    )
    autopilot.run()


if __name__ == "__main__":
    main()
