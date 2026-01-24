"""Notification helpers (currently Bark)."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

import requests

from .config import NotificationConfig

logger = logging.getLogger(__name__)

_BARK_GROUP = "Telegram Watch"


async def send_bark_notification(
    notifications: NotificationConfig,
    title: str,
    body: str,
) -> None:
    """Send a Bark notification if configured."""
    if not notifications.bark_key:
        return
    await asyncio.to_thread(
        _send_bark_sync,
        notifications.bark_key,
        title,
        body,
    )


def _send_bark_sync(bark_key: str, title: str, body: str) -> None:
    base = "https://api.day.app"
    url = f"{base}/{quote(bark_key)}/{quote(title)}/{quote(body)}"
    url += f"?group={quote(_BARK_GROUP)}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code >= 400:
            logger.warning("Bark notification failed: %s", resp.text)
    except requests.RequestException as exc:
        logger.warning("Bark notification error: %s", exc)
