from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

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
from telegram_watch.storage import DbMedia, DbMessage
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
    display = DisplayConfig(show_ids=True, time_format="%Y.%m.%d %H:%M:%S (%Z)")
    notifications = NotificationConfig(bark_key=None)
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
    display = DisplayConfig(show_ids=True, time_format="%Y.%m.%d %H:%M:%S (%Z)")
    notifications = NotificationConfig(bark_key=None)
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
