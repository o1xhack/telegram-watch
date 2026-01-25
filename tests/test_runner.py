from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

import pytest

from telegram_watch import runner
from telegram_watch.config import (
    Config,
    ControlConfig,
    DisplayConfig,
    NotificationConfig,
    ReportingConfig,
    StorageConfig,
    TargetConfig,
    TelegramConfig,
)
from telegram_watch.storage import DbMessage
from telegram_watch.timeutils import utc_now


def build_config(tmp_path: Path) -> Config:
    telegram = TelegramConfig(api_id=1, api_hash="abcdefghijk", session_file=tmp_path / "session")
    target = TargetConfig(
        target_chat_id=-123,
        tracked_user_ids=(111,),
        tracked_user_aliases=MappingProxyType({}),
    )
    control = ControlConfig(control_chat_id=-456)
    storage = StorageConfig(db_path=tmp_path / "db.sqlite3", media_dir=tmp_path / "media")
    reporting = ReportingConfig(
        reports_dir=tmp_path / "reports",
        summary_interval_minutes=120,
        timezone=timezone.utc,
        retention_days=30,
    )
    display = DisplayConfig(show_ids=True, time_format="%Y.%m.%d %H:%M:%S (%Z)")
    notifications = NotificationConfig(bark_key=None)
    return Config(
        telegram=telegram,
        target=target,
        control=control,
        storage=storage,
        reporting=reporting,
        display=display,
        notifications=notifications,
    )


@pytest.mark.asyncio
async def test_summary_loop_passes_tracker_and_bark_context(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    tracker = runner._ActivityTracker()
    loop = runner._SummaryLoop(config, client=object(), tracker=tracker)
    loop._last_summary = utc_now() - timedelta(minutes=120)

    sample_message = DbMessage(
        chat_id=config.target.target_chat_id,
        message_id=1,
        sender_id=config.target.tracked_user_ids[0],
        date=datetime.now(timezone.utc),
        text="hello",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
        media=[],
    )

    @contextmanager
    def fake_db_session(_path: Path):
        yield object()

    def fake_fetch_messages_between(_conn, _ids, _since, _until):
        return [sample_message]

    def fake_generate_report(_messages, _config, _since, _until):
        return tmp_path / "report.html"

    # Track arguments passed to _send_report_bundle.
    captured: dict[str, object] = {}

    async def fake_send_report_bundle(
        _client,
        _config,
        messages,
        _since,
        _until,
        _report,
        *,
        tracker=None,
        bark_context=None,
    ):
        captured["tracker"] = tracker
        captured["bark_context"] = bark_context
        captured["messages"] = messages

    monkeypatch.setattr(runner, "db_session", fake_db_session)
    monkeypatch.setattr(runner, "fetch_messages_between", fake_fetch_messages_between)
    monkeypatch.setattr(runner, "generate_report", fake_generate_report)
    monkeypatch.setattr(runner, "_send_report_bundle", fake_send_report_bundle)
    monkeypatch.setattr(runner, "_purge_old_reports", lambda *_args, **_kwargs: None)

    await loop._send_summary()

    assert captured["messages"] == [sample_message]
    assert captured["tracker"] is tracker
    assert captured["bark_context"] == "(2H)"
