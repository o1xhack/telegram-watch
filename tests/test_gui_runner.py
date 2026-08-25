from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from telegram_watch.config import ConfigError, FullArchiveConfig
from telegram_watch.gui import (
    _RunnerManager,
    _TIME_FORMAT_UNITS,
    _build_timezone_presets,
    _load_raw_config,
    _normalize_config,
    _render_toml,
    _validate_payload,
)

try:  # pragma: no cover - Python 3.11+ uses tomllib
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def _manager(tmp_path: Path) -> _RunnerManager:
    return _RunnerManager(tmp_path / "config.toml")


def test_start_run_requires_retention_confirmation(monkeypatch, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    config = SimpleNamespace(reporting=SimpleNamespace(retention_days=365))

    monkeypatch.setattr(manager, "_current_run", lambda: (False, None))
    monkeypatch.setattr(manager, "_load_config", lambda: (config, None))
    monkeypatch.setattr(manager, "_session_ready", lambda _cfg: (True, None))

    payload = manager.start_run(confirm_retention=False)

    assert payload["ok"] is False
    assert "Retention confirmation required" in payload["status"]


def test_start_run_passes_yes_retention_to_cli(monkeypatch, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    config = SimpleNamespace(reporting=SimpleNamespace(retention_days=365))
    captured_args: list[str] = []

    monkeypatch.setattr(manager, "_current_run", lambda: (False, None))
    monkeypatch.setattr(manager, "_load_config", lambda: (config, None))
    monkeypatch.setattr(manager, "_session_ready", lambda _cfg: (True, None))
    monkeypatch.setattr(manager, "_write_log_header", lambda *_args, **_kwargs: None)

    def fake_spawn(args, *, log_path):
        captured_args.extend(args)
        return SimpleNamespace(pid=43210)

    monkeypatch.setattr(manager, "_spawn_process", fake_spawn)

    payload = manager.start_run(confirm_retention=True)

    assert payload["ok"] is True
    assert "--yes-retention" in captured_args


def test_session_ready_requires_primary_session(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    config = SimpleNamespace(
        telegram=SimpleNamespace(session_file=tmp_path / "primary.session"),
        sender=None,
    )

    ready, message = manager._session_ready(config)

    assert ready is False
    assert "Session file not found" in (message or "")


def test_session_ready_allows_missing_sender_session(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    primary = tmp_path / "primary.session"
    primary.write_text("", encoding="utf-8")
    config = SimpleNamespace(
        telegram=SimpleNamespace(session_file=primary),
        sender=SimpleNamespace(session_file=tmp_path / "sender.session"),
    )

    ready, message = manager._session_ready(config)

    assert ready is True
    assert message is None


def test_start_once_allows_missing_sender_session(monkeypatch, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    primary = tmp_path / "primary.session"
    primary.write_text("", encoding="utf-8")
    config = SimpleNamespace(
        telegram=SimpleNamespace(session_file=primary),
        sender=SimpleNamespace(session_file=tmp_path / "sender.session"),
        target_by_name={},
        target_by_chat_id={},
    )
    captured_args: list[str] = []

    monkeypatch.setattr(manager, "_load_config", lambda: (config, None))
    monkeypatch.setattr(manager, "_write_log_header", lambda *_args, **_kwargs: None)

    def fake_spawn(args, *, log_path):
        captured_args.extend(args)
        return SimpleNamespace(pid=10001)

    monkeypatch.setattr(manager, "_spawn_process", fake_spawn)

    payload = manager.start_once("2h", push=False)

    assert payload["ok"] is True
    assert "--push" not in captured_args


def test_stop_run_no_active_process(monkeypatch, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    monkeypatch.setattr(manager, "_current_run", lambda: (False, None))

    payload = manager.stop_run()

    assert payload["ok"] is True
    assert "not active" in payload["status"]


def test_stop_run_success(monkeypatch, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager._ensure_runtime_dir()
    manager.run_pid_path.write_text("12345", encoding="utf-8")

    monkeypatch.setattr(manager, "_current_run", lambda: (True, 12345))
    monkeypatch.setattr(manager, "_terminate_run_process", lambda _pid: True)
    monkeypatch.setattr(manager, "_write_log_header", lambda *_args, **_kwargs: None)

    payload = manager.stop_run()

    assert payload["ok"] is True
    assert "Run stopped" in payload["status"]
    assert not manager.run_pid_path.exists()


def test_stop_run_failure(monkeypatch, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager._ensure_runtime_dir()
    manager.run_pid_path.write_text("12345", encoding="utf-8")

    monkeypatch.setattr(manager, "_current_run", lambda: (True, 12345))
    monkeypatch.setattr(manager, "_terminate_run_process", lambda _pid: False)

    payload = manager.stop_run()

    assert payload["ok"] is False
    assert "Failed to stop run daemon" in payload["status"]
    assert manager.run_pid_path.exists()


def test_status_payload_marks_stale_event_loop_heartbeat_as_stalled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    manager._ensure_runtime_dir()
    stale_tick = datetime.now(timezone.utc) - timedelta(minutes=2)
    manager.run_health_path.write_text(
        json.dumps(
            {
                "pid": 12345,
                "last_tick": stale_tick.isoformat(),
                "sqlite_pending": 0,
                "sqlite_pending_since": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(manager, "_current_run", lambda: (True, 12345))
    monkeypatch.setattr(
        manager,
        "_config_health",
        lambda: (True, True, 30, False, None),
    )

    payload = manager.status_payload()

    assert payload["running"] is True
    assert payload["healthy"] is False
    assert payload["stalled"] is True
    assert "event-loop heartbeat" in payload["status"]


def test_status_payload_marks_long_sqlite_queue_as_stalled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    manager._ensure_runtime_dir()
    now = datetime.now(timezone.utc)
    manager.run_health_path.write_text(
        json.dumps(
            {
                "pid": 12345,
                "last_tick": now.isoformat(),
                "sqlite_pending": 1,
                "sqlite_pending_since": (now - timedelta(minutes=2)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(manager, "_current_run", lambda: (True, 12345))
    monkeypatch.setattr(
        manager,
        "_config_health",
        lambda: (True, True, 30, False, None),
    )

    payload = manager.status_payload()

    assert payload["healthy"] is False
    assert payload["stalled"] is True
    assert "SQLite made no progress" in payload["status"]


@pytest.mark.parametrize(
    ("heartbeat_archive", "expected_state", "expected_runtime", "expected_healthy"),
    [
        (
            {
                "configured": True,
                "runtime_enabled": True,
                "status": "active",
                "config_fingerprint": "archive-config-v1",
            },
            "active",
            True,
            True,
        ),
        (
            {
                "configured": True,
                "runtime_enabled": False,
                "status": "degraded",
                "config_fingerprint": "archive-config-v1",
            },
            "degraded",
            False,
            False,
        ),
        (None, "unverified", None, False),
    ],
)
def test_status_payload_reports_actual_full_archive_runtime_state(
    monkeypatch,
    tmp_path: Path,
    heartbeat_archive,
    expected_state,
    expected_runtime,
    expected_healthy,
) -> None:
    manager = _manager(tmp_path)
    manager._ensure_runtime_dir()
    heartbeat = {
        "pid": 12345,
        "last_tick": datetime.now(timezone.utc).isoformat(),
        "sqlite_pending": 0,
        "sqlite_pending_since": None,
    }
    if heartbeat_archive is not None:
        heartbeat["full_archive"] = heartbeat_archive
    manager.run_health_path.write_text(json.dumps(heartbeat), encoding="utf-8")
    monkeypatch.setattr(manager, "_current_run", lambda: (True, 12345))
    monkeypatch.setattr(
        manager,
        "_config_health",
        lambda: (True, True, 30, False, None),
    )
    monkeypatch.setattr(
        manager,
        "_load_config",
        lambda: (
            SimpleNamespace(
                full_archive=SimpleNamespace(
                    enabled=True,
                    runtime_fingerprint="archive-config-v1",
                )
            ),
            None,
        ),
    )

    payload = manager.status_payload()

    assert payload["full_archive"] == {
        "configured": True,
        "runtime_enabled": expected_runtime,
        "status": expected_state,
    }
    assert payload["healthy"] is expected_healthy
    if expected_state == "degraded":
        assert "Full Archive live capture is disabled" in payload["status"]
    elif expected_state == "unverified":
        assert "Full Archive runtime status is unavailable" in payload["status"]


def test_status_payload_marks_archive_config_changed_since_daemon_start(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    manager._ensure_runtime_dir()
    manager.run_health_path.write_text(
        json.dumps(
            {
                "pid": 12345,
                "last_tick": datetime.now(timezone.utc).isoformat(),
                "sqlite_pending": 0,
                "sqlite_pending_since": None,
                "full_archive": {
                    "configured": False,
                    "runtime_enabled": False,
                    "status": "disabled",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(manager, "_current_run", lambda: (True, 12345))
    monkeypatch.setattr(manager, "_config_health", lambda: (True, True, 30, False, None))
    monkeypatch.setattr(
        manager,
        "_load_config",
        lambda: (SimpleNamespace(full_archive=SimpleNamespace(enabled=True)), None),
    )

    payload = manager.status_payload()

    assert payload["full_archive"] == {
        "configured": True,
        "runtime_enabled": False,
        "status": "restart_required",
    }
    assert payload["healthy"] is False
    assert "restart the daemon" in payload["status"]


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("root_dir", Path("another-archive")),
        ("source_chat_id", -2002),
        ("capture_scope", "whole_group"),
        ("topic_ids", (20, 30)),
        ("shard_policy", "daily"),
        ("max_messages_per_shard", 123_456),
        ("max_shard_size_mb", 512),
        ("backfill_limit_messages", 2_000),
    ],
)
def test_status_payload_requires_restart_when_archive_settings_change(
    monkeypatch,
    tmp_path: Path,
    field_name,
    changed_value,
) -> None:
    manager = _manager(tmp_path)
    manager._ensure_runtime_dir()
    startup_archive = replace(
        FullArchiveConfig.disabled(),
        enabled=True,
        root_dir=tmp_path / "archive",
        source_chat_id=-1001,
        capture_scope="topics",
        topic_ids=(10, 20),
    )
    current_archive = replace(startup_archive, **{field_name: changed_value})
    manager.run_health_path.write_text(
        json.dumps(
            {
                "pid": 12345,
                "last_tick": datetime.now(timezone.utc).isoformat(),
                "sqlite_pending": 0,
                "sqlite_pending_since": None,
                "full_archive": {
                    "configured": True,
                    "runtime_enabled": True,
                    "status": "active",
                    "config_fingerprint": startup_archive.runtime_fingerprint,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(manager, "_current_run", lambda: (True, 12345))
    monkeypatch.setattr(manager, "_config_health", lambda: (True, True, 30, False, None))
    monkeypatch.setattr(
        manager,
        "_load_config",
        lambda: (SimpleNamespace(full_archive=current_archive), None),
    )

    payload = manager.status_payload()

    assert payload["full_archive"] == {
        "configured": True,
        "runtime_enabled": True,
        "status": "restart_required",
    }
    assert payload["healthy"] is False
    assert "restart the daemon" in payload["status"]


def test_current_run_clears_pid_when_process_identity_mismatch(monkeypatch, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager._ensure_runtime_dir()
    manager.run_pid_path.write_text("12345", encoding="utf-8")

    monkeypatch.setattr(manager, "_pid_is_running", lambda _pid: True)
    monkeypatch.setattr(manager, "_pid_matches_run_daemon", lambda _pid: False)

    running, pid = manager._current_run()

    assert running is False
    assert pid is None
    assert not manager.run_pid_path.exists()


def test_pid_match_rejects_basename_only_config(monkeypatch, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    monkeypatch.setattr(
        manager,
        "_pid_command",
        lambda _pid: "python -m tgwatch run --config config.toml --yes-retention",
    )

    assert manager._pid_matches_run_daemon(12345) is False


def test_pid_match_accepts_exact_absolute_config(monkeypatch, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    config_arg = str(manager.config_path.resolve())
    monkeypatch.setattr(
        manager,
        "_pid_command",
        lambda _pid: f"python -m tgwatch run --config {config_arg} --yes-retention",
    )

    assert manager._pid_matches_run_daemon(12345) is True


def test_pid_match_rejects_relative_config_path(monkeypatch, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    monkeypatch.setattr(
        manager,
        "_pid_command",
        lambda _pid: "python -m tgwatch run --config ./config.toml --yes-retention",
    )

    assert manager._pid_matches_run_daemon(12345) is False


def test_validate_payload_skips_topic_map_errors_when_routing_disabled() -> None:
    payload = {
        "telegram": {"api_id": "42", "api_hash": "abcdefghijk", "session_file": "data/tgwatch.session"},
        "sender": {"enabled": False, "session_file": ""},
        "targets": [
            {
                "name": "group-1",
                "target_chat_id": "-1001",
                "summary_interval_minutes": "",
                "control_group": "default",
                "tracked_users": [{"id": "123", "alias": ""}],
            }
        ],
        "control_groups": [
            {
                "key": "default",
                "control_chat_id": "-2001",
                "is_forum": False,
                "topic_routing_enabled": False,
                "topic_target_map": [{"user_key": "", "target_chat_id": "", "user_id": "", "topic_id": ""}],
            }
        ],
        "storage": {"db_path": "data/tgwatch.sqlite3", "media_dir": "data/media"},
        "reporting": {
            "reports_dir": "reports",
            "summary_interval_minutes": "120",
            "timezone": "UTC",
            "retention_days": "30",
        },
        "display": {"show_ids": True, "time_format": "%Y.%m.%d %H:%M:%S (%Z)"},
        "notifications": {"bark_key": ""},
    }

    errors, normalized = _validate_payload(payload, {})

    assert not errors
    assert normalized["control_groups"][0]["topic_target_map"] == []


def test_timezone_presets_cover_common_regions() -> None:
    presets = _build_timezone_presets()
    values = {entry["value"] for entry in presets}
    required = {
        "Asia/Shanghai",
        "Asia/Hong_Kong",
        "Asia/Tokyo",
        "Asia/Seoul",
        "America/New_York",
        "America/Chicago",
        "America/Los_Angeles",
        "Europe/London",
        "Europe/Paris",
        "Europe/Berlin",
    }
    for timezone in required:
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            continue
        assert timezone in values

    try:
        ZoneInfo("Asia/Osaka")
    except ZoneInfoNotFoundError:
        assert "Asia/Osaka" not in values
    else:
        assert "Asia/Osaka" in values


def test_normalize_config_keeps_custom_timezone_value() -> None:
    data = _normalize_config({"reporting": {"timezone": "Antarctica/Troll"}})

    assert data["reporting"]["timezone"] == "Antarctica/Troll"
    assert data["reporting_timezone_presets"]


def test_normalize_config_includes_time_format_units() -> None:
    data = _normalize_config({})
    assert "display_time_format_units" in data
    units = data["display_time_format_units"]
    assert set(units.keys()) == {
        "year", "month", "day", "hour", "minute", "second",
        "timezone", "date_separator",
    }
    assert len(units["year"]) == 2
    assert len(units["month"]) == 4
    assert len(units["day"]) == 2
    assert len(units["hour"]) == 3
    assert len(units["date_separator"]) == 3


def test_time_format_units_match_module_constant() -> None:
    data = _normalize_config({})
    assert data["display_time_format_units"] is _TIME_FORMAT_UNITS


def test_normalize_config_preserves_custom_time_format() -> None:
    data = _normalize_config({"display": {"time_format": "%B %-d, %Y %I:%M"}})
    assert data["display"]["time_format"] == "%B %-d, %Y %I:%M"


def test_normalize_config_includes_full_archive_defaults() -> None:
    data = _normalize_config({})

    assert data["full_archive"] == {
        "enabled": False,
        "root_dir": "data/full_archive",
        "source_chat_id": "",
        "capture_scope": "whole_group",
        "topic_ids": "",
        "shard_policy": "monthly",
        "max_messages_per_shard": 500000,
        "max_shard_size_mb": 1024,
        "backfill_limit_messages": 10000,
    }


def test_normalize_config_formats_full_archive_topic_ids() -> None:
    data = _normalize_config(
        {
            "full_archive": {
                "enabled": True,
                "source_chat_id": -1001,
                "capture_scope": "topics",
                "topic_ids": [10, 20],
            }
        }
    )

    assert data["full_archive"]["topic_ids"] == "10, 20"


def test_normalize_config_warns_when_full_archive_source_is_not_target() -> None:
    data = _normalize_config(
        {
            "targets": [
                {
                    "target_chat_id": -1001,
                    "tracked_user_ids": [123],
                }
            ],
            "full_archive": {
                "enabled": True,
                "source_chat_id": -2002,
            },
        }
    )

    assert data["full_archive_source_warning"] is True


def test_normalize_config_skips_full_archive_source_warning_when_matching_target() -> None:
    data = _normalize_config(
        {
            "targets": [
                {
                    "target_chat_id": -1001,
                    "tracked_user_ids": [123],
                }
            ],
            "full_archive": {
                "enabled": True,
                "source_chat_id": -1001,
            },
        }
    )

    assert data["full_archive_source_warning"] is False


def test_load_raw_config_reports_invalid_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[telegram\napi_id = 42\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="Invalid TOML"):
        _load_raw_config(config_path)


def test_render_toml_quotes_control_group_key() -> None:
    normalized = {
        "config_version": 1.0,
        "telegram": {"api_id": 42, "api_hash": "abcdefghijk", "session_file": "data/tgwatch.session"},
        "sender": {"enabled": False, "session_file": ""},
        "targets": [
            {
                "name": "group-1",
                "target_chat_id": -1001,
                "tracked_user_ids": [123],
                "tracked_user_aliases": {},
                "summary_interval_minutes": None,
                "control_group": "main group",
            }
        ],
        "control_groups": [
            {
                "key": "main group",
                "control_chat_id": -2001,
                "is_forum": True,
                "topic_routing_enabled": True,
                "skip_html_report": False,
                "topic_target_map": [
                    {"target_chat_id": -1001, "user_id": 123, "topic_id": 9001, "user_key": ""}
                ],
            }
        ],
        "storage": {"db_path": "data/tgwatch.sqlite3", "media_dir": "data/media"},
        "reporting": {
            "reports_dir": "reports",
            "summary_interval_minutes": 120,
            "timezone": "UTC",
            "retention_days": 30,
        },
        "display": {"show_ids": True, "time_format": "%Y.%m.%d %H:%M:%S (%Z)"},
        "notifications": {"bark_key": ""},
    }

    toml_text = _render_toml(normalized, {})
    parsed = tomllib.loads(toml_text)

    assert '[control_groups."main group"]' in toml_text
    assert parsed["control_groups"]["main group"]["control_chat_id"] == -2001
    assert parsed["control_groups"]["main group"]["topic_target_map"]["-1001"]["123"] == 9001


def test_normalize_config_display_template_default_when_missing() -> None:
    data = _normalize_config({})
    assert data["display"]["template"] == "normal"


def test_normalize_config_display_template_preserved() -> None:
    data = _normalize_config({"display": {"template": "minimal"}})
    assert data["display"]["template"] == "minimal"


def _minimal_valid_payload() -> dict:
    return {
        "telegram": {"api_id": "42", "api_hash": "abcdefghijk", "session_file": "data/tgwatch.session"},
        "sender": {"enabled": False, "session_file": ""},
        "targets": [
            {
                "name": "group-1",
                "target_chat_id": "-1001",
                "summary_interval_minutes": "",
                "control_group": "default",
                "tracked_users": [{"id": "123", "alias": ""}],
            }
        ],
        "control_groups": [
            {
                "key": "default",
                "control_chat_id": "-2001",
                "is_forum": False,
                "topic_routing_enabled": False,
                "topic_target_map": [],
            }
        ],
        "storage": {"db_path": "data/tgwatch.sqlite3", "media_dir": "data/media"},
        "reporting": {
            "reports_dir": "reports",
            "summary_interval_minutes": "120",
            "timezone": "UTC",
            "retention_days": "30",
        },
        "display": {"show_ids": True, "time_format": "%Y.%m.%d %H:%M:%S (%Z)", "language": "auto"},
        "notifications": {"bark_key": ""},
    }


def test_validate_payload_accepts_normal_and_minimal_templates() -> None:
    payload = _minimal_valid_payload()
    payload["display"]["template"] = "minimal"
    errors, normalized = _validate_payload(payload, {})
    assert not errors
    assert normalized["display"]["template"] == "minimal"

    payload["display"]["template"] = "normal"
    errors, normalized = _validate_payload(payload, {})
    assert not errors
    assert normalized["display"]["template"] == "normal"


def test_validate_payload_unknown_template_falls_back_to_normal() -> None:
    payload = _minimal_valid_payload()
    payload["display"]["template"] = "fancy"
    errors, normalized = _validate_payload(payload, {})
    assert not errors  # unknown value is coerced to default, not an error
    assert normalized["display"]["template"] == "normal"


def test_validate_payload_missing_template_defaults_to_normal() -> None:
    payload = _minimal_valid_payload()
    assert "template" not in payload["display"]
    errors, normalized = _validate_payload(payload, {})
    assert not errors
    assert normalized["display"]["template"] == "normal"


def test_validate_payload_accepts_full_archive_topics() -> None:
    payload = _minimal_valid_payload()
    payload["full_archive"] = {
        "enabled": True,
        "root_dir": "data/full_archive",
        "source_chat_id": "-1001",
        "capture_scope": "topics",
        "topic_ids": "10, 20",
        "shard_policy": "monthly",
        "max_messages_per_shard": "500000",
        "max_shard_size_mb": "1024",
        "backfill_limit_messages": "100",
    }

    errors, normalized = _validate_payload(payload, {})

    assert not errors
    assert normalized["full_archive"]["enabled"] is True
    assert normalized["full_archive"]["source_chat_id"] == -1001
    assert normalized["full_archive"]["topic_ids"] == [10, 20]


def test_validate_payload_rejects_reserved_full_archive_topic_ids() -> None:
    payload = _minimal_valid_payload()
    payload["full_archive"] = {
        "enabled": True,
        "root_dir": "data/full_archive",
        "source_chat_id": "-1001",
        "capture_scope": "topics",
        "topic_ids": "0, 1, -1",
        "shard_policy": "monthly",
        "max_messages_per_shard": "500000",
        "max_shard_size_mb": "1024",
        "backfill_limit_messages": "100",
    }

    errors, normalized = _validate_payload(payload, {})

    assert (
        "full_archive.topic_ids values must be Telegram forum topic IDs > 1; "
        "use whole_group for General"
    ) in errors
    assert "full_archive.topic_ids is required when capture_scope is 'topics'" in errors
    assert normalized["full_archive"]["topic_ids"] == []


def test_validate_payload_allows_disabled_topic_scope_draft_without_topics() -> None:
    payload = _minimal_valid_payload()
    payload["full_archive"] = {
        "enabled": False,
        "source_chat_id": "",
        "capture_scope": "topics",
        "topic_ids": "",
    }

    errors, normalized = _validate_payload(payload, {})

    assert not errors
    assert normalized["full_archive"]["enabled"] is False
    assert normalized["full_archive"]["capture_scope"] == "topics"
    assert normalized["full_archive"]["topic_ids"] == []


def test_validate_payload_rejects_enabled_full_archive_without_source() -> None:
    payload = _minimal_valid_payload()
    payload["full_archive"] = {
        "enabled": True,
        "source_chat_id": "0",
        "capture_scope": "whole_group",
    }

    errors, _normalized = _validate_payload(payload, {})

    assert "full_archive.source_chat_id must not be 0" in errors


def test_validate_payload_treats_string_false_full_archive_as_disabled() -> None:
    payload = _minimal_valid_payload()
    payload["full_archive"] = {
        "enabled": "false",
        "source_chat_id": "",
        "capture_scope": "whole_group",
    }

    errors, normalized = _validate_payload(payload, {})

    assert not errors
    assert normalized["full_archive"]["enabled"] is False


def test_validate_payload_preserves_zero_full_archive_backfill_limit() -> None:
    payload = _minimal_valid_payload()
    payload["full_archive"] = {
        "enabled": False,
        "source_chat_id": "",
        "capture_scope": "whole_group",
        "backfill_limit_messages": "0",
    }

    errors, normalized = _validate_payload(payload, {})

    assert not errors
    assert normalized["full_archive"]["backfill_limit_messages"] == 0


def test_render_toml_writes_display_template() -> None:
    normalized = {
        "config_version": 1.0,
        "telegram": {"api_id": 42, "api_hash": "abcdefghijk", "session_file": "data/tgwatch.session"},
        "sender": {"enabled": False, "session_file": ""},
        "targets": [
            {
                "name": "group-1",
                "target_chat_id": -1001,
                "tracked_user_ids": [123],
                "tracked_user_aliases": {},
                "summary_interval_minutes": None,
                "control_group": "default",
            }
        ],
        "control_groups": [
            {
                "key": "default",
                "control_chat_id": -2001,
                "is_forum": False,
                "topic_routing_enabled": False,
                "skip_html_report": False,
                "topic_target_map": [],
            }
        ],
        "storage": {"db_path": "data/db", "media_dir": "data/media"},
        "reporting": {"reports_dir": "reports", "summary_interval_minutes": 120, "timezone": "UTC", "retention_days": 30},
        "display": {
            "show_ids": True,
            "time_format": "%Y.%m.%d %H:%M:%S (%Z)",
            "language": "auto",
            "template": "minimal",
        },
        "notifications": {"bark_key": "", "heartbeat_interval_hours": 2, "check_updates": True},
    }

    toml_text = _render_toml(normalized, {})
    assert 'template = "minimal"' in toml_text

    parsed = tomllib.loads(toml_text)
    assert parsed["display"]["template"] == "minimal"


def test_render_toml_writes_full_archive() -> None:
    normalized = _minimal_valid_payload()
    errors, normalized = _validate_payload(normalized, {})
    assert not errors
    normalized["full_archive"] = {
        "enabled": True,
        "root_dir": "data/full_archive",
        "source_chat_id": -1001,
        "capture_scope": "topics",
        "topic_ids": [10, 20],
        "shard_policy": "monthly",
        "max_messages_per_shard": 500000,
        "max_shard_size_mb": 1024,
        "backfill_limit_messages": 10000,
    }

    toml_text = _render_toml(normalized, {})
    parsed = tomllib.loads(toml_text)

    assert parsed["full_archive"]["enabled"] is True
    assert parsed["full_archive"]["source_chat_id"] == -1001
    assert parsed["full_archive"]["topic_ids"] == [10, 20]


def test_render_toml_omits_empty_full_archive_source_chat_id() -> None:
    payload = _minimal_valid_payload()
    errors, normalized = _validate_payload(payload, {})
    assert not errors

    toml_text = _render_toml(normalized, {})
    parsed = tomllib.loads(toml_text)

    assert "source_chat_id" not in parsed["full_archive"]


def test_render_toml_preserves_zero_full_archive_backfill_limit() -> None:
    payload = _minimal_valid_payload()
    payload["full_archive"] = {
        "enabled": False,
        "source_chat_id": "",
        "capture_scope": "whole_group",
        "backfill_limit_messages": "0",
    }
    errors, normalized = _validate_payload(payload, {})
    assert not errors

    toml_text = _render_toml(normalized, {})
    parsed = tomllib.loads(toml_text)

    assert parsed["full_archive"]["backfill_limit_messages"] == 0


def test_gui_i18n_dict_contains_template_keys_both_languages() -> None:
    # Parse the JS _i18n object from gui.py and verify both locales have the new keys.
    from telegram_watch import gui as gui_mod
    import re

    source = Path(gui_mod.__file__).read_text(encoding="utf-8")
    # Extract the substring from `const _i18n = {` to the matching closing `};` (naive but enough).
    start = source.index("const _i18n = {")
    # Find end: the block ends with `};` followed by a newline and the _tzLabels block.
    end = source.index("// Timezone label translations", start)
    block = source[start:end]

    required_keys = [
        "messageTemplateSection",
        "messageTemplateHelp",
        "template:",
        "templateNormal",
        "templateMinimal",
        "templateNormalDesc",
        "templateMinimalDesc",
        "templatePreview",
        "messageFieldsSection",
        "languageSection",
        "notificationsSection",
        "fullArchiveSection",
        "fullArchiveEnabled",
        "fullArchiveTopicIds",
        "fullArchiveTopicIdsHelp",
        "fullArchiveSourceBannerTitle",
        "fullArchiveSourceBannerDesc",
    ]
    for key in required_keys:
        # Each key should appear at least twice (once in en, once in zh).
        key_literal = key.rstrip(":") + ":"
        occurrences = len(re.findall(r"\b" + re.escape(key_literal), block))
        assert occurrences >= 2, f"i18n key {key_literal!r} missing from zh or en ({occurrences} occurrences)"
    assert (
        "Required only when Full Archive is enabled and capture scope is Selected Topics"
        in block
    )
    assert "仅在启用全量归档且采集范围为指定话题时必填" in block
