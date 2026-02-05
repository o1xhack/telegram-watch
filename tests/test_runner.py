from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

import pytest

from telegram_watch import runner
from telegram_watch.config import (
    Config,
    ControlGroupConfig,
    DisplayConfig,
    NotificationConfig,
    ReportingConfig,
    StorageConfig,
    TargetGroupConfig,
    TelegramConfig,
)
from telegram_watch.storage import DbMessage
from telegram_watch.timeutils import utc_now


def build_config(tmp_path: Path) -> Config:
    telegram = TelegramConfig(api_id=1, api_hash="abcdefghijk", session_file=tmp_path / "session")
    target = TargetGroupConfig(
        name="default",
        target_chat_id=-123,
        tracked_user_ids=(111,),
        tracked_user_aliases=MappingProxyType({}),
        summary_interval_minutes=120,
        control_group="default",
    )
    control = ControlGroupConfig(
        key="default",
        control_chat_id=-456,
        is_forum=False,
        topic_routing_enabled=False,
        topic_target_map=MappingProxyType({}),
    )
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
        config_version=1.0,
        telegram=telegram,
        sender=None,
        targets=(target,),
        control_groups=MappingProxyType({"default": control}),
        target_by_chat_id=MappingProxyType({target.target_chat_id: target}),
        target_by_name=MappingProxyType({target.name: target}),
        control_by_chat_id=MappingProxyType({control.control_chat_id: control}),
        targets_by_control=MappingProxyType({"default": (target,)}),
        storage=storage,
        reporting=reporting,
        display=display,
        notifications=notifications,
    )


def test_heartbeat_repeats_after_idle_interval():
    tracker = runner._ActivityTracker()
    now = datetime(2026, 1, 25, 12, 0, 0, tzinfo=timezone.utc)
    tracker.last_activity = now - timedelta(hours=3)

    tracker.last_heartbeat_sent = None
    assert tracker.should_send_heartbeat(now, idle_seconds=2 * 60 * 60) is True

    tracker.last_heartbeat_sent = now - timedelta(hours=1)
    assert tracker.should_send_heartbeat(now, idle_seconds=2 * 60 * 60) is False

    tracker.last_heartbeat_sent = now - timedelta(hours=2, seconds=1)
    assert tracker.should_send_heartbeat(now, idle_seconds=2 * 60 * 60) is True


def test_topic_reply_id_for_message_respects_control_group():
    control = ControlGroupConfig(
        key="main",
        control_chat_id=-456,
        is_forum=True,
        topic_routing_enabled=True,
        topic_target_map=MappingProxyType({-123: MappingProxyType({111: 9001})}),
    )
    message = DbMessage(
        chat_id=-123,
        message_id=1,
        sender_id=111,
        date=datetime.now(timezone.utc),
        text="hello",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
        media=[],
    )
    assert runner._topic_reply_id_for_message(control, -123, message) == 9001

    control_no_map = ControlGroupConfig(
        key="alt",
        control_chat_id=-457,
        is_forum=True,
        topic_routing_enabled=True,
        topic_target_map=MappingProxyType({}),
    )
    assert runner._topic_reply_id_for_message(control_no_map, -123, message) is None


def test_resolve_once_targets_by_name_and_id(tmp_path: Path):
    config = build_config(tmp_path)
    assert runner._resolve_once_targets(config, "default")[0].target_chat_id == -123
    assert runner._resolve_once_targets(config, "-123")[0].name == "default"
    assert runner._resolve_once_targets(config, None)[0].name == "default"


def test_resolve_once_targets_invalid(tmp_path: Path):
    config = build_config(tmp_path)
    with pytest.raises(ValueError):
        runner._resolve_once_targets(config, "missing")


@pytest.mark.asyncio
async def test_summary_loop_passes_tracker_and_bark_context(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    target = config.targets[0]
    control = config.control_groups["default"]
    tracker = runner._ActivityTracker()
    loop = runner._SummaryLoop(config, target, control, client=object(), tracker=tracker)
    loop._last_summary = utc_now() - timedelta(minutes=120)

    sample_message = DbMessage(
        chat_id=target.target_chat_id,
        message_id=1,
        sender_id=target.tracked_user_ids[0],
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

    def fake_fetch_messages_between(_conn, _ids, _since, _until, **_kwargs):
        return [sample_message]

    def fake_generate_report(_messages, _config, _since, _until, **_kwargs):
        return tmp_path / "report.html"

    # Track arguments passed to _send_report_bundle.
    captured: dict[str, object] = {}

    async def fake_send_report_bundle(
        _client,
        _config,
        _control,
        _target,
        messages,
        _since,
        _until,
        _report,
        *,
        tracker=None,
        bark_context=None,
        fallback_client=None,
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
