"""Configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from types import MappingProxyType
from zoneinfo import ZoneInfo

try:  # pragma: no cover - Python 3.11+ always hits first branch
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


class ConfigError(RuntimeError):
    """Raised when a config file is invalid."""


DEFAULT_TIME_FORMAT = "%Y.%m.%d %H:%M:%S (%Z)"
MAX_TARGET_GROUPS = 5
MAX_USERS_PER_TARGET = 5
MAX_CONTROL_GROUPS = 5
CONFIG_VERSION = 1.0


@dataclass(frozen=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    session_file: Path


@dataclass(frozen=True)
class SenderConfig:
    session_file: Path


@dataclass(frozen=True)
class TargetGroupConfig:
    name: str
    target_chat_id: int
    tracked_user_ids: tuple[int, ...]
    tracked_user_aliases: Mapping[int, str]
    summary_interval_minutes: int
    control_group: str | None


@dataclass(frozen=True)
class ControlGroupConfig:
    key: str
    control_chat_id: int
    is_forum: bool
    topic_routing_enabled: bool
    topic_target_map: Mapping[int, Mapping[int, int]]


@dataclass(frozen=True)
class StorageConfig:
    db_path: Path
    media_dir: Path


@dataclass(frozen=True)
class ReportingConfig:
    reports_dir: Path
    summary_interval_minutes: int
    timezone: ZoneInfo
    retention_days: int


@dataclass(frozen=True)
class DisplayConfig:
    show_ids: bool
    time_format: str


@dataclass(frozen=True)
class NotificationConfig:
    bark_key: str | None


@dataclass(frozen=True)
class Config:
    config_version: float
    telegram: TelegramConfig
    sender: SenderConfig | None
    targets: tuple[TargetGroupConfig, ...]
    control_groups: Mapping[str, ControlGroupConfig]
    target_by_chat_id: Mapping[int, TargetGroupConfig]
    target_by_name: Mapping[str, TargetGroupConfig]
    control_by_chat_id: Mapping[int, ControlGroupConfig]
    targets_by_control: Mapping[str, tuple[TargetGroupConfig, ...]]
    storage: StorageConfig
    reporting: ReportingConfig
    display: DisplayConfig
    notifications: NotificationConfig

    @property
    def tracked_users_set(self) -> set[int]:
        tracked: set[int] = set()
        for target in self.targets:
            tracked.update(target.tracked_user_ids)
        return tracked

    def target_for_chat(self, chat_id: int) -> TargetGroupConfig | None:
        return self.target_by_chat_id.get(chat_id)

    def target_for_name(self, name: str) -> TargetGroupConfig | None:
        return self.target_by_name.get(name)

    def control_for_chat(self, chat_id: int) -> ControlGroupConfig | None:
        return self.control_by_chat_id.get(chat_id)

    def targets_for_control(self, control_key: str) -> tuple[TargetGroupConfig, ...]:
        return self.targets_by_control.get(control_key, ())

    def describe_user(
        self,
        user_id: int,
        *,
        target: TargetGroupConfig | None = None,
        chat_id: int | None = None,
    ) -> str:
        alias = self._resolve_alias(user_id, target=target, chat_id=chat_id)
        if alias:
            return f"{alias} ({user_id})"
        return str(user_id)

    def format_user_label(
        self,
        user_id: int,
        include_id: bool | None = None,
        *,
        target: TargetGroupConfig | None = None,
        chat_id: int | None = None,
    ) -> str:
        if include_id is None:
            include_id = self.display.show_ids
        alias = self._resolve_alias(user_id, target=target, chat_id=chat_id)
        if alias:
            return f"{alias} ({user_id})" if include_id else alias
        return str(user_id)

    def _resolve_target(
        self,
        *,
        target: TargetGroupConfig | None,
        chat_id: int | None,
    ) -> TargetGroupConfig | None:
        if target is not None:
            return target
        if chat_id is not None:
            return self.target_by_chat_id.get(chat_id)
        return None

    def _resolve_alias(
        self,
        user_id: int,
        *,
        target: TargetGroupConfig | None,
        chat_id: int | None,
    ) -> str | None:
        resolved = self._resolve_target(target=target, chat_id=chat_id)
        if resolved is not None:
            return resolved.tracked_user_aliases.get(user_id)
        for group in self.targets:
            alias = group.tracked_user_aliases.get(user_id)
            if alias:
                return alias
        return None


def load_config(path: Path) -> Config:
    """Load and validate a config TOML file."""
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception as exc:
        raise ConfigError(
            "config file is invalid TOML. Rewrite config.toml using config.example.toml "
            "and see docs/configuration.md."
        ) from exc
    base_dir = path.parent.resolve()

    config_version = _parse_config_version(data)
    telegram_cfg = _parse_telegram(data.get("telegram") or {}, base_dir)
    sender_cfg = _parse_sender(data.get("sender"), base_dir, telegram_cfg)
    reporting_cfg = _parse_reporting(data.get("reporting") or {}, base_dir)
    targets = _parse_targets(data, reporting_cfg)
    control_groups = _parse_control_groups(data)
    targets = _assign_control_groups(targets, control_groups)
    _validate_control_topic_maps(targets, control_groups)
    storage_cfg = _parse_storage(data.get("storage") or {}, base_dir)
    display_cfg = _parse_display(data.get("display") or {})
    notifications_cfg = _parse_notifications(data.get("notifications") or {})

    target_by_chat: dict[int, TargetGroupConfig] = {}
    target_by_name: dict[str, TargetGroupConfig] = {}
    for target in targets:
        if target.target_chat_id in target_by_chat:
            raise ConfigError(f"Duplicate target_chat_id: {target.target_chat_id}")
        if target.name in target_by_name:
            raise ConfigError(f"Duplicate target name: {target.name}")
        target_by_chat[target.target_chat_id] = target
        target_by_name[target.name] = target

    control_by_chat: dict[int, ControlGroupConfig] = {}
    for control in control_groups.values():
        if control.control_chat_id in control_by_chat:
            raise ConfigError(f"Duplicate control_chat_id: {control.control_chat_id}")
        control_by_chat[control.control_chat_id] = control

    targets_by_control: dict[str, list[TargetGroupConfig]] = {}
    for target in targets:
        if not target.control_group:
            continue
        targets_by_control.setdefault(target.control_group, []).append(target)

    return Config(
        config_version=config_version,
        telegram=telegram_cfg,
        sender=sender_cfg,
        targets=tuple(targets),
        control_groups=MappingProxyType(dict(control_groups)),
        target_by_chat_id=MappingProxyType(target_by_chat),
        target_by_name=MappingProxyType(target_by_name),
        control_by_chat_id=MappingProxyType(control_by_chat),
        targets_by_control=MappingProxyType(
            {key: tuple(value) for key, value in targets_by_control.items()}
        ),
        storage=storage_cfg,
        reporting=reporting_cfg,
        display=display_cfg,
        notifications=notifications_cfg,
    )


def _parse_config_version(data: dict[str, Any]) -> float:
    raw = data.get("config_version")
    if raw is None:
        raise ConfigError(
            "config_version is missing. This config is outdated; "
            "rewrite config.toml using config.example.toml and see docs/configuration.md."
        )
    try:
        version = float(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError("config_version must be 1.0") from exc
    if version != CONFIG_VERSION:
        raise ConfigError(
            f"config_version {version} is not supported. "
            "Rewrite config.toml using config.example.toml and see docs/configuration.md."
        )
    return version


def _parse_telegram(raw: dict[str, Any], base_dir: Path) -> TelegramConfig:
    _require_fields(raw, "telegram", ("api_id", "api_hash"))
    api_id = _require_int(raw["api_id"], "telegram.api_id")
    api_hash = str(raw["api_hash"]).strip()
    if not api_hash or len(api_hash) < 10:
        raise ConfigError("telegram.api_hash looks invalid")
    session_file_raw = raw.get("session_file", "data/tgwatch.session")
    session_file = _resolve_path(session_file_raw, base_dir)
    return TelegramConfig(api_id=api_id, api_hash=api_hash, session_file=session_file)


def _parse_sender(
    raw: dict[str, Any] | None,
    base_dir: Path,
    telegram_cfg: TelegramConfig,
) -> SenderConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("sender must be a table")
    session_file_raw = raw.get("session_file")
    if not session_file_raw:
        raise ConfigError("sender.session_file is required when [sender] is set")
    session_file = _resolve_path(session_file_raw, base_dir)
    if session_file == telegram_cfg.session_file:
        raise ConfigError("sender.session_file must differ from telegram.session_file")
    return SenderConfig(session_file=session_file)


def _parse_targets(
    data: dict[str, Any],
    reporting_cfg: ReportingConfig,
) -> list[TargetGroupConfig]:
    if "targets" in data and "target" in data:
        raise ConfigError("Use either [target] or [[targets]], not both")
    if "targets" in data:
        raw_targets = data.get("targets")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise ConfigError("targets must be a non-empty array of tables")
        targets: list[TargetGroupConfig] = []
        for idx, raw in enumerate(raw_targets, start=1):
            if not isinstance(raw, dict):
                raise ConfigError("Each entry in targets must be a table")
            label = f"targets[{idx}]"
            targets.append(
                _parse_target_group(
                    raw,
                    reporting_cfg,
                    label,
                    require_name=False,
                    default_name=f"group-{idx}",
                )
            )
        if len(targets) > MAX_TARGET_GROUPS:
            raise ConfigError(f"targets cannot exceed {MAX_TARGET_GROUPS} groups")
        return targets
    raw_target = data.get("target")
    if raw_target is None:
        raise ConfigError("missing [target] or [[targets]] section")
    if not isinstance(raw_target, dict):
        raise ConfigError("target must be a table")
    targets = [
        _parse_target_group(
            raw_target,
            reporting_cfg,
            "target",
            require_name=False,
            default_name="default",
        )
    ]
    return targets


def _parse_target_group(
    raw: dict[str, Any],
    reporting_cfg: ReportingConfig,
    label: str,
    *,
    require_name: bool,
    default_name: str | None = None,
) -> TargetGroupConfig:
    name = str(raw.get("name") or default_name or "").strip()
    if require_name and not name:
        raise ConfigError(f"{label}.name is required")
    _require_fields(raw, label, ("target_chat_id", "tracked_user_ids"))
    target_chat_id = _require_int(raw["target_chat_id"], f"{label}.target_chat_id")
    tracked = raw.get("tracked_user_ids")
    if not isinstance(tracked, Iterable):
        raise ConfigError(f"{label}.tracked_user_ids must be a list of ints")
    try:
        ids_iter = tuple(int(user_id) for user_id in tracked)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label}.tracked_user_ids must be ints") from exc
    if not ids_iter:
        raise ConfigError(f"{label}.tracked_user_ids cannot be empty")
    if len(ids_iter) > MAX_USERS_PER_TARGET:
        raise ConfigError(f"{label}.tracked_user_ids cannot exceed {MAX_USERS_PER_TARGET} users")
    aliases_raw = raw.get("tracked_user_aliases", {})
    if aliases_raw and not isinstance(aliases_raw, dict):
        raise ConfigError(f"{label}.tracked_user_aliases must be a table of id = \"Alias\" entries")
    aliases: dict[int, str] = {}
    for key, value in aliases_raw.items():
        try:
            user_id = int(key)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{label}.tracked_user_aliases keys must be integers") from exc
        alias = str(value).strip()
        if not alias:
            raise ConfigError(f"Alias for user {user_id} cannot be empty")
        aliases[user_id] = alias
    unknown_aliases = set(aliases) - set(ids_iter)
    if unknown_aliases:
        formatted = ", ".join(str(uid) for uid in sorted(unknown_aliases))
        raise ConfigError(f"Alias configured for unknown tracked user(s): {formatted}")
    interval_raw = raw.get("summary_interval_minutes", raw.get("interval_minutes"))
    if interval_raw is None:
        interval = reporting_cfg.summary_interval_minutes
    else:
        interval = _require_int(interval_raw, f"{label}.summary_interval_minutes")
    if interval <= 0:
        raise ConfigError(f"{label}.summary_interval_minutes must be > 0")
    control_group = raw.get("control_group")
    if control_group is not None:
        control_group = str(control_group).strip()
        if not control_group:
            control_group = None
    return TargetGroupConfig(
        name=name or "default",
        target_chat_id=target_chat_id,
        tracked_user_ids=ids_iter,
        tracked_user_aliases=MappingProxyType(aliases),
        summary_interval_minutes=interval,
        control_group=control_group,
    )


def _parse_control_groups(data: dict[str, Any]) -> dict[str, ControlGroupConfig]:
    if "control_groups" in data and "control" in data:
        raise ConfigError("Use either [control] or [control_groups], not both")
    if "control_groups" in data:
        raw_groups = data.get("control_groups")
        if not isinstance(raw_groups, dict) or not raw_groups:
            raise ConfigError("control_groups must be a non-empty table")
        parsed: dict[str, ControlGroupConfig] = {}
        for key, raw in raw_groups.items():
            name = str(key).strip()
            if not name:
                raise ConfigError("control_groups keys must be non-empty strings")
            if not isinstance(raw, dict):
                raise ConfigError(f"control_groups.{name} must be a table")
            parsed[name] = _parse_control_group(raw, key=name, label=f"control_groups.{name}")
        if len(parsed) > MAX_CONTROL_GROUPS:
            raise ConfigError(f"control_groups cannot exceed {MAX_CONTROL_GROUPS}")
        return parsed
    raw_control = data.get("control")
    if raw_control is None:
        raise ConfigError("missing [control] or [control_groups] section")
    if not isinstance(raw_control, dict):
        raise ConfigError("control must be a table")
    return {"default": _parse_control_group(raw_control, key="default", label="control")}


def _parse_control_group(
    raw: dict[str, Any],
    *,
    key: str,
    label: str,
) -> ControlGroupConfig:
    _require_fields(raw, label, ("control_chat_id",))
    control_chat_id = _require_int(raw["control_chat_id"], f"{label}.control_chat_id")
    is_forum = _parse_bool(raw.get("is_forum", False))
    topic_routing_enabled = _parse_bool(raw.get("topic_routing_enabled", False))
    if "topic_user_map" in raw:
        raise ConfigError(
            f"{label}.topic_user_map is no longer supported. "
            "Rewrite config.toml using config.example.toml."
        )
    topic_map_raw = raw.get("topic_target_map", {})
    if topic_map_raw and not isinstance(topic_map_raw, dict):
        raise ConfigError(f"{label}.topic_target_map must be a table of target_chat_id tables")
    topic_target_map: dict[int, Mapping[int, int]] = {}
    for target_key, user_map_raw in (topic_map_raw or {}).items():
        try:
            target_chat_id = int(target_key)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{label}.topic_target_map keys must be integers") from exc
        if not isinstance(user_map_raw, dict):
            raise ConfigError(f"{label}.topic_target_map.{target_chat_id} must be a table")
        user_map: dict[int, int] = {}
        for user_key, value in user_map_raw.items():
            try:
                user_id = int(user_key)
            except (TypeError, ValueError) as exc:
                raise ConfigError(
                    f"{label}.topic_target_map.{target_chat_id} keys must be integers"
                ) from exc
            try:
                topic_id = int(value)
            except (TypeError, ValueError) as exc:
                raise ConfigError(
                    f"{label}.topic_target_map.{target_chat_id} values must be integers"
                ) from exc
            if topic_id <= 0:
                raise ConfigError(
                    f"{label}.topic_target_map.{target_chat_id} values must be positive integers"
                )
            user_map[user_id] = topic_id
        topic_target_map[target_chat_id] = MappingProxyType(user_map)
    if topic_routing_enabled and not is_forum:
        raise ConfigError(f"{label}.topic_routing_enabled requires {label}.is_forum = true")
    if topic_routing_enabled and not topic_target_map:
        raise ConfigError(f"{label}.topic_routing_enabled requires {label}.topic_target_map to be set")
    return ControlGroupConfig(
        key=key,
        control_chat_id=control_chat_id,
        is_forum=is_forum,
        topic_routing_enabled=topic_routing_enabled,
        topic_target_map=MappingProxyType(topic_target_map),
    )


def _assign_control_groups(
    targets: list[TargetGroupConfig],
    control_groups: Mapping[str, ControlGroupConfig],
) -> list[TargetGroupConfig]:
    if not control_groups:
        raise ConfigError("At least one control group must be configured")
    control_keys = list(control_groups.keys())
    default_control = control_keys[0] if len(control_keys) == 1 else None
    updated: list[TargetGroupConfig] = []
    for target in targets:
        control_key = target.control_group or default_control
        if control_key is None:
            raise ConfigError(
                f"Target group '{target.name}' is missing control_group mapping; "
                "define target.control_group or reduce to a single control group."
            )
        if control_key not in control_groups:
            raise ConfigError(
                f"Target group '{target.name}' references unknown control group '{control_key}'."
            )
        updated.append(
            TargetGroupConfig(
                name=target.name,
                target_chat_id=target.target_chat_id,
                tracked_user_ids=target.tracked_user_ids,
                tracked_user_aliases=target.tracked_user_aliases,
                summary_interval_minutes=target.summary_interval_minutes,
                control_group=control_key,
            )
        )
    return updated


def _validate_control_topic_maps(
    targets: Iterable[TargetGroupConfig],
    control_groups: Mapping[str, ControlGroupConfig],
) -> None:
    allowed: dict[str, dict[int, set[int]]] = {key: {} for key in control_groups}
    for target in targets:
        if target.control_group:
            allowed.setdefault(target.control_group, {}).setdefault(
                target.target_chat_id, set()
            ).update(target.tracked_user_ids)
    for key, control in control_groups.items():
        if not control.topic_target_map:
            continue
        for target_chat_id, user_map in control.topic_target_map.items():
            allowed_users = allowed.get(key, {}).get(target_chat_id, set())
            if not allowed_users:
                raise ConfigError(
                    f"Topic routing configured for unknown target_chat_id {target_chat_id} "
                    f"in control group '{key}'."
                )
            unknown = set(user_map.keys()) - allowed_users
            if unknown:
                formatted = ", ".join(str(uid) for uid in sorted(unknown))
                raise ConfigError(
                    f"Topic routing configured for unknown tracked user(s) in control group "
                    f"'{key}' for target {target_chat_id}: {formatted}"
                )


def _parse_storage(raw: dict[str, Any], base_dir: Path) -> StorageConfig:
    _require_fields(raw, "storage", ("db_path", "media_dir"))
    db_path = _resolve_path(raw["db_path"], base_dir)
    media_dir = _resolve_path(raw["media_dir"], base_dir)
    return StorageConfig(db_path=db_path, media_dir=media_dir)


def _parse_reporting(raw: dict[str, Any], base_dir: Path) -> ReportingConfig:
    reports_dir = _resolve_path(raw.get("reports_dir", "reports"), base_dir)
    summary = raw.get("summary_interval_minutes", 120)
    summary = _require_int(summary, "reporting.summary_interval_minutes")
    if summary <= 0:
        raise ConfigError("reporting.summary_interval_minutes must be > 0")
    retention = raw.get("retention_days", 30)
    retention = _require_int(retention, "reporting.retention_days")
    if retention <= 0:
        raise ConfigError("reporting.retention_days must be > 0")
    tz_name = raw.get("timezone", "UTC")
    try:
        timezone = ZoneInfo(tz_name)
    except Exception as exc:  # pragma: no cover - zoneinfo raises generic exceptions
        raise ConfigError(f"Invalid timezone '{tz_name}'") from exc
    return ReportingConfig(
        reports_dir=reports_dir,
        summary_interval_minutes=summary,
        timezone=timezone,
        retention_days=retention,
    )


def _parse_display(raw: dict[str, Any]) -> DisplayConfig:
    show_ids = _parse_bool(raw.get("show_ids", True))
    fmt = str(raw.get("time_format", DEFAULT_TIME_FORMAT)).strip()
    if not fmt:
        fmt = DEFAULT_TIME_FORMAT
    return DisplayConfig(show_ids=show_ids, time_format=fmt)


def _parse_notifications(raw: dict[str, Any]) -> NotificationConfig:
    bark_key = raw.get("bark_key")
    if bark_key is not None:
        bark_key = str(bark_key).strip()
        if not bark_key:
            bark_key = None
    return NotificationConfig(bark_key=bark_key)


def _parse_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _require_fields(raw: dict[str, Any], section: str, fields: Iterable[str]) -> None:
    missing = [field for field in fields if field not in raw]
    if missing:
        raise ConfigError(f"missing field(s) in [{section}]: {', '.join(missing)}")


def _require_int(value: Any, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label} must be an integer") from exc
    return parsed


def _resolve_path(raw_path: Any, base_dir: Path) -> Path:
    if isinstance(raw_path, Path):
        return raw_path
    if not isinstance(raw_path, str):
        raise ConfigError(f"expected string path, got {raw_path!r}")
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return candidate
