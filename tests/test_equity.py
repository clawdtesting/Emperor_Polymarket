import time

from src.data.market_data import MarketSnapshot
from src.execution.paper_broker import PaperBroker
from src.storage.models import OrderSide
from src.strategy.risk import RiskManager


def _snap(price: float) -> MarketSnapshot:
    now = time.time()
    return MarketSnapshot("SOL/USDC:USDC", price, price * 0.9995,
                          price * 1.0005, now, now)


def test_total_balances_unchanged_after_placing_buys(cfg):
    broker = PaperBroker(cfg, 2.0, 200.0, fee_rate=0.0)
    tot0 = broker.total_balances()
    for price in (80.0, 81.45, 82.91):
        broker.place_limit(OrderSide.BUY, 8.0 / price, price)
    free_sol, free_usdt = broker.balances()
    tot_sol, tot_usdt = broker.total_balances()
    # Free USDT drops (reserved into orders) ...
    assert free_usdt < 200.0
    # ... but total equity is conserved.
    assert abs(tot_usdt - 200.0) < 1e-9
    assert abs(tot_sol - 2.0) < 1e-9
    assert tot0 == (2.0, 200.0)


def test_placing_buys_does_not_trip_daily_loss(cfg):
    """Reserving cash into resting buy orders must not look like a loss."""
    broker = PaperBroker(cfg, 2.0, 200.0, fee_rate=0.0)
    rm = RiskManager(cfg)
    price = 84.0
    snap = _snap(price)

    # First cycle: equity anchor established from total balances.
    tot_sol, tot_usdt = broker.total_balances()
    rm.check_global(tot_usdt + tot_sol * price, snap)
    assert not rm.state.halted

    # Place grid buys, then re-evaluate using TOTAL equity.
    for p in (80.0, 81.45, 82.91):
        broker.place_limit(OrderSide.BUY, 8.0 / p, p)
    tot_sol, tot_usdt = broker.total_balances()
    rm.check_global(tot_usdt + tot_sol * price, snap)
    assert not rm.state.halted, "equity should be conserved; no daily-loss halt"


def test_free_balances_would_have_tripped(cfg):
    """Guard: using FREE balances reproduces the original false halt."""
    broker = PaperBroker(cfg, 2.0, 200.0, fee_rate=0.0)
    rm = RiskManager(cfg)
    price = 84.0
    snap = _snap(price)
    free_sol, free_usdt = broker.balances()
    rm.check_global(free_usdt + free_sol * price, snap)  # anchor 368
    for p in (80.0, 81.45, 82.91):
        broker.place_limit(OrderSide.BUY, 8.0 / p, p)
    free_sol, free_usdt = broker.balances()
    rm.check_global(free_usdt + free_sol * price, snap)  # ~344 -> >3% loss
    assert rm.state.halted  # demonstrates the bug the fix avoids
