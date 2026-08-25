from pathlib import Path
from textwrap import dedent

import pytest

from telegram_watch import __version__
from telegram_watch.config import ConfigError, load_config


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_config(tmp_path: Path, body: str, *, include_version: bool = True) -> Path:
    cfg_path = tmp_path / "config.toml"
    content = dedent(body).lstrip()
    if include_version and "config_version" not in content:
        content = f"config_version = 1.0\n\n{content}"
    cfg_path.write_text(content, encoding="utf-8")
    return cfg_path


def test_missing_config_version_raises(tmp_path):
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

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
        include_version=False,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_invalid_config_version_raises(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        config_version = 0.9

        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [123]

        [control]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
        include_version=False,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


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


def test_config_example_parses_with_full_archive_disabled():
    config = load_config(REPO_ROOT / "config.example.toml")

    assert config.full_archive.enabled is False
    assert config.full_archive.source_chat_id is None
    assert config.full_archive.capture_scope == "whole_group"
    assert config.full_archive.topic_ids == ()


@pytest.mark.parametrize(
    "doc_path",
    [
        "docs/configuration.md",
        "docs/configuration.zh-Hans.md",
        "docs/configuration.zh-Hant.md",
        "docs/configuration.ja.md",
    ],
)
def test_configuration_docs_include_full_archive_reference(doc_path):
    text = (REPO_ROOT / doc_path).read_text(encoding="utf-8")

    for required in (
        "[full_archive]",
        "source_chat_id",
        "topic_ids",
        "backfill_limit_messages",
        "archive-status",
        "archive-context",
        "archive-backfill",
        "archive-qa-init",
        "reports/full_archive_qa",
        "archive-repair --prune-missing-shards --apply",
        "full_archive.retention_days",
    ):
        assert required in text


def test_full_archive_overview_documents_delivery_proof_levels():
    text = (REPO_ROOT / "docs/full-message-archive/README.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "交付证明分级",
        "离线可合并",
        "本机可验收",
        "真实端到端可交付",
        "archive-qa-init",
        "没有这份脱敏 QA 记录时",
        "只能说“离线测试通过”",
        "CR 只能按已经被证据证明的最高层级下结论",
        "离线通过，待真实 QA",
        "本机可验收，待真实 QA",
        "非真实 TG CR 审计",
        "CR_AUDIT.md",
    ):
        assert required in text


def test_full_archive_cr_audit_documents_non_real_tg_evidence():
    text = (REPO_ROOT / "docs/full-message-archive/CR_AUDIT.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "离线通过，待真实 QA",
        "不能声明：真实端到端可交付",
        "现有 tracked-user watcher 不回归",
        "默认关闭对老 config / 老 DB / 老用户无影响",
        "archive 数据与 tracked DB 建立清晰连接",
        "不重复保存 tracked 正文和媒体",
        "数据库可管理、可删除、可恢复",
        "Topic 归类是第一阶段 best-effort",
        "每轮 CR 最小检查",
        "full_archive.enabled=false",
    ):
        assert required in text


def test_full_archive_release_metadata_is_prepared():
    assert __version__ == "1.8.1"

    changelog = (REPO_ROOT / "docs/CHANGELOG.md").read_text(encoding="utf-8")
    for required in (
        "## 1.8.1 — 2026-08-24",
        "recognizing only canonical archive shard paths",
        "## 1.8.0 — 2026-07-15",
        "serializing all daemon SQLite work",
        "health heartbeat",
        "## 1.8.0",
        "full-message archive",
        "`tracked_ref`",
        "`archive-context`",
        "`archive-qa-init`",
        "Reconnect the configured sender account",
        "falling back to the primary account",
        "control-chat warning",
    ):
        assert required in changelog

    for doc_path in (
        "docs/CHANGELOG.zh-Hans.md",
        "docs/CHANGELOG.zh-Hant.md",
        "docs/CHANGELOG.ja.md",
    ):
        localized = (REPO_ROOT / doc_path).read_text(encoding="utf-8")
        assert "## 1.8.0" in localized
        assert "`archive-context`" in localized


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

        [control.topic_target_map."-1001"]
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
    assert control.topic_target_map[-1001][123] == 9001


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

        [control.topic_target_map."-1001"]
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

        [control.topic_target_map."-1001"]
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

        [control_groups.main.topic_target_map."-1002"]
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

        [control_groups.main.topic_target_map."-1001"]
        123 = 9001

        [control_groups.alt]
        control_chat_id = -1004
        is_forum = true
        topic_routing_enabled = true

        [control_groups.alt.topic_target_map."-1002"]
        456 = 9002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    assert config.control_groups["main"].topic_target_map[-1001][123] == 9001
    assert config.control_groups["alt"].topic_target_map[-1002][456] == 9002


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


def test_target_alias_scope_does_not_fallback_to_other_target(tmp_path):
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
        tracked_user_ids = [123]
        control_group = "main"

        [control_groups.main]
        control_chat_id = -1003

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    target_b = config.target_by_name["group-b"]
    assert config.describe_user(123, target=target_b) == "123"


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


def test_missing_target_name_defaults(tmp_path):
    cfg_path = write_config(
        tmp_path,
        """
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [[targets]]
        target_chat_id = -1001
        tracked_user_ids = [123]

        [[targets]]
        target_chat_id = -1002
        tracked_user_ids = [456]

        [control_groups.main]
        control_chat_id = -1003

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    assert config.targets[0].name == "group-1"
    assert config.targets[1].name == "group-2"


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


def test_skip_html_report_defaults_false(tmp_path):
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

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    assert config.control_groups["default"].skip_html_report is False


def test_skip_html_report_parses_true(tmp_path):
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
        skip_html_report = true

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    assert config.control_groups["default"].skip_html_report is True


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


def test_full_archive_defaults_disabled(tmp_path):
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

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"
        """,
    )
    config = load_config(cfg_path)
    archive = config.full_archive
    assert archive.enabled is False
    assert archive.root_dir == tmp_path / "data" / "full_archive"
    assert archive.source_chat_id is None
    assert archive.capture_scope == "whole_group"
    assert archive.topic_ids == ()
    assert archive.max_messages_per_shard == 500_000


def test_full_archive_parses_whole_group_config(tmp_path):
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

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"

        [full_archive]
        enabled = true
        root_dir = "data/archive"
        source_chat_id = -1001
        capture_scope = "whole_group"
        max_messages_per_shard = 100
        max_shard_size_mb = 2
        backfill_limit_messages = 0
        """,
    )
    config = load_config(cfg_path)
    archive = config.full_archive
    assert archive.enabled is True
    assert archive.root_dir == tmp_path / "data" / "archive"
    assert archive.source_chat_id == -1001
    assert archive.capture_scope == "whole_group"
    assert archive.topic_ids == ()
    assert archive.max_messages_per_shard == 100
    assert archive.max_shard_size_bytes == 2 * 1024 * 1024
    assert archive.backfill_limit_messages == 0


def test_full_archive_parses_topic_config(tmp_path):
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

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"

        [full_archive]
        enabled = true
        source_chat_id = -1001
        capture_scope = "topics"
        topic_ids = [10, 20]
        """,
    )
    config = load_config(cfg_path)
    assert config.full_archive.capture_scope == "topics"
    assert config.full_archive.topic_ids == (10, 20)


def test_full_archive_enabled_requires_source_chat_id(tmp_path):
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

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"

        [full_archive]
        enabled = true
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


@pytest.mark.parametrize("enabled_value", ['"true"', "1"])
def test_full_archive_enabled_requires_boolean(tmp_path, enabled_value):
    cfg_path = write_config(
        tmp_path,
        f"""
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [123]

        [control]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"

        [full_archive]
        enabled = {enabled_value}
        source_chat_id = -1001
        """,
    )
    with pytest.raises(ConfigError, match="full_archive.enabled must be a boolean"):
        load_config(cfg_path)


def test_full_archive_topics_scope_requires_topic_ids(tmp_path):
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

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"

        [full_archive]
        enabled = true
        source_chat_id = -1001
        capture_scope = "topics"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_disabled_full_archive_allows_unfinished_topic_scope_draft(tmp_path):
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

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"

        [full_archive]
        enabled = false
        capture_scope = "topics"
        topic_ids = []
        """,
    )

    config = load_config(cfg_path)

    assert config.full_archive.enabled is False
    assert config.full_archive.capture_scope == "topics"
    assert config.full_archive.topic_ids == ()


def test_full_archive_enabled_rejects_zero_source_chat_id(tmp_path):
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

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"

        [full_archive]
        enabled = true
        source_chat_id = 0
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)


@pytest.mark.parametrize(
    "body",
    [
        'capture_scope = "invalid"',
        "max_messages_per_shard = 0",
        "max_shard_size_mb = 0",
        "backfill_limit_messages = -1",
        "retention_days = 0",
        "topic_ids = [0]",
        "topic_ids = [1]",
        'shard_policy = "daily"',
    ],
)
def test_full_archive_rejects_invalid_values(tmp_path, body):
    cfg_path = write_config(
        tmp_path,
        f"""
        [telegram]
        api_id = 42
        api_hash = "abcdefghijk"

        [target]
        target_chat_id = -1001
        tracked_user_ids = [123]

        [control]
        control_chat_id = -1002

        [storage]
        db_path = "data/app.sqlite3"
        media_dir = "data/media"

        [full_archive]
        source_chat_id = -1001
        {body}
        """,
    )
    with pytest.raises(ConfigError):
        load_config(cfg_path)
