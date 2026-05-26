"""Human-readable status/report rendering."""
from __future__ import annotations

from typing import Optional

from .metrics import Metrics


def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{d}d {h}h {m}m {s}s"


def render(m: Metrics, *, regime: str = "n/a", regime_detail: str = "",
           risk_status: str = "ok", last_error: Optional[str] = None,
           grid_range: str = "n/a", mode: str = "paper") -> str:
    sign = "+" if m.net_sol_accumulated >= 0 else ""
    lines = [
        "=" * 56,
        f" SOL ACCUMULATION GRID BOT  [{mode.upper()}]",
        "=" * 56,
        f" Price (SOL)            : {m.price:.4f}",
        f" Active grid range      : {grid_range}",
        f" Market regime          : {regime}  ({regime_detail})",
        "-" * 56,
        f" Starting SOL           : {m.starting_sol:.6f}",
        f" Current SOL            : {m.current_sol:.6f}",
        f" NET SOL ACCUMULATED    : {sign}{m.net_sol_accumulated:.6f}  <-- key metric",
        "-" * 56,
        f" Starting USDT          : {m.starting_usdt:.2f}",
        f" Current USDT           : {m.current_usdt:.2f}",
        f" Grid SOL inventory     : {m.grid_sol:.6f} @ avg {m.grid_avg_cost:.4f}",
        "-" * 56,
        f" Realized PnL (USDT)    : {m.realized_pnl_usdt:+.4f}",
        f" Unrealized PnL (USDT)  : {m.unrealized_pnl_usdt:+.4f}",
        f" Total value (USDT)     : {m.total_value_usdt:.2f}",
        f" Total value (SOL)      : {m.total_value_sol:.6f}",
        "-" * 56,
        f" Open orders            : {m.open_orders}",
        f" Risk status            : {risk_status}",
        f" Last error             : {last_error or 'none'}",
        f" Uptime                 : {_fmt_duration(m.uptime_sec)}",
        "=" * 56,
    ]
    return "\n".join(lines)
