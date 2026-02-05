from __future__ import annotations

from telegram_watch.cli import _confirm_retention


def test_confirm_retention_auto_confirm_bypasses_prompt() -> None:
    assert _confirm_retention(365, auto_confirm=True) is True

