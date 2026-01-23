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


@dataclass(frozen=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    session_file: Path


@dataclass(frozen=True)
class TargetConfig:
    target_chat_id: int
    tracked_user_ids: tuple[int, ...]
    tracked_user_aliases: Mapping[int, str]


@dataclass(frozen=True)
class ControlConfig:
    control_chat_id: int


@dataclass(frozen=True)
class StorageConfig:
    db_path: Path
    media_dir: Path


@dataclass(frozen=True)
class ReportingConfig:
    reports_dir: Path
    summary_interval_minutes: int
    timezone: ZoneInfo


@dataclass(frozen=True)
class Config:
    telegram: TelegramConfig
    target: TargetConfig
    control: ControlConfig
    storage: StorageConfig
    reporting: ReportingConfig

    @property
    def tracked_users_set(self) -> set[int]:
        return set(self.target.tracked_user_ids)

    def describe_user(self, user_id: int) -> str:
        alias = self.target.tracked_user_aliases.get(user_id)
        if alias:
            return f"{alias} ({user_id})"
        return str(user_id)


def load_config(path: Path) -> Config:
    """Load and validate a config TOML file."""
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    base_dir = path.parent.resolve()

    telegram_cfg = _parse_telegram(data.get("telegram") or {}, base_dir)
    target_cfg = _parse_target(data.get("target") or {})
    control_cfg = _parse_control(data.get("control") or {})
    storage_cfg = _parse_storage(data.get("storage") or {}, base_dir)
    reporting_cfg = _parse_reporting(data.get("reporting") or {}, base_dir)

    return Config(
        telegram=telegram_cfg,
        target=target_cfg,
        control=control_cfg,
        storage=storage_cfg,
        reporting=reporting_cfg,
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


def _parse_control(raw: dict[str, Any]) -> ControlConfig:
    _require_fields(raw, "control", ("control_chat_id",))
    control_chat_id = _require_int(raw["control_chat_id"], "control.control_chat_id")
    return ControlConfig(control_chat_id=control_chat_id)


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
    tz_name = raw.get("timezone", "UTC")
    try:
        timezone = ZoneInfo(tz_name)
    except Exception as exc:  # pragma: no cover - zoneinfo raises generic exceptions
        raise ConfigError(f"Invalid timezone '{tz_name}'") from exc
    return ReportingConfig(
        reports_dir=reports_dir,
        summary_interval_minutes=summary,
        timezone=timezone,
    )


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
