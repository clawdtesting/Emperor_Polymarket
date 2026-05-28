"""SQLite persistence layer. Restart-safe, deterministic state handling."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import Order, OrderSide, OrderStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    client_id TEXT PRIMARY KEY,
    exchange_id TEXT,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    amount REAL NOT NULL,
    filled_amount REAL NOT NULL DEFAULT 0,
    fee REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    grid_level INTEGER,
    created_ts REAL NOT NULL,
    updated_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    amount REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS regimes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    regime TEXT NOT NULL,
    detail TEXT,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS equity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    net_sol REAL NOT NULL,
    total_value_usdt REAL NOT NULL,
    price REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the web console constructs the bot in one
        # thread and runs its loop in another. Writes stay effectively
        # single-threaded (the bot loop owns them).
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- meta / key-value ----------------------------------
    def set_meta(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        self.conn.commit()

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    def ensure_starting_balances(self, sol: float, usdt: float) -> None:
        if self.get_meta("starting_sol") is None:
            self.set_meta("starting_sol", sol)
            self.set_meta("starting_usdt", usdt)
            self.set_meta("started_ts", time.time())

    # ---- orders --------------------------------------------
    def upsert_order(self, order: Order) -> None:
        self.conn.execute(
            """INSERT INTO orders(client_id, exchange_id, side, price, amount,
                   filled_amount, fee, status, grid_level, created_ts, updated_ts)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(client_id) DO UPDATE SET
                   exchange_id=excluded.exchange_id,
                   filled_amount=excluded.filled_amount,
                   fee=excluded.fee,
                   status=excluded.status,
                   updated_ts=excluded.updated_ts""",
            (
                order.client_id, order.exchange_id, order.side.value, order.price,
                order.amount, order.filled_amount, order.fee, order.status.value,
                order.grid_level, order.created_ts or time.time(),
                order.updated_ts or time.time(),
            ),
        )
        self.conn.commit()

    def _row_to_order(self, row: sqlite3.Row) -> Order:
        return Order(
            client_id=row["client_id"],
            exchange_id=row["exchange_id"],
            side=OrderSide(row["side"]),
            price=row["price"],
            amount=row["amount"],
            filled_amount=row["filled_amount"],
            fee=row["fee"],
            status=OrderStatus(row["status"]),
            grid_level=row["grid_level"],
            created_ts=row["created_ts"],
            updated_ts=row["updated_ts"],
        )

    def open_orders(self) -> list[Order]:
        rows = self.conn.execute(
            "SELECT * FROM orders WHERE status=?", (OrderStatus.OPEN.value,)
        ).fetchall()
        return [self._row_to_order(r) for r in rows]

    def get_order(self, client_id: str) -> Optional[Order]:
        row = self.conn.execute(
            "SELECT * FROM orders WHERE client_id=?", (client_id,)
        ).fetchone()
        return self._row_to_order(row) if row else None

    def all_orders(self) -> list[Order]:
        rows = self.conn.execute("SELECT * FROM orders ORDER BY created_ts").fetchall()
        return [self._row_to_order(r) for r in rows]

    # ---- fills ---------------------------------------------
    def record_fill(self, client_id: str, side: OrderSide, price: float,
                    amount: float, fee: float, realized_pnl: float) -> None:
        self.conn.execute(
            "INSERT INTO fills(client_id, side, price, amount, fee, realized_pnl, ts)"
            " VALUES(?,?,?,?,?,?,?)",
            (client_id, side.value, price, amount, fee, realized_pnl, time.time()),
        )
        self.conn.commit()

    def fills(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM fills ORDER BY ts").fetchall()

    def realized_pnl(self) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) AS p FROM fills"
        ).fetchone()
        return float(row["p"])

    # ---- regimes & audit -----------------------------------
    def record_regime(self, regime: str, detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO regimes(regime, detail, ts) VALUES(?,?,?)",
            (regime, detail, time.time()),
        )
        self.conn.commit()

    def last_regime(self) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM regimes ORDER BY ts DESC LIMIT 1"
        ).fetchone()

    def audit(self, level: str, category: str, message: str) -> None:
        self.conn.execute(
            "INSERT INTO audit(level, category, message, ts) VALUES(?,?,?,?)",
            (level, category, message, time.time()),
        )
        self.conn.commit()

    def last_error(self) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM audit WHERE level IN ('ERROR','CRITICAL') "
            "ORDER BY ts DESC LIMIT 1"
        ).fetchone()

    # ---- equity history ------------------------------------
    def record_equity(self, net_sol: float, total_value_usdt: float,
                      price: float) -> None:
        self.conn.execute(
            "INSERT INTO equity_history(ts, net_sol, total_value_usdt, price)"
            " VALUES(?,?,?,?)",
            (time.time(), net_sol, total_value_usdt, price),
        )
        self.conn.commit()

    def equity_history(self, limit: int = 1000) -> list[sqlite3.Row]:
        rows = self.conn.execute(
            "SELECT * FROM equity_history ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return list(reversed(rows))

