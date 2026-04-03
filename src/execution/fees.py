"""Full traditional broker fee model applied to every paper trade."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FeeModel:
    """Full traditional broker fee schedule.

    Defaults mirror a typical traditional broker:
    - $4.95 commission per trade
    - Bid-ask spread: 0.02% equities, 0.30% crypto
    - SEC fee on sells: ~$8 per $1M notional
    - Slippage: 0.10% average
    """

    commission_per_trade: float = 4.95
    spread_pct_equity: float = 0.0002
    spread_pct_crypto: float = 0.003
    sec_fee_per_million: float = 8.00
    slippage_pct: float = 0.001
    min_commission: float = 1.00

    def calculate(self, action: str, symbol: str, quantity: int, price: float) -> dict:
        """Calculate total fees for a trade. Returns breakdown dict."""
        if quantity <= 0 or price <= 0:
            return {
                "commission": 0.0,
                "spread": 0.0,
                "slippage": 0.0,
                "sec_fee": 0.0,
                "total": 0.0,
                "effective_price": price,
            }

        notional = quantity * price
        is_crypto = self._is_crypto(symbol)

        commission = max(self.commission_per_trade, self.min_commission)
        spread_cost = notional * (self.spread_pct_crypto if is_crypto else self.spread_pct_equity)
        slippage_cost = notional * self.slippage_pct
        sec_fee = (notional / 1_000_000) * self.sec_fee_per_million if action == "SELL" else 0.0

        total = commission + spread_cost + slippage_cost + sec_fee

        # Effective price accounts for all friction costs
        if action == "BUY":
            effective_price = price + (total / quantity)
        else:
            effective_price = price - (total / quantity)

        return {
            "commission": round(commission, 4),
            "spread": round(spread_cost, 4),
            "slippage": round(slippage_cost, 4),
            "sec_fee": round(sec_fee, 4),
            "total": round(total, 4),
            "effective_price": round(effective_price, 4),
        }

    @staticmethod
    def _is_crypto(symbol: str) -> bool:
        crypto_markers = ["BTC", "ETH", "SOL", "DOGE", "ADA", "XRP", "-USD"]
        return any(m in symbol.upper() for m in crypto_markers)

    @classmethod
    def from_config(cls, config: dict) -> FeeModel:
        """Create FeeModel from config.yaml fees section."""
        fees_cfg = config.get("fees", {})
        return cls(
            commission_per_trade=fees_cfg.get("commission_per_trade", 4.95),
            spread_pct_equity=fees_cfg.get("spread_pct_equity", 0.0002),
            spread_pct_crypto=fees_cfg.get("spread_pct_crypto", 0.003),
            sec_fee_per_million=fees_cfg.get("sec_fee_per_million", 8.00),
            slippage_pct=fees_cfg.get("slippage_pct", 0.001),
            min_commission=fees_cfg.get("min_commission", 1.00),
        )
