import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config, EnvConfig  # noqa: E402


def _env() -> EnvConfig:
    return EnvConfig(
        live_trading=False, run_mode="paper", exchange="hyperliquid",
        wallet_address="", private_key="", testnet=True,
        telegram_token="", telegram_chat_id="",
        config_file="config/config.yaml", db_path=":memory:",
        kill_switch_file="KILL_SWITCH_TEST",
    )


def _raw() -> dict:
    return {
        "symbol": "SOL/USDC:USDC",
        "starting_sol": 2.0,
        "starting_usdt": 200.0,
        "core_sol_fraction": 0.5,
        "grid_capital_percentage": 0.3,
        "core_sol_minimum": None,
        "grid": {
            "lower_price": 80.0, "upper_price": 96.0, "count": 9,
            "spacing_mode": "arithmetic", "atr_spacing_multiplier": 0.75,
            "dynamic": False, "range_lookback_candles": 200,
            "range_recalc_percentile": 0.05,
        },
        "order": {
            "size_mode": "fixed_usdt", "fixed_usdt": 8.0, "fixed_sol": 0.1,
            "portfolio_percent": 0.04, "min_order_size_usdt": 5.0,
            "max_active_orders": 12,
        },
        "accumulation": {
            "accumulation_mode": True, "profit_conversion_mode": "partial_to_SOL",
            "profit_conversion_percent": 50, "reduce_sells_in_uptrend": True,
            "sell_reduction_factor": 0.5,
        },
        "regime": {
            "ema_fast": 20, "ema_mid": 50, "ema_slow": 200, "atr_period": 14,
            "adx_period": 14, "adx_range_max": 25.0, "max_price_dist_ema50_pct": 4.0,
            "atr_high_vol_pct": 6.0, "volume_spike_multiplier": 3.0,
            "breakout_confirm_percent": 1.0, "candle_timeframe": "1h",
            "candle_lookback": 300,
        },
        "breakout": {
            "upward_breakout_action": "reduce_sells",
            "downward_breakdown_action": "reduce_buys",
        },
        "risk": {
            "profile": "low", "max_drawdown_percent": 8.0,
            "max_daily_loss_percent": 3.0, "max_open_orders": 12,
            "max_sol_exposure_percent": 50.0, "max_usdt_exposure_percent": 30.0,
            "max_usdt_deployment": 60.0, "max_position_sol": 1.0,
            "min_free_usdt_reserve": 20.0, "max_order_retries": 3,
            "api_stale_data_timeout_sec": 60, "max_spread_percent": 0.5,
            "price_gap_percent": 10.0, "circuit_breaker_enabled": True,
        },
        "engine": {"poll_interval_sec": 15, "rebalance_interval_sec": 300,
                   "reconcile_on_startup": True},
        "backtest": {"data_file": "data/sol_ohlcv.csv", "timeframe": "1h",
                     "fee_rate": 0.00035},
    }


@pytest.fixture
def cfg() -> Config:
    return Config(env=_env(), raw=_raw())
