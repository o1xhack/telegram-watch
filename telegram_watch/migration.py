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

    backup_path = _next_backup_path(config_path)

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


def _next_backup_path(config_path: Path) -> Path:
    backup_path = config_path.with_name(CONFIG_BACKUP_NAME)
    if not backup_path.exists():
        return backup_path
    stem = backup_path.stem
    suffix = backup_path.suffix
    index = 1
    while True:
        candidate = backup_path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


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

    migrated_controls: dict[str, dict[str, Any]] = {}
    default_control_key = "default"
    if control_groups:
        for idx, (key, group_obj) in enumerate(control_groups.items(), start=1):
            group = group_obj if isinstance(group_obj, dict) else {}
            control_key = str(key) if str(key).strip() else f"control-{idx}"
            if idx == 1:
                default_control_key = control_key
            migrated_controls[control_key] = {
                "control_chat_id": group.get("control_chat_id"),
                "is_forum": bool(group.get("is_forum", False)),
                "topic_routing_enabled": bool(group.get("topic_routing_enabled", False)),
                "topic_target_map": _normalize_topic_target_map(group.get("topic_target_map")),
                "topic_user_map": _normalize_int_map(group.get("topic_user_map")),
            }
    elif control_raw:
        migrated_controls[default_control_key] = {
            "control_chat_id": control_raw.get("control_chat_id"),
            "is_forum": bool(control_raw.get("is_forum", False)),
            "topic_routing_enabled": bool(control_raw.get("topic_routing_enabled", False)),
            "topic_target_map": _normalize_topic_target_map(control_raw.get("topic_target_map")),
            "topic_user_map": _normalize_int_map(control_raw.get("topic_user_map")),
        }
    else:
        migrated_controls[default_control_key] = {
            "control_chat_id": None,
            "is_forum": False,
            "topic_routing_enabled": False,
            "topic_target_map": {},
            "topic_user_map": {},
        }

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
        control_group = target.get("control_group") or default_control_key

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

    target_ids_by_control: dict[str, list[Any]] = {}
    for target in targets_raw:
        if not isinstance(target, dict):
            continue
        target_chat_id = target.get("target_chat_id")
        if target_chat_id is None:
            continue
        control_key = str(target.get("control_group") or default_control_key)
        target_ids_by_control.setdefault(control_key, []).append(target_chat_id)

    for control_key, control in migrated_controls.items():
        lines.append("")
        lines.append(f"[control_groups.{control_key}]")
        control_chat_id = control.get("control_chat_id")
        if control_chat_id is not None:
            lines.append(f"control_chat_id = {control_chat_id}")
        is_forum = bool(control.get("is_forum", False))
        topic_routing_enabled = bool(control.get("topic_routing_enabled", False))
        lines.append(f"is_forum = {toml_bool(is_forum)}")
        lines.append(f"topic_routing_enabled = {toml_bool(topic_routing_enabled)}")

        if not topic_routing_enabled:
            continue
        topic_target_map = dict(control.get("topic_target_map", {}) or {})
        if not topic_target_map:
            topic_user_map = dict(control.get("topic_user_map", {}) or {})
            mapped_targets = target_ids_by_control.get(control_key) or []
            for target_chat_id in mapped_targets:
                topic_target_map[str(target_chat_id)] = dict(topic_user_map)
        for target_chat_id, user_map in topic_target_map.items():
            if not user_map:
                continue
            lines.append("")
            lines.append(
                f"[control_groups.{control_key}.topic_target_map.{toml_string(str(target_chat_id))}]"
            )
            for user_id, topic_id in user_map.items():
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


def _normalize_int_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for raw_key, raw_val in value.items():
        try:
            key = str(int(raw_key))
            val = int(raw_val)
        except (TypeError, ValueError):
            continue
        out[key] = val
    return out


def _normalize_topic_target_map(value: Any) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, dict[str, int]] = {}
    for target_chat_id, user_map in value.items():
        normalized = _normalize_int_map(user_map)
        if normalized:
            out[str(target_chat_id)] = normalized
    return out
