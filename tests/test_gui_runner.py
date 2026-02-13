from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from telegram_watch.config import ConfigError
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
