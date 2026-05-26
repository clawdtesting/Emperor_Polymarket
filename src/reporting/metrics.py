"""Performance metrics. The headline metric is NET_SOL_ACCUMULATED."""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..config import Config
from ..execution.order_manager import OrderManager
from ..storage.db import Database


@dataclass
class Metrics:
    starting_sol: float
    current_sol: float
    net_sol_accumulated: float
    starting_usdt: float
    current_usdt: float
    price: float
    grid_sol: float
    grid_avg_cost: float
    realized_pnl_usdt: float
    unrealized_pnl_usdt: float
    total_value_usdt: float
    total_value_sol: float
    open_orders: int
    uptime_sec: float

    def as_dict(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def compute(cfg: Config, db: Database, om: OrderManager,
            current_sol: float, current_usdt: float, price: float) -> Metrics:
    starting_sol = float(db.get_meta("starting_sol", cfg.starting_sol))
    starting_usdt = float(db.get_meta("starting_usdt", cfg.starting_usdt))
    started_ts = float(db.get_meta("started_ts", time.time()))

    realized = db.realized_pnl()
    unrealized = (price - om.inv.avg_cost) * om.inv.grid_sol if om.inv.grid_sol else 0.0

    total_value_usdt = current_usdt + current_sol * price
    total_value_sol = (current_usdt / price + current_sol) if price > 0 else current_sol

    return Metrics(
        starting_sol=starting_sol,
        current_sol=current_sol,
        net_sol_accumulated=current_sol - starting_sol,
        starting_usdt=starting_usdt,
        current_usdt=current_usdt,
        price=price,
        grid_sol=om.inv.grid_sol,
        grid_avg_cost=om.inv.avg_cost,
        realized_pnl_usdt=realized,
        unrealized_pnl_usdt=unrealized,
        total_value_usdt=total_value_usdt,
        total_value_sol=total_value_sol,
        open_orders=len(om.open_orders),
        uptime_sec=time.time() - started_ts,
    )
