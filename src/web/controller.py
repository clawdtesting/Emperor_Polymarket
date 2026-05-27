"""Owns the Bot instance and runs its trading loop in a background thread.

The web console process is single-worker: exactly one BotController, and
therefore exactly one trading loop, exists per process.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from ..config import Config
from ..main import Bot

log = logging.getLogger("solgrid.controller")


class BotController:
    def __init__(self, cfg: Config, mode: str) -> None:
        self.cfg = cfg
        self.mode = mode
        self.bot = Bot(cfg, mode)
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._thread = threading.Thread(
                target=self._run, name="bot-loop", daemon=True)
            self._thread.start()
            log.info("Bot loop thread started (%s mode)", self.mode)

    def _run(self) -> None:
        try:
            self.bot.run()
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Bot loop crashed: %s", exc)
            self.bot._set_snapshot({"state": "crashed", "error": str(exc)})

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def status(self) -> dict[str, object]:
        snap = self.bot.get_snapshot()
        snap["loop_alive"] = self.alive
        return snap

    # ---- control proxies -----------------------------------
    def pause(self) -> None:
        self.bot.pause()

    def resume(self) -> None:
        self.bot.resume()

    def cancel_all(self) -> None:
        self.bot.request_cancel_all()

    def convert(self) -> None:
        self.bot.request_convert()

    def emergency_stop(self) -> None:
        self.bot.engage_kill_switch()

    def clear_kill_switch(self) -> None:
        self.bot.clear_kill_switch()
