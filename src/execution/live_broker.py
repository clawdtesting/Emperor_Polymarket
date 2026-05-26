"""Live broker. Places real spot orders via the exchange wrapper.

This object is only constructed when LIVE_TRADING=true and run mode is live.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from ..exchange import Exchange
from ..storage.models import Order, OrderSide, OrderStatus


class LiveBroker:
    def __init__(self, exchange: Exchange) -> None:
        self.ex = exchange

    @property
    def trading_enabled(self) -> bool:
        return True

    def place_limit(self, side: OrderSide, amount: float, price: float,
                    grid_level: Optional[int] = None) -> Order:
        cid = f"live-{uuid.uuid4().hex[:12]}"
        resp = self.ex.create_limit_order(side.value, amount, price, client_id=cid)
        return Order(
            client_id=cid,
            side=side,
            price=price,
            amount=amount,
            status=OrderStatus.OPEN,
            exchange_id=str(resp.get("id") or cid),
            grid_level=grid_level,
            created_ts=time.time(),
            updated_ts=time.time(),
        )

    def cancel(self, order: Order) -> None:
        if order.exchange_id:
            self.ex.cancel_order(order.exchange_id)
        order.status = OrderStatus.CANCELLED
        order.updated_ts = time.time()

    def poll_fills(self, tracked: list[Order]) -> list[Order]:
        """Check tracked open orders against the exchange; return newly filled."""
        filled: list[Order] = []
        open_ids = {str(o.get("id")) for o in self.ex.fetch_open_orders()}
        for order in tracked:
            if order.status != OrderStatus.OPEN or not order.exchange_id:
                continue
            if order.exchange_id in open_ids:
                continue
            # No longer open: confirm via fetch_order.
            try:
                info = self.ex.fetch_order(order.exchange_id)
            except Exception:
                continue
            status = (info.get("status") or "").lower()
            if status in ("closed", "filled"):
                order.status = OrderStatus.FILLED
                order.filled_amount = float(info.get("filled") or order.amount)
                fee_info = info.get("fee") or {}
                order.fee = float(fee_info.get("cost") or 0.0)
                order.updated_ts = time.time()
                filled.append(order)
            elif status in ("canceled", "cancelled", "rejected"):
                order.status = OrderStatus.CANCELLED
                order.updated_ts = time.time()
        return filled
