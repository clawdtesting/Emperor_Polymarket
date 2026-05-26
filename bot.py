#!/usr/bin/env python3
"""Entry point for the SOL accumulation grid bot.

Usage:
    python bot.py init
    python bot.py backtest
    python bot.py paper
    python bot.py live
    python bot.py status
    python bot.py report
    python bot.py cancel-all
    python bot.py emergency-stop
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
