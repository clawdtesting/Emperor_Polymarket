"""OHLCV handling and technical indicators (pure functions, no I/O)."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class Candle:
    ts: float
    open: float
    high: float
    low: float
    close: float
    volume: float


def from_ccxt(rows: Sequence[Sequence[float]]) -> list[Candle]:
    return [Candle(r[0] / 1000.0, r[1], r[2], r[3], r[4], r[5]) for r in rows]


def load_csv(path: str) -> list[Candle]:
    out: list[Candle] = []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"OHLCV file not found: {path}")
    with open(p, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            out.append(Candle(
                ts=float(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0) or 0),
            ))
    return out


def ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def true_ranges(candles: Sequence[Candle]) -> list[float]:
    trs: list[float] = []
    prev_close = candles[0].close if candles else 0.0
    for c in candles:
        tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        trs.append(tr)
        prev_close = c.close
    return trs


def atr(candles: Sequence[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    trs = true_ranges(candles)
    window = trs[-period:] if len(trs) >= period else trs
    return sum(window) / len(window)


def adx(candles: Sequence[Candle], period: int = 14) -> float:
    """Wilder's ADX. Returns 0 when not enough data."""
    n = len(candles)
    if n < period * 2:
        return 0.0
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    for i in range(1, n):
        up = candles[i].high - candles[i - 1].high
        down = candles[i - 1].low - candles[i].low
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        tr = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i - 1].close),
            abs(candles[i].low - candles[i - 1].close),
        )
        trs.append(tr or 1e-9)

    def smooth(vals: list[float]) -> list[float]:
        out = [sum(vals[:period])]
        for v in vals[period:]:
            out.append(out[-1] - out[-1] / period + v)
        return out

    tr_s = smooth(trs)
    pdm_s = smooth(plus_dm)
    mdm_s = smooth(minus_dm)
    dx: list[float] = []
    for tr_v, pdm_v, mdm_v in zip(tr_s, pdm_s, mdm_s):
        pdi = 100 * pdm_v / tr_v
        mdi = 100 * mdm_v / tr_v
        denom = (pdi + mdi) or 1e-9
        dx.append(100 * abs(pdi - mdi) / denom)
    if len(dx) < period:
        return sum(dx) / len(dx) if dx else 0.0
    return sum(dx[-period:]) / period


def recent_high_low(candles: Sequence[Candle], lookback: int) -> tuple[float, float]:
    window = candles[-lookback:] if len(candles) >= lookback else candles
    highs = [c.high for c in window]
    lows = [c.low for c in window]
    return (max(highs) if highs else 0.0, min(lows) if lows else 0.0)


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(q * (len(s) - 1))
    return s[idx]


def volume_spike(candles: Sequence[Candle], multiplier: float, lookback: int = 20) -> bool:
    if len(candles) < lookback + 1:
        return False
    window = candles[-lookback - 1:-1]
    avg = sum(c.volume for c in window) / len(window)
    if avg <= 0:
        return False
    return candles[-1].volume > avg * multiplier
