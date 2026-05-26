from src.strategy import grid
from src.storage.models import OrderSide


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
