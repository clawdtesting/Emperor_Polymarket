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
                 candles: Optional[Sequence[Candle]] = None,
                 range_override: Optional[tuple[float, float]] = None) -> GridSpec:
    g = cfg.grid
    count = int(g["count"])
    mode = g["spacing_mode"]

    if range_override is not None:
        lower, upper = range_override
    elif g.get("dynamic") and candles:
        lower, upper = compute_range(cfg, candles, ref_price)
    else:
        lower, upper = float(g["lower_price"]), float(g["upper_price"])

    prices = _spaced_prices(lower, upper, count, mode, cfg, candles)
    levels: list[GridLevel] = []
    for i, p in enumerate(prices):
        side = OrderSide.BUY if p < ref_price else OrderSide.SELL
        levels.append(GridLevel(index=i, price=round(p, 4), side=side))
    return GridSpec(lower=lower, upper=upper, levels=levels)


def compute_range(cfg: Config, candles: Sequence[Candle],
                  price: float) -> tuple[float, float]:
    """Detect the recent trading range and center it on the current price.

    Uses percentile bands of recent highs/lows (robust to wicks), then ensures
    the band actually contains ``price`` and is at least a minimum width so the
    grid sits where the market is currently trading."""
    g = cfg.grid
    lookback = int(g.get("range_lookback_candles", 120))
    window = candles[-lookback:] if len(candles) >= lookback else candles
    if not window:
        return float(g["lower_price"]), float(g["upper_price"])

    q = float(g.get("range_recalc_percentile", 0.1))
    lower = percentile([c.low for c in window], q)
    upper = percentile([c.high for c in window], 1 - q)
    if lower >= upper:
        lower, upper = price * 0.97, price * 1.03

    # Always include the current price (plus a small margin) inside the grid.
    margin = float(g.get("range_price_margin", 0.005))
    lower = min(lower, price * (1 - margin))
    upper = max(upper, price * (1 + margin))

    # Enforce a minimum total width so the grid isn't tighter than the spread.
    min_width_pct = float(g.get("range_min_width_pct", 3.0)) / 100.0
    if (upper - lower) / price < min_width_pct:
        half = price * min_width_pct / 2.0
        lower, upper = price - half, price + half
    return round(lower, 4), round(upper, 4)


def _dynamic_range(cfg: Config, candles: Sequence[Candle]) -> tuple[float, float]:
    # Backwards-compatible wrapper; prefers the current last close as price.
    price = candles[-1].close if candles else 0.0
    return compute_range(cfg, candles, price)


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
