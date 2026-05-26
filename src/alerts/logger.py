"""Structured logging setup shared across the bot."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False


def setup_logging(level: str = "INFO", log_file: str = "logs/bot.log") -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("solgrid")
    if _CONFIGURED:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        logger.warning("Could not open log file %s; logging to stdout only", log_file)

    logger.propagate = False
    _CONFIGURED = True
    return logger


def get_logger(name: str = "solgrid") -> logging.Logger:
    return logging.getLogger(name)
