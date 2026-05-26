import time

from src.data.candles import Candle
from src.data.market_data import MarketSnapshot
from src.storage.models import Regime
from src.strategy.regime import classify


def _snap(price: float, spread_pct: float = 0.05) -> MarketSnapshot:
    half = price * spread_pct / 200.0
    now = time.time()
    return MarketSnapshot("SOL/USDC:USDC", price, price - half, price + half, now, now)


def _flat_candles(n: int, price: float) -> list[Candle]:
    out = []
    for i in range(n):
        wob = 0.05 * (1 if i % 2 else -1)
        out.append(Candle(ts=i, open=price, high=price + 0.1,
                          low=price - 0.1, close=price + wob, volume=100.0))
    return out


def _trending_up(n: int, start: float) -> list[Candle]:
    out = []
    p = start
    for i in range(n):
        p += 0.8
        out.append(Candle(ts=i, open=p - 0.4, high=p + 0.2, low=p - 0.6,
                          close=p, volume=100.0))
    return out


def test_range_allows_trading(cfg):
    candles = _flat_candles(120, 88.0)
    res = classify(cfg, candles, _snap(88.0))
    assert res.regime == Regime.RANGE
    assert res.trade_allowed


def test_wide_spread_is_low_liquidity(cfg):
    candles = _flat_candles(120, 88.0)
    res = classify(cfg, candles, _snap(88.0, spread_pct=2.0))
    assert res.regime == Regime.LOW_LIQUIDITY
    assert not res.trade_allowed


def test_stale_data_is_low_liquidity(cfg):
    candles = _flat_candles(120, 88.0)
    snap = _snap(88.0)
    snap.fetched_ts = time.time() - 9999
    res = classify(cfg, candles, snap)
    assert res.regime == Regime.LOW_LIQUIDITY


def test_strong_uptrend_not_tradeable(cfg):
    candles = _trending_up(120, 70.0)
    last = candles[-1].close
    res = classify(cfg, candles, _snap(last))
    assert res.regime in (Regime.UPTREND_BREAKOUT, Regime.HIGH_VOLATILITY)
    assert not res.trade_allowed
