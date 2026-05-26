"""Live market data snapshot: price, spread, staleness, order book."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketSnapshot:
    symbol: str
    last: float
    bid: float
    ask: float
    ts: float          # exchange timestamp (seconds)
    fetched_ts: float  # local time we fetched it

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def spread_percent(self) -> float:
        if self.bid <= 0 or self.ask <= 0:
            return 100.0
        return (self.ask - self.bid) / self.mid * 100.0

    def is_stale(self, timeout_sec: float) -> bool:
        return (time.time() - self.fetched_ts) > timeout_sec

    def is_valid(self) -> bool:
        return self.last > 0 and self.bid > 0 and self.ask > 0 and self.ask >= self.bid
