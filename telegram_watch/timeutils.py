"""Time helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

_SINCE_RE = re.compile(r"^(?P<value>\d+)(?P<unit>[mh])$", re.IGNORECASE)


def utc_now() -> datetime:
    """Get timezone-aware now timestamp."""
    return datetime.now(tz=timezone.utc)


def parse_since_spec(spec: str, *, now: datetime | None = None) -> datetime:
    """Parse --since spec like '10m', '2h', or ISO date string."""
    if not spec:
        raise ValueError("empty --since value")
    spec = spec.strip()
    now_dt = now or utc_now()
    match = _SINCE_RE.match(spec)
    if match:
        value = int(match.group("value"))
        unit = match.group("unit").lower()
        delta = timedelta(minutes=value) if unit == "m" else timedelta(hours=value)
        return now_dt - delta
    try:
        dt = datetime.fromisoformat(spec)
    except ValueError as exc:
        raise ValueError(
            f"invalid --since '{spec}'. Examples: '10m', '2h', '2024-01-01T12:00:00+00:00'"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def humanize_timedelta(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes = total_seconds // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes}m"
    return f"{minutes}m"
