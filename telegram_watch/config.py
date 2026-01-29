"""Configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Mapping
from types import MappingProxyType
from zoneinfo import ZoneInfo

try:  # pragma: no cover - Python 3.11+ always hits first branch
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


class ConfigError(RuntimeError):
    """Raised when a config file is invalid."""


DEFAULT_TIME_FORMAT = "%Y.%m.%d %H:%M:%S (%Z)"


@dataclass(frozen=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    session_file: Path


@dataclass(frozen=True)
class SenderConfig:
    session_file: Path


@dataclass(frozen=True)
class TargetConfig:
    target_chat_id: int
    tracked_user_ids: tuple[int, ...]
    tracked_user_aliases: Mapping[int, str]


@dataclass(frozen=True)
class ControlConfig:
    control_chat_id: int
    is_forum: bool
    topic_routing_enabled: bool
    topic_user_map: Mapping[int, int]


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
    telegram: TelegramConfig
    sender: SenderConfig | None
    target: TargetConfig
    control: ControlConfig
    storage: StorageConfig
    reporting: ReportingConfig
    display: DisplayConfig
    notifications: NotificationConfig

    @property
    def tracked_users_set(self) -> set[int]:
        return set(self.target.tracked_user_ids)

    def describe_user(self, user_id: int) -> str:
        alias = self.target.tracked_user_aliases.get(user_id)
        if alias:
            return f"{alias} ({user_id})"
        return str(user_id)

    def format_user_label(self, user_id: int, include_id: bool | None = None) -> str:
        if include_id is None:
            include_id = self.display.show_ids
        alias = self.target.tracked_user_aliases.get(user_id)
        if alias:
            return f"{alias} ({user_id})" if include_id else alias
        return str(user_id)


def load_config(path: Path) -> Config:
    """Load and validate a config TOML file."""
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    base_dir = path.parent.resolve()

    telegram_cfg = _parse_telegram(data.get("telegram") or {}, base_dir)
    sender_cfg = _parse_sender(data.get("sender"), base_dir, telegram_cfg)
    target_cfg = _parse_target(data.get("target") or {})
    control_cfg = _parse_control(data.get("control") or {}, target_cfg.tracked_user_ids)
    storage_cfg = _parse_storage(data.get("storage") or {}, base_dir)
    reporting_cfg = _parse_reporting(data.get("reporting") or {}, base_dir)
    display_cfg = _parse_display(data.get("display") or {})
    notifications_cfg = _parse_notifications(data.get("notifications") or {})

    return Config(
        telegram=telegram_cfg,
        sender=sender_cfg,
        target=target_cfg,
        control=control_cfg,
        storage=storage_cfg,
        reporting=reporting_cfg,
        display=display_cfg,
        notifications=notifications_cfg,
    )


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


def _parse_target(raw: dict[str, Any]) -> TargetConfig:
    _require_fields(raw, "target", ("target_chat_id", "tracked_user_ids"))
    target_chat_id = _require_int(raw["target_chat_id"], "target.target_chat_id")
    tracked = raw.get("tracked_user_ids")
    if not isinstance(tracked, Iterable):
        raise ConfigError("target.tracked_user_ids must be a list of ints")
    try:
        ids_iter = tuple(int(user_id) for user_id in tracked)
    except (TypeError, ValueError) as exc:
        raise ConfigError("target.tracked_user_ids must be ints") from exc
    if not ids_iter:
        raise ConfigError("target.tracked_user_ids cannot be empty")
    aliases_raw = raw.get("tracked_user_aliases", {})
    if aliases_raw and not isinstance(aliases_raw, dict):
        raise ConfigError("target.tracked_user_aliases must be a table of id = \"Alias\" entries")
    aliases: dict[int, str] = {}
    for key, value in aliases_raw.items():
        try:
            user_id = int(key)
        except (TypeError, ValueError) as exc:
            raise ConfigError("tracked_user_aliases keys must be integers") from exc
        alias = str(value).strip()
        if not alias:
            raise ConfigError(f"Alias for user {user_id} cannot be empty")
        aliases[user_id] = alias
    unknown_aliases = set(aliases) - set(ids_iter)
    if unknown_aliases:
        formatted = ", ".join(str(uid) for uid in sorted(unknown_aliases))
        raise ConfigError(f"Alias configured for unknown tracked user(s): {formatted}")
    return TargetConfig(
        target_chat_id=target_chat_id,
        tracked_user_ids=ids_iter,
        tracked_user_aliases=MappingProxyType(aliases),
    )


def _parse_control(raw: dict[str, Any], tracked_user_ids: tuple[int, ...]) -> ControlConfig:
    _require_fields(raw, "control", ("control_chat_id",))
    control_chat_id = _require_int(raw["control_chat_id"], "control.control_chat_id")
    is_forum = _parse_bool(raw.get("is_forum", False))
    topic_routing_enabled = _parse_bool(raw.get("topic_routing_enabled", False))
    topic_map_raw = raw.get("topic_user_map", {})
    if topic_map_raw and not isinstance(topic_map_raw, dict):
        raise ConfigError("control.topic_user_map must be a table of user_id = topic_id entries")
    topic_map: dict[int, int] = {}
    for key, value in topic_map_raw.items():
        try:
            user_id = int(key)
        except (TypeError, ValueError) as exc:
            raise ConfigError("control.topic_user_map keys must be integers") from exc
        try:
            topic_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError("control.topic_user_map values must be integers") from exc
        if topic_id <= 0:
            raise ConfigError("control.topic_user_map values must be positive integers")
        topic_map[user_id] = topic_id
    unknown_users = set(topic_map) - set(tracked_user_ids)
    if unknown_users:
        formatted = ", ".join(str(uid) for uid in sorted(unknown_users))
        raise ConfigError(f"Topic routing configured for unknown tracked user(s): {formatted}")
    if topic_routing_enabled and not is_forum:
        raise ConfigError("control.topic_routing_enabled requires control.is_forum = true")
    if topic_routing_enabled and not topic_map:
        raise ConfigError("control.topic_routing_enabled requires control.topic_user_map to be set")
    return ControlConfig(
        control_chat_id=control_chat_id,
        is_forum=is_forum,
        topic_routing_enabled=topic_routing_enabled,
        topic_user_map=MappingProxyType(topic_map),
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
