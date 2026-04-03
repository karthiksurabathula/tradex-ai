"""Rich-based terminal dashboard for Bloomberg-style paper trading display."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.execution.portfolio import Portfolio
from src.state.models import TradeSignal


class TerminalUI:
    """Terminal-based UI for displaying portfolio, signals, and trade results."""

    def __init__(self):
        self.console = Console()

    def show_portfolio(self, portfolio: Portfolio, prices: dict[str, float]):
        """Display current portfolio positions and summary."""
        table = Table(title="Paper Portfolio", show_header=True, header_style="bold cyan")
        table.add_column("Symbol", style="cyan", width=10)
        table.add_column("Qty", justify="right", width=8)
        table.add_column("Avg Cost", justify="right", width=12)
        table.add_column("Current", justify="right", width=12)
        table.add_column("Unrealized P&L", justify="right", width=16)
        table.add_column("Market Value", justify="right", width=14)

        for sym, pos in portfolio.positions.items():
            price = prices.get(sym, pos.avg_cost)
            pnl = pos.unrealized_pnl(price)
            mkt_val = pos.market_value(price)
            style = "green" if pnl >= 0 else "red"
            table.add_row(
                sym,
                str(pos.quantity),
                f"${pos.avg_cost:,.2f}",
                f"${price:,.2f}",
                f"[{style}]${pnl:+,.2f}[/]",
                f"${mkt_val:,.2f}",
            )

        self.console.print(table)

        summary = portfolio.summary(prices)
        self.console.print(
            f"  Cash: ${summary['cash']:,.2f}  |  "
            f"Realized P&L: [{'green' if summary['realized_pnl'] >= 0 else 'red'}]"
            f"${summary['realized_pnl']:+,.2f}[/]  |  "
            f"Total Value: ${summary['total_value']:,.2f}  |  "
            f"Fees Paid: [yellow]${summary['total_fees_paid']:,.2f}[/]"
        )

    def show_signal(self, signal: TradeSignal):
        """Display a trade signal with color coding."""
        color_map = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}
        color = color_map.get(signal.action.value, "white")

        self.console.print(
            Panel(
                f"[bold {color}]{signal.action.value}[/] {signal.symbol}  "
                f"(confidence: {signal.confidence:.0%})\n\n"
                f"[dim]{signal.reasoning[:300]}[/]",
                title=f"Signal: {signal.symbol}",
                border_style=color,
            )
        )

    def show_execution(self, result: dict):
        """Display trade execution result."""
        if not result.get("executed"):
            reason = result.get("reason", "N/A")
            self.console.print(f"  [dim]Not executed: {reason}[/]")
            return

        action = result["action"]
        color = "green" if action == "BUY" else "red"
        qty = result.get("quantity", 0)
        price = result.get("price", 0)
        fees = result.get("fees", {})

        self.console.print(
            f"  [bold {color}]EXECUTED[/] {action} {qty} @ ${price:,.2f}  "
            f"(fees: ${fees.get('total', 0):,.2f})"
        )

        if "net_pnl" in result:
            pnl_color = "green" if result["net_pnl"] >= 0 else "red"
            self.console.print(
                f"  P&L: [{pnl_color}]${result['net_pnl']:+,.2f}[/] "
                f"(gross: ${result.get('gross_pnl', 0):+,.2f})"
            )

    def show_divider(self, label: str = ""):
        """Print a visual divider."""
        if label:
            self.console.rule(f"[bold]{label}[/]")
        else:
            self.console.rule()
