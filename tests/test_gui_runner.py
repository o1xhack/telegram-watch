from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from telegram_watch.gui import _RunnerManager, _validate_payload


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
