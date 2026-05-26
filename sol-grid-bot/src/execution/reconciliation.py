"""Startup reconciliation between local DB state and the exchange.

Live trading must not begin until local and exchange order state are
consistent. In paper mode there is no exchange to reconcile against.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..exchange import Exchange
from ..storage.db import Database
from ..storage.models import OrderStatus

log = logging.getLogger("solgrid.reconcile")


@dataclass
class ReconcileReport:
    local_open: int
    exchange_open: int
    matched: int
    only_local: list[str] = field(default_factory=list)
    only_exchange: list[str] = field(default_factory=list)
    balance_ok: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return not self.only_local and not self.only_exchange and self.balance_ok


def reconcile_live(db: Database, exchange: Exchange,
                   expected_sol: float, expected_usdt: float,
                   tolerance: float = 0.05) -> ReconcileReport:
    local = db.open_orders()
    local_ids = {o.exchange_id for o in local if o.exchange_id}
    ex_orders = exchange.fetch_open_orders()
    ex_ids = {str(o.get("id")) for o in ex_orders}

    only_local = [oid for oid in local_ids if oid not in ex_ids]
    only_exchange = [oid for oid in ex_ids if oid not in local_ids]
    matched = len(local_ids & ex_ids)

    # Mark local orders the exchange no longer knows about as no longer open;
    # they were filled or cancelled while we were offline.
    for order in local:
        if order.exchange_id and order.exchange_id in only_local:
            order.status = OrderStatus.CANCELLED
            order.updated_ts = order.updated_ts
            db.upsert_order(order)
            db.audit("WARNING", "reconcile",
                     f"local order {order.client_id} not on exchange; marked closed")

    sol, usdt = exchange.fetch_balances()
    balance_ok = True
    notes: list[str] = []
    if expected_sol > 0 and abs(sol - expected_sol) / expected_sol > tolerance:
        balance_ok = False
        notes.append(f"SOL balance {sol} differs from expected {expected_sol}")
    if expected_usdt > 0 and abs(usdt - expected_usdt) / expected_usdt > tolerance:
        notes.append(f"USDT balance {usdt} differs from expected {expected_usdt}")

    report = ReconcileReport(
        local_open=len(local), exchange_open=len(ex_orders), matched=matched,
        only_local=only_local, only_exchange=only_exchange,
        balance_ok=balance_ok, notes=notes,
    )
    if only_exchange:
        report.notes.append(
            f"{len(only_exchange)} exchange orders unknown to bot; "
            "cancel-all recommended before live trading")
    return report
