import time

from src.execution.order_manager import OrderManager
from src.execution.paper_broker import PaperBroker
from src.execution.reconciliation import reconcile_live
from src.storage.db import Database
from src.storage.models import Order, OrderSide, OrderStatus


class _StubExchange:
    def __init__(self, open_ids, sol, usdt):
        self._open_ids = open_ids
        self._sol = sol
        self._usdt = usdt

    def fetch_open_orders(self):
        return [{"id": i} for i in self._open_ids]

    def fetch_balances(self):
        return self._sol, self._usdt


def _db_with_orders(*exchange_ids):
    db = Database(":memory:")
    for i, eid in enumerate(exchange_ids):
        db.upsert_order(Order(client_id=f"c{i}", side=OrderSide.BUY, price=85.0,
                              amount=0.1, status=OrderStatus.OPEN, exchange_id=eid,
                              created_ts=time.time(), updated_ts=time.time()))
    return db


def test_consistent_state(cfg):
    db = _db_with_orders("a", "b")
    ex = _StubExchange(["a", "b"], 2.0, 200.0)
    report = reconcile_live(db, ex, 2.0, 200.0)
    assert report.consistent
    assert report.matched == 2


def test_only_exchange_order_flagged(cfg):
    db = _db_with_orders("a")
    ex = _StubExchange(["a", "ghost"], 2.0, 200.0)
    report = reconcile_live(db, ex, 2.0, 200.0)
    assert "ghost" in report.only_exchange
    assert not report.consistent


def test_missing_local_order_marked_closed(cfg):
    db = _db_with_orders("a", "b")
    ex = _StubExchange(["a"], 2.0, 200.0)   # 'b' filled while offline
    report = reconcile_live(db, ex, 2.0, 200.0)
    assert "b" in report.only_local
    remaining = [o.exchange_id for o in db.open_orders()]
    assert "b" not in remaining


def test_balance_divergence_blocks(cfg):
    db = _db_with_orders("a")
    ex = _StubExchange(["a"], 0.5, 200.0)   # SOL far below expected 2.0
    report = reconcile_live(db, ex, 2.0, 200.0)
    assert not report.balance_ok


def test_order_manager_fill_accounting(cfg):
    db = Database(":memory:")
    broker = PaperBroker(cfg, 2.0, 200.0, fee_rate=0.0)
    om = OrderManager(cfg, db, broker)
    buy = om.place(OrderSide.BUY, 0.1, 80.0)
    broker.poll_fills(80.0, 80.0, 80.0)
    om.register_fill(buy)
    assert abs(om.inv.grid_sol - 0.1) < 1e-9
    assert abs(om.inv.avg_cost - 80.0) < 1e-9
    sell = om.place(OrderSide.SELL, 0.1, 90.0)
    broker.poll_fills(90.0, 90.0, 90.0)
    realized = om.register_fill(sell)
    assert abs(realized - 1.0) < 1e-9  # (90-80)*0.1
