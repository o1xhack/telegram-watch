from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import logging
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest
from telethon import errors
from telethon.tl import types as tl_types

from telegram_watch import runner
from telegram_watch.config import (
    Config,
    ControlGroupConfig,
    DisplayConfig,
    FullArchiveConfig,
    NotificationConfig,
    RealtimeConfig,
    ReportingConfig,
    StorageConfig,
    TargetGroupConfig,
    TelegramConfig,
)
from telegram_watch import storage
from telegram_watch.storage import DbMedia, DbMessage
from telegram_watch.timeutils import utc_now


@pytest.mark.asyncio
async def test_async_sqlite_gate_serializes_blocking_work() -> None:
    gate = runner._AsyncSqliteGate()
    state_lock = threading.Lock()
    active = 0
    peak_active = 0

    def blocking_work(value: int) -> int:
        nonlocal active, peak_active
        with state_lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.02)
        with state_lock:
            active -= 1
        return value

    results = await asyncio.gather(
        gate.run(blocking_work, 1),
        gate.run(blocking_work, 2),
        gate.run(blocking_work, 3),
    )

    assert results == [1, 2, 3]
    assert peak_active == 1
    assert gate.pending == 0
    assert gate.pending_since is None


@pytest.mark.parametrize(
    ("configured", "runtime_enabled", "expected_status"),
    [
        (False, False, "disabled"),
        (True, True, "active"),
        (True, False, "degraded"),
    ],
)
def test_runner_health_heartbeat_reports_actual_full_archive_state(
    tmp_path: Path,
    configured: bool,
    runtime_enabled: bool,
    expected_status: str,
) -> None:
    health_path = tmp_path / "run.health.json"
    health_loop = runner._RunnerHealthLoop(
        health_path,
        runner._AsyncSqliteGate(),
        full_archive_configured=configured,
    )
    health_loop.full_archive_runtime_enabled = runtime_enabled

    health_loop._write()

    payload = json.loads(health_path.read_text(encoding="utf-8"))
    assert payload["full_archive"] == {
        "configured": configured,
        "runtime_enabled": runtime_enabled,
        "status": expected_status,
    }


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
    display = DisplayConfig(show_ids=True, time_format="%Y.%m.%d %H:%M:%S (%Z)", language="auto")
    notifications = NotificationConfig(bark_key=None, heartbeat_interval_hours=2, check_updates=True)
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
        realtime=RealtimeConfig(
            push_mode="interval",
            report_interval_minutes=120,
            rate_limit_per_minute=20,
            rate_limit_per_hour=200,
            rate_limit_per_day=1000,
            min_interval_sec=3.0,
            media_extra_delay_sec=2.0,
            warmup_minutes=5.0,
            warmup_rate=5,
        ),
    )


def enable_full_archive(
    config: Config,
    tmp_path: Path,
    *,
    capture_scope: str = "whole_group",
    topic_ids: tuple[int, ...] = (),
    backfill_limit_messages: int = 10_000,
) -> Config:
    return replace(
        config,
        full_archive=FullArchiveConfig(
            enabled=True,
            root_dir=tmp_path / "full_archive",
            source_chat_id=config.targets[0].target_chat_id,
            capture_scope=capture_scope,
            topic_ids=topic_ids,
            shard_policy="monthly",
            max_messages_per_shard=500_000,
            max_shard_size_mb=1024,
            backfill_limit_messages=backfill_limit_messages,
        ),
    )


def build_multi_target_config(tmp_path: Path) -> Config:
    telegram = TelegramConfig(api_id=1, api_hash="abcdefghijk", session_file=tmp_path / "session")
    target1 = TargetGroupConfig(
        name="group-1",
        target_chat_id=-1001,
        tracked_user_ids=(111,),
        tracked_user_aliases=MappingProxyType({}),
        summary_interval_minutes=120,
        control_group="default",
    )
    target2 = TargetGroupConfig(
        name="group-2",
        target_chat_id=-1002,
        tracked_user_ids=(222,),
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
    display = DisplayConfig(show_ids=True, time_format="%Y.%m.%d %H:%M:%S (%Z)", language="auto")
    notifications = NotificationConfig(bark_key=None, heartbeat_interval_hours=2, check_updates=True)
    targets = (target1, target2)
    return Config(
        config_version=1.0,
        telegram=telegram,
        sender=None,
        targets=targets,
        control_groups=MappingProxyType({"default": control}),
        target_by_chat_id=MappingProxyType({target1.target_chat_id: target1, target2.target_chat_id: target2}),
        target_by_name=MappingProxyType({target1.name: target1, target2.name: target2}),
        control_by_chat_id=MappingProxyType({control.control_chat_id: control}),
        targets_by_control=MappingProxyType({"default": targets}),
        storage=storage,
        reporting=reporting,
        display=display,
        notifications=notifications,
        realtime=RealtimeConfig(
            push_mode="interval",
            report_interval_minutes=120,
            rate_limit_per_minute=20,
            rate_limit_per_hour=200,
            rate_limit_per_day=1000,
            min_interval_sec=3.0,
            media_extra_delay_sec=2.0,
            warmup_minutes=5.0,
            warmup_rate=5,
        ),
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


def test_is_explicit_reply_non_forum_reply_is_true():
    message = SimpleNamespace(
        is_reply=True,
        reply_to_msg_id=42,
        reply_to=SimpleNamespace(
            forum_topic=False,
            reply_to_top_id=None,
            quote=False,
        ),
    )
    assert runner._is_explicit_reply(message) is True


def test_is_explicit_reply_forum_topic_linkage_is_false():
    message = SimpleNamespace(
        is_reply=True,
        reply_to_msg_id=161204,
        reply_to=SimpleNamespace(
            forum_topic=True,
            reply_to_top_id=None,
            quote=False,
        ),
    )
    assert runner._is_explicit_reply(message) is False


def test_is_explicit_reply_forum_explicit_reply_is_true():
    message = SimpleNamespace(
        is_reply=True,
        reply_to_msg_id=367090,
        reply_to=SimpleNamespace(
            forum_topic=True,
            reply_to_top_id=161204,
            quote=False,
        ),
    )
    assert runner._is_explicit_reply(message) is True


@pytest.mark.asyncio
async def test_get_reply_snapshot_skips_forum_topic_linkage(tmp_path: Path):
    class Message:
        id = 1
        is_reply = True
        reply_to_msg_id = 161204
        reply_to = SimpleNamespace(forum_topic=True, reply_to_top_id=None, quote=False)

        async def get_reply_message(self):
            raise AssertionError("forum topic linkage should skip reply fetch")

    snapshot = await runner._get_reply_snapshot(
        object(),
        tmp_path,
        Message(),
        chat_id=-123,
    )

    assert snapshot is None


@pytest.mark.asyncio
async def test_get_reply_snapshot_keeps_forum_explicit_reply(tmp_path: Path):
    class Reply:
        id = 99
        sender_id = 555
        message = "quoted text"
        raw_text = "quoted text"
        date = datetime(2026, 2, 12, 12, 0, tzinfo=timezone.utc)
        media = None
        file = None

    class Message:
        id = 100
        is_reply = True
        reply_to_msg_id = 367090
        reply_to = SimpleNamespace(forum_topic=True, reply_to_top_id=161204, quote=False)

        async def get_reply_message(self):
            return Reply()

    snapshot = await runner._get_reply_snapshot(
        object(),
        tmp_path,
        Message(),
        chat_id=-123,
    )

    assert snapshot is not None
    assert snapshot.sender_id == 555
    assert snapshot.text == "quoted text"
    assert snapshot.media == []


@pytest.mark.asyncio
async def test_run_reply_cleanup_dry_run_counts(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    object.__setattr__(config.targets[0], "target_chat_id", -123)

    @contextmanager
    def fake_db_session(_path: Path):
        yield object()

    class DummyClient:
        async def get_entity(self, _chat_id):
            return SimpleNamespace(forum=True)

        async def get_messages(self, _chat_id, ids):
            msg1 = SimpleNamespace(
                id=ids[0],
                is_reply=True,
                reply_to=SimpleNamespace(forum_topic=True, reply_to_top_id=None, quote=False),
            )
            msg2 = SimpleNamespace(
                id=ids[1],
                is_reply=True,
                reply_to=SimpleNamespace(forum_topic=True, reply_to_top_id=100, quote=False),
            )
            return [msg1, msg2, None]

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    async def fake_with_floodwait(func, *args, **kwargs):
        return await func(*args, **kwargs)

    monkeypatch.setattr(runner, "db_session", fake_db_session)
    monkeypatch.setattr(
        runner,
        "fetch_reply_snapshot_candidates",
        lambda _conn, **_kwargs: [(-123, 1), (-123, 2), (-123, 3)],
    )
    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner, "_with_floodwait", fake_with_floodwait)
    monkeypatch.setattr(
        runner,
        "clear_reply_snapshots",
        lambda _conn, _keys: (_ for _ in ()).throw(AssertionError("dry-run should not clear")),
    )

    stats = await runner.run_reply_cleanup(config, apply=False, backup=False)
    assert stats.scanned == 3
    assert stats.kept_explicit_reply == 1
    assert stats.missing_messages == 1
    assert stats.to_clear == 1
    assert stats.cleared_messages == 0
    assert stats.cleared_media == 0


@pytest.mark.asyncio
async def test_run_reply_cleanup_apply_clears_candidates(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    object.__setattr__(config.targets[0], "target_chat_id", -123)

    @contextmanager
    def fake_db_session(_path: Path):
        yield object()

    class DummyClient:
        async def get_entity(self, _chat_id):
            return SimpleNamespace(forum=True)

        async def get_messages(self, _chat_id, ids):
            msg = SimpleNamespace(
                id=ids[0],
                is_reply=True,
                reply_to=SimpleNamespace(forum_topic=True, reply_to_top_id=None, quote=False),
            )
            return [msg]

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    async def fake_with_floodwait(func, *args, **kwargs):
        return await func(*args, **kwargs)

    captured: dict[str, object] = {}

    def fake_clear_reply_snapshots(_conn, keys):
        captured["keys"] = list(keys)
        return (1, 2)

    monkeypatch.setattr(runner, "db_session", fake_db_session)
    monkeypatch.setattr(
        runner,
        "fetch_reply_snapshot_candidates",
        lambda _conn, **_kwargs: [(-123, 42)],
    )
    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner, "_with_floodwait", fake_with_floodwait)
    monkeypatch.setattr(runner, "clear_reply_snapshots", fake_clear_reply_snapshots)

    stats = await runner.run_reply_cleanup(config, apply=True, backup=False)
    assert captured["keys"] == [(-123, 42)]
    assert stats.to_clear == 1
    assert stats.cleared_messages == 1
    assert stats.cleared_media == 2
    assert stats.backup_path is None


def test_resolve_once_targets_by_name_and_id(tmp_path: Path):
    config = build_config(tmp_path)
    assert runner._resolve_once_targets(config, "default")[0].target_chat_id == -123
    assert runner._resolve_once_targets(config, "-123")[0].name == "default"
    assert runner._resolve_once_targets(config, None)[0].name == "default"


def test_resolve_once_targets_invalid(tmp_path: Path):
    config = build_config(tmp_path)
    with pytest.raises(ValueError):
        runner._resolve_once_targets(config, "missing")


def make_archive_event_message(
    *,
    message_id: int = 1,
    chat_id: int = -123,
    sender_id: int | None = 999,
    topic_id: int | None = None,
    text: str = "context",
    media: object | None = None,
    file: object | None = None,
    action: object | None = None,
) -> SimpleNamespace:
    reply_to = None
    reply_to_msg_id = None
    if topic_id is not None:
        reply_to = SimpleNamespace(
            forum_topic=True,
            reply_to_top_id=topic_id,
            reply_to_msg_id=topic_id,
        )
        reply_to_msg_id = topic_id
    return SimpleNamespace(
        id=message_id,
        chat_id=chat_id,
        sender_id=sender_id,
        date=datetime(2026, 5, 1, 12, message_id, tzinfo=timezone.utc),
        message=text,
        raw_text=text,
        media=media,
        file=file,
        action=action,
        reply_to=reply_to,
        reply_to_msg_id=reply_to_msg_id,
    )


def test_archive_topic_id_prefers_reply_to_top_id() -> None:
    message = SimpleNamespace(
        reply_to_msg_id=367090,
        reply_to=SimpleNamespace(
            forum_topic=True,
            reply_to_top_id=161204,
            reply_to_msg_id=367090,
        ),
    )

    assert runner._archive_topic_id_for_message(message) == 161204


def test_archive_topic_id_treats_general_topic_as_unclassified() -> None:
    message = SimpleNamespace(
        reply_to_msg_id=1,
        reply_to=SimpleNamespace(
            forum_topic=True,
            reply_to_top_id=1,
            reply_to_msg_id=1,
        ),
    )

    assert runner._archive_topic_id_for_message(message) is None


def test_archive_topic_id_uses_forum_linkage_reply_as_best_effort_root() -> None:
    message = SimpleNamespace(
        reply_to_msg_id=161204,
        reply_to=SimpleNamespace(
            forum_topic=True,
            reply_to_top_id=None,
            reply_to_msg_id=161204,
        ),
    )

    assert runner._archive_topic_id_for_message(message) == 161204


def test_archive_topic_id_ignores_general_linkage_reply_root() -> None:
    message = SimpleNamespace(
        reply_to_msg_id=1,
        reply_to=SimpleNamespace(
            forum_topic=True,
            reply_to_top_id=None,
            reply_to_msg_id=1,
        ),
    )

    assert runner._archive_topic_id_for_message(message) is None


def test_archive_topic_id_keeps_non_forum_reply_unclassified() -> None:
    message = SimpleNamespace(
        reply_to_msg_id=42,
        reply_to=SimpleNamespace(
            forum_topic=False,
            reply_to_top_id=None,
            reply_to_msg_id=42,
        ),
    )

    assert runner._archive_topic_id_for_message(message) is None


def test_archive_message_from_telegram_uses_default_chat_and_tolerates_bad_optional_fields() -> None:
    message = SimpleNamespace(
        id="42",
        chat_id=None,
        sender_id="unknown",
        date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        message="context",
        raw_text="context",
        media=SimpleNamespace(document=SimpleNamespace(mime_type="image/jpeg")),
        file=SimpleNamespace(mime_type="image/jpeg", size="unknown", name="chart.jpg"),
        action=None,
        reply_to=SimpleNamespace(
            forum_topic=True,
            reply_to_top_id="77",
            reply_to_msg_id="bad",
        ),
        reply_to_msg_id="bad",
    )

    archive_message = runner._archive_message_from_telegram(
        message,
        chat_id_default=-1001,
    )

    assert archive_message is not None
    assert archive_message.chat_id == -1001
    assert archive_message.message_id == 42
    assert archive_message.sender_id is None
    assert archive_message.topic_id == 77
    assert archive_message.reply_to_msg_id is None
    assert archive_message.reply_to_top_id == 77
    assert archive_message.media[0].file_size is None


def test_archive_message_from_telegram_skips_messages_without_stable_identity() -> None:
    missing_chat = SimpleNamespace(
        id=1,
        chat_id=None,
        date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    )
    bad_message_id = SimpleNamespace(
        id="not-a-message-id",
        chat_id=-1001,
        date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    )
    missing_date = SimpleNamespace(id=1, chat_id=-1001, date=None)
    bad_date = SimpleNamespace(id=1, chat_id=-1001, date="not-a-datetime")

    assert runner._archive_message_from_telegram(missing_chat) is None
    assert runner._archive_message_from_telegram(bad_message_id) is None
    assert runner._archive_message_from_telegram(missing_date) is None
    assert runner._archive_message_from_telegram(bad_date) is None


def test_archive_message_from_telegram_keeps_service_messages_without_text() -> None:
    message = make_archive_event_message(
        message_id=9,
        text="",
        action=SimpleNamespace(kind="MessageActionPinMessage"),
    )
    message.raw_text = ""

    archive_message = runner._archive_message_from_telegram(message)

    assert archive_message is not None
    assert archive_message.message_kind == "service"
    assert archive_message.text == ""
    assert archive_message.raw_text == ""


@pytest.mark.asyncio
async def test_full_archive_handler_captures_non_tracked_message(tmp_path: Path):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)
    msg = make_archive_event_message(sender_id=999, text="non tracked context")

    await handler.handle(SimpleNamespace(message=msg))

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        row = conn.execute(
            "SELECT sender_id, text, payload_mode FROM archive_messages"
        ).fetchone()
    finally:
        conn.close()
    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        tracked_db_link_count = manifest.execute(
            "SELECT COUNT(*) FROM tracked_db_links WHERE status = 'active'"
        ).fetchone()[0]
    finally:
        manifest.close()

    assert row == (999, "non tracked context", "archive")
    assert tracked_db_link_count == 1


@pytest.mark.asyncio
async def test_full_archive_handler_caches_and_updates_sender_snapshot(tmp_path: Path):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)
    sender_calls = 0

    async def get_sender():
        nonlocal sender_calls
        sender_calls += 1
        return tl_types.User(
            id=999,
            first_name="Alice",
            last_name="Example",
            username="alice",
        )

    for message_id in (1, 2):
        await handler.handle(
            SimpleNamespace(
                message=make_archive_event_message(
                    message_id=message_id,
                    sender_id=999,
                ),
                get_sender=get_sender,
            )
        )

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        row = conn.execute(
            """
            SELECT username, display_name, first_seen_at, last_seen_at
            FROM archive_senders
            WHERE sender_id = ?
            """,
            (999,),
        ).fetchone()
    finally:
        conn.close()

    assert sender_calls == 1
    assert row == (
        "alice",
        "Alice Example",
        "2026-05-01T12:01:00+00:00",
        "2026-05-01T12:02:00+00:00",
    )


@pytest.mark.asyncio
async def test_full_archive_handler_keeps_message_when_sender_lookup_fails(
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)

    async def get_sender():
        raise RuntimeError("sender unavailable")

    await handler.handle(
        SimpleNamespace(
            message=make_archive_event_message(sender_id=999),
            get_sender=get_sender,
        )
    )

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        message_count = conn.execute(
            "SELECT COUNT(*) FROM archive_messages"
        ).fetchone()[0]
        sender_count = conn.execute(
            "SELECT COUNT(*) FROM archive_senders"
        ).fetchone()[0]
    finally:
        conn.close()

    assert message_count == 1
    assert sender_count == 0


@pytest.mark.asyncio
async def test_full_archive_handler_retries_sender_after_failure_cooldown(
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)
    sender_calls = 0

    async def get_sender():
        nonlocal sender_calls
        sender_calls += 1
        if sender_calls == 1:
            raise RuntimeError("temporary sender lookup failure")
        return tl_types.User(
            id=999,
            first_name="Recovered",
            last_name="Sender",
            username="recovered_sender",
        )

    for message_id in (1, 2):
        await handler.handle(
            SimpleNamespace(
                message=make_archive_event_message(
                    message_id=message_id,
                    sender_id=999,
                ),
                get_sender=get_sender,
            )
        )
    assert sender_calls == 1

    handler._sender_lookup_retry_after[999] = 0
    await handler.handle(
        SimpleNamespace(
            message=make_archive_event_message(message_id=3, sender_id=999),
            get_sender=get_sender,
        )
    )

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        message_count = conn.execute(
            "SELECT COUNT(*) FROM archive_messages"
        ).fetchone()[0]
        sender_row = conn.execute(
            "SELECT username, display_name FROM archive_senders WHERE sender_id = ?",
            (999,),
        ).fetchone()
    finally:
        conn.close()

    assert sender_calls == 2
    assert message_count == 3
    assert sender_row == ("recovered_sender", "Recovered Sender")


@pytest.mark.asyncio
async def test_full_archive_handler_honors_sender_lookup_floodwait(
    tmp_path: Path,
    caplog,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)
    sender_calls = 0

    async def get_sender():
        nonlocal sender_calls
        sender_calls += 1
        raise errors.FloodWaitError(None, 120)

    loop = asyncio.get_running_loop()
    with caplog.at_level(logging.WARNING):
        for message_id in (1, 2):
            await handler.handle(
                SimpleNamespace(
                    message=make_archive_event_message(
                        message_id=message_id,
                        sender_id=999,
                    ),
                    get_sender=get_sender,
                )
            )

    retry_delay = handler._sender_lookup_retry_after[999] - loop.time()
    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        message_count = conn.execute(
            "SELECT COUNT(*) FROM archive_messages"
        ).fetchone()[0]
    finally:
        conn.close()

    assert sender_calls == 1
    assert retry_delay > 119
    assert retry_delay <= 121
    assert message_count == 2
    assert "FloodWait during full archive sender lookup" in caplog.text


@pytest.mark.asyncio
async def test_full_archive_handler_keeps_message_when_sender_entity_is_invalid(
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)

    async def get_sender():
        return object()

    await handler.handle(
        SimpleNamespace(
            message=make_archive_event_message(sender_id=999),
            get_sender=get_sender,
        )
    )

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        message_count = conn.execute(
            "SELECT COUNT(*) FROM archive_messages"
        ).fetchone()[0]
        sender_count = conn.execute(
            "SELECT COUNT(*) FROM archive_senders"
        ).fetchone()[0]
    finally:
        conn.close()

    assert message_count == 1
    assert sender_count == 0


@pytest.mark.asyncio
async def test_full_archive_handler_stores_media_metadata_without_download(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)

    def fail_download(*_args, **_kwargs):
        raise AssertionError("full archive must not download media")

    monkeypatch.setattr(runner, "_download_media", fail_download)
    msg = make_archive_event_message(
        message_id=2,
        media=SimpleNamespace(document=SimpleNamespace(mime_type="image/png", size=456)),
        file=SimpleNamespace(mime_type="image/png", size=456, name="chart.png"),
    )

    await handler.handle(SimpleNamespace(message=msg))

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        row = conn.execute(
            """
            SELECT media_index, media_kind, mime_type, file_size, file_name
            FROM archive_media
            WHERE chat_id = ? AND message_id = ?
            """,
            (msg.chat_id, msg.id),
        ).fetchone()
    finally:
        conn.close()

    assert tuple(row) == (0, "SimpleNamespace", "image/png", 456, "chart.png")


@pytest.mark.asyncio
async def test_full_archive_handler_persists_in_thread(monkeypatch, tmp_path: Path):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)
    calls: list[object] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(runner.asyncio, "to_thread", fake_to_thread)

    await handler.handle(SimpleNamespace(message=make_archive_event_message()))

    assert calls == [runner._persist_archive_message_to_storage]


@pytest.mark.asyncio
async def test_full_archive_handler_filters_unconfigured_topics(tmp_path: Path):
    config = enable_full_archive(
        build_config(tmp_path),
        tmp_path,
        capture_scope="topics",
        topic_ids=(10,),
    )
    handler = runner._FullArchiveHandler(config)

    await handler.handle(
        SimpleNamespace(message=make_archive_event_message(topic_id=20))
    )

    assert not config.full_archive.root_dir.exists()


@pytest.mark.asyncio
async def test_full_archive_handler_topic_scope_excludes_other_topics_and_general(
    tmp_path: Path,
):
    config = enable_full_archive(
        build_config(tmp_path),
        tmp_path,
        capture_scope="topics",
        topic_ids=(10,),
    )
    handler = runner._FullArchiveHandler(config)

    await handler.handle(
        SimpleNamespace(
            message=make_archive_event_message(
                message_id=1,
                topic_id=10,
                text="configured topic",
            )
        )
    )
    await handler.handle(
        SimpleNamespace(
            message=make_archive_event_message(
                message_id=2,
                topic_id=20,
                text="other topic",
            )
        )
    )
    await handler.handle(
        SimpleNamespace(
            message=make_archive_event_message(
                message_id=3,
                text="general or unknown topic",
            )
        )
    )

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        rows = conn.execute(
            "SELECT message_id, topic_id, text FROM archive_messages"
        ).fetchall()
    finally:
        conn.close()
    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_count = manifest.execute(
            "SELECT SUM(message_count) FROM archive_shards"
        ).fetchone()[0]
    finally:
        manifest.close()

    assert [tuple(row) for row in rows] == [(1, 10, "configured topic")]
    assert manifest_count == 1


@pytest.mark.asyncio
async def test_full_archive_handler_after_root_deletion_keeps_tracked_ref_dedup(
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)
    tracked_message = make_archive_event_message(
        message_id=2,
        sender_id=config.targets[0].tracked_user_ids[0],
        text="archive duplicate candidate",
        media=SimpleNamespace(document=SimpleNamespace(mime_type="image/png", size=123)),
        file=SimpleNamespace(mime_type="image/png", size=123, name="chart.png"),
    )
    tracked = storage.connect(config.storage.db_path)
    storage.ensure_schema(tracked)
    try:
        storage.persist_message(
            tracked,
            storage.StoredMessage(
                chat_id=tracked_message.chat_id,
                message_id=tracked_message.id,
                sender_id=tracked_message.sender_id,
                date=tracked_message.date,
                text="tracked payload survives live archive reset",
                reply_to_msg_id=None,
                replied_sender_id=None,
                replied_date=None,
                replied_text=None,
            ),
            [],
        )
    finally:
        tracked.close()

    await handler.handle(
        SimpleNamespace(
            message=make_archive_event_message(message_id=1, text="before deletion")
        )
    )
    assert (config.full_archive.root_dir / "manifest.sqlite3").exists()

    shutil.rmtree(config.full_archive.root_dir)

    await handler.handle(SimpleNamespace(message=tracked_message))

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_count = manifest.execute(
            "SELECT SUM(message_count) FROM archive_shards"
        ).fetchone()[0]
        shard_path = manifest.execute("SELECT path FROM archive_shards").fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(config.full_archive.root_dir / shard_path)
    try:
        row = shard.execute(
            """
            SELECT message_id, payload_mode, text, raw_text,
                   tracked_message_chat_id, tracked_message_id
            FROM archive_messages
            """
        ).fetchone()
        archive_media_count = shard.execute(
            "SELECT COUNT(*) FROM archive_media"
        ).fetchone()[0]
        link_count = shard.execute(
            "SELECT COUNT(*) FROM archive_tracked_links"
        ).fetchone()[0]
    finally:
        shard.close()

    assert manifest_count == 1
    assert tuple(row) == (
        2,
        "tracked_ref",
        None,
        None,
        tracked_message.chat_id,
        tracked_message.id,
    )
    assert archive_media_count == 0
    assert link_count == 1


@pytest.mark.asyncio
async def test_full_archive_handler_swallows_storage_errors(
    monkeypatch, tmp_path: Path, caplog
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)

    def fail_persist(*_args, **_kwargs):
        raise OSError("archive unavailable")

    monkeypatch.setattr(runner, "_persist_archive_message_to_storage", fail_persist)

    with caplog.at_level(logging.WARNING):
        await handler.handle(SimpleNamespace(message=make_archive_event_message()))

    assert "Full archive capture failed without stopping watcher" in caplog.text


def test_archive_persist_does_not_record_tracked_db_link_when_shard_write_fails(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    message = runner._archive_message_from_telegram(make_archive_event_message())
    assert message is not None

    def fail_persist(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(runner, "persist_archive_message_with_result", fail_persist)

    with pytest.raises(sqlite3.OperationalError, match="disk full"):
        runner._persist_archive_message_to_storage(
            config,
            message,
            tracked_db_path=config.storage.db_path,
        )

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        count = manifest.execute(
            "SELECT COUNT(*) FROM tracked_db_links WHERE status = 'active'"
        ).fetchone()[0]
    finally:
        manifest.close()

    assert count == 0


def test_archive_persist_does_not_record_tracked_db_link_when_manifest_count_fails(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    message = runner._archive_message_from_telegram(make_archive_event_message())
    assert message is not None

    def fail_record_shard_write(*_args, **_kwargs):
        raise sqlite3.OperationalError("manifest write failed")

    monkeypatch.setattr(runner, "record_shard_write", fail_record_shard_write)

    with pytest.raises(sqlite3.OperationalError, match="manifest write failed"):
        runner._persist_archive_message_to_storage(
            config,
            message,
            tracked_db_path=config.storage.db_path,
        )

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        link_count = manifest.execute(
            "SELECT COUNT(*) FROM tracked_db_links WHERE status = 'active'"
        ).fetchone()[0]
    finally:
        manifest.close()

    assert link_count == 0


@pytest.mark.asyncio
async def test_tracked_persist_relinks_existing_archive_row(monkeypatch, tmp_path: Path):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    msg = make_archive_event_message(
        sender_id=config.targets[0].tracked_user_ids[0],
        text="archive copy",
    )
    archive_msg = runner._archive_message_from_telegram(msg)
    assert archive_msg is not None
    runner._persist_archive_message_to_storage(
        config,
        archive_msg,
        tracked_db_path=config.storage.db_path,
    )

    tracked = storage.connect(config.storage.db_path)
    storage.ensure_schema(tracked)
    storage.persist_message(
        tracked,
        storage.StoredMessage(
            chat_id=msg.chat_id,
            message_id=msg.id,
            sender_id=msg.sender_id,
            date=msg.date,
            text="tracked payload",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()

    calls: list[object] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(runner.asyncio, "to_thread", fake_to_thread)

    await runner._relink_archive_message_after_tracked_persist(
        config,
        msg,
        storage.StoredMessage(
            chat_id=msg.chat_id,
            message_id=msg.id,
            sender_id=msg.sender_id,
            date=msg.date,
            text="tracked payload",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
    )

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        row = conn.execute(
            """
            SELECT text, raw_text, payload_mode, tracked_message_chat_id,
                   tracked_message_id
            FROM archive_messages
            WHERE chat_id = ? AND message_id = ?
            """,
            (msg.chat_id, msg.id),
        ).fetchone()
    finally:
        conn.close()

    assert row == (None, None, "tracked_ref", msg.chat_id, msg.id)
    assert calls == [runner._persist_archive_message_to_storage]


@pytest.mark.asyncio
@pytest.mark.parametrize("topic_id", [20, None])
async def test_tracked_persist_relink_respects_topic_scope(
    monkeypatch,
    tmp_path: Path,
    topic_id: int | None,
):
    config = enable_full_archive(
        build_config(tmp_path),
        tmp_path,
        capture_scope="topics",
        topic_ids=(10,),
    )
    msg = make_archive_event_message(
        message_id=9,
        topic_id=topic_id,
        sender_id=config.targets[0].tracked_user_ids[0],
        text="tracked message outside archive topic",
    )
    tracked_message = storage.StoredMessage(
        chat_id=msg.chat_id,
        message_id=msg.id,
        sender_id=msg.sender_id,
        date=msg.date,
        text="tracked payload outside topic",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
    )
    tracked = storage.connect(config.storage.db_path)
    storage.ensure_schema(tracked)
    try:
        storage.persist_message(tracked, tracked_message, [])
    finally:
        tracked.close()

    calls: list[object] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(runner.asyncio, "to_thread", fake_to_thread)

    await runner._relink_archive_message_after_tracked_persist(
        config,
        msg,
        tracked_message,
    )

    assert calls == []
    assert not config.full_archive.root_dir.exists()


@pytest.mark.asyncio
async def test_archive_relink_scheduler_tracks_task_until_done(monkeypatch, tmp_path: Path):
    disabled_config = build_config(tmp_path)
    config = enable_full_archive(disabled_config, tmp_path)
    msg = make_archive_event_message(
        sender_id=config.targets[0].tracked_user_ids[0],
        text="tracked payload",
    )
    stored = storage.StoredMessage(
        chat_id=msg.chat_id,
        message_id=msg.id,
        sender_id=msg.sender_id,
        date=msg.date,
        text="tracked payload",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
    )
    disabled_tasks: set[asyncio.Task[None]] = set()

    assert (
        runner._schedule_archive_relink_after_tracked_persist(
            disabled_config,
            msg,
            stored,
            task_set=disabled_tasks,
        )
        is None
    )
    assert disabled_tasks == set()

    relink_started = asyncio.Event()
    release_relink = asyncio.Event()

    async def fake_relink(*_args, **_kwargs):
        relink_started.set()
        await release_relink.wait()

    monkeypatch.setattr(
        runner,
        "_relink_archive_message_after_tracked_persist",
        fake_relink,
    )

    pending_tasks: set[asyncio.Task[None]] = set()
    task = runner._schedule_archive_relink_after_tracked_persist(
        config,
        msg,
        stored,
        task_set=pending_tasks,
    )

    assert task is not None
    assert task in pending_tasks
    await asyncio.wait_for(relink_started.wait(), timeout=0.2)
    assert task in pending_tasks

    release_relink.set()
    await asyncio.wait_for(task, timeout=0.2)
    await asyncio.sleep(0)
    assert task not in pending_tasks


@pytest.mark.asyncio
async def test_tracked_handler_drain_archive_relinks_waits_for_pending_task(
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._TargetHandler(config, SimpleNamespace(), config.targets[0])
    release_relink = asyncio.Event()

    async def pending_relink() -> None:
        await release_relink.wait()

    task = asyncio.create_task(pending_relink())
    handler._archive_relink_tasks.add(task)
    task.add_done_callback(handler._archive_relink_tasks.discard)

    release_relink.set()
    pending_count = await handler.drain_archive_relinks(timeout=0.2)

    assert pending_count == 0
    assert task.done()
    assert task not in handler._archive_relink_tasks


@pytest.mark.asyncio
async def test_tracked_handler_drain_archive_relinks_warns_on_timeout(
    tmp_path: Path,
    caplog,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._TargetHandler(config, SimpleNamespace(), config.targets[0])
    release_relink = asyncio.Event()

    async def pending_relink() -> None:
        await release_relink.wait()

    task = asyncio.create_task(pending_relink())
    handler._archive_relink_tasks.add(task)
    task.add_done_callback(handler._archive_relink_tasks.discard)

    with caplog.at_level(logging.WARNING):
        pending_count = await handler.drain_archive_relinks(timeout=0.01)

    assert pending_count == 1
    assert task in handler._archive_relink_tasks
    assert "Full archive relink still pending at shutdown" in caplog.text

    release_relink.set()
    await asyncio.wait_for(task, timeout=0.2)
    await asyncio.sleep(0)
    assert task not in handler._archive_relink_tasks


@pytest.mark.asyncio
async def test_tracked_handler_drain_archive_relinks_handles_cancelled_task(
    tmp_path: Path,
    caplog,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._TargetHandler(config, SimpleNamespace(), config.targets[0])

    async def pending_relink() -> None:
        await asyncio.sleep(10)

    task = asyncio.create_task(pending_relink())
    handler._archive_relink_tasks.add(task)
    task.add_done_callback(handler._archive_relink_tasks.discard)
    task.cancel()

    with caplog.at_level(logging.WARNING):
        pending_count = await handler.drain_archive_relinks(timeout=0.2)

    assert pending_count == 0
    assert task.cancelled()
    assert task not in handler._archive_relink_tasks
    assert "Full archive relink task was cancelled during shutdown" in caplog.text


@pytest.mark.asyncio
async def test_tracked_handler_continues_realtime_after_archive_relink_error(
    monkeypatch,
    tmp_path: Path,
    caplog,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    queue: asyncio.Queue[tuple[DbMessage, TargetGroupConfig]] = asyncio.Queue()
    handler = runner._TargetHandler(
        config,
        SimpleNamespace(),
        config.targets[0],
        realtime_queue=queue,
    )
    msg = make_archive_event_message(
        sender_id=config.targets[0].tracked_user_ids[0],
        text="tracked payload",
    )

    async def fake_capture_message(_client, _config, message, *, chat_id_default=None):
        return (
            storage.StoredMessage(
                chat_id=int(getattr(message, "chat_id", chat_id_default or 0)),
                message_id=int(message.id),
                sender_id=int(message.sender_id),
                date=message.date,
                text="tracked payload",
                reply_to_msg_id=None,
                replied_sender_id=None,
                replied_date=None,
                replied_text=None,
            ),
            [],
        )

    def fail_archive_persist(*_args, **_kwargs):
        raise OSError("archive unavailable")

    created_tasks: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def record_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(runner, "_capture_message", fake_capture_message)
    monkeypatch.setattr(
        runner,
        "_persist_archive_message_to_storage",
        fail_archive_persist,
    )
    monkeypatch.setattr(runner.asyncio, "create_task", record_create_task)

    with caplog.at_level(logging.WARNING):
        await handler.handle(SimpleNamespace(message=msg))
        await asyncio.gather(*created_tasks)

    with storage.db_session(config.storage.db_path) as conn:
        db_row = conn.execute(
            """
            SELECT text
            FROM messages
            WHERE chat_id = ? AND message_id = ?
            """,
            (msg.chat_id, msg.id),
        ).fetchone()

    queued_message, queued_target = queue.get_nowait()
    assert db_row is not None
    assert db_row["text"] == "tracked payload"
    assert queued_message.message_id == msg.id
    assert queued_message.text == "tracked payload"
    assert queued_target == config.targets[0]
    assert "Full archive relink failed after tracked persist" in caplog.text


@pytest.mark.asyncio
async def test_tracked_handler_does_not_wait_for_archive_relink_before_realtime(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    queue: asyncio.Queue[tuple[DbMessage, TargetGroupConfig]] = asyncio.Queue()
    handler = runner._TargetHandler(
        config,
        SimpleNamespace(),
        config.targets[0],
        realtime_queue=queue,
    )
    msg = make_archive_event_message(
        sender_id=config.targets[0].tracked_user_ids[0],
        text="tracked payload",
    )
    relink_started = asyncio.Event()
    release_relink = asyncio.Event()
    created_tasks: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    async def fake_capture_message(_client, _config, message, *, chat_id_default=None):
        return (
            storage.StoredMessage(
                chat_id=int(getattr(message, "chat_id", chat_id_default or 0)),
                message_id=int(message.id),
                sender_id=int(message.sender_id),
                date=message.date,
                text="tracked payload",
                reply_to_msg_id=None,
                replied_sender_id=None,
                replied_date=None,
                replied_text=None,
            ),
            [],
        )

    async def hanging_relink(*_args, **_kwargs):
        relink_started.set()
        await release_relink.wait()

    def record_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(runner, "_capture_message", fake_capture_message)
    monkeypatch.setattr(
        runner,
        "_relink_archive_message_after_tracked_persist",
        hanging_relink,
    )
    monkeypatch.setattr(runner.asyncio, "create_task", record_create_task)

    await asyncio.wait_for(handler.handle(SimpleNamespace(message=msg)), timeout=0.2)

    queued_message, queued_target = queue.get_nowait()
    assert queued_message.message_id == msg.id
    assert queued_target == config.targets[0]
    assert relink_started.is_set() or created_tasks

    release_relink.set()
    await asyncio.gather(*created_tasks)


@pytest.mark.asyncio
async def test_full_archive_then_tracked_handler_relinks_without_duplicate_payload(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    msg = make_archive_event_message(
        sender_id=config.targets[0].tracked_user_ids[0],
        text="archive duplicate",
        media=SimpleNamespace(document=SimpleNamespace(mime_type="image/png", size=456)),
        file=SimpleNamespace(mime_type="image/png", size=456, name="chart.png"),
    )
    full_archive_handler = runner._FullArchiveHandler(config)
    target_handler = runner._TargetHandler(
        config,
        SimpleNamespace(),
        config.targets[0],
    )

    async def immediate_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    async def fake_capture_message(_client, _config, message, *, chat_id_default=None):
        return (
            storage.StoredMessage(
                chat_id=int(getattr(message, "chat_id", chat_id_default or 0)),
                message_id=int(message.id),
                sender_id=int(message.sender_id),
                date=message.date,
                text="tracked payload",
                reply_to_msg_id=None,
                replied_sender_id=None,
                replied_date=None,
                replied_text=None,
            ),
            [],
        )

    created_tasks: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def record_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(runner.asyncio, "to_thread", immediate_to_thread)
    monkeypatch.setattr(runner, "_capture_message", fake_capture_message)
    monkeypatch.setattr(runner.asyncio, "create_task", record_create_task)

    await full_archive_handler.handle(SimpleNamespace(message=msg))
    await target_handler.handle(SimpleNamespace(message=msg))
    await asyncio.gather(*created_tasks)

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        row = conn.execute(
            """
            SELECT text, raw_text, payload_mode, tracked_message_chat_id,
                   tracked_message_id
            FROM archive_messages
            WHERE chat_id = ? AND message_id = ?
            """,
            (msg.chat_id, msg.id),
        ).fetchone()
        media_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM archive_media
            WHERE chat_id = ? AND message_id = ?
            """,
            (msg.chat_id, msg.id),
        ).fetchone()[0]
        link_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM archive_tracked_links
            WHERE chat_id = ? AND message_id = ?
            """,
            (msg.chat_id, msg.id),
        ).fetchone()[0]
    finally:
        conn.close()

    assert tuple(row) == (None, None, "tracked_ref", msg.chat_id, msg.id)
    assert media_count == 0
    assert link_count == 1


@pytest.mark.asyncio
async def test_tracked_then_full_archive_handler_keeps_tracked_ref_idempotent(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    msg = make_archive_event_message(
        sender_id=config.targets[0].tracked_user_ids[0],
        text="archive duplicate",
        media=SimpleNamespace(document=SimpleNamespace(mime_type="image/png", size=456)),
        file=SimpleNamespace(mime_type="image/png", size=456, name="chart.png"),
    )
    full_archive_handler = runner._FullArchiveHandler(config)
    target_handler = runner._TargetHandler(
        config,
        SimpleNamespace(),
        config.targets[0],
    )

    async def immediate_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    async def fake_capture_message(_client, _config, message, *, chat_id_default=None):
        return (
            storage.StoredMessage(
                chat_id=int(getattr(message, "chat_id", chat_id_default or 0)),
                message_id=int(message.id),
                sender_id=int(message.sender_id),
                date=message.date,
                text="tracked payload",
                reply_to_msg_id=None,
                replied_sender_id=None,
                replied_date=None,
                replied_text=None,
            ),
            [],
        )

    created_tasks: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def record_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(runner.asyncio, "to_thread", immediate_to_thread)
    monkeypatch.setattr(runner, "_capture_message", fake_capture_message)
    monkeypatch.setattr(runner.asyncio, "create_task", record_create_task)

    await target_handler.handle(SimpleNamespace(message=msg))
    await asyncio.gather(*created_tasks)
    await full_archive_handler.handle(SimpleNamespace(message=msg))

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        row = conn.execute(
            """
            SELECT text, raw_text, payload_mode, tracked_message_chat_id,
                   tracked_message_id
            FROM archive_messages
            WHERE chat_id = ? AND message_id = ?
            """,
            (msg.chat_id, msg.id),
        ).fetchone()
        media_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM archive_media
            WHERE chat_id = ? AND message_id = ?
            """,
            (msg.chat_id, msg.id),
        ).fetchone()[0]
        link_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM archive_tracked_links
            WHERE chat_id = ? AND message_id = ?
            """,
            (msg.chat_id, msg.id),
        ).fetchone()[0]
    finally:
        conn.close()

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_count = manifest.execute(
            "SELECT message_count FROM archive_shards"
        ).fetchone()[0]
    finally:
        manifest.close()

    assert tuple(row) == (None, None, "tracked_ref", msg.chat_id, msg.id)
    assert media_count == 0
    assert link_count == 1
    assert manifest_count == 1


@pytest.mark.asyncio
async def test_full_archive_handler_updates_archive_row_for_edited_message(
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)
    original = make_archive_event_message(message_id=7, text="before edit")
    edited = make_archive_event_message(message_id=7, text="after edit")

    await handler.handle(SimpleNamespace(message=original))
    await handler.handle(SimpleNamespace(message=edited))

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        row = conn.execute(
            """
            SELECT text, raw_text, payload_mode
            FROM archive_messages
            WHERE chat_id = ? AND message_id = ?
            """,
            (original.chat_id, original.id),
        ).fetchone()
    finally:
        conn.close()
    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_count = manifest.execute(
            "SELECT message_count FROM archive_shards"
        ).fetchone()[0]
    finally:
        manifest.close()

    assert row == ("after edit", "after edit", "archive")
    assert manifest_count == 1


@pytest.mark.asyncio
async def test_full_archive_edited_message_preserves_tracked_ref_without_duplicate_payload(
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    handler = runner._FullArchiveHandler(config)
    tracked = storage.connect(config.storage.db_path)
    storage.ensure_schema(tracked)
    try:
        storage.persist_message(
            tracked,
            storage.StoredMessage(
                chat_id=config.full_archive.source_chat_id or config.targets[0].target_chat_id,
                message_id=8,
                sender_id=config.targets[0].tracked_user_ids[0],
                date=datetime(2026, 5, 1, 12, 8, tzinfo=timezone.utc),
                text="tracked payload",
                reply_to_msg_id=None,
                replied_sender_id=None,
                replied_date=None,
                replied_text=None,
            ),
            [],
        )
    finally:
        tracked.close()

    original = make_archive_event_message(
        message_id=8,
        sender_id=config.targets[0].tracked_user_ids[0],
        text="archive duplicate before edit",
        media=SimpleNamespace(document=SimpleNamespace(mime_type="image/png", size=456)),
        file=SimpleNamespace(mime_type="image/png", size=456, name="before.png"),
    )
    edited = make_archive_event_message(
        message_id=8,
        sender_id=config.targets[0].tracked_user_ids[0],
        text="archive duplicate after edit",
        media=SimpleNamespace(document=SimpleNamespace(mime_type="image/png", size=789)),
        file=SimpleNamespace(mime_type="image/png", size=789, name="after.png"),
    )

    await handler.handle(SimpleNamespace(message=original))
    await handler.handle(SimpleNamespace(message=edited))

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        row = conn.execute(
            """
            SELECT text, raw_text, payload_mode, tracked_message_chat_id,
                   tracked_message_id
            FROM archive_messages
            WHERE chat_id = ? AND message_id = ?
            """,
            (original.chat_id, original.id),
        ).fetchone()
        media_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM archive_media
            WHERE chat_id = ? AND message_id = ?
            """,
            (original.chat_id, original.id),
        ).fetchone()[0]
    finally:
        conn.close()
    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_count = manifest.execute(
            "SELECT message_count FROM archive_shards"
        ).fetchone()[0]
    finally:
        manifest.close()

    assert tuple(row) == (None, None, "tracked_ref", original.chat_id, original.id)
    assert media_count == 0
    assert manifest_count == 1


@pytest.mark.asyncio
async def test_run_daemon_registers_full_archive_handler_when_enabled(
    monkeypatch, tmp_path: Path
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    config = replace(
        config,
        notifications=NotificationConfig(
            bark_key=None,
            heartbeat_interval_hours=0,
            check_updates=False,
        ),
    )
    handlers = []

    class DummyClient:
        def add_event_handler(self, callback, event):
            handlers.append((callback, event))

        async def get_me(self):
            return SimpleNamespace(id=42, username="me")

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    async def fake_run_with_reconnect(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner, "_run_with_reconnect", fake_run_with_reconnect)

    health_path = tmp_path / "run.health.json"
    await runner.run_daemon(config, health_path=health_path)

    archive_events = [
        event
        for callback, event in handlers
        if isinstance(getattr(callback, "__self__", None), runner._FullArchiveHandler)
    ]
    assert len(archive_events) == 2
    assert any(isinstance(event, runner.events.NewMessage) for event in archive_events)
    assert any(
        isinstance(event, runner.events.MessageEdited) for event in archive_events
    )
    health = json.loads(health_path.read_text(encoding="utf-8"))
    assert health["full_archive"] == {
        "configured": True,
        "runtime_enabled": True,
        "status": "active",
    }


def test_full_archive_runtime_migrates_sender_only_schema_before_health_gate(
    tmp_path: Path,
    caplog,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    tracked = storage.connect(config.storage.db_path)
    try:
        storage.ensure_schema(tracked)
    finally:
        tracked.close()
    archive_message = runner._archive_message_from_telegram(
        make_archive_event_message(sender_id=999)
    )
    assert archive_message is not None
    runner._persist_archive_message_to_storage(
        config,
        archive_message,
        tracked_db_path=config.storage.db_path,
    )
    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    shard = sqlite3.connect(shard_path)
    try:
        shard.execute("DROP TABLE archive_senders")
        shard.commit()
    finally:
        shard.close()

    before = runner.inspect_archive_status(
        config.full_archive.root_dir,
        tracked_db_path=config.storage.db_path,
    )
    assert before.degraded is True
    assert runner.only_archive_sender_schema_missing(before) is True

    with caplog.at_level(logging.INFO):
        enabled = runner._full_archive_runtime_enabled(config)

    after = runner.inspect_archive_status(
        config.full_archive.root_dir,
        tracked_db_path=config.storage.db_path,
    )
    assert enabled is True
    assert after.degraded is False
    assert "Added archive_senders table to 1 existing full archive shard" in caplog.text


@pytest.mark.asyncio
async def test_run_daemon_skips_full_archive_handlers_when_archive_degraded(
    monkeypatch,
    tmp_path: Path,
    caplog,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    config = replace(
        config,
        notifications=NotificationConfig(
            bark_key=None,
            heartbeat_interval_hours=0,
            check_updates=False,
        ),
    )
    handlers = []

    class DummyClient:
        def add_event_handler(self, callback, event):
            handlers.append((callback, event))

        async def get_me(self):
            return SimpleNamespace(id=42, username="me")

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    async def fake_run_with_reconnect(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner, "_run_with_reconnect", fake_run_with_reconnect)
    monkeypatch.setattr(
        runner,
        "inspect_archive_status",
        lambda *_args, **_kwargs: SimpleNamespace(
            degraded=True,
            shards=(),
            errors=("hidden shard data",),
        ),
    )

    with caplog.at_level(logging.WARNING):
        health_path = tmp_path / "run.health.json"
        await runner.run_daemon(config, health_path=health_path)

    target_handlers = [
        getattr(callback, "__self__", None)
        for callback, _event in handlers
        if isinstance(getattr(callback, "__self__", None), runner._TargetHandler)
    ]
    assert len(target_handlers) == 1
    assert target_handlers[0]._archive_relink_enabled is False
    assert not any(
        isinstance(getattr(callback, "__self__", None), runner._FullArchiveHandler)
        for callback, _event in handlers
    )
    assert "Full archive live capture disabled" in caplog.text
    assert "hidden shard data" in caplog.text
    health = json.loads(health_path.read_text(encoding="utf-8"))
    assert health["full_archive"] == {
        "configured": True,
        "runtime_enabled": False,
        "status": "degraded",
    }


@pytest.mark.asyncio
async def test_run_daemon_does_not_register_full_archive_handler_when_disabled(
    monkeypatch, tmp_path: Path
):
    config = replace(
        build_config(tmp_path),
        notifications=NotificationConfig(
            bark_key=None,
            heartbeat_interval_hours=0,
            check_updates=False,
        ),
    )
    handlers = []

    class DummyClient:
        def add_event_handler(self, callback, event):
            handlers.append((callback, event))

        async def get_me(self):
            return SimpleNamespace(id=42, username="me")

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    async def fake_run_with_reconnect(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner, "_run_with_reconnect", fake_run_with_reconnect)

    await runner.run_daemon(config)

    assert not any(
        isinstance(getattr(callback, "__self__", None), runner._FullArchiveHandler)
        for callback, _event in handlers
    )


@pytest.mark.asyncio
async def test_archive_backfill_dry_run_scans_without_writing(
    monkeypatch, tmp_path: Path
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    messages = [
        make_archive_event_message(message_id=1, text="a"),
        make_archive_event_message(message_id=2, text="b"),
    ]

    class DummyClient:
        def iter_messages(self, chat_id, *, limit=None, offset_id=0, wait_time=None):
            assert chat_id == config.full_archive.source_chat_id
            assert limit == config.full_archive.backfill_limit_messages
            assert offset_id == 0
            assert wait_time == runner.ARCHIVE_BACKFILL_WAIT_TIME_SECONDS

            async def gen():
                for message in messages:
                    yield message

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    stats = await runner.run_archive_backfill(config)

    assert stats.scanned == 2
    assert stats.matched == 2
    assert stats.archived == 0
    assert stats.dry_run is True
    assert not config.full_archive.root_dir.exists()


@pytest.mark.asyncio
async def test_archive_backfill_zero_limit_is_noop_without_telegram(
    monkeypatch, tmp_path: Path
):
    config = enable_full_archive(
        build_config(tmp_path),
        tmp_path,
        backfill_limit_messages=0,
    )

    def fail_build_client(_config):
        raise AssertionError("zero-limit backfill must not connect to Telegram")

    monkeypatch.setattr(runner, "_build_client", fail_build_client)

    stats = await runner.run_archive_backfill(config)

    assert stats.scanned == 0
    assert stats.matched == 0
    assert stats.archived == 0
    assert stats.linked == 0
    assert stats.dry_run is True
    assert not config.full_archive.root_dir.exists()


@pytest.mark.asyncio
async def test_archive_backfill_explicit_zero_limit_is_noop_without_telegram(
    monkeypatch, tmp_path: Path
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)

    def fail_build_client(_config):
        raise AssertionError("zero-limit backfill must not connect to Telegram")

    monkeypatch.setattr(runner, "_build_client", fail_build_client)

    stats = await runner.run_archive_backfill(config, limit=0, apply=True)

    assert stats.scanned == 0
    assert stats.matched == 0
    assert stats.archived == 0
    assert stats.linked == 0
    assert stats.dry_run is False
    assert not config.full_archive.root_dir.exists()


@pytest.mark.asyncio
async def test_archive_backfill_apply_writes_archive_rows(monkeypatch, tmp_path: Path):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    messages = [
        make_archive_event_message(message_id=1, text="a"),
        make_archive_event_message(message_id=2, text="b"),
    ]

    class DummyClient:
        def iter_messages(self, _chat_id, *, limit=None, offset_id=0, wait_time=None):
            assert limit == 1
            assert offset_id == 0
            assert wait_time is None

            async def gen():
                for message in messages:
                    yield message

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    stats = await runner.run_archive_backfill(config, limit=1, apply=True)

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    conn = sqlite3.connect(shard_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM archive_messages").fetchone()[0]
    finally:
        conn.close()

    assert stats.scanned == 1
    assert stats.matched == 1
    assert stats.archived == 1
    assert count == 1


def test_archive_persist_recreates_archive_after_root_deletion(tmp_path: Path):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    first = runner._archive_message_from_telegram(
        make_archive_event_message(message_id=1, text="before deletion")
    )
    assert first is not None
    runner._persist_archive_message_to_storage(config, first, tracked_db_path=None)
    assert (config.full_archive.root_dir / "manifest.sqlite3").exists()

    shutil.rmtree(config.full_archive.root_dir)

    second = runner._archive_message_from_telegram(
        make_archive_event_message(message_id=2, text="after deletion")
    )
    assert second is not None
    result = runner._persist_archive_message_to_storage(
        config,
        second,
        tracked_db_path=None,
    )

    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_count = manifest.execute(
            "SELECT SUM(message_count) FROM archive_shards"
        ).fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(shard_path)
    try:
        rows = shard.execute(
            "SELECT message_id, text FROM archive_messages ORDER BY message_id"
        ).fetchall()
    finally:
        shard.close()

    assert result.created is True
    assert manifest_count == 1
    assert rows == [(2, "after deletion")]


def test_archive_persist_does_not_increment_manifest_for_existing_message(
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    message = runner._archive_message_from_telegram(
        make_archive_event_message(message_id=1, text="first")
    )
    duplicate = runner._archive_message_from_telegram(
        make_archive_event_message(message_id=1, text="edited")
    )
    assert message is not None
    assert duplicate is not None

    first = runner._persist_archive_message_to_storage(
        config,
        message,
        tracked_db_path=None,
    )
    second = runner._persist_archive_message_to_storage(
        config,
        duplicate,
        tracked_db_path=None,
    )

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_count = manifest.execute(
            "SELECT SUM(message_count) FROM archive_shards"
        ).fetchone()[0]
        shard_path = manifest.execute("SELECT path FROM archive_shards").fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(config.full_archive.root_dir / shard_path)
    try:
        rows = shard.execute(
            "SELECT message_id, text FROM archive_messages ORDER BY message_id"
        ).fetchall()
    finally:
        shard.close()

    assert first.created is True
    assert second.created is False
    assert manifest_count == 1
    assert rows == [(1, "edited")]


@pytest.mark.asyncio
async def test_archive_backfill_apply_recreates_archive_after_root_deletion(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    tracked_conn = storage.connect(config.storage.db_path)
    try:
        storage.ensure_schema(tracked_conn)
        tracked_conn.execute(
            """
            INSERT INTO messages (
                chat_id, message_id, sender_id, date, text
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                config.full_archive.source_chat_id,
                900,
                111,
                "2026-05-01T11:00:00+00:00",
                "tracked row must survive archive deletion",
            ),
        )
        tracked_conn.commit()
    finally:
        tracked_conn.close()

    batches = [
        [make_archive_event_message(message_id=1, text="before deletion")],
        [make_archive_event_message(message_id=2, text="after deletion")],
    ]

    class DummyClient:
        def __init__(self, messages):
            self.messages = messages

        def iter_messages(self, _chat_id, *, limit=None, offset_id=0, wait_time=None):
            assert limit == 1
            assert offset_id == 0
            assert wait_time is None

            async def gen():
                for message in self.messages:
                    yield message

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    def fake_build_client(_config):
        return DummyClient(batches.pop(0))

    monkeypatch.setattr(runner, "_build_client", fake_build_client)
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    first = await runner.run_archive_backfill(config, limit=1, apply=True)
    assert (config.full_archive.root_dir / "manifest.sqlite3").exists()

    shutil.rmtree(config.full_archive.root_dir)

    tracked_conn = sqlite3.connect(config.storage.db_path)
    try:
        tracked_text = tracked_conn.execute(
            "SELECT text FROM messages WHERE chat_id = ? AND message_id = ?",
            (config.full_archive.source_chat_id, 900),
        ).fetchone()[0]
    finally:
        tracked_conn.close()

    second = await runner.run_archive_backfill(config, limit=1, apply=True)

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_count = manifest.execute(
            "SELECT SUM(message_count) FROM archive_shards"
        ).fetchone()[0]
        shard_path = manifest.execute("SELECT path FROM archive_shards").fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(config.full_archive.root_dir / shard_path)
    try:
        rows = shard.execute(
            "SELECT message_id, text FROM archive_messages ORDER BY message_id"
        ).fetchall()
    finally:
        shard.close()

    assert first.archived == 1
    assert second.archived == 1
    assert tracked_text == "tracked row must survive archive deletion"
    assert manifest_count == 1
    assert rows == [(2, "after deletion")]


@pytest.mark.asyncio
async def test_archive_backfill_after_root_deletion_keeps_tracked_ref_dedup(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    tracked_message = make_archive_event_message(
        message_id=2,
        sender_id=config.targets[0].tracked_user_ids[0],
        text="archive duplicate candidate",
        media=SimpleNamespace(document=SimpleNamespace(mime_type="image/png", size=123)),
        file=SimpleNamespace(mime_type="image/png", size=123, name="chart.png"),
    )
    tracked = storage.connect(config.storage.db_path)
    storage.ensure_schema(tracked)
    try:
        storage.persist_message(
            tracked,
            storage.StoredMessage(
                chat_id=tracked_message.chat_id,
                message_id=tracked_message.id,
                sender_id=tracked_message.sender_id,
                date=tracked_message.date,
                text="tracked payload survives archive reset",
                reply_to_msg_id=None,
                replied_sender_id=None,
                replied_date=None,
                replied_text=None,
            ),
            [],
        )
    finally:
        tracked.close()

    batches = [
        [make_archive_event_message(message_id=1, text="before deletion")],
        [tracked_message],
    ]

    class DummyClient:
        def __init__(self, messages):
            self.messages = messages

        def iter_messages(self, _chat_id, *, limit=None, offset_id=0, wait_time=None):
            assert limit == 1
            assert offset_id == 0
            assert wait_time is None

            async def gen():
                for message in self.messages:
                    yield message

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    def fake_build_client(_config):
        return DummyClient(batches.pop(0))

    monkeypatch.setattr(runner, "_build_client", fake_build_client)
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    first = await runner.run_archive_backfill(config, limit=1, apply=True)
    assert first.archived == 1

    shutil.rmtree(config.full_archive.root_dir)

    second = await runner.run_archive_backfill(config, limit=1, apply=True)

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_count = manifest.execute(
            "SELECT SUM(message_count) FROM archive_shards"
        ).fetchone()[0]
        shard_path = manifest.execute("SELECT path FROM archive_shards").fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(config.full_archive.root_dir / shard_path)
    try:
        row = shard.execute(
            """
            SELECT message_id, payload_mode, text, raw_text,
                   tracked_message_chat_id, tracked_message_id
            FROM archive_messages
            """
        ).fetchone()
        archive_media_count = shard.execute(
            "SELECT COUNT(*) FROM archive_media"
        ).fetchone()[0]
        link_count = shard.execute(
            "SELECT COUNT(*) FROM archive_tracked_links"
        ).fetchone()[0]
    finally:
        shard.close()

    assert second.archived == 0
    assert second.linked == 1
    assert manifest_count == 1
    assert tuple(row) == (
        2,
        "tracked_ref",
        None,
        None,
        tracked_message.chat_id,
        tracked_message.id,
    )
    assert archive_media_count == 0
    assert link_count == 1


@pytest.mark.asyncio
async def test_archive_backfill_skips_invalid_message_and_continues(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    invalid = SimpleNamespace(
        id="not-a-message-id",
        chat_id=config.full_archive.source_chat_id,
        sender_id=999,
        date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        message="bad",
        raw_text="bad",
        media=None,
        file=None,
        action=None,
        reply_to=None,
        reply_to_msg_id=None,
    )
    invalid_date = SimpleNamespace(
        id=1,
        chat_id=config.full_archive.source_chat_id,
        sender_id=999,
        date="not-a-datetime",
        message="bad date",
        raw_text="bad date",
        media=None,
        file=None,
        action=None,
        reply_to=None,
        reply_to_msg_id=None,
    )
    valid = make_archive_event_message(message_id=2, text="after invalid")

    class DummyClient:
        def iter_messages(self, _chat_id, *, limit=None, offset_id=0, wait_time=None):
            assert limit == 3
            assert offset_id == 0
            assert wait_time is None

            async def gen():
                yield invalid
                yield invalid_date
                yield valid

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    stats = await runner.run_archive_backfill(config, limit=3, apply=True)

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_message_count = manifest.execute(
            "SELECT SUM(message_count) FROM archive_shards"
        ).fetchone()[0]
        shard_path = manifest.execute("SELECT path FROM archive_shards").fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(config.full_archive.root_dir / shard_path)
    try:
        row = shard.execute(
            "SELECT message_id, text FROM archive_messages"
        ).fetchone()
    finally:
        shard.close()

    assert stats.scanned == 3
    assert stats.skipped_invalid == 2
    assert stats.matched == 1
    assert stats.archived == 1
    assert manifest_message_count == 1
    assert tuple(row) == (2, "after invalid")


@pytest.mark.asyncio
async def test_archive_backfill_apply_persists_service_messages_without_text(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    service_message = make_archive_event_message(
        message_id=1,
        text="",
        action=SimpleNamespace(type="pin"),
    )

    class DummyClient:
        def iter_messages(self, _chat_id, *, limit=None, offset_id=0, wait_time=None):
            assert limit == 1
            assert offset_id == 0
            assert wait_time is None

            async def gen():
                yield service_message

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    stats = await runner.run_archive_backfill(config, limit=1, apply=True)

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        shard_path = manifest.execute("SELECT path FROM archive_shards").fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(config.full_archive.root_dir / shard_path)
    try:
        row = shard.execute(
            "SELECT message_id, message_kind, text, raw_text FROM archive_messages"
        ).fetchone()
    finally:
        shard.close()

    assert stats.scanned == 1
    assert stats.matched == 1
    assert stats.skipped_invalid == 0
    assert stats.archived == 1
    assert tuple(row) == (1, "service", "", "")


@pytest.mark.asyncio
async def test_archive_backfill_apply_is_idempotent(monkeypatch, tmp_path: Path):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    message = make_archive_event_message(message_id=1, text="context")

    class DummyClient:
        def iter_messages(self, _chat_id, *, limit=None, offset_id=0, wait_time=None):
            assert limit == 1
            assert offset_id == 0
            assert wait_time is None

            async def gen():
                yield message

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    first = await runner.run_archive_backfill(config, limit=1, apply=True)
    second = await runner.run_archive_backfill(config, limit=1, apply=True)

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_message_count = manifest.execute(
            "SELECT SUM(message_count) FROM archive_shards"
        ).fetchone()[0]
        tracked_db_link_count = manifest.execute(
            "SELECT COUNT(*) FROM tracked_db_links WHERE status = 'active'"
        ).fetchone()[0]
        shard_path = manifest.execute("SELECT path FROM archive_shards").fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(config.full_archive.root_dir / shard_path)
    try:
        archive_row_count = shard.execute(
            "SELECT COUNT(*) FROM archive_messages"
        ).fetchone()[0]
    finally:
        shard.close()

    assert first.scanned == second.scanned == 1
    assert first.matched == second.matched == 1
    assert first.archived == 1
    assert first.updated == 0
    assert second.archived == 0
    assert second.linked == 0
    assert second.updated == 1
    assert archive_row_count == 1
    assert manifest_message_count == 1
    assert tracked_db_link_count == 1


@pytest.mark.asyncio
async def test_archive_backfill_counts_first_tracked_ref_as_tracked_link(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    message = make_archive_event_message(
        message_id=1,
        sender_id=config.targets[0].tracked_user_ids[0],
        text="duplicate archive candidate",
    )
    tracked = storage.connect(config.storage.db_path)
    storage.ensure_schema(tracked)
    try:
        storage.persist_message(
            tracked,
            storage.StoredMessage(
                chat_id=message.chat_id,
                message_id=message.id,
                sender_id=message.sender_id,
                date=message.date,
                text="tracked payload",
                reply_to_msg_id=None,
                replied_sender_id=None,
                replied_date=None,
                replied_text=None,
            ),
            [],
        )
    finally:
        tracked.close()

    class DummyClient:
        def iter_messages(self, _chat_id, *, limit=None, offset_id=0, wait_time=None):
            assert limit == 1
            assert offset_id == 0
            assert wait_time is None

            async def gen():
                yield message

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    stats = await runner.run_archive_backfill(config, limit=1, apply=True)

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_message_count = manifest.execute(
            "SELECT SUM(message_count) FROM archive_shards"
        ).fetchone()[0]
        shard_path = manifest.execute("SELECT path FROM archive_shards").fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(config.full_archive.root_dir / shard_path)
    try:
        row = shard.execute(
            """
            SELECT payload_mode, text, raw_text
            FROM archive_messages
            WHERE chat_id = ? AND message_id = ?
            """,
            (message.chat_id, message.id),
        ).fetchone()
        archive_row_count = shard.execute(
            "SELECT COUNT(*) FROM archive_messages"
        ).fetchone()[0]
        link_count = shard.execute(
            "SELECT COUNT(*) FROM archive_tracked_links"
        ).fetchone()[0]
    finally:
        shard.close()

    assert stats.scanned == 1
    assert stats.matched == 1
    assert stats.archived == 0
    assert stats.updated == 0
    assert stats.linked == 1
    assert tuple(row) == ("tracked_ref", None, None)
    assert archive_row_count == 1
    assert manifest_message_count == 1
    assert link_count == 1


@pytest.mark.asyncio
async def test_archive_backfill_counts_existing_archive_row_relink_as_tracked_link(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    message = make_archive_event_message(
        message_id=1,
        sender_id=config.targets[0].tracked_user_ids[0],
        text="context before tracked DB",
    )

    initial = runner._archive_message_from_telegram(message)
    assert initial is not None
    runner._persist_archive_message_to_storage(
        config,
        initial,
        tracked_db_path=config.storage.db_path,
    )

    tracked = storage.connect(config.storage.db_path)
    storage.ensure_schema(tracked)
    try:
        storage.persist_message(
            tracked,
            storage.StoredMessage(
                chat_id=message.chat_id,
                message_id=message.id,
                sender_id=message.sender_id,
                date=message.date,
                text="tracked payload",
                reply_to_msg_id=None,
                replied_sender_id=None,
                replied_date=None,
                replied_text=None,
            ),
            [],
        )
    finally:
        tracked.close()

    class DummyClient:
        def iter_messages(self, _chat_id, *, limit=None, offset_id=0, wait_time=None):
            assert limit == 1
            assert offset_id == 0
            assert wait_time is None

            async def gen():
                yield message

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    stats = await runner.run_archive_backfill(config, limit=1, apply=True)

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_message_count = manifest.execute(
            "SELECT SUM(message_count) FROM archive_shards"
        ).fetchone()[0]
        shard_path = manifest.execute("SELECT path FROM archive_shards").fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(config.full_archive.root_dir / shard_path)
    try:
        row = shard.execute(
            """
            SELECT payload_mode, text, raw_text
            FROM archive_messages
            WHERE chat_id = ? AND message_id = ?
            """,
            (message.chat_id, message.id),
        ).fetchone()
        archive_row_count = shard.execute(
            "SELECT COUNT(*) FROM archive_messages"
        ).fetchone()[0]
        link_count = shard.execute(
            "SELECT COUNT(*) FROM archive_tracked_links"
        ).fetchone()[0]
    finally:
        shard.close()

    assert stats.scanned == 1
    assert stats.matched == 1
    assert stats.archived == 0
    assert stats.updated == 0
    assert stats.linked == 1
    assert tuple(row) == ("tracked_ref", None, None)
    assert archive_row_count == 1
    assert manifest_message_count == 1
    assert link_count == 1


@pytest.mark.asyncio
async def test_archive_backfill_topic_scope_matches_live_capture(
    monkeypatch, tmp_path: Path
):
    config = enable_full_archive(
        build_config(tmp_path),
        tmp_path,
        capture_scope="topics",
        topic_ids=(10,),
    )
    messages = [
        make_archive_event_message(message_id=1, topic_id=10),
        make_archive_event_message(message_id=2, topic_id=20),
        make_archive_event_message(message_id=3, text="general or unknown topic"),
    ]

    class DummyClient:
        def iter_messages(self, _chat_id, *, limit=None, offset_id=0, wait_time=None):
            assert offset_id == 0
            assert wait_time == runner.ARCHIVE_BACKFILL_WAIT_TIME_SECONDS

            async def gen():
                for message in messages:
                    yield message

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    stats = await runner.run_archive_backfill(config, apply=True)

    assert stats.scanned == 3
    assert stats.matched == 1
    assert stats.skipped_scope == 2

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        shard_path = manifest.execute("SELECT path FROM archive_shards").fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(config.full_archive.root_dir / shard_path)
    try:
        rows = shard.execute(
            "SELECT message_id, topic_id FROM archive_messages ORDER BY message_id"
        ).fetchall()
    finally:
        shard.close()

    assert [tuple(row) for row in rows] == [(1, 10)]


@pytest.mark.asyncio
async def test_archive_backfill_resumes_after_floodwait(
    monkeypatch, tmp_path: Path
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    first = make_archive_event_message(message_id=10, text="newer")
    second = make_archive_event_message(message_id=9, text="older")
    calls: list[tuple[int | None, int, float | None]] = []
    sleeps: list[float] = []

    class DummyClient:
        def iter_messages(self, _chat_id, *, limit=None, offset_id=0, wait_time=None):
            calls.append((limit, offset_id, wait_time))

            async def gen():
                if len(calls) == 1:
                    yield first
                    raise errors.FloodWaitError(None, 0)
                yield second

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner.asyncio, "sleep", fake_sleep)

    stats = await runner.run_archive_backfill(config, limit=2)

    assert calls == [
        (2, 0, None),
        (1, 10, runner.ARCHIVE_BACKFILL_WAIT_TIME_SECONDS),
    ]
    assert sleeps == [1]
    assert stats.scanned == 2
    assert stats.matched == 2
    assert stats.dry_run is True
    assert not config.full_archive.root_dir.exists()


@pytest.mark.asyncio
async def test_archive_backfill_apply_after_floodwait_keeps_counts_exact(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    first = make_archive_event_message(message_id=10, text="newer")
    second = make_archive_event_message(message_id=9, text="older")
    calls: list[tuple[int | None, int, float | None]] = []

    class DummyClient:
        def iter_messages(self, _chat_id, *, limit=None, offset_id=0, wait_time=None):
            calls.append((limit, offset_id, wait_time))

            async def gen():
                if len(calls) == 1:
                    yield first
                    raise errors.FloodWaitError(None, 0)
                yield second

            return gen()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner.asyncio, "sleep", fake_sleep)

    stats = await runner.run_archive_backfill(config, limit=2, apply=True)

    manifest = sqlite3.connect(config.full_archive.root_dir / "manifest.sqlite3")
    try:
        manifest_message_count = manifest.execute(
            "SELECT SUM(message_count) FROM archive_shards"
        ).fetchone()[0]
        shard_path = manifest.execute("SELECT path FROM archive_shards").fetchone()[0]
    finally:
        manifest.close()
    shard = sqlite3.connect(config.full_archive.root_dir / shard_path)
    try:
        archive_rows = shard.execute(
            "SELECT message_id, text FROM archive_messages ORDER BY message_id DESC"
        ).fetchall()
    finally:
        shard.close()

    assert calls == [
        (2, 0, None),
        (1, 10, runner.ARCHIVE_BACKFILL_WAIT_TIME_SECONDS),
    ]
    assert stats.scanned == 2
    assert stats.matched == 2
    assert stats.archived == 2
    assert stats.updated == 0
    assert manifest_message_count == 2
    assert [tuple(row) for row in archive_rows] == [(10, "newer"), (9, "older")]


@pytest.mark.asyncio
async def test_archive_backfill_requires_full_archive_enabled(tmp_path: Path):
    with pytest.raises(ValueError):
        await runner.run_archive_backfill(build_config(tmp_path), apply=True)


@pytest.mark.asyncio
async def test_archive_senders_backfill_dry_run_does_not_connect_to_telegram(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    archive_message = runner._archive_message_from_telegram(
        make_archive_event_message(sender_id=999)
    )
    assert archive_message is not None
    runner._persist_archive_message_to_storage(
        config,
        archive_message,
        tracked_db_path=config.storage.db_path,
    )
    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    shard = sqlite3.connect(shard_path)
    try:
        shard.execute("DROP TABLE archive_senders")
        shard.commit()
    finally:
        shard.close()

    def fail_build_client(_config):
        raise AssertionError("dry-run sender backfill must not connect to Telegram")

    monkeypatch.setattr(runner, "_build_client", fail_build_client)

    stats = await runner.run_archive_senders_backfill(config)

    assert stats.candidates == 1
    assert stats.schema_updates == 0
    assert stats.written_senders == 0
    assert stats.dry_run is True
    shard = sqlite3.connect(shard_path)
    try:
        sender_table = shard.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("archive_senders",),
        ).fetchone()
    finally:
        shard.close()
    assert sender_table is None


@pytest.mark.asyncio
async def test_archive_senders_backfill_zero_limit_is_noop_without_schema_write(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    archive_message = runner._archive_message_from_telegram(
        make_archive_event_message(sender_id=999)
    )
    assert archive_message is not None
    runner._persist_archive_message_to_storage(
        config,
        archive_message,
        tracked_db_path=config.storage.db_path,
    )
    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    shard = sqlite3.connect(shard_path)
    try:
        shard.execute("DROP TABLE archive_senders")
        shard.commit()
    finally:
        shard.close()

    def fail_build_client(_config):
        raise AssertionError("zero-limit sender backfill must not connect to Telegram")

    monkeypatch.setattr(runner, "_build_client", fail_build_client)

    stats = await runner.run_archive_senders_backfill(config, limit=0, apply=True)

    shard = sqlite3.connect(shard_path)
    try:
        sender_table = shard.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("archive_senders",),
        ).fetchone()
    finally:
        shard.close()

    assert stats.candidates == 0
    assert stats.schema_updates == 0
    assert stats.written_senders == 0
    assert stats.dry_run is False
    assert sender_table is None


@pytest.mark.asyncio
async def test_archive_senders_backfill_reuses_other_shard_without_telegram(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    may_message = runner._archive_message_from_telegram(
        make_archive_event_message(message_id=1, sender_id=999)
    )
    june_event_message = make_archive_event_message(message_id=2, sender_id=999)
    june_event_message.date = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    june_message = runner._archive_message_from_telegram(june_event_message)
    assert may_message is not None
    assert june_message is not None
    runner._persist_archive_message_to_storage(
        config,
        may_message,
        tracked_db_path=config.storage.db_path,
        sender_snapshot=runner.ArchiveSender(
            sender_id=999,
            username="existing_user",
            display_name="Existing User",
            first_seen_at=may_message.date,
            last_seen_at=may_message.date,
        ),
    )
    runner._persist_archive_message_to_storage(
        config,
        june_message,
        tracked_db_path=config.storage.db_path,
    )

    def fail_build_client(_config):
        raise AssertionError("existing archive snapshot must skip Telegram")

    monkeypatch.setattr(runner, "_build_client", fail_build_client)

    stats = await runner.run_archive_senders_backfill(config, apply=True)

    june_shard = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-06.sqlite3"
    )
    conn = sqlite3.connect(june_shard)
    try:
        row = conn.execute(
            "SELECT username, display_name FROM archive_senders WHERE sender_id = ?",
            (999,),
        ).fetchone()
    finally:
        conn.close()

    assert stats.reused == 1
    assert stats.cached == 0
    assert stats.fetched == 0
    assert stats.written_senders == 1
    assert stats.shard_writes == 2
    assert row == ("existing_user", "Existing User")


@pytest.mark.asyncio
async def test_archive_senders_backfill_prefers_session_entity_cache(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    archive_message = runner._archive_message_from_telegram(
        make_archive_event_message(sender_id=999)
    )
    assert archive_message is not None
    runner._persist_archive_message_to_storage(
        config,
        archive_message,
        tracked_db_path=config.storage.db_path,
    )
    shard_path = (
        config.full_archive.root_dir
        / "shards"
        / f"group_{config.full_archive.source_chat_id}"
        / "2026-05.sqlite3"
    )
    shard = sqlite3.connect(shard_path)
    try:
        shard.execute("DROP TABLE archive_senders")
        shard.commit()
    finally:
        shard.close()

    class DummySession:
        def get_cached_sender_identity(self, sender_id):
            assert sender_id == 999
            return runner._ArchiveSenderIdentity(
                username="cached_user",
                display_name="Cached User",
            )

    class DummyClient:
        session = DummySession()

        async def get_messages(self, *_args, **_kwargs):
            raise AssertionError("session cache hit must skip Telegram history")

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    stats = await runner.run_archive_senders_backfill(config, apply=True)

    conn = sqlite3.connect(shard_path)
    try:
        row = conn.execute(
            "SELECT username, display_name FROM archive_senders WHERE sender_id = ?",
            (999,),
        ).fetchone()
    finally:
        conn.close()

    assert stats.schema_updates == 1
    assert stats.cached == 1
    assert stats.fetched == 0
    assert stats.written_senders == 1
    assert stats.shard_writes == 1
    assert row == ("cached_user", "Cached User")


@pytest.mark.asyncio
async def test_archive_senders_backfill_fetches_history_with_floodwait_retry(
    monkeypatch,
    tmp_path: Path,
):
    config = enable_full_archive(build_config(tmp_path), tmp_path)
    archive_message = runner._archive_message_from_telegram(
        make_archive_event_message(sender_id=999)
    )
    assert archive_message is not None
    runner._persist_archive_message_to_storage(
        config,
        archive_message,
        tracked_db_path=config.storage.db_path,
    )
    get_message_calls = 0
    get_sender_calls = 0
    sleeps: list[float] = []

    class DummySession:
        def get_cached_sender_identity(self, sender_id):
            assert sender_id == 999
            return None

    class HistoryMessage:
        async def get_sender(self):
            nonlocal get_sender_calls
            get_sender_calls += 1
            return tl_types.User(
                id=999,
                first_name="History",
                last_name="User",
                username="history_user",
            )

    class DummyClient:
        session = DummySession()

        async def get_messages(self, chat_id, *, ids):
            nonlocal get_message_calls
            assert chat_id == config.full_archive.source_chat_id
            assert ids == archive_message.message_id
            get_message_calls += 1
            if get_message_calls == 1:
                raise errors.FloodWaitError(None, 0)
            return HistoryMessage()

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner.asyncio, "sleep", fake_sleep)

    stats = await runner.run_archive_senders_backfill(config, apply=True)

    assert get_message_calls == 2
    assert get_sender_calls == 1
    assert sleeps == [1]
    assert stats.cached == 0
    assert stats.fetched == 1
    assert stats.unresolved == 0
    assert stats.written_senders == 1


@pytest.mark.asyncio
async def test_list_topics_fetches_forum_topics(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    requests = []

    class DummyClient:
        async def get_input_entity(self, chat):
            assert chat == -100123
            return "input-peer"

        async def __call__(self, request):
            requests.append(request)
            return SimpleNamespace(
                topics=[
                    SimpleNamespace(
                        id=10,
                        title="FLT",
                        top_message=10,
                        unread_count=2,
                        closed=False,
                        hidden=False,
                        pinned=True,
                    ),
                    SimpleNamespace(id=20, title="雅克科技", top_message=20),
                    SimpleNamespace(id=30),
                ]
            )

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    topics = await runner.run_list_topics(
        config,
        chat=-100123,
        limit=50,
        query="FLT",
    )

    assert len(requests) == 1
    assert requests[0].peer == "input-peer"
    assert requests[0].limit == 50
    assert requests[0].q == "FLT"
    assert [(topic.topic_id, topic.title, topic.pinned) for topic in topics] == [
        (10, "FLT", True),
        (20, "雅克科技", False),
    ]


@pytest.mark.asyncio
async def test_list_topics_prefers_channels_api(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    requests = []

    class ChannelForumTopicsRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class DummyClient:
        async def get_input_entity(self, chat):
            assert chat == -100123
            return "input-channel"

        async def __call__(self, request):
            requests.append(request)
            return SimpleNamespace(topics=[])

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(
        runner.functions,
        "channels",
        SimpleNamespace(GetForumTopicsRequest=ChannelForumTopicsRequest),
    )

    await runner.run_list_topics(config, chat=-100123, limit=25, query="FLT")

    assert len(requests) == 1
    assert requests[0].channel == "input-channel"
    assert requests[0].limit == 25
    assert requests[0].q == "FLT"


@pytest.mark.asyncio
async def test_list_topics_falls_back_to_messages_api(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    requests = []

    class BrokenChannelForumTopicsRequest:
        def __init__(self, **_kwargs):
            raise TypeError("unexpected keyword argument channel")

    class MessageForumTopicsRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class DummyClient:
        async def get_input_entity(self, chat):
            assert chat == -100123
            return "input-peer"

        async def __call__(self, request):
            requests.append(request)
            return SimpleNamespace(topics=[])

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(
        runner.functions,
        "channels",
        SimpleNamespace(GetForumTopicsRequest=BrokenChannelForumTopicsRequest),
    )
    monkeypatch.setattr(
        runner.functions,
        "messages",
        SimpleNamespace(GetForumTopicsRequest=MessageForumTopicsRequest),
    )

    await runner.run_list_topics(config, chat=-100123, limit=25, query="FLT")

    assert len(requests) == 1
    assert requests[0].peer == "input-peer"
    assert requests[0].limit == 25
    assert requests[0].q == "FLT"


@pytest.mark.asyncio
async def test_list_topics_rejects_invalid_limit(tmp_path: Path):
    with pytest.raises(ValueError):
        await runner.run_list_topics(build_config(tmp_path), chat=-100123, limit=0)


@pytest.mark.asyncio
async def test_list_topics_wraps_rpc_errors(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)

    class DummyClient:
        async def get_input_entity(self, _chat):
            raise runner.errors.UsernameInvalidError(request=None)

        async def disconnect(self):
            return None

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    with pytest.raises(ValueError, match="Cannot list topics"):
        await runner.run_list_topics(config, chat="bad-chat")


@pytest.mark.asyncio
async def test_list_topics_wraps_entity_lookup_errors(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    disconnected = False

    class DummyClient:
        async def get_input_entity(self, _chat):
            raise ValueError("Cannot find any entity")

        async def disconnect(self):
            nonlocal disconnected
            disconnected = True

    async def fake_start_client(_client, _role):
        return None

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)

    with pytest.raises(ValueError, match="Cannot list topics"):
        await runner.run_list_topics(config, chat="bad-chat")
    assert disconnected is True


@pytest.mark.asyncio
async def test_list_topics_wraps_api_signature_errors(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    disconnected = False

    class DummyClient:
        async def get_input_entity(self, chat):
            assert chat == -100123
            return "input-peer"

        async def disconnect(self):
            nonlocal disconnected
            disconnected = True

    async def fake_start_client(_client, _role):
        return None

    def broken_get_forum_topics_request(**_kwargs):
        raise TypeError("unexpected keyword argument")

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(
        runner.functions.messages,
        "GetForumTopicsRequest",
        broken_get_forum_topics_request,
    )

    with pytest.raises(ValueError, match="Cannot list topics"):
        await runner.run_list_topics(config, chat=-100123)
    assert disconnected is True


@pytest.mark.asyncio
async def test_list_topics_wraps_missing_api_errors(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    disconnected = False

    class DummyClient:
        async def get_input_entity(self, chat):
            assert chat == -100123
            return "input-peer"

        async def disconnect(self):
            nonlocal disconnected
            disconnected = True

    async def fake_start_client(_client, _role):
        return None

    class MissingForumTopics:
        def __getattr__(self, name):
            if name == "GetForumTopicsRequest":
                raise AttributeError(name)
            raise AttributeError(name)

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner.functions, "messages", MissingForumTopics())

    with pytest.raises(ValueError, match="Cannot list topics"):
        await runner.run_list_topics(config, chat=-100123)
    assert disconnected is True


@pytest.mark.asyncio
async def test_push_once_reports_uses_selected_targets(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    selected = (config.targets[0],)
    captured: list[str] = []

    async def fake_send_report_bundle(
        _client,
        _config,
        _control,
        target,
        _messages,
        _since,
        _until,
        _report_path,
        **_kwargs,
    ):
        captured.append(target.name)

    monkeypatch.setattr(runner, "_send_report_bundle", fake_send_report_bundle)

    await runner._push_once_reports(
        object(),
        config,
        selected,
        {selected[0].name: []},
        datetime.now(timezone.utc) - timedelta(hours=1),
        datetime.now(timezone.utc),
        [tmp_path / "report.html"],
    )

    assert captured == [selected[0].name]


@pytest.mark.asyncio
async def test_run_once_multi_target_generates_unique_report_files(monkeypatch, tmp_path: Path):
    config = build_multi_target_config(tmp_path)
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    class DummyClient:
        async def disconnect(self) -> None:
            return None

    @contextmanager
    def fake_db_session(_path: Path):
        yield object()

    async def fake_start_client(_client, _role):
        return None

    async def fake_collect_window(_client, _config, _target, _since):
        return []

    def fake_fetch_messages_between(_conn, _ids, _since, _until, **_kwargs):
        return []

    def fake_generate_report(_messages, _config, _since, _until, **kwargs):
        report_dir = kwargs["report_dir"]
        report_name = kwargs["report_name"]
        return report_dir / report_name

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner, "_collect_window", fake_collect_window)
    monkeypatch.setattr(runner, "db_session", fake_db_session)
    monkeypatch.setattr(runner, "persist_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "fetch_messages_between", fake_fetch_messages_between)
    monkeypatch.setattr(runner, "generate_report", fake_generate_report)

    report_paths = await runner.run_once(config, since, push=False)

    assert len(report_paths) == 2
    assert len(set(report_paths)) == 2
    assert sorted(path.name for path in report_paths) == ["index_-1001.html", "index_-1002.html"]


@pytest.mark.asyncio
async def test_run_once_push_passes_primary_fallback_when_sender_is_active(
    monkeypatch, tmp_path: Path
):
    config = build_config(tmp_path)
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    class DummyClient:
        def __init__(self, name: str) -> None:
            self.name = name
            self.disconnected = False

        async def disconnect(self) -> None:
            self.disconnected = True

    capture_primary = DummyClient("capture-primary")
    fallback_primary = DummyClient("fallback-primary")
    sender = DummyClient("sender")
    built_clients = iter([capture_primary, fallback_primary])
    pushed: dict[str, object] = {}

    @contextmanager
    def fake_db_session(_path: Path):
        yield object()

    async def fake_start_client(_client, _role):
        return None

    async def fake_collect_window(_client, _config, _target, _since):
        return []

    async def fake_start_sender_client(_config):
        return sender

    def fake_fetch_messages_between(_conn, _ids, _since, _until, **_kwargs):
        return []

    def fake_generate_report(_messages, _config, _since, _until, **kwargs):
        return kwargs["report_dir"] / kwargs["report_name"]

    async def fake_push_once_reports(
        client,
        _config,
        _targets,
        _stored_by_target,
        _since,
        _until,
        _report_paths,
        *,
        fallback_client=None,
        **_kwargs,
    ):
        pushed["client"] = client
        pushed["fallback_client"] = fallback_client

    monkeypatch.setattr(runner, "_build_client", lambda _config: next(built_clients))
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner, "_start_sender_client", fake_start_sender_client)
    monkeypatch.setattr(runner, "_collect_window", fake_collect_window)
    monkeypatch.setattr(runner, "db_session", fake_db_session)
    monkeypatch.setattr(runner, "persist_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "fetch_messages_between", fake_fetch_messages_between)
    monkeypatch.setattr(runner, "generate_report", fake_generate_report)
    monkeypatch.setattr(runner, "_push_once_reports", fake_push_once_reports)

    await runner.run_once(config, since, push=True)

    assert pushed == {"client": sender, "fallback_client": fallback_primary}
    assert capture_primary.disconnected is True
    assert sender.disconnected is True
    assert fallback_primary.disconnected is True


@pytest.mark.asyncio
async def test_run_once_selected_target_in_multi_target_config_uses_scoped_filename(
    monkeypatch, tmp_path: Path
):
    config = build_multi_target_config(tmp_path)
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    class DummyClient:
        async def disconnect(self) -> None:
            return None

    @contextmanager
    def fake_db_session(_path: Path):
        yield object()

    async def fake_start_client(_client, _role):
        return None

    async def fake_collect_window(_client, _config, _target, _since):
        return []

    def fake_fetch_messages_between(_conn, _ids, _since, _until, **_kwargs):
        return []

    def fake_generate_report(_messages, _config, _since, _until, **kwargs):
        return kwargs["report_dir"] / kwargs["report_name"]

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner, "_collect_window", fake_collect_window)
    monkeypatch.setattr(runner, "db_session", fake_db_session)
    monkeypatch.setattr(runner, "persist_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "fetch_messages_between", fake_fetch_messages_between)
    monkeypatch.setattr(runner, "generate_report", fake_generate_report)

    selected = str(config.targets[0].target_chat_id)
    report_paths = await runner.run_once(config, since, push=False, target_selector=selected)

    assert len(report_paths) == 1
    assert report_paths[0].name == "index_-1001.html"


@pytest.mark.asyncio
async def test_run_once_single_target_config_keeps_index_html(monkeypatch, tmp_path: Path):
    config = build_config(tmp_path)
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    class DummyClient:
        async def disconnect(self) -> None:
            return None

    @contextmanager
    def fake_db_session(_path: Path):
        yield object()

    async def fake_start_client(_client, _role):
        return None

    async def fake_collect_window(_client, _config, _target, _since):
        return []

    def fake_fetch_messages_between(_conn, _ids, _since, _until, **_kwargs):
        return []

    def fake_generate_report(_messages, _config, _since, _until, **kwargs):
        return kwargs["report_dir"] / kwargs["report_name"]

    monkeypatch.setattr(runner, "_build_client", lambda _config: DummyClient())
    monkeypatch.setattr(runner, "_start_client", fake_start_client)
    monkeypatch.setattr(runner, "_collect_window", fake_collect_window)
    monkeypatch.setattr(runner, "db_session", fake_db_session)
    monkeypatch.setattr(runner, "persist_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "fetch_messages_between", fake_fetch_messages_between)
    monkeypatch.setattr(runner, "generate_report", fake_generate_report)

    report_paths = await runner.run_once(config, since, push=False, target_selector=str(config.targets[0].target_chat_id))

    assert len(report_paths) == 1
    assert report_paths[0].name == "index.html"


@pytest.mark.asyncio
async def test_reply_media_caption_uses_target_scoped_alias(monkeypatch, tmp_path: Path):
    telegram = TelegramConfig(api_id=1, api_hash="abcdefghijk", session_file=tmp_path / "session")
    target_a = TargetGroupConfig(
        name="group-a",
        target_chat_id=-1001,
        tracked_user_ids=(111,),
        tracked_user_aliases=MappingProxyType({111: "Alpha"}),
        summary_interval_minutes=120,
        control_group="default",
    )
    target_b = TargetGroupConfig(
        name="group-b",
        target_chat_id=-1002,
        tracked_user_ids=(222, 999),
        tracked_user_aliases=MappingProxyType({999: "ReplyAliasInOtherTarget"}),
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
    display = DisplayConfig(show_ids=True, time_format="%Y.%m.%d %H:%M:%S (%Z)", language="auto")
    notifications = NotificationConfig(bark_key=None, heartbeat_interval_hours=2, check_updates=True)
    config = Config(
        config_version=1.0,
        telegram=telegram,
        sender=None,
        targets=(target_a, target_b),
        control_groups=MappingProxyType({"default": control}),
        target_by_chat_id=MappingProxyType({target_a.target_chat_id: target_a, target_b.target_chat_id: target_b}),
        target_by_name=MappingProxyType({target_a.name: target_a, target_b.name: target_b}),
        control_by_chat_id=MappingProxyType({control.control_chat_id: control}),
        targets_by_control=MappingProxyType({"default": (target_a, target_b)}),
        storage=storage,
        reporting=reporting,
        display=display,
        notifications=notifications,
        realtime=RealtimeConfig(
            push_mode="interval",
            report_interval_minutes=120,
            rate_limit_per_minute=20,
            rate_limit_per_hour=200,
            rate_limit_per_day=1000,
            min_interval_sec=3.0,
            media_extra_delay_sec=2.0,
            warmup_minutes=5.0,
            warmup_rate=5,
        ),
    )

    media_file = tmp_path / "reply.jpg"
    media_file.write_bytes(b"x")
    message = DbMessage(
        chat_id=target_a.target_chat_id,
        message_id=42,
        sender_id=111,
        date=datetime.now(timezone.utc),
        text="hello",
        reply_to_msg_id=1,
        replied_sender_id=999,
        replied_date=datetime.now(timezone.utc),
        replied_text="quoted",
        media=[DbMedia(media_index=0, file_path=str(media_file), mime_type="image/jpeg", file_size=1, is_reply=True)],
    )
    sent: list[str] = []

    async def fake_send_file_with_fallback(
        _client,
        _fallback,
        _chat_id,
        _file_path,
        *,
        caption=None,
        reply_to=None,
    ):
        sent.append(caption or "")

    monkeypatch.setattr(runner, "_send_file_with_fallback", fake_send_file_with_fallback)

    await runner._send_media_for_message(
        object(),
        control.control_chat_id,
        message,
        config,
        target_a,
        reply_to=None,
    )

    assert len(sent) == 1
    assert "ReplyAliasInOtherTarget" not in sent[0]
    assert "Original sender: 999" in sent[0]


@pytest.mark.asyncio
async def test_topic_report_filenames_include_target_chat_id(monkeypatch, tmp_path: Path):
    config = build_multi_target_config(tmp_path)
    control = config.control_groups["default"]
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    until = datetime.now(timezone.utc)
    report_dir = tmp_path / "reports"
    report_names: list[str] = []

    message_a = DbMessage(
        chat_id=config.targets[0].target_chat_id,
        message_id=1,
        sender_id=777,
        date=until,
        text="A",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
        media=[],
    )
    message_b = DbMessage(
        chat_id=config.targets[1].target_chat_id,
        message_id=2,
        sender_id=777,
        date=until,
        text="B",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
        media=[],
    )

    def fake_generate_report(_messages, _config, _since, _until, **kwargs):
        report_name = kwargs["report_name"]
        report_names.append(report_name)
        return kwargs["report_dir"] / report_name

    async def fake_send_file_with_fallback(
        _client,
        _fallback_client,
        _chat_id,
        _file_path,
        *,
        caption=None,
        reply_to=None,
    ):
        return None

    monkeypatch.setattr(runner, "generate_report", fake_generate_report)
    monkeypatch.setattr(runner, "_send_file_with_fallback", fake_send_file_with_fallback)

    await runner._send_topic_reports(
        object(),
        config,
        control,
        config.targets[0],
        [message_a],
        since,
        until,
        report_dir,
    )
    await runner._send_topic_reports(
        object(),
        config,
        control,
        config.targets[1],
        [message_b],
        since,
        until,
        report_dir,
    )

    assert report_names == ["index_-1001_777.html", "index_-1002_777.html"]


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

    captured_report_name: dict[str, object] = {}

    def fake_generate_report(_messages, _config, _since, _until, **kwargs):
        captured_report_name["report_name"] = kwargs.get("report_name")
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
    assert captured_report_name["report_name"] == "index_-123.html"


@pytest.mark.asyncio
async def test_summary_loop_continues_after_send_exception(monkeypatch, tmp_path: Path, caplog):
    config = build_config(tmp_path)
    target = config.targets[0]
    control = config.control_groups["default"]
    tracker = runner._ActivityTracker()

    # Force immediate timeout so _run enters the summary path without waiting.
    object.__setattr__(target, "summary_interval_minutes", 0)
    loop = runner._SummaryLoop(config, target, control, client=object(), tracker=tracker)

    async def fake_send_summary() -> None:
        loop._stop.set()
        raise RuntimeError("send failed")

    monkeypatch.setattr(loop, "_send_summary", fake_send_summary)

    with caplog.at_level(logging.ERROR):
        await loop._run()

    assert "Summary send failed for target 'default' (chat_id=-123)" in caplog.text


# --- skip_html_report tests ---


@pytest.mark.asyncio
async def test_send_report_bundle_sends_html_by_default(monkeypatch, tmp_path: Path):
    """With skip_html_report=False (default), HTML file is sent."""
    config = build_config(tmp_path)
    control = config.control_groups["default"]
    target = config.targets[0]
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    until = datetime.now(timezone.utc)
    report_path = tmp_path / "report.html"
    report_path.write_text("<html></html>")

    sent_files: list[Path] = []

    async def fake_send_file_with_fallback(
        _client, _fallback, _chat_id, file_path, *, caption=None, reply_to=None
    ):
        sent_files.append(file_path)

    async def fake_send_message_with_fallback(
        _client, _fallback, _chat_id, _text, *, parse_mode=None, reply_to=None
    ):
        pass

    monkeypatch.setattr(runner, "_send_file_with_fallback", fake_send_file_with_fallback)
    monkeypatch.setattr(runner, "_send_message_with_fallback", fake_send_message_with_fallback)
    monkeypatch.setattr(runner, "send_bark_notification", lambda *a, **k: asyncio.sleep(0))

    await runner._send_report_bundle(
        object(), config, control, target, [], since, until, report_path
    )

    assert report_path in sent_files


@pytest.mark.asyncio
async def test_send_report_bundle_skips_html_when_enabled(monkeypatch, tmp_path: Path):
    """With skip_html_report=True, HTML file is NOT sent but messages still go through."""
    config = build_config(tmp_path)
    target = config.targets[0]
    control_skip = ControlGroupConfig(
        key="default",
        control_chat_id=-456,
        is_forum=False,
        topic_routing_enabled=False,
        topic_target_map=MappingProxyType({}),
        skip_html_report=True,
    )
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    until = datetime.now(timezone.utc)
    report_path = tmp_path / "report.html"
    report_path.write_text("<html></html>")

    sent_files: list[Path] = []
    sent_messages: list[str] = []

    async def fake_send_file_with_fallback(
        _client, _fallback, _chat_id, file_path, *, caption=None, reply_to=None
    ):
        sent_files.append(file_path)

    async def fake_send_message_with_fallback(
        _client, _fallback, _chat_id, text, *, parse_mode=None, reply_to=None
    ):
        sent_messages.append(text)

    monkeypatch.setattr(runner, "_send_file_with_fallback", fake_send_file_with_fallback)
    monkeypatch.setattr(runner, "_send_message_with_fallback", fake_send_message_with_fallback)
    monkeypatch.setattr(runner, "send_bark_notification", lambda *a, **k: asyncio.sleep(0))

    message = DbMessage(
        chat_id=target.target_chat_id,
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

    await runner._send_report_bundle(
        object(), config, control_skip, target, [message], since, until, report_path
    )

    # HTML file should NOT have been sent
    assert report_path not in sent_files
    # But the individual message should have been sent
    assert len(sent_messages) == 1
    assert "hello" in sent_messages[0]


@pytest.mark.asyncio
async def test_send_report_bundle_skips_topic_reports_when_enabled(monkeypatch, tmp_path: Path):
    """With skip_html_report=True and topic routing, per-user HTML reports are NOT sent."""
    config = build_config(tmp_path)
    target = config.targets[0]
    control_skip = ControlGroupConfig(
        key="default",
        control_chat_id=-456,
        is_forum=True,
        topic_routing_enabled=True,
        topic_target_map=MappingProxyType({target.target_chat_id: MappingProxyType({111: 9001})}),
        skip_html_report=True,
    )
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    until = datetime.now(timezone.utc)
    report_path = tmp_path / "reports" / "report.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("<html></html>")

    topic_reports_called = []

    async def fake_send_topic_reports(*args, **kwargs):
        topic_reports_called.append(True)

    async def fake_send_message_with_fallback(
        _client, _fallback, _chat_id, _text, *, parse_mode=None, reply_to=None
    ):
        pass

    monkeypatch.setattr(runner, "_send_topic_reports", fake_send_topic_reports)
    monkeypatch.setattr(runner, "_send_message_with_fallback", fake_send_message_with_fallback)
    monkeypatch.setattr(runner, "send_bark_notification", lambda *a, **k: asyncio.sleep(0))

    await runner._send_report_bundle(
        object(), config, control_skip, target, [], since, until, report_path
    )

    # _send_topic_reports should NOT have been called
    assert topic_reports_called == []


# --- _format_report_caption / _extract_time_format tests ---


def test_format_report_caption_same_day(tmp_path: Path) -> None:
    cfg = build_config(tmp_path)
    since = datetime(2026, 2, 13, 6, 48, 39, tzinfo=timezone.utc)
    until = datetime(2026, 2, 13, 6, 51, 41, tzinfo=timezone.utc)
    caption = runner._format_report_caption("FLT", 3, since, until, cfg)
    lines = caption.split("\n")
    assert lines[0] == "\U0001f4cb FLT \u2014 3 messages"
    # Same day: end time should omit date portion
    assert "\u2192" in lines[1]
    # Full start timestamp present
    assert "2026.02.13" in lines[1]
    # End should NOT repeat the date
    parts = lines[1].split("\u2192")
    assert "2026.02.13" not in parts[1]


def test_format_report_caption_cross_day(tmp_path: Path) -> None:
    cfg = build_config(tmp_path)
    since = datetime(2026, 2, 12, 23, 50, 0, tzinfo=timezone.utc)
    until = datetime(2026, 2, 13, 0, 10, 0, tzinfo=timezone.utc)
    caption = runner._format_report_caption("FLT", 5, since, until, cfg)
    lines = caption.split("\n")
    assert lines[0] == "\U0001f4cb FLT \u2014 5 messages"
    # Cross-day: both dates should be present
    parts = lines[1].split("\u2192")
    assert "2026.02.12" in parts[0]
    assert "2026.02.13" in parts[1]


def test_format_report_caption_until_none(tmp_path: Path) -> None:
    cfg = build_config(tmp_path)
    since = datetime(2026, 2, 13, 6, 0, 0, tzinfo=timezone.utc)
    caption = runner._format_report_caption("Report", 1, since, None, cfg)
    assert "now" in caption
    assert "\U0001f4cb Report \u2014 1 messages" in caption


def test_extract_time_format_strips_date() -> None:
    assert runner._extract_time_format("%Y.%m.%d %H:%M:%S (%Z)") == "%H:%M:%S (%Z)"
    assert runner._extract_time_format("%m-%d %H:%M") == "%H:%M"
    # No time code at all — returns full format
    assert runner._extract_time_format("%Y.%m.%d") == "%Y.%m.%d"


# --- Reconnect logic tests ---


class _FakeSendClient:
    def __init__(
        self,
        *,
        connected: bool = True,
        fail_after_connect: bool = False,
        fail_messages: set[str] | None = None,
        fail_entities: set[object] | None = None,
    ) -> None:
        self.connected = connected
        self.fail_after_connect = fail_after_connect
        self.fail_messages = set(fail_messages or ())
        self.fail_entities = set(fail_entities or ())
        self.connect_count = 0
        self.sent_messages: list[tuple[object, str]] = []
        self.sent_files: list[tuple[object, Path]] = []

    async def connect(self) -> None:
        self.connect_count += 1
        self.connected = True

    async def get_input_entity(self, entity):
        return f"resolved:{entity}"

    async def send_message(self, entity, message, **_kwargs) -> None:
        if (
            not self.connected
            or self.fail_after_connect
            or message in self.fail_messages
            or entity in self.fail_entities
        ):
            raise RuntimeError("Cannot send requests while disconnected")
        self.sent_messages.append((entity, message))

    async def send_file(self, entity, *, file, **_kwargs) -> None:
        if not self.connected or self.fail_after_connect:
            raise RuntimeError("Cannot send requests while disconnected")
        self.sent_files.append((entity, Path(file)))


@pytest.mark.asyncio
async def test_send_message_reconnects_sender_before_primary_fallback() -> None:
    sender = _FakeSendClient(connected=False)
    primary = _FakeSendClient()

    await runner._send_message_with_fallback(sender, primary, "control", "hello")

    assert sender.connect_count == 1
    assert sender.sent_messages == [("resolved:control", "hello")]
    assert primary.sent_messages == []


@pytest.mark.asyncio
async def test_send_file_reconnects_sender_before_primary_fallback(tmp_path: Path) -> None:
    sender = _FakeSendClient(connected=False)
    primary = _FakeSendClient()
    attachment = tmp_path / "report.txt"
    attachment.write_text("report", encoding="utf-8")

    await runner._send_file_with_fallback(sender, primary, "control", attachment)

    assert sender.connect_count == 1
    assert sender.sent_files == [("resolved:control", attachment)]
    assert primary.sent_files == []


@pytest.mark.asyncio
async def test_send_message_falls_back_to_primary_when_sender_retry_fails() -> None:
    sender = _FakeSendClient(connected=False, fail_after_connect=True)
    primary = _FakeSendClient()

    await runner._send_message_with_fallback(sender, primary, "control", "hello")

    assert sender.connect_count == 1
    assert sender.sent_messages == []
    assert primary.sent_messages == [
        ("resolved:control", "hello"),
        ("resolved:control", runner._SENDER_FALLBACK_ALERT),
    ]


@pytest.mark.asyncio
async def test_send_file_fallback_warns_control_chat_when_sender_retry_fails(tmp_path: Path) -> None:
    sender = _FakeSendClient(connected=False, fail_after_connect=True)
    primary = _FakeSendClient()
    attachment = tmp_path / "report.txt"
    attachment.write_text("report", encoding="utf-8")

    await runner._send_file_with_fallback(sender, primary, "control", attachment)

    assert sender.connect_count == 1
    assert sender.sent_files == []
    assert primary.sent_files == [("resolved:control", attachment)]
    assert primary.sent_messages == [("resolved:control", runner._SENDER_FALLBACK_ALERT)]


@pytest.mark.asyncio
async def test_sender_fallback_alert_is_sent_once_until_sender_recovers() -> None:
    sender = _FakeSendClient(connected=False, fail_after_connect=True)
    primary = _FakeSendClient()

    await runner._send_message_with_fallback(sender, primary, "control", "first")
    await runner._send_message_with_fallback(sender, primary, "control", "second")

    assert primary.sent_messages == [
        ("resolved:control", "first"),
        ("resolved:control", runner._SENDER_FALLBACK_ALERT),
        ("resolved:control", "second"),
    ]

    sender.fail_after_connect = False
    await runner._send_message_with_fallback(sender, primary, "control", "recovered")

    sender.fail_after_connect = True
    sender.connected = False
    await runner._send_message_with_fallback(sender, primary, "control", "third")

    assert primary.sent_messages == [
        ("resolved:control", "first"),
        ("resolved:control", runner._SENDER_FALLBACK_ALERT),
        ("resolved:control", "second"),
        ("resolved:control", "third"),
        ("resolved:control", runner._SENDER_FALLBACK_ALERT),
    ]
    assert sender.sent_messages == [("resolved:control", "recovered")]


@pytest.mark.asyncio
async def test_sender_fallback_alert_is_throttled_per_control_chat() -> None:
    sender = _FakeSendClient(connected=False, fail_after_connect=True)
    primary = _FakeSendClient()

    await runner._send_message_with_fallback(sender, primary, "control-a", "first")
    await runner._send_message_with_fallback(sender, primary, "control-b", "second")
    await runner._send_message_with_fallback(sender, primary, "control-a", "third")

    assert primary.sent_messages == [
        ("resolved:control-a", "first"),
        ("resolved:control-a", runner._SENDER_FALLBACK_ALERT),
        ("resolved:control-b", "second"),
        ("resolved:control-b", runner._SENDER_FALLBACK_ALERT),
        ("resolved:control-a", "third"),
    ]


@pytest.mark.asyncio
async def test_sender_fallback_recovery_only_clears_recovered_control_chat() -> None:
    sender = _FakeSendClient(connected=True, fail_entities={"resolved:control-a"})
    primary = _FakeSendClient()

    await runner._send_message_with_fallback(sender, primary, "control-a", "first")
    await runner._send_message_with_fallback(sender, primary, "control-b", "second")
    await runner._send_message_with_fallback(sender, primary, "control-a", "third")

    assert sender.sent_messages == [("resolved:control-b", "second")]
    assert primary.sent_messages == [
        ("resolved:control-a", "first"),
        ("resolved:control-a", runner._SENDER_FALLBACK_ALERT),
        ("resolved:control-a", "third"),
    ]


@pytest.mark.asyncio
async def test_sender_fallback_alert_retries_after_alert_delivery_failure() -> None:
    sender = _FakeSendClient(connected=False, fail_after_connect=True)
    primary = _FakeSendClient(fail_messages={runner._SENDER_FALLBACK_ALERT})

    await runner._send_message_with_fallback(sender, primary, "control", "first")

    assert primary.sent_messages == [("resolved:control", "first")]

    primary.fail_messages.clear()
    await runner._send_message_with_fallback(sender, primary, "control", "second")

    assert primary.sent_messages == [
        ("resolved:control", "first"),
        ("resolved:control", "second"),
        ("resolved:control", runner._SENDER_FALLBACK_ALERT),
    ]


class _FakeClient:
    """Minimal fake TelegramClient for reconnect tests."""

    def __init__(self, side_effects: list[BaseException | None]) -> None:
        self._side_effects = list(side_effects)
        self.connect_count = 0

    async def run_until_disconnected(self) -> None:
        effect = self._side_effects.pop(0)
        if effect is not None:
            raise effect

    async def connect(self) -> None:
        self.connect_count += 1


@pytest.mark.asyncio
async def test_run_with_reconnect_retries_on_connection_error(tmp_path: Path) -> None:
    """ConnectionError triggers retry; second attempt succeeds."""
    client = _FakeClient([ConnectionError("fail"), None])
    config = build_config(tmp_path)
    notifications: list[str] = []

    original = runner._send_reconnect_notification

    async def _capture_notification(cl, cfg, downtime, *, fallback_client=None):
        notifications.append(str(downtime))

    runner._send_reconnect_notification = _capture_notification
    try:
        with _patch_sleep():
            await runner._run_with_reconnect(client, client, config)
    finally:
        runner._send_reconnect_notification = original

    assert client.connect_count == 1
    assert len(notifications) == 1


@pytest.mark.asyncio
async def test_run_with_reconnect_raises_auth_error(tmp_path: Path) -> None:
    """Auth-related errors are not retried."""
    client = _FakeClient([ConnectionError("authorization key invalid")])
    config = build_config(tmp_path)
    with pytest.raises(ConnectionError, match="authorization"):
        await runner._run_with_reconnect(client, client, config)
    assert client.connect_count == 0


@pytest.mark.asyncio
async def test_run_with_reconnect_backoff_increases(tmp_path: Path) -> None:
    """Backoff doubles when connect() also fails."""
    client = _FakeClient([
        ConnectionError("net down"),
        ConnectionError("still down"),
        None,
    ])
    delays: list[float] = []
    original_connect = client.connect

    async def _failing_then_ok() -> None:
        if client.connect_count == 0:
            client.connect_count += 1
            raise OSError("connect failed")
        client.connect_count += 1

    client.connect = _failing_then_ok
    config = build_config(tmp_path)

    original_notification = runner._send_reconnect_notification
    runner._send_reconnect_notification = _noop_notification
    try:
        with _patch_sleep(record=delays):
            await runner._run_with_reconnect(client, client, config)
    finally:
        runner._send_reconnect_notification = original_notification

    # First sleep = 10s, second sleep = 20s (doubled after connect failure)
    assert delays[0] == 10
    assert delays[1] == 20


def test_is_auth_error() -> None:
    assert runner._is_auth_error(ConnectionError("authorization key invalid"))
    assert runner._is_auth_error(ConnectionError("user session revoked"))
    assert runner._is_auth_error(ConnectionError("account deactivated"))
    assert not runner._is_auth_error(ConnectionError("Network is unreachable"))
    assert not runner._is_auth_error(OSError("[Errno 51]"))


async def _noop_notification(cl, cfg, downtime, *, fallback_client=None):
    pass


@contextmanager
def _patch_sleep(record: list[float] | None = None):
    """Replace asyncio.sleep in runner module with an instant no-op."""
    original = asyncio.sleep

    async def _fake_sleep(delay, *a, **kw):
        if record is not None:
            record.append(delay)

    runner.asyncio.sleep = _fake_sleep
    try:
        yield
    finally:
        runner.asyncio.sleep = original


# --- SQLite retry counter reset tests ---


@pytest.mark.asyncio
async def test_sqlite_retry_resets_after_burst_window(tmp_path: Path) -> None:
    """Sporadic SQLite errors spread far apart should not accumulate to fatal."""
    import time as _time

    call_count = 0

    class _SqliteFlakyClient(_FakeClient):
        def __init__(self):
            super().__init__([])

        async def run_until_disconnected(self):
            nonlocal call_count
            call_count += 1
            if call_count <= 6:
                raise sqlite3.OperationalError("database is locked")
            # Graceful exit
            return

    client = _SqliteFlakyClient()
    config = build_config(tmp_path)

    # Patch time.monotonic so errors 1-3 are in one burst, then a gap, then 4-6.
    fake_time = [0.0]
    original_monotonic = _time.monotonic

    def _fake_monotonic():
        return fake_time[0]

    original_sleep = asyncio.sleep

    async def _fake_sleep(delay, *a, **kw):
        nonlocal call_count
        # After 3rd error, simulate a long gap (beyond burst window).
        if call_count == 3:
            fake_time[0] += 60.0
        else:
            fake_time[0] += delay

    runner.asyncio.sleep = _fake_sleep
    runner.time.monotonic = _fake_monotonic
    try:
        await runner._run_with_reconnect(client, client, config)
    finally:
        runner.asyncio.sleep = original_sleep
        runner.time.monotonic = original_monotonic

    # Should have survived all 6 errors (two bursts of 3) and returned on call 7.
    assert call_count == 7


@pytest.mark.asyncio
async def test_sqlite_retry_fatal_on_consecutive_burst(tmp_path: Path) -> None:
    """Consecutive SQLite errors within burst window should still be fatal."""
    call_count = 0

    class _SqliteBurstClient(_FakeClient):
        def __init__(self):
            super().__init__([])

        async def run_until_disconnected(self):
            nonlocal call_count
            call_count += 1
            raise sqlite3.OperationalError("database is locked")

    client = _SqliteBurstClient()
    config = build_config(tmp_path)

    with _patch_sleep():
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            await runner._run_with_reconnect(client, client, config)

    # 1 initial + 3 retries = 4 calls, then fatal on the 4th retry
    assert call_count == 4
