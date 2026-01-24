"""Utilities for generating Telegram links."""

from __future__ import annotations


def build_message_link(chat_id: int, message_id: int | None) -> str | None:
    """Return https://t.me link for the given chat/message if possible."""
    if not message_id:
        return None
    chat_str = str(chat_id)
    if chat_str.startswith("-100"):
        channel_id = chat_str[4:]
    elif chat_str.startswith("-"):
        channel_id = chat_str[1:]
    else:
        channel_id = chat_str
    if not channel_id.isdigit():
        return None
    return f"https://t.me/c/{channel_id}/{message_id}"
