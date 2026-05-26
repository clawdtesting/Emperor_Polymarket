"""Optional Telegram alerting. No-op when not configured."""
from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger("solgrid.telegram")


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, enabled: bool) -> None:
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled and bool(token) and bool(chat_id)

    def send(self, message: str) -> None:
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": message,
                      "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=10,
            )
            if resp.status_code != 200:
                log.warning("Telegram send failed: %s %s", resp.status_code, resp.text)
        except requests.RequestException as exc:  # network errors must not crash bot
            log.warning("Telegram send error: %s", exc)
