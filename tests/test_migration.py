from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import tomllib

from telegram_watch.migration import CONFIG_BACKUP_NAME, detect_migration_needed, migrate_config


def write(path: Path, body: str) -> None:
    path.write_text(dedent(body).lstrip(), encoding="utf-8")


def test_detect_migration_needed_missing_version(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write(
        config_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"
        """,
    )
    needs, reason = detect_migration_needed(config_path)
    assert needs is True
    assert "config_version" in reason


def test_detect_migration_needed_ok(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write(config_path, "config_version = 1.0\n")
    needs, reason = detect_migration_needed(config_path)
    assert needs is False
    assert "ok" in reason


def test_migrate_config_creates_backup_and_new_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    original = dedent(
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [123]

        [control]
        control_chat_id = -2000
        is_forum = true
        topic_routing_enabled = true

        [control.topic_user_map]
        123 = 9001

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """
    ).lstrip()
    config_path.write_text(original, encoding="utf-8")

    result = migrate_config(config_path)
    assert result.ok is True
    assert result.backup_path is not None

    backup_path = tmp_path / CONFIG_BACKUP_NAME
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == original

    assert not (tmp_path / "config-sample.toml").exists()

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data["config_version"] == 1.0
    assert "control_groups" in data
    topic_map = data["control_groups"]["default"]["topic_target_map"]["-1001"]
    assert topic_map["123"] == 9001
