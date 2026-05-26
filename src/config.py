"""Configuration loading and validation.

Merges environment variables (.env / process env) with the YAML strategy
config into a single immutable, validated ``Config`` object.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

try:  # optional dependency; env may already be populated
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


class ConfigError(Exception):
    """Raised when configuration is missing or inconsistent."""


def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class EnvConfig:
    live_trading: bool
    run_mode: str
    exchange: str
    wallet_address: str
    private_key: str
    testnet: bool
    telegram_token: str
    telegram_chat_id: str
    config_file: str
    db_path: str
    kill_switch_file: str

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


@dataclass(frozen=True)
class Config:
    env: EnvConfig
    raw: dict[str, Any]

    # --- convenient typed accessors -------------------------
    @property
    def symbol(self) -> str:
        return str(self.raw["symbol"])

    @property
    def starting_sol(self) -> float:
        return float(self.raw["starting_sol"])

    @property
    def starting_usdt(self) -> float:
        return float(self.raw["starting_usdt"])

    @property
    def core_sol_fraction(self) -> float:
        return float(self.raw["core_sol_fraction"])

    @property
    def core_sol_minimum(self) -> float:
        explicit = self.raw.get("core_sol_minimum")
        if explicit is not None:
            return float(explicit)
        return self.starting_sol * self.core_sol_fraction

    @property
    def grid_capital_percentage(self) -> float:
        return float(self.raw["grid_capital_percentage"])

    def section(self, name: str) -> dict[str, Any]:
        return dict(self.raw.get(name, {}))

    @property
    def grid(self) -> dict[str, Any]:
        return self.section("grid")

    @property
    def order(self) -> dict[str, Any]:
        return self.section("order")

    @property
    def accumulation(self) -> dict[str, Any]:
        return self.section("accumulation")

    @property
    def regime(self) -> dict[str, Any]:
        return self.section("regime")

    @property
    def breakout(self) -> dict[str, Any]:
        return self.section("breakout")

    @property
    def risk(self) -> dict[str, Any]:
        return self.section("risk")

    @property
    def engine(self) -> dict[str, Any]:
        return self.section("engine")

    @property
    def backtest(self) -> dict[str, Any]:
        return self.section("backtest")


def load_env(base_dir: Optional[Path] = None) -> EnvConfig:
    base = base_dir or Path.cwd()
    if load_dotenv is not None:
        env_path = base / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    return EnvConfig(
        live_trading=_get_bool("LIVE_TRADING", False),
        run_mode=os.getenv("RUN_MODE", "paper").strip().lower(),
        exchange=os.getenv("EXCHANGE", "hyperliquid").strip().lower(),
        wallet_address=os.getenv("HYPERLIQUID_WALLET_ADDRESS", "").strip(),
        private_key=os.getenv("HYPERLIQUID_PRIVATE_KEY", "").strip(),
        testnet=_get_bool("HYPERLIQUID_TESTNET", True),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        config_file=os.getenv("CONFIG_FILE", "config/config.yaml").strip(),
        db_path=os.getenv("DB_PATH", "data/bot_state.sqlite3").strip(),
        kill_switch_file=os.getenv("KILL_SWITCH_FILE", "KILL_SWITCH").strip(),
    )


def _apply_risk_profile(raw: dict[str, Any]) -> None:
    risk = raw.get("risk", {})
    profile = str(risk.get("profile", "low")).lower()
    overrides = raw.get("risk_profiles", {}).get(profile)
    if overrides:
        risk.update(overrides)
        raw["risk"] = risk


def load_config(base_dir: Optional[Path] = None) -> Config:
    base = base_dir or Path.cwd()
    env = load_env(base)
    cfg_path = base / env.config_file
    if not cfg_path.exists():
        raise ConfigError(
            f"Config file not found: {cfg_path}. "
            "Run `python bot.py init` or copy config/config.example.yaml."
        )
    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    _apply_risk_profile(raw)
    cfg = Config(env=env, raw=raw)
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    """Static validation independent of any exchange connection."""
    required_top = ["symbol", "starting_sol", "starting_usdt",
                    "core_sol_fraction", "grid_capital_percentage"]
    for key in required_top:
        if key not in cfg.raw:
            raise ConfigError(f"Missing required config key: {key}")

    if cfg.env.run_mode not in {"paper", "live", "backtest"}:
        raise ConfigError(f"Invalid RUN_MODE: {cfg.env.run_mode}")

    if not (0.0 <= cfg.core_sol_fraction <= 1.0):
        raise ConfigError("core_sol_fraction must be between 0 and 1")
    if not (0.0 < cfg.grid_capital_percentage <= 1.0):
        raise ConfigError("grid_capital_percentage must be in (0, 1]")

    grid = cfg.grid
    if grid.get("lower_price", 0) <= 0 or grid.get("upper_price", 0) <= 0:
        raise ConfigError("grid lower/upper price must be positive")
    if grid["lower_price"] >= grid["upper_price"]:
        raise ConfigError("grid lower_price must be < upper_price")
    if int(grid.get("count", 0)) < 2:
        raise ConfigError("grid count must be >= 2")
    if grid.get("spacing_mode") not in {"arithmetic", "geometric", "atr"}:
        raise ConfigError("grid.spacing_mode must be arithmetic|geometric|atr")

    order = cfg.order
    if order.get("size_mode") not in {"fixed_usdt", "fixed_sol", "portfolio_percent"}:
        raise ConfigError("order.size_mode invalid")
    if order.get("min_order_size_usdt", 0) <= 0:
        raise ConfigError("order.min_order_size_usdt must be positive")

    acc = cfg.accumulation
    if acc.get("profit_conversion_mode") not in {"none", "partial_to_SOL", "full_to_SOL"}:
        raise ConfigError("accumulation.profit_conversion_mode invalid")

    bo = cfg.breakout
    if bo.get("upward_breakout_action") not in {"pause", "shift_grid_up", "reduce_sells"}:
        raise ConfigError("breakout.upward_breakout_action invalid")
    if bo.get("downward_breakdown_action") not in {"pause", "reduce_buys", "emergency_stop"}:
        raise ConfigError("breakout.downward_breakdown_action invalid")

    # If live trading is requested, credentials must be present.
    if cfg.env.run_mode == "live" or cfg.env.live_trading:
        if not cfg.env.wallet_address or not cfg.env.private_key:
            raise ConfigError(
                "Live trading requires HYPERLIQUID_WALLET_ADDRESS and "
                "HYPERLIQUID_PRIVATE_KEY in .env"
            )
