"""Coordinates grid intents, broker orders, the database, and realized PnL.

Realized PnL and SOL accumulation are tracked with average-cost accounting:
every BUY raises the grid cost basis; every SELL realizes PnL against it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..config import Config
from ..storage.db import Database
from ..storage.models import Order, OrderSide, OrderStatus

log = logging.getLogger("solgrid.orders")


@dataclass
class Inventory:
    """Grid-only inventory (excludes the locked core SOL)."""
    grid_sol: float = 0.0       # SOL currently held by the grid (filled buys)
    avg_cost: float = 0.0       # average USDT cost basis of grid_sol
    deployed_usdt: float = 0.0  # USDT tied up in open buy orders + held grid SOL


class OrderManager:
    def __init__(self, cfg: Config, db: Database, broker) -> None:
        self.cfg = cfg
        self.db = db
        self.broker = broker
        self.inv = Inventory()
        self.tracked: dict[str, Order] = {}

    def load_state(self) -> None:
        for order in self.db.open_orders():
            self.tracked[order.client_id] = order
        self.inv.grid_sol = float(self.db.get_meta("grid_sol", 0.0))
        self.inv.avg_cost = float(self.db.get_meta("grid_avg_cost", 0.0))

    def _persist_inventory(self) -> None:
        self.db.set_meta("grid_sol", self.inv.grid_sol)
        self.db.set_meta("grid_avg_cost", self.inv.avg_cost)

    @property
    def open_orders(self) -> list[Order]:
        return [o for o in self.tracked.values() if o.status == OrderStatus.OPEN]

    @property
    def deployed_usdt(self) -> float:
        open_buys = sum(o.amount * o.price for o in self.open_orders
                        if o.side == OrderSide.BUY)
        return open_buys + self.inv.grid_sol * self.inv.avg_cost

    def place(self, side: OrderSide, amount: float, price: float,
              grid_level: Optional[int] = None) -> Order:
        order = self.broker.place_limit(side, amount, price, grid_level)
        self.tracked[order.client_id] = order
        self.db.upsert_order(order)
        self.db.audit("INFO", "order",
                      f"placed {side.value} {amount:.4f}@{price:.4f}")
        return order

    def cancel(self, order: Order) -> None:
        self.broker.cancel(order)
        self.db.upsert_order(order)
        self.tracked.pop(order.client_id, None)
        self.db.audit("INFO", "order", f"cancelled {order.client_id}")

    def cancel_all(self) -> int:
        count = 0
        for order in list(self.open_orders):
            self.cancel(order)
            count += 1
        return count

    def register_fill(self, order: Order) -> float:
        """Update inventory + realized PnL for a filled order. Returns realized."""
        realized = 0.0
        if order.side == OrderSide.BUY:
            total_cost = self.inv.grid_sol * self.inv.avg_cost + order.amount * order.price
            self.inv.grid_sol += order.amount
            self.inv.avg_cost = total_cost / self.inv.grid_sol if self.inv.grid_sol else 0.0
        else:  # SELL
            realized = (order.price - self.inv.avg_cost) * order.amount - order.fee
            self.inv.grid_sol = max(0.0, self.inv.grid_sol - order.amount)
            if self.inv.grid_sol == 0:
                self.inv.avg_cost = 0.0
        order.status = OrderStatus.FILLED
        self.db.upsert_order(order)
        self.db.record_fill(order.client_id, order.side, order.price,
                            order.amount, order.fee, realized)
        self.tracked.pop(order.client_id, None)
        self._persist_inventory()
        return realized

    def has_order_near(self, price: float, side: OrderSide, tol: float = 1e-6) -> bool:
        return any(o.side == side and abs(o.price - price) <= tol
                   for o in self.open_orders)
