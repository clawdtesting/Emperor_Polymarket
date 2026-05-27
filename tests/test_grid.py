from src.data.candles import Candle
from src.strategy import grid
from src.storage.models import OrderSide


def _candles_around(price: float, spread: float, n: int = 150):
    out = []
    for i in range(n):
        wob = spread * (0.5 if i % 2 else -0.5)
        mid = price + wob
        out.append(Candle(ts=i, open=mid, high=mid + spread * 0.2,
                          low=mid - spread * 0.2, close=mid, volume=100.0))
    return out


def test_compute_range_tracks_current_price(cfg):
    candles = _candles_around(84.0, 2.0)
    lower, upper = grid.compute_range(cfg, candles, price=84.0)
    assert lower < 84.0 < upper
    assert lower > 80.0          # must not anchor to the stale 80 config floor
    assert upper < 96.0


def test_compute_range_includes_price_when_outside_band(cfg):
    candles = _candles_around(84.0, 1.0)
    lower, upper = grid.compute_range(cfg, candles, price=86.0)
    assert lower < 86.0 < upper


def test_compute_range_enforces_min_width(cfg):
    cfg.raw["grid"]["range_min_width_pct"] = 4.0
    candles = _candles_around(84.0, 0.05)   # almost flat
    lower, upper = grid.compute_range(cfg, candles, price=84.0)
    assert (upper - lower) / 84.0 >= 0.04 - 1e-9


def test_dynamic_levels_sit_around_price_not_static_floor(cfg):
    cfg.raw["grid"]["dynamic"] = True
    candles = _candles_around(84.0, 2.0)
    spec = grid.build_levels(cfg, ref_price=84.0, candles=candles)
    assert all(l.price > 80.5 for l in spec.levels)
    buys = [l for l in spec.levels if l.side == OrderSide.BUY]
    sells = [l for l in spec.levels if l.side == OrderSide.SELL]
    assert buys and sells
    assert max(l.price for l in buys) < 84.0


def test_range_override_used_verbatim(cfg):
    spec = grid.build_levels(cfg, ref_price=84.0, range_override=(82.0, 86.0))
    assert spec.lower == 82.0 and spec.upper == 86.0


def test_arithmetic_levels_count_and_bounds(cfg):
    spec = grid.build_levels(cfg, ref_price=88.0)
    assert len(spec.levels) == cfg.grid["count"]
    assert spec.levels[0].price == cfg.grid["lower_price"]
    assert spec.levels[-1].price == cfg.grid["upper_price"]


def test_levels_split_buy_sell_around_reference(cfg):
    spec = grid.build_levels(cfg, ref_price=88.0)
    buys = [l for l in spec.levels if l.side == OrderSide.BUY]
    sells = [l for l in spec.levels if l.side == OrderSide.SELL]
    assert all(l.price < 88.0 for l in buys)
    assert all(l.price >= 88.0 for l in sells)
    assert buys and sells


def test_geometric_spacing_increases(cfg):
    cfg.raw["grid"]["spacing_mode"] = "geometric"
    spec = grid.build_levels(cfg, ref_price=88.0)
    diffs = [spec.levels[i + 1].price - spec.levels[i].price
             for i in range(len(spec.levels) - 1)]
    assert all(diffs[i] <= diffs[i + 1] + 1e-9 for i in range(len(diffs) - 1))


def test_order_amount_respects_min_notional(cfg):
    cfg.raw["order"]["fixed_usdt"] = 1.0  # below the 5.0 minimum
    amt = grid.order_amount_sol(cfg, price=80.0, total_portfolio_usdt=200.0)
    assert amt * 80.0 >= cfg.order["min_order_size_usdt"] - 1e-9


def test_fixed_sol_sizing(cfg):
    cfg.raw["order"]["size_mode"] = "fixed_sol"
    cfg.raw["order"]["fixed_sol"] = 0.2
    amt = grid.order_amount_sol(cfg, price=90.0, total_portfolio_usdt=200.0)
    assert abs(amt - 0.2) < 1e-9
