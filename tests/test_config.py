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
    assert config.targets[0].tracked_user_ids == (123, 456)
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
    assert config.targets[0].tracked_user_aliases[123] == "Alice"
    assert config.describe_user(123, target=config.targets[0]) == "Alice (123)"


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
    control = config.control_groups["default"]
    assert control.is_forum is True
    assert control.topic_routing_enabled is True
    assert control.topic_user_map[123] == 9001


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


def test_multi_control_requires_target_mapping(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        name = "group-a"
        target_chat_id = -1001
        tracked_user_ids = [123]

        [[targets]]
        name = "group-b"
        target_chat_id = -1002
        tracked_user_ids = [456]

        [control_groups.main]
        control_chat_id = -1003

        [control_groups.alt]
        control_chat_id = -1004

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_single_control_group_is_default(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        name = "group-a"
        target_chat_id = -1001
        tracked_user_ids = [123]

        [control_groups.main]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    assert config.targets[0].control_group == "main"
    assert config.targets_by_control["main"][0].name == "group-a"


def test_unknown_control_group_raises(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        name = "group-a"
        target_chat_id = -1001
        tracked_user_ids = [123]
        control_group = "missing"

        [control_groups.main]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_topic_map_scoped_to_control_group(tmp_path):
    cfg_path = write_config(
        tmp_path,
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
        control_chat_id = -1003
        is_forum = true
        topic_routing_enabled = true

        [control_groups.main.topic_user_map]
        456 = 9001

        [control_groups.alt]
        control_chat_id = -1004

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_target_interval_overrides_reporting_default(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        name = "group-a"
        target_chat_id = -1001
        tracked_user_ids = [123]
        summary_interval_minutes = 15

        [control_groups.main]
        control_chat_id = -1002

        [reporting]
        summary_interval_minutes = 120

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    assert config.targets[0].summary_interval_minutes == 15


def test_multi_control_group_mapping_ok(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        name = "group-a"
        target_chat_id = -1001
        tracked_user_ids = [123, 124]
        control_group = "main"

        [[targets]]
        name = "group-b"
        target_chat_id = -1002
        tracked_user_ids = [456]
        control_group = "alt"

        [control_groups.main]
        control_chat_id = -1003

        [control_groups.alt]
        control_chat_id = -1004

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    assert config.targets_by_control["main"][0].name == "group-a"
    assert config.targets_by_control["alt"][0].name == "group-b"
    assert config.control_groups["main"].control_chat_id == -1003
    assert config.control_groups["alt"].control_chat_id == -1004


def test_forum_topic_map_valid_per_control_group(tmp_path):
    cfg_path = write_config(
        tmp_path,
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
        control_chat_id = -1003
        is_forum = true
        topic_routing_enabled = true

        [control_groups.main.topic_user_map]
        123 = 9001

        [control_groups.alt]
        control_chat_id = -1004
        is_forum = true
        topic_routing_enabled = true

        [control_groups.alt.topic_user_map]
        456 = 9002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    assert config.control_groups["main"].topic_user_map[123] == 9001
    assert config.control_groups["alt"].topic_user_map[456] == 9002


def test_target_aliases_are_scoped(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        name = "group-a"
        target_chat_id = -1001
        tracked_user_ids = [123]
        control_group = "main"

        [targets.tracked_user_aliases]
        123 = "Alpha"

        [[targets]]
        name = "group-b"
        target_chat_id = -1002
        tracked_user_ids = [456]
        control_group = "main"

        [targets.tracked_user_aliases]
        456 = "Beta"

        [control_groups.main]
        control_chat_id = -1003

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    target_a = config.target_by_name["group-a"]
    target_b = config.target_by_name["group-b"]
    assert config.describe_user(123, target=target_a) == "Alpha (123)"
    assert config.describe_user(456, target=target_b) == "Beta (456)"


def test_rejects_target_and_targets_both_set(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [123]

        [[targets]]
        name = "group-a"
        target_chat_id = -1002
        tracked_user_ids = [456]

        [control]
        control_chat_id = -1003

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_rejects_control_and_control_groups_both_set(tmp_path):
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

        [control_groups.main]
        control_chat_id = -1003

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_duplicate_target_chat_id_rejected(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        name = "group-a"
        target_chat_id = -1001
        tracked_user_ids = [123]

        [[targets]]
        name = "group-b"
        target_chat_id = -1001
        tracked_user_ids = [456]

        [control_groups.main]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_duplicate_target_name_rejected(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        name = "group-a"
        target_chat_id = -1001
        tracked_user_ids = [123]

        [[targets]]
        name = "group-a"
        target_chat_id = -1002
        tracked_user_ids = [456]

        [control_groups.main]
        control_chat_id = -1003

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_duplicate_control_chat_id_rejected(tmp_path):
    cfg_path = write_config(
        tmp_path,
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
        control_chat_id = -1003

        [control_groups.alt]
        control_chat_id = -1003

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_target_group_limit_exceeded(tmp_path):
    targets = "\n\n".join(
        f"""
        [[targets]]
        name = "group-{idx}"
        target_chat_id = -100{idx}
        tracked_user_ids = [123]
        """
        for idx in range(1, 7)
    )
    cfg_path = write_config(
        tmp_path,
        f"""
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        {targets}

        [control_groups.main]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_users_per_target_limit_exceeded(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        name = "group-a"
        target_chat_id = -1001
        tracked_user_ids = [1, 2, 3, 4, 5, 6]

        [control_groups.main]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_control_group_limit_exceeded(tmp_path):
    controls = "\n\n".join(
        f"""
        [control_groups.group{idx}]
        control_chat_id = -100{idx}
        """
        for idx in range(1, 7)
    )
    cfg_path = write_config(
        tmp_path,
        f"""
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        name = "group-a"
        target_chat_id = -1001
        tracked_user_ids = [123]
        control_group = "group1"

        {controls}

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)
