"""Typed records used across the bot and persisted by the storage layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Regime(str, Enum):
    RANGE = "RANGE"
    UPTREND_BREAKOUT = "UPTREND_BREAKOUT"
    DOWNTREND_BREAKDOWN = "DOWNTREND_BREAKDOWN"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"


@dataclass
class Order:
    client_id: str
    side: OrderSide
    price: float
    amount: float            # SOL amount
    status: OrderStatus = OrderStatus.OPEN
    exchange_id: Optional[str] = None
    grid_level: Optional[int] = None
    filled_amount: float = 0.0
    fee: float = 0.0
    created_ts: float = 0.0
    updated_ts: float = 0.0

    @property
    def notional(self) -> float:
        return self.price * self.amount


@dataclass
class Balances:
    sol: float
    usdt: float
    ts: float = 0.0


@dataclass
class GridLevel:
    index: int
    price: float
    side: OrderSide   # the action this level triggers
