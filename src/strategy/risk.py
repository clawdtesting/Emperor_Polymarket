"""Risk management: pre-trade checks, circuit breaker, kill switch."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import Config
from ..data.market_data import MarketSnapshot
from ..storage.models import OrderSide


@dataclass
class RiskState:
    halted: bool = False
    reason: str = ""
    halted_ts: float = 0.0
    daily_anchor_value: float = 0.0
    daily_anchor_ts: float = 0.0
    peak_value: float = 0.0
    consecutive_order_errors: int = 0
    last_price: float = 0.0


class RiskManager:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.r = cfg.risk
        self.state = RiskState()

    # ---- global halts --------------------------------------
    def kill_switch_active(self) -> bool:
        return Path(self.cfg.env.kill_switch_file).exists()

    def halt(self, reason: str) -> None:
        if not self.state.halted:
            self.state.halted_ts = time.time()
        self.state.halted = True
        self.state.reason = reason

    def check_global(self, portfolio_value_usdt: float,
                     snapshot: MarketSnapshot) -> Optional[str]:
        """Returns a halt reason string, or None if trading may continue."""
        if not self.r.get("circuit_breaker_enabled", True):
            pass  # breaker disabled but kill switch / staleness still apply

        if self.kill_switch_active():
            self.halt("kill switch file present")
            return self.state.reason

        # Daily loss anchor (reset every 24h).
        now = time.time()
        if self.state.daily_anchor_ts == 0 or now - self.state.daily_anchor_ts > 86400:
            self.state.daily_anchor_value = portfolio_value_usdt
            self.state.daily_anchor_ts = now
        if self.state.peak_value < portfolio_value_usdt:
            self.state.peak_value = portfolio_value_usdt

        if self.r.get("circuit_breaker_enabled", True):
            dd = self._drawdown_pct(portfolio_value_usdt)
            if dd > float(self.r["max_drawdown_percent"]):
                self.halt(f"max drawdown exceeded: {dd:.2f}%")
                return self.state.reason
            daily = self._daily_loss_pct(portfolio_value_usdt)
            if daily > float(self.r["max_daily_loss_percent"]):
                self.halt(f"max daily loss exceeded: {daily:.2f}%")
                return self.state.reason

        # Price gap detection.
        if self.state.last_price > 0 and snapshot.mid > 0:
            gap = abs(snapshot.mid - self.state.last_price) / self.state.last_price * 100
            if gap > float(self.r["price_gap_percent"]):
                self.halt(f"price gap {gap:.2f}% exceeds threshold")
                self.state.last_price = snapshot.mid
                return self.state.reason
        self.state.last_price = snapshot.mid

        # Stale / invalid data.
        if not snapshot.is_valid():
            return "invalid market data; skipping cycle"
        if snapshot.is_stale(float(self.r["api_stale_data_timeout_sec"])):
            return "stale market data; skipping cycle"
        if snapshot.spread_percent > float(self.r["max_spread_percent"]):
            return f"spread {snapshot.spread_percent:.3f}% too wide; skipping cycle"
        return None

    def record_order_error(self) -> bool:
        """Returns True if the consecutive-error breaker tripped."""
        self.state.consecutive_order_errors += 1
        if self.state.consecutive_order_errors >= int(self.r["max_order_retries"]):
            self.halt("repeated order placement failures")
            return True
        return False

    def record_order_success(self) -> None:
        self.state.consecutive_order_errors = 0

    # ---- per-order pre-trade checks ------------------------
    def allow_order(self, side: OrderSide, amount_sol: float, price: float,
                    sol_balance: float, usdt_balance: float,
                    grid_sol_inventory: float, deployed_usdt: float,
                    open_order_count: int) -> tuple[bool, str]:
        if self.state.halted:
            return False, f"halted: {self.state.reason}"
        if open_order_count >= int(self.r["max_open_orders"]):
            return False, "max open orders reached"

        notional = amount_sol * price
        if side == OrderSide.BUY:
            if usdt_balance - notional < float(self.r["min_free_usdt_reserve"]):
                return False, "would breach min USDT reserve"
            if deployed_usdt + notional > float(self.r["max_usdt_deployment"]):
                return False, "would exceed max USDT deployment"
            if deployed_usdt + notional > usdt_balance + deployed_usdt:
                return False, "insufficient USDT"
            max_usdt_exp = float(self.r["max_usdt_exposure_percent"]) / 100.0
            total_usdt = usdt_balance + deployed_usdt
            if total_usdt > 0 and (deployed_usdt + notional) / total_usdt > max_usdt_exp:
                return False, "USDT exposure cap reached"
        else:  # SELL
            core_min = self.cfg.core_sol_minimum
            if sol_balance - amount_sol < core_min:
                return False, "would sell into core SOL reserve"
            if grid_sol_inventory - amount_sol < 0:
                return False, "no grid SOL inventory to sell"
            if grid_sol_inventory > float(self.r["max_position_sol"]):
                return False, "grid SOL position cap reached"
        return True, "ok"

    # ---- helpers -------------------------------------------
    def _drawdown_pct(self, value: float) -> float:
        if self.state.peak_value <= 0:
            return 0.0
        return max(0.0, (self.state.peak_value - value) / self.state.peak_value * 100.0)

    def _daily_loss_pct(self, value: float) -> float:
        if self.state.daily_anchor_value <= 0:
            return 0.0
        return max(0.0, (self.state.daily_anchor_value - value)
                   / self.state.daily_anchor_value * 100.0)

    def status(self) -> dict[str, object]:
        return {
            "halted": self.state.halted,
            "reason": self.state.reason,
            "drawdown_pct": round(self._drawdown_pct(self.state.peak_value
                                                     and self.state.last_price), 2),
            "consecutive_order_errors": self.state.consecutive_order_errors,
            "kill_switch": self.kill_switch_active(),
        }
