"""CCXT exchange wrapper for Hyperliquid (spot).

Hyperliquid authenticates with a wallet address + an API/agent private key
(not a classic apiKey/secret). This wrapper exposes the narrow surface the
bot needs and validates that no withdrawal capability is being relied upon.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .config import Config, ConfigError
from .data.candles import Candle, from_ccxt
from .data.market_data import MarketSnapshot

log = logging.getLogger("solgrid.exchange")

try:
    import ccxt  # type: ignore
except Exception:  # pragma: no cover
    ccxt = None


class ExchangeError(Exception):
    pass


class Exchange:
    """Thin CCXT wrapper. Read-only methods are always allowed; trading
    methods raise unless the client was created with trading credentials."""

    def __init__(self, cfg: Config, trading_enabled: bool) -> None:
        if ccxt is None:
            raise ExchangeError("ccxt is not installed. pip install ccxt")
        self.cfg = cfg
        self.symbol = cfg.symbol
        self.trading_enabled = trading_enabled
        self._client = self._build_client(cfg, trading_enabled)
        self._markets: dict[str, Any] = {}

    def _build_client(self, cfg: Config, trading_enabled: bool):
        if cfg.env.exchange != "hyperliquid":
            raise ConfigError(f"Unsupported exchange: {cfg.env.exchange}")
        params: dict[str, Any] = {"enableRateLimit": True}
        if trading_enabled:
            if not cfg.env.wallet_address or not cfg.env.private_key:
                raise ConfigError("Trading requires wallet address + private key")
            params["walletAddress"] = cfg.env.wallet_address
            params["privateKey"] = cfg.env.private_key
        else:
            # Public/read-only: wallet address (if present) lets us read balances.
            if cfg.env.wallet_address:
                params["walletAddress"] = cfg.env.wallet_address
        client = ccxt.hyperliquid(params)
        if cfg.env.testnet:
            try:
                client.set_sandbox_mode(True)
            except Exception:  # pragma: no cover
                log.warning("Could not enable sandbox mode for hyperliquid")
        return client

    # ---- startup validation --------------------------------
    def load_markets(self) -> None:
        self._markets = self._client.load_markets()
        if self.symbol not in self._markets:
            raise ConfigError(
                f"Symbol {self.symbol} not found on exchange. "
                f"Available example: {next(iter(self._markets), 'n/a')}"
            )

    def market(self) -> dict[str, Any]:
        if not self._markets:
            self.load_markets()
        return self._markets[self.symbol]

    def min_order_amount(self) -> float:
        m = self.market()
        return float((m.get("limits", {}).get("amount", {}) or {}).get("min") or 0.0)

    def assert_no_withdrawal_dependency(self) -> None:
        """The bot never withdraws. We surface the agent capabilities so the
        operator can confirm the key has trade-only scope."""
        log.info("Bot uses trade + read scope only; withdrawal is never invoked.")

    # ---- read-only -----------------------------------------
    def fetch_snapshot(self) -> MarketSnapshot:
        t = self._client.fetch_ticker(self.symbol)
        ob_bid = t.get("bid") or 0.0
        ob_ask = t.get("ask") or 0.0
        if not ob_bid or not ob_ask:
            ob = self._client.fetch_order_book(self.symbol, limit=5)
            ob_bid = ob["bids"][0][0] if ob.get("bids") else 0.0
            ob_ask = ob["asks"][0][0] if ob.get("asks") else 0.0
        ts = (t.get("timestamp") or int(time.time() * 1000)) / 1000.0
        return MarketSnapshot(
            symbol=self.symbol,
            last=float(t.get("last") or t.get("close") or ob_ask or 0.0),
            bid=float(ob_bid),
            ask=float(ob_ask),
            ts=ts,
            fetched_ts=time.time(),
        )

    def fetch_candles(self, timeframe: str, limit: int) -> list[Candle]:
        rows = self._client.fetch_ohlcv(self.symbol, timeframe=timeframe, limit=limit)
        return from_ccxt(rows)

    def fetch_ohlcv_symbol(self, symbol: str, timeframe: str,
                           limit: int) -> list[list[float]]:
        """Raw OHLCV for an arbitrary symbol (used by the dashboard chart)."""
        if not self._markets:
            self.load_markets()
        if symbol not in self._markets:
            raise ExchangeError(f"symbol not available: {symbol}")
        return self._client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def fetch_balances(self) -> tuple[float, float]:
        """Returns (sol, quote). Quote currency depends on the symbol."""
        bal = self._client.fetch_balance()
        base, quote = self._split_symbol()
        sol = float((bal.get(base, {}) or {}).get("free", 0) or 0)
        usdt = float((bal.get(quote, {}) or {}).get("free", 0) or 0)
        return sol, usdt

    def fetch_open_orders(self) -> list[dict[str, Any]]:
        return self._client.fetch_open_orders(self.symbol)

    def _split_symbol(self) -> tuple[str, str]:
        # "SOL/USDC:USDC" -> base SOL, quote USDC
        base = self.symbol.split("/")[0]
        quote = self.symbol.split("/")[1].split(":")[0]
        return base, quote

    # ---- trading (live only) -------------------------------
    def create_limit_order(self, side: str, amount: float, price: float,
                           client_id: Optional[str] = None) -> dict[str, Any]:
        if not self.trading_enabled:
            raise ExchangeError("create_limit_order called without trading enabled")
        params: dict[str, Any] = {}
        if client_id:
            params["clientOrderId"] = client_id
        return self._client.create_order(
            self.symbol, "limit", side, amount, price, params
        )

    def cancel_order(self, exchange_id: str) -> dict[str, Any]:
        if not self.trading_enabled:
            raise ExchangeError("cancel_order called without trading enabled")
        return self._client.cancel_order(exchange_id, self.symbol)

    def fetch_order(self, exchange_id: str) -> dict[str, Any]:
        return self._client.fetch_order(exchange_id, self.symbol)
