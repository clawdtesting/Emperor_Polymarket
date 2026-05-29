"""Regression tests for the halt / auto-resume behaviour."""
import time

from src.data.market_data import MarketSnapshot
from src.strategy.risk import RiskManager


def _snap() -> MarketSnapshot:
    now = time.time()
    return MarketSnapshot("SOL/USDC:USDC", 100.0, 99.95, 100.05, now, now)


def test_halt_records_timestamp(cfg):
    rm = RiskManager(cfg)
    assert rm.state.halted_ts == 0.0
    rm.halt("test")
    assert rm.state.halted
    assert rm.state.halted_ts > 0
    first_ts = rm.state.halted_ts
    rm.halt("second")
    # Subsequent halts do not reset the original timestamp.
    assert rm.state.halted_ts == first_ts


def test_consecutive_errors_trip_breaker(cfg):
    cfg.raw["risk"]["max_order_retries"] = 3
    rm = RiskManager(cfg)
    assert rm.record_order_error() is False  # 1
    assert rm.record_order_error() is False  # 2
    assert rm.record_order_error() is True   # 3 -> trip
    assert rm.state.halted


def test_record_success_resets_counter(cfg):
    rm = RiskManager(cfg)
    rm.record_order_error()
    rm.record_order_error()
    rm.record_order_success()
    assert rm.state.consecutive_order_errors == 0
