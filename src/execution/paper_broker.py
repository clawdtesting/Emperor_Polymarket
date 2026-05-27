"""Simulated broker for paper trading and backtests.

Fills are deterministic: a BUY fills when the market trades at or below its
limit price; a SELL fills at or above. Fees are applied from config.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from ..config import Config
from ..storage.models import Order, OrderSide, OrderStatus


class PaperBroker:
    def __init__(self, cfg: Config, sol: float, usdt: float,
                 fee_rate: float = 0.00035) -> None:
        self.cfg = cfg
        self.sol = sol
        self.usdt = usdt
        self.fee_rate = fee_rate
        self.open: dict[str, Order] = {}

    @property
    def trading_enabled(self) -> bool:
        return True

    def place_limit(self, side: OrderSide, amount: float, price: float,
                    grid_level: Optional[int] = None) -> Order:
        cid = f"paper-{uuid.uuid4().hex[:12]}"
        order = Order(client_id=cid, side=side, price=price, amount=amount,
                      status=OrderStatus.OPEN, exchange_id=cid, grid_level=grid_level,
                      created_ts=time.time(), updated_ts=time.time())
        # Reserve funds so we cannot oversubscribe.
        if side == OrderSide.BUY:
            self.usdt -= amount * price
        else:
            self.sol -= amount
        self.open[cid] = order
        return order

    def cancel(self, order: Order) -> None:
        o = self.open.pop(order.client_id, None)
        if o is None:
            return
        # Return reserved funds.
        if o.side == OrderSide.BUY:
            self.usdt += o.amount * o.price
        else:
            self.sol += o.amount
        o.status = OrderStatus.CANCELLED
        o.updated_ts = time.time()

    def poll_fills(self, high: float, low: float, last: float) -> list[Order]:
        """Given the price action of the latest tick/candle, return filled orders.

        ``high``/``low`` allow backtests to fill intrabar; for paper trading
        pass last for all three.
        """
        filled: list[Order] = []
        for cid, o in list(self.open.items()):
            hit = (o.side == OrderSide.BUY and low <= o.price) or \
                  (o.side == OrderSide.SELL and high >= o.price)
            if not hit:
                continue
            fee = o.amount * o.price * self.fee_rate
            if o.side == OrderSide.BUY:
                self.sol += o.amount
                self.usdt -= fee  # notional already reserved
            else:
                self.usdt += o.amount * o.price - fee
            o.status = OrderStatus.FILLED
            o.filled_amount = o.amount
            o.fee = fee
            o.updated_ts = time.time()
            filled.append(o)
            del self.open[cid]
        return filled

    def balances(self) -> tuple[float, float]:
        """Free (unreserved) balances."""
        return self.sol, self.usdt

    def reserved(self) -> tuple[float, float]:
        """SOL/USDT currently locked in open orders."""
        rusdt = sum(o.amount * o.price for o in self.open.values()
                    if o.side == OrderSide.BUY)
        rsol = sum(o.amount for o in self.open.values()
                   if o.side == OrderSide.SELL)
        return rsol, rusdt

    def total_balances(self) -> tuple[float, float]:
        """Free balances plus funds reserved in open orders (total equity)."""
        rsol, rusdt = self.reserved()
        return self.sol + rsol, self.usdt + rusdt
