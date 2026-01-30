from pathlib import Path
from textwrap import dedent

import pytest

from telegram_watch.config import ConfigError, load_config


def write_config(tmp_path: Path, body: str) -> Path:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(dedent(body), encoding="utf-8")
    return cfg_path


def test_load_config_resolves_relative_paths(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"
        session_file = "sessions/user.session"

        [sender]
        session_file = "sessions/sender.session"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [123, 456]

        [control]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"

        [reporting]
        reports_dir = "reports"
        summary_interval_minutes = 60
        """,
    )
    config = load_config(cfg_path)
    assert config.telegram.api_id == 42
    assert config.target.tracked_user_ids == (123, 456)
    assert config.storage.db_path.is_absolute()
    assert config.storage.media_dir.is_absolute()
    assert config.reporting.reports_dir.is_absolute()
    assert config.telegram.session_file.is_absolute()
    assert config.sender is not None
    assert config.sender.session_file.is_absolute()


def test_missing_fields_raise(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [target]
        target_chat_id = -1001
        tracked_user_ids = []

        [control]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_tracked_user_aliases_optional(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [123]

        [target.tracked_user_aliases]
        123 = "Alice"

        [control]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    assert config.target.tracked_user_aliases[123] == "Alice"
    assert config.describe_user(123) == "Alice (123)"


def test_sender_session_must_differ_from_primary(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"
        session_file = "sessions/shared.session"

        [sender]
        session_file = "sessions/shared.session"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [123]

        [control]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_aliases_must_match_tracked_users(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [321]

        [target.tracked_user_aliases]
        999 = "Ghost"

        [control]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_topic_routing_parses_when_enabled(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [123, 456]

        [control]
        control_chat_id = -1002
        is_forum = true
        topic_routing_enabled = true

        [control.topic_user_map]
        123 = 9001
        456 = 9002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    assert config.control.is_forum is True
    assert config.control.topic_routing_enabled is True
    assert config.control.topic_user_map[123] == 9001


def test_topic_routing_requires_forum_flag(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [123]

        [control]
        control_chat_id = -1002
        is_forum = false
        topic_routing_enabled = true

        [control.topic_user_map]
        123 = 9001

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_topic_routing_rejects_unknown_users(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [123]

        [control]
        control_chat_id = -1002
        is_forum = true
        topic_routing_enabled = true

        [control.topic_user_map]
        999 = 9001

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)
