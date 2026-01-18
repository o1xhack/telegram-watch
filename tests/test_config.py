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
