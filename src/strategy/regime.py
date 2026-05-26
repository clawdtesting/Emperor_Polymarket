"""Market regime classification.

Returns one of the Regime enum values plus a human-readable detail string.
The classifier is deterministic and pure given its inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..config import Config
from ..data.candles import (Candle, adx, atr, ema, recent_high_low, volume_spike)
from ..data.market_data import MarketSnapshot
from ..storage.models import Regime


@dataclass
class RegimeResult:
    regime: Regime
    detail: str
    adx: float
    atr_pct: float
    ema50: float
    range_high: float
    range_low: float
    trade_allowed: bool


def classify(cfg: Config, candles: Sequence[Candle],
             snapshot: MarketSnapshot) -> RegimeResult:
    r = cfg.regime
    price = snapshot.mid

    # Liquidity / data integrity checks first.
    if not snapshot.is_valid() or snapshot.is_stale(
            float(cfg.risk.get("api_stale_data_timeout_sec", 60))):
        return _result(Regime.LOW_LIQUIDITY, "stale or invalid market data",
                       0, 0, 0, 0, 0, False)
    if snapshot.spread_percent > float(cfg.risk.get("max_spread_percent", 0.5)):
        return _result(Regime.LOW_LIQUIDITY,
                       f"spread {snapshot.spread_percent:.3f}% too wide",
                       0, 0, 0, 0, 0, False)
    if len(candles) < int(r.get("ema_mid", 50)):
        return _result(Regime.LOW_LIQUIDITY, "insufficient candle history",
                       0, 0, 0, 0, 0, False)

    closes = [c.close for c in candles]
    ema50 = ema(closes, int(r["ema_mid"]))[-1]
    a = atr(candles, int(r["atr_period"]))
    atr_pct = (a / price * 100.0) if price > 0 else 0.0
    adx_val = adx(candles, int(r["adx_period"]))
    high, low = recent_high_low(candles, int(r.get("candle_lookback", 300)))
    breakout_pct = float(r["breakout_confirm_percent"]) / 100.0
    dist_ema = abs(price - ema50) / ema50 * 100.0 if ema50 > 0 else 999.0

    # High volatility dominates.
    if atr_pct > float(r["atr_high_vol_pct"]) or volume_spike(
            candles, float(r["volume_spike_multiplier"])):
        return _result(Regime.HIGH_VOLATILITY,
                       f"ATR {atr_pct:.2f}% / volume spike", adx_val, atr_pct,
                       ema50, high, low, False)

    # Breakouts beyond the recent range with trend strength.
    if price > high * (1 + breakout_pct) and adx_val >= float(r["adx_range_max"]):
        return _result(Regime.UPTREND_BREAKOUT,
                       f"price>{high:.2f} ADX {adx_val:.1f}", adx_val, atr_pct,
                       ema50, high, low, False)
    if price < low * (1 - breakout_pct) and adx_val >= float(r["adx_range_max"]):
        return _result(Regime.DOWNTREND_BREAKDOWN,
                       f"price<{low:.2f} ADX {adx_val:.1f}", adx_val, atr_pct,
                       ema50, high, low, False)

    # Ranging conditions: low trend, price near EMA50.
    if adx_val < float(r["adx_range_max"]) and dist_ema <= float(
            r["max_price_dist_ema50_pct"]):
        return _result(Regime.RANGE,
                       f"ADX {adx_val:.1f} distEMA50 {dist_ema:.2f}%",
                       adx_val, atr_pct, ema50, high, low, True)

    # Trending but not a confirmed breakout: be cautious, don't grid.
    return _result(Regime.UPTREND_BREAKOUT if price > ema50
                   else Regime.DOWNTREND_BREAKDOWN,
                   f"trending ADX {adx_val:.1f} distEMA50 {dist_ema:.2f}%",
                   adx_val, atr_pct, ema50, high, low, False)


def _result(regime: Regime, detail: str, adx_v: float, atr_pct: float,
            ema50: float, high: float, low: float,
            trade_allowed: bool) -> RegimeResult:
    return RegimeResult(regime=regime, detail=detail, adx=adx_v, atr_pct=atr_pct,
                        ema50=ema50, range_high=high, range_low=low,
                        trade_allowed=trade_allowed)
