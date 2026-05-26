"""Grid construction and order-intent generation.

The grid is a set of price levels. Levels below the reference price are BUY
intents; levels above are SELL intents. Sizing respects the configured mode
and the minimum notional.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from ..config import Config
from ..data.candles import Candle, atr, percentile
from ..storage.models import GridLevel, OrderSide


@dataclass
class GridSpec:
    lower: float
    upper: float
    levels: list[GridLevel]


def build_levels(cfg: Config, ref_price: float,
                 candles: Optional[Sequence[Candle]] = None) -> GridSpec:
    g = cfg.grid
    lower = float(g["lower_price"])
    upper = float(g["upper_price"])
    count = int(g["count"])
    mode = g["spacing_mode"]

    if g.get("dynamic") and candles:
        lower, upper = _dynamic_range(cfg, candles)

    prices = _spaced_prices(lower, upper, count, mode, cfg, candles)
    levels: list[GridLevel] = []
    for i, p in enumerate(prices):
        side = OrderSide.BUY if p < ref_price else OrderSide.SELL
        levels.append(GridLevel(index=i, price=round(p, 4), side=side))
    return GridSpec(lower=lower, upper=upper, levels=levels)


def _dynamic_range(cfg: Config, candles: Sequence[Candle]) -> tuple[float, float]:
    g = cfg.grid
    lookback = int(g.get("range_lookback_candles", 200))
    window = candles[-lookback:] if len(candles) >= lookback else candles
    lows = [c.low for c in window]
    highs = [c.high for c in window]
    q = float(g.get("range_recalc_percentile", 0.05))
    lower = percentile(lows, q)
    upper = percentile(highs, 1 - q)
    if lower >= upper:  # fallback to static
        return float(g["lower_price"]), float(g["upper_price"])
    return lower, upper


def _spaced_prices(lower: float, upper: float, count: int, mode: str,
                   cfg: Config, candles: Optional[Sequence[Candle]]) -> list[float]:
    if mode == "arithmetic":
        step = (upper - lower) / (count - 1)
        return [lower + step * i for i in range(count)]
    if mode == "geometric":
        ratio = (upper / lower) ** (1 / (count - 1))
        return [lower * (ratio ** i) for i in range(count)]
    if mode == "atr":
        a = atr(candles, int(cfg.regime.get("atr_period", 14))) if candles else 0.0
        if a <= 0:
            step = (upper - lower) / (count - 1)
            return [lower + step * i for i in range(count)]
        mult = float(cfg.grid.get("atr_spacing_multiplier", 0.75))
        step = a * mult
        prices: list[float] = []
        p = lower
        while p <= upper and len(prices) < count:
            prices.append(p)
            p += step
        if not prices:
            prices = [lower, upper]
        return prices
    raise ValueError(f"Unknown spacing mode: {mode}")


def order_amount_sol(cfg: Config, price: float, total_portfolio_usdt: float) -> float:
    """SOL amount per grid order, honoring the size mode and min notional."""
    o = cfg.order
    mode = o["size_mode"]
    if mode == "fixed_usdt":
        notional = float(o["fixed_usdt"])
    elif mode == "fixed_sol":
        notional = float(o["fixed_sol"]) * price
    elif mode == "portfolio_percent":
        notional = total_portfolio_usdt * float(o["portfolio_percent"])
    else:
        raise ValueError(f"Unknown size mode: {mode}")

    notional = max(notional, float(o["min_order_size_usdt"]))
    return notional / price if price > 0 else 0.0
