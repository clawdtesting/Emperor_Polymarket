from src.strategy.risk import RiskManager
from src.storage.models import OrderSide


def test_sell_into_core_is_blocked(cfg):
    rm = RiskManager(cfg)
    # core minimum = 2.0 * 0.5 = 1.0; balance 1.05, selling 0.1 would breach
    ok, reason = rm.allow_order(OrderSide.SELL, 0.1, 90.0, sol_balance=1.05,
                                usdt_balance=100, grid_sol_inventory=0.5,
                                deployed_usdt=0, open_order_count=0)
    assert not ok
    assert "core" in reason


def test_buy_blocked_when_breaching_usdt_reserve(cfg):
    rm = RiskManager(cfg)
    # min_free_usdt_reserve = 20; balance 25, buy notional 8 -> 17 left -> blocked
    ok, reason = rm.allow_order(OrderSide.BUY, 0.1, 90.0, sol_balance=2.0,
                                usdt_balance=25.0, grid_sol_inventory=0.0,
                                deployed_usdt=0, open_order_count=0)
    assert not ok
    assert "reserve" in reason


def test_max_open_orders_enforced(cfg):
    rm = RiskManager(cfg)
    ok, reason = rm.allow_order(OrderSide.BUY, 0.05, 85.0, sol_balance=2.0,
                                usdt_balance=200.0, grid_sol_inventory=0.0,
                                deployed_usdt=0, open_order_count=12)
    assert not ok
    assert "open orders" in reason


def test_drawdown_circuit_breaker(cfg):
    rm = RiskManager(cfg)
    from src.data.market_data import MarketSnapshot
    import time
    snap = MarketSnapshot("SOL/USDC:USDC", 90, 89.9, 90.1, time.time(), time.time())
    rm.check_global(380.0, snap)        # establishes peak
    reason = rm.check_global(330.0, snap)  # ~13% drawdown > 8%
    assert rm.state.halted
    assert "drawdown" in (reason or "")


def test_valid_buy_allowed(cfg):
    rm = RiskManager(cfg)
    ok, reason = rm.allow_order(OrderSide.BUY, 0.05, 85.0, sol_balance=2.0,
                                usdt_balance=200.0, grid_sol_inventory=0.0,
                                deployed_usdt=0, open_order_count=0)
    assert ok, reason
