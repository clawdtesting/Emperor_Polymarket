"""Bot engine: wires modules together and runs the trading loop.

Supports three modes:
  * paper    - live market data, simulated fills (default)
  * live     - real spot orders (requires LIVE_TRADING=true)
  * backtest - historical OHLCV replay
"""
from __future__ import annotations

import logging
import signal
import time
from typing import Optional

from .alerts.logger import setup_logging
from .alerts.telegram import TelegramNotifier
from .config import Config, load_config
from .data import candles as cndl
from .data.market_data import MarketSnapshot
from .exchange import Exchange
from .execution.live_broker import LiveBroker
from .execution.order_manager import OrderManager
from .execution.paper_broker import PaperBroker
from .execution.reconciliation import reconcile_live
from .reporting import metrics as metrics_mod
from .reporting.report import render
from .storage.db import Database
from .storage.models import OrderSide, OrderStatus, Regime
from .strategy import accumulation, grid
from .strategy.regime import classify
from .strategy.risk import RiskManager

log = logging.getLogger("solgrid.engine")


class Bot:
    def __init__(self, cfg: Config, mode: str) -> None:
        self.cfg = cfg
        self.mode = mode
        self.db = Database(cfg.env.db_path)
        self.risk = RiskManager(cfg)
        self.notifier = TelegramNotifier(
            cfg.env.telegram_token, cfg.env.telegram_chat_id, cfg.env.telegram_enabled)
        self._running = True

        self.exchange: Optional[Exchange] = None
        self.broker = None
        self.om: Optional[OrderManager] = None
        self._last_rebalance = 0.0

    # ---- lifecycle -----------------------------------------
    def _install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            log.info("Received signal %s; shutting down gracefully", signum)
            self._running = False
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def setup(self) -> None:
        live = self.mode == "live"
        self.exchange = Exchange(self.cfg, trading_enabled=live)
        self.exchange.load_markets()
        self.exchange.assert_no_withdrawal_dependency()

        if live:
            if not self.cfg.env.live_trading:
                raise RuntimeError("Refusing live mode: LIVE_TRADING is not true")
            sol, usdt = self.exchange.fetch_balances()
            self.broker = LiveBroker(self.exchange)
        else:
            sol, usdt = self.cfg.starting_sol, self.cfg.starting_usdt
            fee = float(self.cfg.backtest.get("fee_rate", 0.00035))
            self.broker = PaperBroker(self.cfg, sol, usdt, fee_rate=fee)

        self.db.ensure_starting_balances(sol, usdt)
        self.om = OrderManager(self.cfg, self.db, self.broker)
        self.om.load_state()

        if live and self.cfg.engine.get("reconcile_on_startup", True):
            report = reconcile_live(self.db, self.exchange,
                                    self.cfg.starting_sol, self.cfg.starting_usdt)
            log.info("Reconcile: local=%d exchange=%d matched=%d notes=%s",
                     report.local_open, report.exchange_open, report.matched,
                     report.notes)
            if not report.consistent:
                self.notifier.send(
                    "Startup reconciliation found divergence; trading paused. "
                    f"Notes: {report.notes}")
                self.risk.halt("startup reconciliation divergence; run cancel-all")

    # ---- main loop -----------------------------------------
    def run(self) -> None:
        self._install_signal_handlers()
        self.setup()
        poll = int(self.cfg.engine.get("poll_interval_sec", 15))
        self.notifier.send(f"SOL grid bot started in {self.mode.upper()} mode.")
        log.info("Engine running in %s mode (poll=%ss)", self.mode, poll)
        while self._running:
            try:
                self.cycle()
            except Exception as exc:  # never let one cycle kill the loop
                log.exception("cycle error: %s", exc)
                self.db.audit("ERROR", "cycle", str(exc))
                if self.risk.record_order_error():
                    self.notifier.send(f"Circuit breaker tripped: {exc}")
            self._sleep(poll)
        self.shutdown()

    def _sleep(self, seconds: int) -> None:
        # responsive to shutdown signals
        for _ in range(seconds):
            if not self._running:
                return
            time.sleep(1)

    def shutdown(self) -> None:
        log.info("Shutting down; persisting state")
        self.db.audit("INFO", "lifecycle", "graceful shutdown")
        self.notifier.send("SOL grid bot stopped.")
        self.db.close()

    # ---- one trading cycle ---------------------------------
    def cycle(self) -> None:
        assert self.exchange and self.om and self.broker
        snapshot = self.exchange.fetch_snapshot()
        candles = self.exchange.fetch_candles(
            self.cfg.regime.get("candle_timeframe", "1h"),
            int(self.cfg.regime.get("candle_lookback", 300)))

        sol, usdt = self.broker.balances() if self.mode != "live" \
            else self.exchange.fetch_balances()
        port_value = usdt + sol * snapshot.mid

        skip = self.risk.check_global(port_value, snapshot)
        if self.risk.state.halted:
            log.warning("HALTED: %s", self.risk.state.reason)
            return
        if skip:
            log.info("Skipping cycle: %s", skip)
            return

        regime = classify(self.cfg, candles, snapshot)
        self.db.record_regime(regime.regime.value, regime.detail)

        self._process_fills(snapshot)

        if regime.trade_allowed:
            self._manage_grid(snapshot, candles, regime.regime, sol, usdt, port_value)
        else:
            self._handle_non_range(regime.regime, snapshot)

        self._maybe_rebalance(snapshot)
        self.risk.record_order_success()

    def _process_fills(self, snapshot: MarketSnapshot) -> None:
        assert self.om and self.broker
        if self.mode == "live":
            filled = self.broker.poll_fills(self.om.open_orders)
        else:
            filled = self.broker.poll_fills(snapshot.mid, snapshot.mid, snapshot.mid)
        for order in filled:
            realized = self.om.register_fill(order)
            msg = (f"FILL {order.side.value} {order.filled_amount:.4f} SOL "
                   f"@ {order.price:.4f} (realized {realized:+.4f} USDT)")
            log.info(msg)
            self.notifier.send(msg)

    def _manage_grid(self, snapshot: MarketSnapshot, candles, regime: Regime,
                     sol: float, usdt: float, port_value: float) -> None:
        assert self.om
        spec = grid.build_levels(self.cfg, snapshot.mid, candles)
        max_active = int(self.cfg.order.get("max_active_orders", 12))
        for level in spec.levels:
            if len(self.om.open_orders) >= max_active:
                break
            if self.om.has_order_near(level.price, level.side):
                continue
            # Don't place orders straddling the current price too tightly.
            if abs(level.price - snapshot.mid) / snapshot.mid < 0.001:
                continue

            amount = grid.order_amount_sol(self.cfg, level.price, port_value)
            if level.side == OrderSide.SELL:
                adj = accumulation.adjust_sell_amount(self.cfg, amount, regime)
                amount = adj.amount_sol

            ok, reason = self.risk.allow_order(
                level.side, amount, level.price, sol, usdt,
                self.om.inv.grid_sol, self.om.deployed_usdt, len(self.om.open_orders))
            if not ok:
                log.debug("skip level %.4f %s: %s", level.price, level.side.value, reason)
                continue
            self.om.place(level.side, amount, level.price, grid_level=level.index)

    def _handle_non_range(self, regime: Regime, snapshot: MarketSnapshot) -> None:
        """Breakout/breakdown/volatility handling: preserve inventory."""
        assert self.om
        bo = self.cfg.breakout
        if regime == Regime.UPTREND_BREAKOUT:
            action = bo.get("upward_breakout_action", "reduce_sells")
            # Always stop new sells that reduce SOL; cancel open sells.
            for order in list(self.om.open_orders):
                if order.side == OrderSide.SELL:
                    self.om.cancel(order)
            self._alert_once("uptrend_breakout",
                             f"Uptrend breakout: preserving SOL ({action}). "
                             f"Price {snapshot.mid:.4f}")
            if action == "pause":
                self.risk.halt("upward breakout pause (manual resume required)")
        elif regime == Regime.DOWNTREND_BREAKDOWN:
            action = bo.get("downward_breakdown_action", "reduce_buys")
            for order in list(self.om.open_orders):
                if order.side == OrderSide.BUY:
                    self.om.cancel(order)
            self._alert_once("downtrend_breakdown",
                             f"Downtrend breakdown: protecting USDT ({action}). "
                             f"Price {snapshot.mid:.4f}")
            if action == "emergency_stop":
                self.risk.halt("downward breakdown emergency stop")
        elif regime in (Regime.HIGH_VOLATILITY, Regime.LOW_LIQUIDITY):
            self._alert_once(regime.value,
                             f"{regime.value}: pausing new grid orders.")

    def _alert_once(self, key: str, message: str) -> None:
        last = self.db.get_meta(f"alert_{key}", 0)
        now = time.time()
        if now - float(last) > 1800:  # throttle repeated alerts to 30 min
            log.info(message)
            self.notifier.send(message)
            self.db.set_meta(f"alert_{key}", now)

    def _maybe_rebalance(self, snapshot: MarketSnapshot) -> None:
        assert self.om and self.broker
        interval = int(self.cfg.engine.get("rebalance_interval_sec", 300))
        now = time.time()
        if now - self._last_rebalance < interval:
            return
        self._last_rebalance = now

        # Convert realized USDT profit into SOL per accumulation policy.
        realized = self.db.realized_pnl()
        already = float(self.db.get_meta("converted_usdt", 0.0))
        convertible = accumulation.profit_to_convert(self.cfg, realized) - already
        if convertible >= self.cfg.order.get("min_order_size_usdt", 5.0):
            amount = convertible / snapshot.mid
            sol, usdt = (self.broker.balances() if self.mode != "live"
                         else self.exchange.fetch_balances())
            ok, reason = self.risk.allow_order(
                OrderSide.BUY, amount, snapshot.ask, sol, usdt,
                self.om.inv.grid_sol, self.om.deployed_usdt, len(self.om.open_orders))
            if ok:
                self.om.place(OrderSide.BUY, amount, snapshot.ask)
                self.db.set_meta("converted_usdt", already + convertible)
                self._alert_once("profit_convert",
                                 f"Converting {convertible:.2f} USDT profit into SOL")


def run_backtest(cfg: Config) -> None:
    """Replay historical OHLCV through the grid + paper broker."""
    db = Database(":memory:")
    db.ensure_starting_balances(cfg.starting_sol, cfg.starting_usdt)
    fee = float(cfg.backtest.get("fee_rate", 0.00035))
    broker = PaperBroker(cfg, cfg.starting_sol, cfg.starting_usdt, fee_rate=fee)
    om = OrderManager(cfg, db, broker)
    risk = RiskManager(cfg)

    data = cndl.load_csv(cfg.backtest["data_file"])
    lookback = int(cfg.regime.get("candle_lookback", 300))
    warm = max(lookback, int(cfg.regime.get("ema_mid", 50)))
    if len(data) <= warm:
        raise RuntimeError("Not enough candles to backtest")

    for i in range(warm, len(data)):
        window = data[:i + 1]
        c = data[i]
        snap = MarketSnapshot(symbol=cfg.symbol, last=c.close, bid=c.close * 0.9995,
                              ask=c.close * 1.0005, ts=c.ts, fetched_ts=time.time())
        regime = classify(cfg, window, snap)
        # fills using intrabar high/low
        for order in broker.poll_fills(c.high, c.low, c.close):
            om.register_fill(order)
        if regime.trade_allowed and not risk.state.halted:
            spec = grid.build_levels(cfg, c.close, window)
            for level in spec.levels:
                if len(om.open_orders) >= int(cfg.order.get("max_active_orders", 12)):
                    break
                if om.has_order_near(level.price, level.side):
                    continue
                port_value = broker.usdt + broker.sol * c.close
                amt = grid.order_amount_sol(cfg, level.price, port_value)
                if level.side == OrderSide.SELL:
                    amt = accumulation.adjust_sell_amount(cfg, amt, regime.regime).amount_sol
                ok, _ = risk.allow_order(level.side, amt, level.price, broker.sol,
                                         broker.usdt, om.inv.grid_sol,
                                         om.deployed_usdt, len(om.open_orders))
                if ok:
                    om.place(level.side, amt, level.price, level.index)

    final = data[-1].close
    m = metrics_mod.compute(cfg, db, om, broker.sol, broker.usdt, final)
    print(render(m, mode="backtest",
                 grid_range=f"{cfg.grid['lower_price']}-{cfg.grid['upper_price']}"))
    db.close()
