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


def test_migrate_config_preserves_multiple_control_groups(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    original = dedent(
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        name = "group-a"
        target_chat_id = -1001
        tracked_user_ids = [123]
        control_group = "main"

        [[targets]]
        name = "group-b"
        target_chat_id = -1002
        tracked_user_ids = [456]
        control_group = "alt"

        [control_groups.main]
        control_chat_id = -2001
        is_forum = true
        topic_routing_enabled = true

        [control_groups.main.topic_target_map."-1001"]
        123 = 901

        [control_groups.alt]
        control_chat_id = -2002
        is_forum = true
        topic_routing_enabled = true

        [control_groups.alt.topic_target_map."-1002"]
        456 = 902

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """
    ).lstrip()
    config_path.write_text(original, encoding="utf-8")

    result = migrate_config(config_path)
    assert result.ok is True

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert set(data["control_groups"].keys()) == {"main", "alt"}
    assert data["control_groups"]["main"]["control_chat_id"] == -2001
    assert data["control_groups"]["alt"]["control_chat_id"] == -2002
    assert data["control_groups"]["main"]["topic_target_map"]["-1001"]["123"] == 901
    assert data["control_groups"]["alt"]["topic_target_map"]["-1002"]["456"] == 902


def test_migrate_config_keeps_existing_backup_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    original = dedent(
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"
        """
    ).lstrip()
    config_path.write_text(original, encoding="utf-8")

    existing_backup = tmp_path / CONFIG_BACKUP_NAME
    existing_backup.write_text("old-backup", encoding="utf-8")

    result = migrate_config(config_path)

    assert result.ok is True
    assert result.backup_path is not None
    assert result.backup_path.name == "config-old-0.1-1.toml"
    assert existing_backup.read_text(encoding="utf-8") == "old-backup"
    assert result.backup_path.read_text(encoding="utf-8") == original
