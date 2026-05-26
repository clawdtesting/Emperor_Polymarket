from src.strategy import accumulation
from src.storage.models import Regime


def test_sell_reduced_in_uptrend(cfg):
    adj = accumulation.adjust_sell_amount(cfg, 1.0, Regime.UPTREND_BREAKOUT)
    assert abs(adj.amount_sol - 0.5) < 1e-9


def test_sell_full_in_range(cfg):
    adj = accumulation.adjust_sell_amount(cfg, 1.0, Regime.RANGE)
    assert abs(adj.amount_sol - 1.0) < 1e-9


def test_partial_profit_conversion(cfg):
    assert abs(accumulation.profit_to_convert(cfg, 10.0) - 5.0) < 1e-9


def test_full_profit_conversion(cfg):
    cfg.raw["accumulation"]["profit_conversion_mode"] = "full_to_SOL"
    assert abs(accumulation.profit_to_convert(cfg, 10.0) - 10.0) < 1e-9


def test_no_conversion_when_loss(cfg):
    assert accumulation.profit_to_convert(cfg, -5.0) == 0.0


def test_no_conversion_when_disabled(cfg):
    cfg.raw["accumulation"]["profit_conversion_mode"] = "none"
    assert accumulation.profit_to_convert(cfg, 10.0) == 0.0
