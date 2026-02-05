"""Config migration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # pragma: no cover - Python 3.11+ always hits first branch
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

CONFIG_BACKUP_NAME = "config-old-0.1.toml"


@dataclass(frozen=True)
class MigrationResult:
    ok: bool
    status: str
    backup_path: Path | None = None


def detect_migration_needed(config_path: Path) -> tuple[bool, str]:
    if not config_path.exists():
        return False, "config.toml not found"
    try:
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception:
        return True, "config file invalid"
    raw_version = data.get("config_version")
    if raw_version is None:
        return True, "config_version missing"
    try:
        version = float(raw_version)
    except (TypeError, ValueError):
        return True, "config_version invalid"
    if version != 1.0:
        return True, f"config_version {version} unsupported"
    return False, "config_version ok"


def migrate_config(config_path: Path) -> MigrationResult:
    if not config_path.exists():
        return MigrationResult(False, "config.toml not found")

    backup_path = config_path.with_name(CONFIG_BACKUP_NAME)

    raw = {}
    raw_status = None
    try:
        raw = _read_raw(config_path)
    except Exception:
        raw_status = "Old config could not be parsed; created a fresh template."

    # Backup old config
    config_path.replace(backup_path)

    # Build a best-effort new config
    new_text = _build_new_config(raw)
    config_path.write_text(new_text, encoding="utf-8")

    status = "Migration completed. Review config.toml before running."
    if raw_status:
        status = raw_status
    return MigrationResult(True, status, backup_path=backup_path)


def _read_raw(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _build_new_config(raw: dict[str, Any]) -> str:
    telegram = raw.get("telegram", {}) or {}
    storage = raw.get("storage", {}) or {}
    reporting = raw.get("reporting", {}) or {}
    display = raw.get("display", {}) or {}
    notifications = raw.get("notifications", {}) or {}

    sender_raw = raw.get("sender") if isinstance(raw.get("sender"), dict) else None

    # Targets: old config used [target] or [[targets]]
    targets_raw = []
    if "targets" in raw:
        targets_raw = raw.get("targets", []) or []
    elif "target" in raw:
        targets_raw = [raw.get("target", {})]

    if not targets_raw:
        targets_raw = [{}]

    control_groups = raw.get("control_groups") if isinstance(raw.get("control_groups"), dict) else None
    control_raw = raw.get("control") if isinstance(raw.get("control"), dict) else None

    control_key = "default"
    control_chat_id = None
    is_forum = False
    topic_routing_enabled = False
    topic_user_map = {}

    if control_groups:
        # pick first control group as default
        first_key = next(iter(control_groups.keys()))
        control_key = str(first_key)
        first_group = control_groups[first_key] or {}
        control_chat_id = first_group.get("control_chat_id")
        is_forum = bool(first_group.get("is_forum", False))
        topic_routing_enabled = bool(first_group.get("topic_routing_enabled", False))
        topic_user_map = first_group.get("topic_user_map", {}) or {}
    elif control_raw:
        control_chat_id = control_raw.get("control_chat_id")
        is_forum = bool(control_raw.get("is_forum", False))
        topic_routing_enabled = bool(control_raw.get("topic_routing_enabled", False))
        topic_user_map = control_raw.get("topic_user_map", {}) or {}

    lines: list[str] = []
    lines.append("config_version = 1.0")
    lines.append("")

    lines.append("[telegram]")
    if "api_id" in telegram:
        lines.append(f"api_id = {telegram.get('api_id')}")
    if "api_hash" in telegram:
        api_hash = str(telegram.get("api_hash", ""))
        lines.append(f"api_hash = {toml_string(api_hash)}")
    session_file = telegram.get("session_file", "data/tgwatch.session")
    lines.append(f"session_file = {toml_string(str(session_file))}")

    if sender_raw:
        lines.append("")
        lines.append("[sender]")
        sender_session = sender_raw.get("session_file", "")
        lines.append(f"session_file = {toml_string(str(sender_session))}")

    for idx, target in enumerate(targets_raw, start=1):
        if not isinstance(target, dict):
            continue
        name = target.get("name") or f"group-{idx}"
        target_chat_id = target.get("target_chat_id")
        tracked_ids = target.get("tracked_user_ids", []) or []
        summary_interval = target.get("summary_interval_minutes")
        control_group = target.get("control_group") or control_key

        lines.append("")
        lines.append("[[targets]]")
        lines.append(f"name = {toml_string(str(name))}")
        if target_chat_id is not None:
            lines.append(f"target_chat_id = {target_chat_id}")
        if tracked_ids:
            lines.append(f"tracked_user_ids = {toml_list(tracked_ids)}")
        if summary_interval:
            lines.append(f"summary_interval_minutes = {summary_interval}")
        if control_group:
            lines.append(f"control_group = {toml_string(str(control_group))}")

        aliases = target.get("tracked_user_aliases", {}) or {}
        if aliases:
            lines.append("")
            lines.append("[targets.tracked_user_aliases]")
            for user_id, alias in aliases.items():
                lines.append(f"{user_id} = {toml_string(str(alias))}")

    lines.append("")
    lines.append(f"[control_groups.{control_key}]")
    if control_chat_id is not None:
        lines.append(f"control_chat_id = {control_chat_id}")
    lines.append(f"is_forum = {toml_bool(is_forum)}")
    lines.append(f"topic_routing_enabled = {toml_bool(topic_routing_enabled)}")

    # Build topic_target_map from the first target
    if topic_routing_enabled and topic_user_map and targets_raw:
        first_target = targets_raw[0] if isinstance(targets_raw[0], dict) else {}
        target_chat_id = first_target.get("target_chat_id")
        if target_chat_id is not None:
            lines.append("")
            lines.append(
                f"[control_groups.{control_key}.topic_target_map.{toml_string(str(target_chat_id))}]"
            )
            for user_id, topic_id in topic_user_map.items():
                lines.append(f"{user_id} = {topic_id}")

    lines.append("")
    lines.append("[storage]")
    db_path = storage.get("db_path", "data/tgwatch.sqlite3")
    media_dir = storage.get("media_dir", "data/media")
    lines.append(f"db_path = {toml_string(str(db_path))}")
    lines.append(f"media_dir = {toml_string(str(media_dir))}")

    lines.append("")
    lines.append("[reporting]")
    reports_dir = reporting.get("reports_dir", "reports")
    summary_interval_minutes = reporting.get("summary_interval_minutes", 120)
    timezone = reporting.get("timezone", "UTC")
    retention_days = reporting.get("retention_days", 30)
    lines.append(f"reports_dir = {toml_string(str(reports_dir))}")
    lines.append(f"summary_interval_minutes = {summary_interval_minutes}")
    lines.append(f"timezone = {toml_string(str(timezone))}")
    lines.append(f"retention_days = {retention_days}")

    lines.append("")
    lines.append("[display]")
    show_ids = display.get("show_ids", True)
    time_format = display.get("time_format", "%Y.%m.%d %H:%M:%S (%Z)")
    lines.append(f"show_ids = {toml_bool(bool(show_ids))}")
    lines.append(f"time_format = {toml_string(str(time_format))}")

    lines.append("")
    lines.append("[notifications]")
    bark_key = notifications.get("bark_key", "")
    lines.append(f"bark_key = {toml_string(str(bark_key))}")

    return "\n".join(lines).strip() + "\n"


def toml_string(value: str) -> str:
    value = value.replace("\\", "\\\\").replace('"', "\\\"")
    return f'"{value}"'


def toml_bool(value: bool) -> str:
    return "true" if value else "false"


def toml_list(values: list[Any]) -> str:
    return "[" + ", ".join(str(value) for value in values) + "]"
