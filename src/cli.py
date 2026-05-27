"""Command-line interface for the SOL accumulation grid bot."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .alerts.logger import setup_logging
from .config import ConfigError, load_config
from .exchange import Exchange
from .execution.order_manager import OrderManager
from .reporting import metrics as metrics_mod
from .reporting.report import render
from .storage.db import Database


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def cmd_init(_args: argparse.Namespace) -> int:
    root = _project_root()
    pairs = [
        (root / "config" / "config.example.yaml", root / "config" / "config.yaml"),
        (root / ".env.example", root / ".env"),
    ]
    for src, dst in pairs:
        if dst.exists():
            print(f"exists, skipping: {dst.name}")
            continue
        if src.exists():
            shutil.copy(src, dst)
            print(f"created: {dst.name}")
    print("\nEdit config/config.yaml and .env, then run: python bot.py paper")
    return 0


def cmd_backtest(_args: argparse.Namespace) -> int:
    from .main import run_backtest
    cfg = load_config(_project_root())
    run_backtest(cfg)
    return 0


def _run_mode(mode: str) -> int:
    from .main import Bot
    cfg = load_config(_project_root())
    setup_logging()
    bot = Bot(cfg, mode=mode)
    bot.run()
    return 0


def cmd_paper(_args: argparse.Namespace) -> int:
    return _run_mode("paper")


def cmd_live(_args: argparse.Namespace) -> int:
    cfg = load_config(_project_root())
    if not cfg.env.live_trading:
        print("LIVE_TRADING is not true in .env. Refusing to place real orders.",
              file=sys.stderr)
        return 2
    confirm = input("Type 'LIVE' to place REAL orders: ").strip()
    if confirm != "LIVE":
        print("Aborted.")
        return 1
    return _run_mode("live")


def _read_only_context():
    cfg = load_config(_project_root())
    db = Database(cfg.env.db_path)
    return cfg, db


def cmd_status(_args: argparse.Namespace) -> int:
    cfg, db = _read_only_context()
    ex = Exchange(cfg, trading_enabled=False)
    ex.load_markets()
    snap = ex.fetch_snapshot()
    om = OrderManager(cfg, db, broker=None)
    om.load_state()
    if cfg.env.live_trading and cfg.env.run_mode == "live":
        sol, usdt = ex.fetch_balances()
    else:
        sol = float(db.get_meta("starting_sol", cfg.starting_sol)) + om.inv.grid_sol
        usdt = float(db.get_meta("starting_usdt", cfg.starting_usdt))
    m = metrics_mod.compute(cfg, db, om, sol, usdt, snap.mid)
    last_regime = db.last_regime()
    last_err = db.last_error()
    print(render(
        m,
        regime=last_regime["regime"] if last_regime else "n/a",
        regime_detail=last_regime["detail"] if last_regime else "",
        grid_range=f"{cfg.grid['lower_price']}-{cfg.grid['upper_price']}",
        last_error=last_err["message"] if last_err else None,
        mode=cfg.env.run_mode,
    ))
    db.close()
    return 0


def cmd_report(_args: argparse.Namespace) -> int:
    return cmd_status(_args)


def cmd_cancel_all(_args: argparse.Namespace) -> int:
    cfg, db = _read_only_context()
    if cfg.env.run_mode == "live" and cfg.env.live_trading:
        ex = Exchange(cfg, trading_enabled=True)
        ex.load_markets()
        from .execution.live_broker import LiveBroker
        broker = LiveBroker(ex)
    else:
        from .execution.paper_broker import PaperBroker
        broker = PaperBroker(cfg, cfg.starting_sol, cfg.starting_usdt)
    om = OrderManager(cfg, db, broker)
    om.load_state()
    n = om.cancel_all()
    print(f"Cancelled {n} open orders.")
    db.close()
    return 0


def cmd_web(_args: argparse.Namespace) -> int:
    import os
    from .web.app import create_app
    setup_logging()
    if not os.getenv("CONSOLE_PASSWORD"):
        print("Warning: CONSOLE_PASSWORD is not set; logins will be refused "
              "until you set it.")
    app = create_app(_project_root())
    port = int(os.getenv("PORT", "8000"))
    print(f"Web console on http://0.0.0.0:{port}  (Ctrl+C to stop)")
    app.run(host="0.0.0.0", port=port)
    return 0


def cmd_emergency_stop(_args: argparse.Namespace) -> int:
    cfg, db = _read_only_context()
    Path(cfg.env.kill_switch_file).write_text("STOP\n", encoding="utf-8")
    db.audit("CRITICAL", "kill_switch", "emergency stop engaged via CLI")
    print(f"Kill switch file created: {cfg.env.kill_switch_file}")
    print("The running bot will halt on its next cycle. Delete the file to resume.")
    db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bot.py", description="SOL accumulation grid bot")
    sub = p.add_subparsers(dest="command", required=True)
    commands = {
        "init": cmd_init,
        "backtest": cmd_backtest,
        "paper": cmd_paper,
        "live": cmd_live,
        "status": cmd_status,
        "report": cmd_report,
        "cancel-all": cmd_cancel_all,
        "emergency-stop": cmd_emergency_stop,
        "web": cmd_web,
    }
    for name, fn in commands.items():
        sp = sub.add_parser(name, help=fn.__doc__ or name)
        sp.set_defaults(func=fn)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
