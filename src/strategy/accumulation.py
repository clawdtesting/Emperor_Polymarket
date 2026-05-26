"""SOL accumulation bias and realized-profit-to-SOL conversion logic."""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Config
from ..storage.models import Regime


@dataclass
class SellAdjustment:
    amount_sol: float
    reason: str


def adjust_sell_amount(cfg: Config, base_amount: float, regime: Regime) -> SellAdjustment:
    """Reduce sell size in bullish regimes to preserve SOL exposure."""
    acc = cfg.accumulation
    if not acc.get("accumulation_mode", True):
        return SellAdjustment(base_amount, "accumulation off")
    if acc.get("reduce_sells_in_uptrend", True) and regime in (
            Regime.UPTREND_BREAKOUT,):
        factor = float(acc.get("sell_reduction_factor", 0.5))
        return SellAdjustment(base_amount * factor,
                              f"reduced sell x{factor} (bullish)")
    return SellAdjustment(base_amount, "full sell")


def profit_to_convert(cfg: Config, realized_usdt: float) -> float:
    """How much realized USDT profit to convert into SOL on this rebalance."""
    acc = cfg.accumulation
    mode = acc.get("profit_conversion_mode", "none")
    if not acc.get("accumulation_mode", True) or mode == "none":
        return 0.0
    if realized_usdt <= 0:
        return 0.0
    if mode == "full_to_SOL":
        return realized_usdt
    if mode == "partial_to_SOL":
        pct = float(acc.get("profit_conversion_percent", 50)) / 100.0
        return realized_usdt * pct
    return 0.0
