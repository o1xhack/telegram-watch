"""Async runners for `once` and `run` commands."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence, TypeVar

from telethon import TelegramClient, events, errors, functions, utils
from telethon.sessions import SQLiteSession
from telethon.tl.custom import message as custom_message

from .config import (
    Config,
    ControlGroupConfig,
    DEFAULT_TIME_FORMAT,
    TargetGroupConfig,
)
from .full_archive_storage import (
    ArchiveMedia,
    ArchiveMessage,
    ArchiveSender,
    ArchiveSenderCandidate,
    archive_message_exists,
    connect as archive_connect,
    ensure_archive_sender_schema,
    find_shard_for_message,
    inspect_archive_status,
    list_archive_sender_candidates,
    only_archive_sender_schema_missing,
    persist_archive_message,
    persist_archive_message_with_result,
    persist_archive_sender_to_shards,
    record_tracked_db_link,
    record_shard_write,
    select_shard,
)
from .links import build_message_link
from .notifications import send_bark_notification
from .rate_limiter import CircuitBrokenError, RateProtectionSuite
from .reporting import generate_report
from .storage import (
    DbMessage,
    StoredMedia,
    StoredMessage,
    clear_reply_snapshots,
    db_session,
    fetch_reply_snapshot_candidates,
    fetch_messages_between,
    fetch_recent_messages,
    fetch_summary_counts,
    persist_message,
)
from .timeutils import parse_since_spec, utc_now

logger = logging.getLogger(__name__)

_SENDER_FALLBACK_ALERT = (
    "\u26a0\ufe0f Sender account is unavailable after reconnect retry; "
    "using the primary account for outgoing control messages. "
    "Check the sender session and restart the daemon if this persists."
)

ARCHIVE_BACKFILL_WAIT_THRESHOLD = 1_000
ARCHIVE_BACKFILL_WAIT_TIME_SECONDS = 1.0
ARCHIVE_RELINK_SHUTDOWN_TIMEOUT_SECONDS = 5.0
ARCHIVE_SENDER_LOOKUP_RETRY_SECONDS = 60.0
RUNNER_HEALTH_INTERVAL_SECONDS = 15.0


class _AsyncSqliteGate:
    """Serialize daemon SQLite work and keep blocking calls off the event loop."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.pending = 0
        self.pending_since: datetime | None = None
        self.last_success_at = utc_now()

    async def run(
        self,
        func: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self.pending += 1
        if self.pending_since is None:
            self.pending_since = utc_now()
        try:
            async with self._lock:
                result = await asyncio.to_thread(func, *args, **kwargs)
                self.last_success_at = utc_now()
                return result
        finally:
            self.pending -= 1
            if self.pending == 0:
                self.pending_since = None


class _RunnerHealthLoop:
    """Write a liveness heartbeat that the GUI can validate independently of PID."""

    def __init__(
        self,
        path: Path,
        sqlite_gate: _AsyncSqliteGate,
        *,
        full_archive_configured: bool = False,
        full_archive_fingerprint: str | None = None,
        interval_seconds: float = RUNNER_HEALTH_INTERVAL_SECONDS,
    ) -> None:
        self.path = path
        self.sqlite_gate = sqlite_gate
        self.interval_seconds = interval_seconds
        self.started_at = utc_now()
        self.full_archive_configured = full_archive_configured
        self.full_archive_fingerprint = full_archive_fingerprint
        self.full_archive_runtime_enabled = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._write()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            self._write()

    def _write(self) -> None:
        payload = {
            "pid": os.getpid(),
            "started_at": self.started_at.isoformat(),
            "last_tick": utc_now().isoformat(),
            "sqlite_pending": self.sqlite_gate.pending,
            "sqlite_pending_since": (
                self.sqlite_gate.pending_since.isoformat()
                if self.sqlite_gate.pending_since is not None
                else None
            ),
            "sqlite_last_success": self.sqlite_gate.last_success_at.isoformat(),
            "full_archive": {
                "configured": self.full_archive_configured,
                "runtime_enabled": self.full_archive_runtime_enabled,
                "status": (
                    "active"
                    if self.full_archive_runtime_enabled
                    else "degraded" if self.full_archive_configured else "disabled"
                ),
                "config_fingerprint": self.full_archive_fingerprint,
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.path)


@dataclass
class ReplyCleanupStats:
    scanned: int = 0
    skipped_non_forum: int = 0
    kept_explicit_reply: int = 0
    missing_messages: int = 0
    to_clear: int = 0
    cleared_messages: int = 0
    cleared_media: int = 0
    backup_path: Path | None = None


@dataclass
class ArchiveBackfillStats:
    scanned: int = 0
    matched: int = 0
    skipped_scope: int = 0
    skipped_invalid: int = 0
    archived: int = 0
    linked: int = 0
    updated: int = 0
    dry_run: bool = True


@dataclass
class ArchiveSenderBackfillStats:
    candidates: int = 0
    schema_updates: int = 0
    reused: int = 0
    cached: int = 0
    fetched: int = 0
    unresolved: int = 0
    written_senders: int = 0
    shard_writes: int = 0
    dry_run: bool = True


@dataclass(frozen=True)
class _ArchiveSenderIdentity:
    username: str | None
    display_name: str | None


@dataclass(frozen=True)
class ArchivePersistResult:
    payload_mode: str
    created: bool
    linked: bool


@dataclass(frozen=True)
class ForumTopicInfo:
    topic_id: int
    title: str
    top_message: int | None
    unread_count: int
    closed: bool
    hidden: bool
    pinned: bool


def _build_get_forum_topics_request(
    peer: object,
    *,
    limit: int,
    query: str | None,
) -> Any:
    channels_api = getattr(functions, "channels", None)
    channels_request = getattr(channels_api, "GetForumTopicsRequest", None)
    if channels_request is not None:
        try:
            return channels_request(
                channel=peer,
                offset_date=None,
                offset_id=0,
                offset_topic=0,
                limit=limit,
                q=query,
            )
        except TypeError:
            # Telethon has exposed this raw API under both channels.* and
            # messages.* across versions. Fall through to the older signature.
            pass

    messages_api = getattr(functions, "messages", None)
    messages_request = getattr(messages_api, "GetForumTopicsRequest")
    return messages_request(
        peer=peer,
        offset_date=None,
        offset_id=0,
        offset_topic=0,
        limit=limit,
        q=query,
    )


def _role_label(role: str) -> str:
    if role == "primary":
        return "primary account (A)"
    if role == "sender":
        return "sender account (B)"
    return "account"


def _phone_prompt(role: str) -> str:
    label = _role_label(role)
    if os.environ.get("TGWATCH_NON_INTERACTIVE"):
        raise RuntimeError(
            f"Session expired or missing for {label}. "
            "Cannot prompt for phone in non-interactive mode. "
            "Re-generate the session file locally and update the GitHub Secret."
        )
    print(f"Next: log in {label}.")
    return input(f"{label} phone (or bot token): ")


class _WalSqliteSession(SQLiteSession):
    """SQLiteSession with WAL mode and busy_timeout for cloud-sync resilience."""

    def _cursor(self):
        c = super()._cursor()
        if not getattr(self, "_wal_set", False):
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA busy_timeout = 5000")
            self._wal_set = True
        return c

    def get_cached_sender_identity(
        self,
        sender_id: int,
    ) -> _ArchiveSenderIdentity | None:
        row = self._execute(
            "SELECT username, name FROM entities WHERE id = ?",
            sender_id,
        )
        if row is None:
            return None
        username = _normalize_sender_username(row[0])
        display_name = _normalize_sender_text(row[1])
        if not username and not display_name:
            return None
        return _ArchiveSenderIdentity(
            username=username,
            display_name=display_name,
        )


def _resolve_once_targets(config: Config, selector: str | None) -> tuple[TargetGroupConfig, ...]:
    if not selector:
        return tuple(config.targets)
    selector = selector.strip()
    if not selector:
        return tuple(config.targets)
    if selector in config.target_by_name:
        return (config.target_by_name[selector],)
    try:
        target_chat_id = int(selector)
    except (TypeError, ValueError):
        target_chat_id = None
    if target_chat_id is not None and target_chat_id in config.target_by_chat_id:
        return (config.target_by_chat_id[target_chat_id],)
    raise ValueError(f"Unknown target selector: {selector}")


async def _start_client(client: TelegramClient, role: str) -> None:
    await client.start(phone=lambda: _phone_prompt(role))


async def run_once(
    config: Config,
    since: datetime,
    push: bool = False,
    since_label: str | None = None,
    target_selector: str | None = None,
) -> list[Path]:
    """Fetch messages for a window, store them, and return report paths."""
    targets = _resolve_once_targets(config, target_selector)
    client = _build_client(config)
    await _start_client(client, "primary")
    try:
        captures: list[tuple[StoredMessage, list[StoredMedia]]] = []
        for target in targets:
            captures.extend(await _collect_window(client, config, target, since))
    finally:
        await client.disconnect()
    until = utc_now()
    report_now = utc_now()
    once_report_dir = (
        config.reporting.reports_dir
        / report_now.strftime("%Y-%m-%d")
        / report_now.strftime("%H%M")
    )
    stored_by_target: dict[str, list[DbMessage]] = {}
    with db_session(config.storage.db_path) as conn:
        for message, media in captures:
            persist_message(conn, message, media)
        for target in targets:
            stored_by_target[target.name] = fetch_messages_between(
                conn,
                target.tracked_user_ids,
                since,
                until,
                chat_ids=[target.target_chat_id],
            )
    report_paths: list[Path] = []
    # Keep per-target filenames when config contains multiple targets,
    # even for `once --target ...`, to avoid same-minute overwrites.
    multi_target_config = len(config.targets) > 1
    for target in targets:
        report_name = "index.html"
        if multi_target_config:
            report_name = f"index_{target.target_chat_id}.html"
        report_path = generate_report(
            stored_by_target.get(target.name, []),
            config,
            since,
            until,
            target=target,
            report_dir=once_report_dir,
            report_name=report_name,
        )
        report_paths.append(report_path)
    if push:
        sender_client = await _start_sender_client(config)
        fallback_client: TelegramClient | None = None
        if sender_client is None:
            send_client = _build_client(config)
            await _start_client(send_client, "primary")
        else:
            send_client = sender_client
            fallback_client = _build_client(config)
            await _start_client(fallback_client, "primary")
        try:
            await _push_once_reports(
                send_client,
                config,
                targets,
                stored_by_target,
                since,
                until,
                report_paths,
                bark_context=(f"(since {since_label})" if since_label else None),
                fallback_client=fallback_client,
            )
        finally:
            await send_client.disconnect()
            if fallback_client is not None:
                await fallback_client.disconnect()
    return report_paths


async def run_reply_cleanup(
    config: Config,
    *,
    apply: bool = False,
    backup: bool = True,
) -> ReplyCleanupStats:
    stats = ReplyCleanupStats()
    target_chat_ids = tuple(target.target_chat_id for target in config.targets)
    with db_session(config.storage.db_path) as conn:
        candidates = fetch_reply_snapshot_candidates(conn, chat_ids=target_chat_ids)
    if not candidates:
        return stats

    candidates_by_chat: dict[int, list[int]] = {}
    for chat_id, message_id in candidates:
        candidates_by_chat.setdefault(chat_id, []).append(message_id)

    client = _build_client(config)
    await _start_client(client, "primary")
    to_clear: list[tuple[int, int]] = []
    try:
        for target in config.targets:
            chat_id = target.target_chat_id
            message_ids = candidates_by_chat.get(chat_id, [])
            if not message_ids:
                continue
            chat_entity = await _with_floodwait(client.get_entity, chat_id)
            if not bool(getattr(chat_entity, "forum", False)):
                stats.scanned += len(message_ids)
                stats.skipped_non_forum += len(message_ids)
                continue
            for start in range(0, len(message_ids), 100):
                batch = message_ids[start : start + 100]
                msgs = await _with_floodwait(client.get_messages, chat_id, ids=batch)
                msg_map = {int(msg.id): msg for msg in msgs if msg is not None}
                for message_id in batch:
                    stats.scanned += 1
                    live_message = msg_map.get(message_id)
                    if live_message is None:
                        stats.missing_messages += 1
                        continue
                    if _is_explicit_reply(live_message):
                        stats.kept_explicit_reply += 1
                        continue
                    to_clear.append((chat_id, message_id))
    finally:
        await client.disconnect()

    stats.to_clear = len(to_clear)
    if not apply or not to_clear:
        return stats
    if backup:
        timestamp = utc_now().strftime("%Y%m%d%H%M%S")
        backup_path = config.storage.db_path.with_suffix(
            f"{config.storage.db_path.suffix}.bak.{timestamp}"
        )
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config.storage.db_path, backup_path)
        stats.backup_path = backup_path
    with db_session(config.storage.db_path) as conn:
        cleared_messages, cleared_media = clear_reply_snapshots(conn, to_clear)
    stats.cleared_messages = cleared_messages
    stats.cleared_media = cleared_media
    return stats


async def run_archive_backfill(
    config: Config,
    *,
    limit: int | None = None,
    apply: bool = False,
) -> ArchiveBackfillStats:
    archive = config.full_archive
    if not archive.enabled or archive.source_chat_id is None:
        raise ValueError("full_archive must be enabled before running archive-backfill")
    effective_limit = limit if limit is not None else archive.backfill_limit_messages
    if effective_limit < 0:
        raise ValueError("archive-backfill limit must be >= 0")

    stats = ArchiveBackfillStats(dry_run=not apply)
    if effective_limit == 0:
        return stats

    client = _build_client(config)
    await _start_client(client, "primary")
    try:
        remaining = effective_limit
        offset_id = 0
        wait_time = (
            ARCHIVE_BACKFILL_WAIT_TIME_SECONDS
            if effective_limit > ARCHIVE_BACKFILL_WAIT_THRESHOLD
            else None
        )
        while remaining > 0:
            try:
                async for msg in client.iter_messages(
                    archive.source_chat_id,
                    limit=remaining,
                    offset_id=offset_id,
                    wait_time=wait_time,
                ):
                    msg_id = _coerce_optional_int(getattr(msg, "id", None))
                    if msg_id is not None:
                        offset_id = msg_id
                    remaining -= 1
                    stats.scanned += 1
                    archive_message = _archive_message_from_telegram(
                        msg,
                        chat_id_default=archive.source_chat_id,
                    )
                    if archive_message is None:
                        stats.skipped_invalid += 1
                        if remaining <= 0:
                            break
                        continue
                    if not _archive_message_matches_scope(config, archive_message):
                        stats.skipped_scope += 1
                        if remaining <= 0:
                            break
                        continue
                    stats.matched += 1
                    if not apply:
                        if remaining <= 0:
                            break
                        continue
                    persist_result = _persist_archive_message_to_storage(
                        config,
                        archive_message,
                        tracked_db_path=config.storage.db_path,
                    )
                    if persist_result.linked:
                        stats.linked += 1
                    elif not persist_result.created:
                        stats.updated += 1
                    else:
                        stats.archived += 1
                    if remaining <= 0:
                        break
                break
            except errors.FloodWaitError as exc:
                if remaining <= 0:
                    break
                wait_time = ARCHIVE_BACKFILL_WAIT_TIME_SECONDS
                wait_for = exc.seconds + 1
                logger.warning(
                    "FloodWait during archive backfill: sleeping for %ss",
                    wait_for,
                )
                await asyncio.sleep(wait_for)
    finally:
        await client.disconnect()
    return stats


async def run_archive_senders_backfill(
    config: Config,
    *,
    limit: int | None = None,
    apply: bool = False,
) -> ArchiveSenderBackfillStats:
    """Resolve missing full-archive sender snapshots without exposing IDs."""
    archive = config.full_archive
    if not archive.enabled or archive.source_chat_id is None:
        raise ValueError(
            "full_archive must be enabled before running archive-senders-backfill"
        )
    if limit is not None and limit < 0:
        raise ValueError("archive-senders-backfill limit must be >= 0")
    if limit == 0:
        return ArchiveSenderBackfillStats(dry_run=not apply)

    schema_updates = 0
    if apply:
        schema_updates = await asyncio.to_thread(
            ensure_archive_sender_schema,
            archive.root_dir,
        )
    candidates = list_archive_sender_candidates(archive.root_dir, limit=limit)
    stats = ArchiveSenderBackfillStats(
        candidates=len(candidates),
        schema_updates=schema_updates,
        dry_run=not apply,
    )
    if not apply or not candidates:
        return stats

    unresolved_candidates: list[ArchiveSenderCandidate] = []
    for candidate in candidates:
        if candidate.existing_sender is None:
            unresolved_candidates.append(candidate)
            continue
        stats.reused += 1
        stats.shard_writes += await asyncio.to_thread(
            persist_archive_sender_to_shards,
            candidate.existing_sender,
            candidate.shard_paths,
        )
        stats.written_senders += 1
    if not unresolved_candidates:
        return stats

    client = _build_client(config)
    await _start_client(client, "primary")
    try:
        cached_lookup = getattr(client.session, "get_cached_sender_identity", None)
        for candidate in unresolved_candidates:
            identity = (
                cached_lookup(candidate.sender_id)
                if callable(cached_lookup)
                else None
            )
            if identity is not None:
                stats.cached += 1
            else:
                identity = await _fetch_archive_sender_identity(client, candidate)
                if identity is not None:
                    stats.fetched += 1
            if identity is None:
                stats.unresolved += 1
                continue
            snapshot = _archive_sender_from_identity(candidate, identity)

            stats.shard_writes += await asyncio.to_thread(
                persist_archive_sender_to_shards,
                snapshot,
                candidate.shard_paths,
            )
            stats.written_senders += 1
    finally:
        await client.disconnect()
    return stats


async def _fetch_archive_sender_identity(
    client: TelegramClient,
    candidate: ArchiveSenderCandidate,
) -> _ArchiveSenderIdentity | None:
    try:
        message = await _with_floodwait(
            client.get_messages,
            candidate.chat_id,
            ids=candidate.message_id,
        )
        if isinstance(message, (list, tuple)):
            message = message[0] if message else None
        if message is None:
            return None
        get_sender = getattr(message, "get_sender", None)
        if not callable(get_sender):
            return _sender_identity_from_entity(getattr(message, "sender", None))
        entity = await _with_floodwait(get_sender)
        return _sender_identity_from_entity(entity)
    except (errors.RPCError, ValueError, TypeError, AttributeError):
        return None


def _archive_sender_from_identity(
    candidate: ArchiveSenderCandidate,
    identity: _ArchiveSenderIdentity,
) -> ArchiveSender:
    return ArchiveSender(
        sender_id=candidate.sender_id,
        username=identity.username,
        display_name=identity.display_name,
        first_seen_at=candidate.first_seen_at,
        last_seen_at=candidate.last_seen_at,
    )


async def run_list_topics(
    config: Config,
    *,
    chat: int | str,
    limit: int = 100,
    query: str | None = None,
) -> list[ForumTopicInfo]:
    if limit <= 0:
        raise ValueError("list-topics limit must be > 0")
    client = _build_client(config)
    await _start_client(client, "primary")
    try:
        try:
            peer = await _with_floodwait(client.get_input_entity, chat)
            request = _build_get_forum_topics_request(
                peer,
                limit=limit,
                query=query,
            )
            result = await _with_floodwait(client.__call__, request)
        except (errors.RPCError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"Cannot list topics for {chat}: {exc}") from exc
    finally:
        await client.disconnect()
    topics: list[ForumTopicInfo] = []
    for topic in getattr(result, "topics", []):
        topic_id = getattr(topic, "id", None)
        title = getattr(topic, "title", None)
        if topic_id is None or title is None:
            continue
        topics.append(
            ForumTopicInfo(
                topic_id=int(topic_id),
                title=str(title),
                top_message=(
                    int(getattr(topic, "top_message"))
                    if getattr(topic, "top_message", None) is not None
                    else None
                ),
                unread_count=int(getattr(topic, "unread_count", 0) or 0),
                closed=bool(getattr(topic, "closed", False)),
                hidden=bool(getattr(topic, "hidden", False)),
                pinned=bool(getattr(topic, "pinned", False)),
            )
        )
    return topics


_RECONNECT_INITIAL_DELAY = 10
_RECONNECT_MAX_DELAY = 300
_RECONNECT_NETWORK_ERRORS = (ConnectionError, OSError)
_SQLITE_MAX_RETRIES = 3
_SQLITE_RETRY_DELAY = 1


async def _run_with_reconnect(
    client: TelegramClient,
    send_client: TelegramClient,
    config: Config,
    *,
    fallback_client: TelegramClient | None = None,
) -> None:
    """Run ``client.run_until_disconnected()`` with auto-reconnect on network errors."""
    delay = _RECONNECT_INITIAL_DELAY
    sqlite_retries = 0
    _last_sqlite_error: float | None = None
    _SQLITE_BURST_WINDOW = 30.0  # reset counter if errors are > 30s apart
    while True:
        try:
            await client.run_until_disconnected()
            return  # graceful disconnect
        except sqlite3.OperationalError as exc:
            now = time.monotonic()
            if _last_sqlite_error is not None and (now - _last_sqlite_error) > _SQLITE_BURST_WINDOW:
                sqlite_retries = 0  # sporadic error, not a burst
            _last_sqlite_error = now
            sqlite_retries += 1
            if sqlite_retries > _SQLITE_MAX_RETRIES:
                logger.error(
                    "sqlite3.OperationalError persisted after %d retries: %s",
                    _SQLITE_MAX_RETRIES, exc,
                )
                raise
            logger.warning(
                "sqlite3.OperationalError (retry %d/%d): %s",
                sqlite_retries, _SQLITE_MAX_RETRIES, exc,
            )
            await asyncio.sleep(_SQLITE_RETRY_DELAY)
            continue
        except _RECONNECT_NETWORK_ERRORS as exc:
            if _is_auth_error(exc):
                raise
            sqlite_retries = 0  # reset on network-level reconnect
            disconnected_at = utc_now()
            logger.warning(
                "Connection lost: %s. Reconnecting in %ds...", exc, delay,
            )
            await asyncio.sleep(delay)
            try:
                await client.connect()
            except _RECONNECT_NETWORK_ERRORS:
                delay = min(delay * 2, _RECONNECT_MAX_DELAY)
                continue
            # Connected — reset backoff and notify
            downtime = utc_now() - disconnected_at
            delay = _RECONNECT_INITIAL_DELAY
            logger.info("Reconnected after %s", downtime)
            await _send_reconnect_notification(
                send_client, config, downtime,
                fallback_client=fallback_client,
            )


def _is_auth_error(exc: BaseException) -> bool:
    """Return True for authentication/authorization failures that should not be retried."""
    auth_keywords = ("auth", "authorization", "session", "banned", "deactivated")
    msg = str(exc).lower()
    return any(kw in msg for kw in auth_keywords)


async def _send_reconnect_notification(
    client: TelegramClient,
    config: Config,
    downtime: timedelta,
    *,
    fallback_client: TelegramClient | None = None,
) -> None:
    minutes = int(downtime.total_seconds()) // 60
    seconds = int(downtime.total_seconds()) % 60
    message = f"Watcher reconnected after {minutes}m{seconds}s downtime."
    try:
        for control in config.control_groups.values():
            await _send_message_with_fallback(
                client, fallback_client, control.control_chat_id, message,
            )
    except Exception as notify_exc:
        logger.warning("Failed to send reconnect notification: %s", notify_exc)


async def run_daemon(
    config: Config,
    *,
    health_path: Path | None = None,
) -> None:
    """Run watcher daemon."""
    _purge_old_reports(
        config.reporting.reports_dir,
        config.reporting.retention_days,
    )
    client = _build_client(config)
    activity_tracker = _ActivityTracker()
    await _start_client(client, "primary")
    sender_client = await _start_sender_client(config)
    send_client = sender_client or client
    fallback_client = client if sender_client else None
    me = await client.get_me()
    self_user_id = int(me.id)
    logger.info("Logged in as %s", getattr(me, "username", self_user_id))
    sqlite_gate = _AsyncSqliteGate()
    health_loop = (
        _RunnerHealthLoop(
            health_path,
            sqlite_gate,
            full_archive_configured=config.full_archive.enabled,
            full_archive_fingerprint=config.full_archive.runtime_fingerprint,
        )
        if health_path is not None
        else None
    )

    is_realtime = config.realtime.push_mode == "realtime"
    realtime_pusher: _RealtimePusher | None = None

    if is_realtime:
        rt = config.realtime
        rate_protection = RateProtectionSuite(
            rate_limit_per_minute=rt.rate_limit_per_minute,
            rate_limit_per_hour=rt.rate_limit_per_hour,
            rate_limit_per_day=rt.rate_limit_per_day,
            min_interval_sec=rt.min_interval_sec,
            media_extra_delay_sec=rt.media_extra_delay_sec,
            warmup_minutes=rt.warmup_minutes,
            warmup_rate=rt.warmup_rate,
        )
        realtime_pusher = _RealtimePusher(
            config,
            send_client,
            rate_protection,
            fallback_client=fallback_client,
        )
        realtime_pusher.start()
        logger.info(
            "Realtime push mode active. %s",
            rate_protection.get_status_summary(),
        )

    summary_loops: list[_SummaryLoop] = []
    for target in config.targets:
        control = config.control_groups[target.control_group or ""]
        loop = _SummaryLoop(
            config,
            target,
            control,
            send_client,
            activity_tracker,
            fallback_client=fallback_client,
            html_only=is_realtime,
            sqlite_gate=sqlite_gate,
            interval_override_minutes=(
                config.realtime.report_interval_minutes if is_realtime else None
            ),
        )
        loop.start()
        summary_loops.append(loop)

    heartbeat_loop: _HeartbeatLoop | None = None
    if config.notifications.heartbeat_interval_hours > 0:
        heartbeat_loop = _HeartbeatLoop(
            config, send_client, activity_tracker, fallback_client=fallback_client,
        )

    update_check_loop: _UpdateCheckLoop | None = None
    if config.notifications.check_updates:
        update_check_loop = _UpdateCheckLoop(
            config, send_client, fallback_client=fallback_client,
        )

    control_handler = _ControlHandler(
        config,
        client,
        send_client,
        self_user_id,
        activity_tracker,
        fallback_client=fallback_client,
        sqlite_gate=sqlite_gate,
    )

    archive_runtime_enabled = _full_archive_runtime_enabled(config)
    if health_loop is not None:
        health_loop.full_archive_runtime_enabled = archive_runtime_enabled
    target_handlers: list[_TargetHandler] = []
    for target in config.targets:
        target_handler = _TargetHandler(
            config,
            client,
            target,
            realtime_queue=realtime_pusher.queue if realtime_pusher else None,
            archive_relink_enabled=archive_runtime_enabled,
            sqlite_gate=sqlite_gate,
        )
        target_handlers.append(target_handler)
        client.add_event_handler(
            target_handler.handle,
            events.NewMessage(chats=[target.target_chat_id]),
        )
    if archive_runtime_enabled:
        full_archive_handler = _FullArchiveHandler(config, sqlite_gate=sqlite_gate)
        client.add_event_handler(
            full_archive_handler.handle,
            events.NewMessage(chats=[config.full_archive.source_chat_id]),
        )
        client.add_event_handler(
            full_archive_handler.handle,
            events.MessageEdited(chats=[config.full_archive.source_chat_id]),
        )
    client.add_event_handler(
        control_handler.handle,
        events.NewMessage(chats=list(config.control_by_chat_id.keys())),
    )

    if is_realtime:
        rt = config.realtime
        startup_msg = (
            "\u26a0\ufe0f [EXPERIMENTAL] Realtime mode active | "
            f"Rate limits: {rt.rate_limit_per_minute}/min, "
            f"{rt.rate_limit_per_hour}/hr, "
            f"{rt.rate_limit_per_day}/day | "
            f"Warmup: {rt.warmup_minutes:.0f} min @ {rt.warmup_rate}/min"
        )
        for control in config.control_groups.values():
            try:
                await _send_message_with_fallback(
                    send_client,
                    fallback_client,
                    control.control_chat_id,
                    startup_msg,
                )
            except Exception as exc:
                logger.warning("Failed to send realtime startup message: %s", exc)

    if heartbeat_loop is not None:
        heartbeat_loop.start()
    if update_check_loop is not None:
        update_check_loop.start()
    if health_loop is not None:
        health_loop.start()
    try:
        await _run_with_reconnect(client, send_client, config, fallback_client=fallback_client)
    except Exception as exc:
        await _send_error_notification(send_client, config, exc, fallback_client=fallback_client)
        raise
    finally:
        if realtime_pusher:
            await realtime_pusher.stop()
        if heartbeat_loop is not None:
            await heartbeat_loop.stop()
        if update_check_loop is not None:
            await update_check_loop.stop()
        if health_loop is not None:
            await health_loop.stop()
        for loop in summary_loops:
            await loop.stop()
        if target_handlers:
            await asyncio.gather(
                *(handler.drain_archive_relinks() for handler in target_handlers)
            )
        if sender_client:
            await sender_client.disconnect()
        await client.disconnect()


def _full_archive_runtime_enabled(config: Config) -> bool:
    archive = config.full_archive
    if not archive.enabled or archive.source_chat_id is None:
        return False
    report = inspect_archive_status(
        archive.root_dir,
        tracked_db_path=config.storage.db_path,
    )
    if only_archive_sender_schema_missing(report):
        try:
            updated = ensure_archive_sender_schema(archive.root_dir)
        except (OSError, sqlite3.Error) as exc:
            logger.warning("Failed to migrate full archive sender schema: %s", exc)
        else:
            if updated:
                logger.info(
                    "Added archive_senders table to %s existing full archive shard(s)",
                    updated,
                )
            report = inspect_archive_status(
                archive.root_dir,
                tracked_db_path=config.storage.db_path,
            )
    if not report.degraded:
        return True
    logger.warning(
        "Full archive live capture disabled because archive health is degraded; "
        "run archive-status and archive-repair --dry-run before restarting daemon."
    )
    for error in report.errors:
        logger.warning("Full archive health error: %s", error)
    return False


def _build_client(config: Config) -> TelegramClient:
    session_path = config.telegram.session_file
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        _WalSqliteSession(str(session_path)),
        config.telegram.api_id,
        config.telegram.api_hash,
    )


def _build_sender_client(config: Config) -> TelegramClient | None:
    if config.sender is None:
        return None
    session_path = config.sender.session_file
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        _WalSqliteSession(str(session_path)),
        config.telegram.api_id,
        config.telegram.api_hash,
    )


async def _start_sender_client(config: Config) -> TelegramClient | None:
    sender = _build_sender_client(config)
    if sender is None:
        return None
    try:
        await _start_client(sender, "sender")
    except Exception as exc:
        logger.warning("Failed to start sender session: %s", exc)
        try:
            await sender.disconnect()
        except Exception:
            pass
        return None
    return sender


async def _collect_window(
    client: TelegramClient,
    config: Config,
    target: TargetGroupConfig,
    since: datetime,
) -> list[tuple[StoredMessage, list[StoredMedia]]]:
    tracked = set(target.tracked_user_ids)
    captures: list[tuple[StoredMessage, list[StoredMedia]]] = []
    async for msg in client.iter_messages(target.target_chat_id):
        if msg.date is None:
            continue
        msg_dt = _ensure_tz(msg.date)
        if msg_dt < since:
            break
        sender_id = getattr(msg, "sender_id", None)
        if sender_id is None or int(sender_id) not in tracked:
            continue
        capture = await _capture_message(client, config, msg, chat_id_default=target.target_chat_id)
        if capture:
            captures.append(capture)
    captures.reverse()
    return captures


async def _capture_message(
    client: TelegramClient,
    config: Config,
    message: custom_message.Message,
    *,
    chat_id_default: int | None = None,
) -> tuple[StoredMessage, list[StoredMedia]] | None:
    sender_id = getattr(message, "sender_id", None)
    if sender_id is None:
        return None
    chat_id = int(getattr(message, "chat_id", chat_id_default or 0))
    msg_dt = _ensure_tz(message.date)
    reply_info = await _get_reply_snapshot(
        client, config.storage.media_dir, message, chat_id
    )
    media_items = await _download_media(
        client, config.storage.media_dir, message, chat_id
    )
    if reply_info and reply_info.media:
        base_index = len(media_items)
        for offset, media in enumerate(reply_info.media, start=base_index):
            media.media_index = offset
        media_items.extend(reply_info.media)
    stored_msg = StoredMessage(
        chat_id=chat_id,
        message_id=int(message.id),
        sender_id=int(sender_id),
        date=msg_dt,
        text=message.message or message.raw_text,
        reply_to_msg_id=getattr(message, "reply_to_msg_id", None),
        replied_sender_id=reply_info.sender_id if reply_info else None,
        replied_date=reply_info.date if reply_info else None,
        replied_text=reply_info.text if reply_info else None,
    )
    return stored_msg, media_items


@dataclass
class ReplySnapshot:
    sender_id: int | None
    text: str | None
    date: datetime | None
    media: list[StoredMedia]


def _is_explicit_reply(message: custom_message.Message) -> bool:
    """Return True when a message semantically replies to another message."""
    if not message.is_reply:
        return False
    reply_header = getattr(message, "reply_to", None)
    if reply_header is None:
        return True
    if not bool(getattr(reply_header, "forum_topic", False)):
        return True
    if bool(getattr(reply_header, "quote", False)):
        return True
    # Forum topic posts may carry a synthetic "reply" to the topic root.
    # Treat those as topic linkage instead of explicit user replies.
    return getattr(reply_header, "reply_to_top_id", None) is not None


async def _get_reply_snapshot(
    client: TelegramClient,
    media_dir: Path,
    message: custom_message.Message,
    chat_id: int,
) -> ReplySnapshot | None:
    if not _is_explicit_reply(message):
        return None
    try:
        reply = await _with_floodwait(message.get_reply_message)
    except errors.RPCError as exc:
        logger.warning("Failed to fetch reply snapshot: %s", exc)
        return None
    if reply is None:
        return None
    text = reply.message or reply.raw_text or ""
    if len(text) > 280:
        text = text[:279] + "…"
    reply_media = await _download_media(
        client,
        media_dir,
        reply,
        chat_id,
        base_name=f"{message.id}_reply_{reply.id}",
        is_reply=True,
        owner_message_id=int(message.id),
    )
    return ReplySnapshot(
        sender_id=getattr(reply, "sender_id", None),
        text=text,
        date=_ensure_tz(reply.date) if reply.date else None,
        media=reply_media,
    )


async def _download_media(
    client: TelegramClient,
    media_dir: Path,
    message: custom_message.Message,
    chat_id: int,
    *,
    base_name: str | None = None,
    is_reply: bool = False,
    owner_message_id: int | None = None,
) -> list[StoredMedia]:
    if not message.media:
        return []
    target_dir = media_dir / str(chat_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    file_stub = base_name or f"{message.id}"
    downloaded_path = await _with_floodwait(
        client.download_media,
        message,
        file=target_dir / file_stub,
    )
    if not downloaded_path:
        return []
    path = Path(downloaded_path).resolve()
    stat = path.stat()
    mime = None
    if message.file:
        mime = getattr(message.file, "mime_type", None)
    return [
        StoredMedia(
            chat_id=chat_id,
            message_id=owner_message_id or int(message.id),
            file_path=str(path),
            mime_type=mime,
            file_size=stat.st_size,
            media_index=0,
            is_reply=is_reply,
        )
    ]


def _ensure_tz(dt: datetime) -> datetime:
    if dt.tzinfo:
        return dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=timezone.utc)


class _TargetHandler:
    def __init__(
        self,
        config: Config,
        client: TelegramClient,
        target: TargetGroupConfig,
        *,
        realtime_queue: "asyncio.Queue[tuple[DbMessage, TargetGroupConfig]] | None" = None,
        archive_relink_enabled: bool = True,
        sqlite_gate: _AsyncSqliteGate | None = None,
    ):
        self.config = config
        self.client = client
        self.target = target
        self._tracked = set(target.tracked_user_ids)
        self._realtime_queue = realtime_queue
        self._archive_relink_enabled = archive_relink_enabled
        self._sqlite_gate = sqlite_gate or _AsyncSqliteGate()
        self._archive_relink_tasks: set[asyncio.Task[None]] = set()

    async def drain_archive_relinks(
        self,
        *,
        timeout: float = ARCHIVE_RELINK_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> int:
        if not self._archive_relink_tasks:
            return 0
        done, pending = await asyncio.wait(
            tuple(self._archive_relink_tasks),
            timeout=timeout,
        )
        for task in done:
            self._archive_relink_tasks.discard(task)
            if task.cancelled():
                logger.warning("Full archive relink task was cancelled during shutdown")
                continue
            try:
                task.result()
            except Exception as exc:
                logger.warning(
                    "Full archive relink task failed during shutdown: %s",
                    exc,
                    exc_info=True,
                )
        if pending:
            logger.warning(
                "Full archive relink still pending at shutdown: %d task(s)",
                len(pending),
            )
        return len(pending)

    async def handle(self, event: events.NewMessage.Event) -> None:
        msg = event.message
        sender_id = getattr(msg, "sender_id", None)
        if sender_id is None or int(sender_id) not in self._tracked:
            return
        capture = await _capture_message(
            self.client,
            self.config,
            msg,
            chat_id_default=self.target.target_chat_id,
        )
        if not capture:
            return
        message, media = capture
        db_msg = await self._sqlite_gate.run(
            _persist_tracked_message,
            self.config.storage.db_path,
            message,
            media,
            include_realtime=self._realtime_queue is not None,
        )
        if self._archive_relink_enabled:
            _schedule_archive_relink_after_tracked_persist(
                self.config,
                msg,
                message,
                task_set=self._archive_relink_tasks,
                sqlite_gate=self._sqlite_gate,
            )
        logger.info(
            "Captured message %s from %s",
            message.message_id,
            self.config.describe_user(int(message.sender_id), target=self.target),
        )
        if self._realtime_queue is not None and db_msg is not None:
            self._realtime_queue.put_nowait((db_msg, self.target))


def _persist_tracked_message(
    db_path: Path,
    message: StoredMessage,
    media: Sequence[StoredMedia],
    *,
    include_realtime: bool,
) -> DbMessage | None:
    """Persist a tracked message and optionally return its media-populated DB row."""
    with db_session(db_path) as conn:
        persist_message(conn, message, media)
        if not include_realtime:
            return None
        db_messages = fetch_messages_between(
            conn,
            (int(message.sender_id),),
            message.date - timedelta(seconds=1),
            message.date + timedelta(seconds=1),
            chat_ids=[message.chat_id],
        )
    return next(
        (item for item in db_messages if item.message_id == message.message_id),
        None,
    )


class _FullArchiveHandler:
    def __init__(
        self,
        config: Config,
        *,
        sqlite_gate: _AsyncSqliteGate | None = None,
    ):
        self.config = config
        self._sqlite_gate = sqlite_gate or _AsyncSqliteGate()
        self._sender_identity_cache: dict[int, _ArchiveSenderIdentity] = {}
        self._sender_lookup_retry_after: dict[int, float] = {}
        self._sender_lookup_tasks: dict[
            int,
            asyncio.Task[_ArchiveSenderIdentity | None],
        ] = {}

    async def handle(self, event: events.NewMessage.Event) -> None:
        try:
            message = _archive_message_from_telegram(
                event.message,
                chat_id_default=self.config.full_archive.source_chat_id,
            )
            if message is None or not _archive_message_matches_scope(
                self.config,
                message,
            ):
                return
            sender_snapshot = await self._sender_snapshot(event, message)
            await self._sqlite_gate.run(
                _persist_archive_message_to_storage,
                self.config,
                message,
                tracked_db_path=self.config.storage.db_path,
                sender_snapshot=sender_snapshot,
            )
        except Exception as exc:
            logger.warning(
                "Full archive capture failed without stopping watcher: %s",
                exc,
                exc_info=True,
            )

    async def _sender_snapshot(
        self,
        event: events.NewMessage.Event,
        message: ArchiveMessage,
    ) -> ArchiveSender | None:
        if message.sender_id is None:
            return None
        identity = await self._sender_identity(event, message.sender_id)
        if identity is None:
            return None
        return ArchiveSender(
            sender_id=message.sender_id,
            username=identity.username,
            display_name=identity.display_name,
            first_seen_at=message.date,
            last_seen_at=message.date,
        )

    async def _sender_identity(
        self,
        event: events.NewMessage.Event,
        sender_id: int,
    ) -> _ArchiveSenderIdentity | None:
        if sender_id in self._sender_identity_cache:
            return self._sender_identity_cache[sender_id]
        loop = asyncio.get_running_loop()
        retry_after = self._sender_lookup_retry_after.get(sender_id)
        if retry_after is not None and loop.time() < retry_after:
            return None
        task = self._sender_lookup_tasks.get(sender_id)
        if task is None:
            task = asyncio.create_task(self._load_sender_identity(event))
            self._sender_lookup_tasks[sender_id] = task
        try:
            identity = await task
        except errors.FloodWaitError as exc:
            wait_for = max(
                ARCHIVE_SENDER_LOOKUP_RETRY_SECONDS,
                float(exc.seconds + 1),
            )
            self._sender_lookup_retry_after[sender_id] = loop.time() + wait_for
            logger.warning(
                "FloodWait during full archive sender lookup; retrying after %ss",
                wait_for,
            )
            return None
        finally:
            self._sender_lookup_tasks.pop(sender_id, None)
        if identity is None:
            self._sender_lookup_retry_after[sender_id] = (
                loop.time() + ARCHIVE_SENDER_LOOKUP_RETRY_SECONDS
            )
            return None
        self._sender_lookup_retry_after.pop(sender_id, None)
        self._sender_identity_cache[sender_id] = identity
        return identity

    async def _load_sender_identity(
        self,
        event: events.NewMessage.Event,
    ) -> _ArchiveSenderIdentity | None:
        get_sender = getattr(event, "get_sender", None)
        if not callable(get_sender):
            get_sender = getattr(event.message, "get_sender", None)
        try:
            if callable(get_sender):
                entity = get_sender()
                if hasattr(entity, "__await__"):
                    entity = await entity
            else:
                entity = getattr(event.message, "sender", None)
            return _sender_identity_from_entity(entity)
        except errors.FloodWaitError:
            raise
        except Exception:
            return None


def _schedule_archive_relink_after_tracked_persist(
    config: Config,
    telegram_message: custom_message.Message,
    stored_message: StoredMessage,
    *,
    task_set: set[asyncio.Task[None]] | None = None,
    sqlite_gate: _AsyncSqliteGate | None = None,
) -> asyncio.Task[None] | None:
    if not config.full_archive.enabled:
        return None
    task = asyncio.create_task(
        _relink_archive_message_after_tracked_persist(
            config,
            telegram_message,
            stored_message,
            sqlite_gate=sqlite_gate,
        )
    )
    if task_set is not None:
        task_set.add(task)
        task.add_done_callback(task_set.discard)
    return task


async def _relink_archive_message_after_tracked_persist(
    config: Config,
    telegram_message: custom_message.Message,
    stored_message: StoredMessage,
    *,
    sqlite_gate: _AsyncSqliteGate | None = None,
) -> None:
    if not config.full_archive.enabled:
        return
    try:
        archive_message = _archive_message_from_telegram(
            telegram_message,
            chat_id_default=stored_message.chat_id,
        )
        if archive_message is None or not _archive_message_matches_scope(
            config,
            archive_message,
        ):
            return
        gate = sqlite_gate or _AsyncSqliteGate()
        await gate.run(
            _persist_archive_message_to_storage,
            config,
            archive_message,
            tracked_db_path=config.storage.db_path,
        )
    except Exception as exc:
        logger.warning(
            "Full archive relink failed after tracked persist: %s",
            exc,
            exc_info=True,
        )


def _archive_message_from_telegram(
    message: custom_message.Message,
    *,
    chat_id_default: int | None = None,
) -> ArchiveMessage | None:
    message_id = _coerce_optional_int(getattr(message, "id", None))
    date = _coerce_optional_datetime(getattr(message, "date", None))
    chat_id = _coerce_optional_int(getattr(message, "chat_id", None))
    if chat_id is None:
        chat_id = _coerce_optional_int(chat_id_default)
    if message_id is None or date is None or chat_id is None or chat_id == 0:
        return None
    topic_id = _archive_topic_id_for_message(message)
    text = getattr(message, "message", None) or getattr(message, "raw_text", None)
    raw_text = getattr(message, "raw_text", None) or text
    sender_id = _coerce_optional_int(getattr(message, "sender_id", None))
    return ArchiveMessage(
        chat_id=chat_id,
        message_id=message_id,
        topic_id=topic_id,
        sender_id=sender_id,
        date=date,
        text=text,
        raw_text=raw_text,
        message_kind="service" if getattr(message, "action", None) is not None else "message",
        reply_to_msg_id=_coerce_optional_int(getattr(message, "reply_to_msg_id", None)),
        reply_to_top_id=_reply_to_top_id_for_message(message),
        is_forum_topic_link=bool(
            getattr(getattr(message, "reply_to", None), "forum_topic", False)
        ),
        has_media=bool(getattr(message, "media", None)),
        media=_archive_media_from_telegram(message),
    )


def _archive_message_matches_scope(config: Config, message: ArchiveMessage) -> bool:
    archive = config.full_archive
    if not archive.enabled or archive.source_chat_id is None:
        return False
    if message.chat_id != archive.source_chat_id:
        return False
    if archive.capture_scope == "topics":
        return message.topic_id in set(archive.topic_ids)
    return True


def _archive_media_from_telegram(
    message: custom_message.Message,
) -> tuple[ArchiveMedia, ...]:
    media = getattr(message, "media", None)
    if media is None:
        return ()
    file_info = getattr(message, "file", None)
    document = getattr(media, "document", None)
    media_kind = type(media).__name__ or "media"
    mime_type = (
        getattr(file_info, "mime_type", None)
        or getattr(media, "mime_type", None)
        or getattr(document, "mime_type", None)
    )
    file_size = (
        getattr(file_info, "size", None)
        or getattr(media, "size", None)
        or getattr(document, "size", None)
    )
    file_name = getattr(file_info, "name", None) or getattr(media, "file_name", None)
    return (
        ArchiveMedia(
            media_index=0,
            media_kind=str(media_kind),
            mime_type=str(mime_type) if mime_type is not None else None,
            file_size=_coerce_optional_int(file_size),
            file_name=str(file_name) if file_name is not None else None,
        ),
    )


def _persist_archive_message_to_storage(
    config: Config,
    message: ArchiveMessage,
    *,
    tracked_db_path: Path | None,
    sender_snapshot: ArchiveSender | None = None,
) -> ArchivePersistResult:
    archive = config.full_archive
    manifest_path = archive.root_dir / "manifest.sqlite3"
    manifest_conn = archive_connect(manifest_path)
    try:
        shard = find_shard_for_message(
            manifest_conn,
            archive.root_dir,
            chat_id=message.chat_id,
            message_date=message.date,
            message_id=message.message_id,
        )
        if shard is None:
            shard = select_shard(
                manifest_conn,
                archive.root_dir,
                chat_id=message.chat_id,
                message_date=message.date,
                max_messages_per_shard=archive.max_messages_per_shard,
                max_shard_size_bytes=archive.max_shard_size_bytes,
            )
        shard_conn = archive_connect(shard.path)
        try:
            previous_payload_mode = _archive_message_payload_mode(
                shard_conn,
                chat_id=message.chat_id,
                message_id=message.message_id,
            )
            existed = previous_payload_mode is not None
            persist_result = persist_archive_message_with_result(
                shard_conn,
                message,
                tracked_db_path=tracked_db_path,
                archive_root_dir=archive.root_dir,
                sender=sender_snapshot,
            )
            payload_mode = persist_result.payload_mode
        finally:
            shard_conn.close()
        if persist_result.created:
            record_shard_write(manifest_conn, shard)
        if tracked_db_path is not None:
            record_tracked_db_link(
                manifest_conn,
                tracked_db_path,
                archive_root_dir=archive.root_dir,
            )
        linked = (
            payload_mode == "tracked_ref"
            and previous_payload_mode != "tracked_ref"
        )
        return ArchivePersistResult(
            payload_mode=payload_mode,
            created=persist_result.created,
            linked=linked,
        )
    finally:
        manifest_conn.close()


def _archive_message_payload_mode(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    message_id: int,
) -> str | None:
    if not archive_message_exists(conn, chat_id=chat_id, message_id=message_id):
        return None
    row = conn.execute(
        """
        SELECT payload_mode
        FROM archive_messages
        WHERE chat_id = ? AND message_id = ?
        LIMIT 1
        """,
        (chat_id, message_id),
    ).fetchone()
    return str(row["payload_mode"]) if row is not None else None


def _archive_topic_id_for_message(message: custom_message.Message) -> int | None:
    top_id = _reply_to_top_id_for_message(message)
    normalized_top_id = _normalize_archive_topic_id(top_id)
    if normalized_top_id is not None:
        return normalized_top_id
    reply_to = getattr(message, "reply_to", None)
    if reply_to is None or not bool(getattr(reply_to, "forum_topic", False)):
        return None
    reply_to_msg_id = getattr(message, "reply_to_msg_id", None) or getattr(
        reply_to,
        "reply_to_msg_id",
        None,
    )
    return _normalize_archive_topic_id(_coerce_optional_int(reply_to_msg_id))


def _reply_to_top_id_for_message(message: custom_message.Message) -> int | None:
    reply_to = getattr(message, "reply_to", None)
    if reply_to is None:
        return None
    top_id = getattr(reply_to, "reply_to_top_id", None)
    return _coerce_optional_int(top_id)


def _normalize_archive_topic_id(value: int | None) -> int | None:
    if value is None or value <= 1:
        return None
    return value


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sender_identity_from_entity(entity: object) -> _ArchiveSenderIdentity | None:
    if entity is None:
        return None
    username = _normalize_sender_username(getattr(entity, "username", None))
    display_name = _normalize_sender_text(utils.get_display_name(entity))
    if not username and not display_name:
        return None
    return _ArchiveSenderIdentity(
        username=username,
        display_name=display_name,
    )


def _normalize_sender_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized or None


def _normalize_sender_username(value: object) -> str | None:
    normalized = _normalize_sender_text(value)
    if normalized is None:
        return None
    normalized = normalized.lstrip("@").strip()
    return normalized or None


def _coerce_optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return _ensure_tz(value)


class _RealtimePusher:
    """Consumes captured messages and pushes them to control chats in realtime.

    Uses ``RateProtectionSuite`` to stay within safe Telegram rate limits.
    """

    def __init__(
        self,
        config: Config,
        client: TelegramClient,
        rate_protection: RateProtectionSuite,
        *,
        fallback_client: TelegramClient | None = None,
    ):
        self.config = config
        self.client = client
        self.rate_protection = rate_protection
        self._fallback_client = fallback_client
        self.queue: asyncio.Queue[tuple[DbMessage, TargetGroupConfig]] = asyncio.Queue()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    _MAX_RETRIES = 3

    async def _run(self) -> None:
        retry_counts: dict[tuple[int, int], int] = {}  # (chat_id, message_id) -> attempts
        while not self._stop.is_set():
            try:
                # Use a short timeout so we can check the stop flag periodically.
                try:
                    db_msg, target = await asyncio.wait_for(
                        self.queue.get(), timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue
                msg_key = (db_msg.chat_id, db_msg.message_id)
                try:
                    await self._push_message(db_msg, target)
                    retry_counts.pop(msg_key, None)
                except errors.FloodWaitError:
                    # Already handled inside _push_message (re-enqueued there).
                    pass
                except Exception:
                    attempts = retry_counts.get(msg_key, 0) + 1
                    if attempts < self._MAX_RETRIES:
                        retry_counts[msg_key] = attempts
                        logger.warning(
                            "Realtime push failed for msg %s:%s (attempt %d/%d); will retry.",
                            db_msg.chat_id, db_msg.message_id, attempts, self._MAX_RETRIES,
                        )
                        self.queue.put_nowait((db_msg, target))
                    else:
                        retry_counts.pop(msg_key, None)
                        logger.exception(
                            "Realtime push failed for msg %s:%s after %d attempts; dropping.",
                            db_msg.chat_id, db_msg.message_id, self._MAX_RETRIES,
                        )
                # Safety: cap dict size to prevent unbounded growth.
                if len(retry_counts) > 1000:
                    retry_counts.clear()
            except asyncio.CancelledError:
                break

    async def _push_message(
        self, db_msg: DbMessage, target: TargetGroupConfig,
    ) -> None:
        control = self.config.control_groups.get(target.control_group or "")
        if control is None:
            logger.warning(
                "No control group for target '%s'; dropping realtime push.",
                target.name,
            )
            return

        has_media = bool(db_msg.media)
        while True:
            try:
                await self.rate_protection.acquire(has_media=has_media)
                break
            except CircuitBrokenError as exc:
                logger.critical(
                    "Circuit breaker tripped — sleeping %.0f s before retry.",
                    exc.remaining_seconds,
                )
                await send_bark_notification(
                    self.config.notifications,
                    "Rate limit circuit breaker",
                    f"All sends blocked for {exc.remaining_seconds:.0f}s",
                )
                await asyncio.sleep(exc.remaining_seconds)

        flood_cb = self.rate_protection.record_flood_wait

        try:
            reply_to = _topic_reply_id_for_message(
                control, target.target_chat_id, db_msg,
            )
            text = _format_control_message(db_msg, self.config, target)
            await _send_message_with_fallback(
                self.client,
                self._fallback_client,
                control.control_chat_id,
                text,
                on_flood_wait=flood_cb,
                parse_mode="html",
                reply_to=reply_to,
            )
            self.rate_protection.record_send()

            # Each media attachment is a separate Telegram API call —
            # account for it individually in rate windows.
            if db_msg.media:
                for media in db_msg.media:
                    file_path = Path(media.file_path)
                    if not file_path.exists():
                        logger.warning("Media file missing on disk: %s", file_path)
                        continue
                    sender_label = self.config.format_user_label(
                        db_msg.sender_id, target=target,
                    )
                    if media.is_reply:
                        reply_label = (
                            self.config.format_user_label(
                                db_msg.replied_sender_id, target=target,
                            )
                            if db_msg.replied_sender_id
                            else "unknown"
                        )
                        caption = (
                            f"Reply media for message #{db_msg.message_id}\n"
                            f"Original sender: {reply_label}"
                        )
                    else:
                        caption = f"Media for {sender_label} — message #{db_msg.message_id}"

                    await self.rate_protection.acquire(has_media=True)
                    await _send_file_with_fallback(
                        self.client,
                        self._fallback_client,
                        control.control_chat_id,
                        file_path,
                        on_flood_wait=flood_cb,
                        caption=caption,
                        reply_to=reply_to,
                    )
                    self.rate_protection.record_send()
        except errors.FloodWaitError as exc:
            # FloodWait that escaped _with_floodwait (should be rare).
            adjusted = self.rate_protection.record_flood_wait(exc.seconds)
            wait_for = max(exc.seconds + 1, adjusted)
            logger.warning(
                "FloodWait during realtime push: sleeping %ds then retrying.",
                wait_for,
            )
            await asyncio.sleep(wait_for)
            self.queue.put_nowait((db_msg, target))


class _ControlHandler:
    def __init__(
        self,
        config: Config,
        client: TelegramClient,
        send_client: TelegramClient,
        owner_id: int,
        tracker: "_ActivityTracker",
        *,
        fallback_client: TelegramClient | None = None,
        sqlite_gate: _AsyncSqliteGate | None = None,
    ):
        self.config = config
        self.client = client
        self.send_client = send_client
        self.owner_id = owner_id
        self._tracker = tracker
        self._fallback_client = fallback_client
        self._sqlite_gate = sqlite_gate or _AsyncSqliteGate()

    async def handle(self, event: events.NewMessage.Event) -> None:
        if int(getattr(event.message, "sender_id", 0)) != self.owner_id:
            return
        chat_id = int(getattr(event.message, "chat_id", event.chat_id))
        control = self.config.control_for_chat(chat_id)
        if control is None:
            return
        targets = self.config.targets_for_control(control.key)
        if not targets:
            await _reply(
                event,
                "No target groups are mapped to this control group.",
                client=self.send_client,
                fallback_client=self._fallback_client,
            )
            return
        text = (event.message.raw_text or "").strip()
        if not text.startswith("/"):
            return
        parts = text.split()
        command = parts[0]
        if command == "/help":
            await _reply(event, _HELP_TEXT, client=self.send_client, fallback_client=self._fallback_client)
            return
        if command == "/last":
            await self._cmd_last(event, parts[1:], control, targets)
            return
        if command == "/since":
            await self._cmd_since(event, parts[1:], control, targets)
            return
        if command == "/export":
            await self._cmd_export(event, parts[1:], control, targets)
            return
        await _reply(event, "Unknown command. Use /help", client=self.send_client, fallback_client=self._fallback_client)

    async def _cmd_last(
        self,
        event: events.NewMessage.Event,
        args: Sequence[str],
        control: ControlGroupConfig,
        targets: Sequence[TargetGroupConfig],
    ) -> None:
        if not args:
            await _reply(
                event,
                "Usage: /last <user_id> [N]",
                client=self.send_client,
                fallback_client=self._fallback_client,
            )
            return
        try:
            user_id = await self._resolve_user(args[0])
        except ValueError as exc:
            await _reply(event, f"Cannot resolve user: {exc}", client=self.send_client, fallback_client=self._fallback_client)
            return
        tracked_ids = _tracked_ids_for_targets(targets)
        if user_id not in tracked_ids:
            await _reply(
                event,
                f"User {user_id} not in tracked list for this control group.",
                client=self.send_client,
                fallback_client=self._fallback_client,
            )
            return
        try:
            limit = int(args[1]) if len(args) > 1 else 5
        except ValueError:
            await _reply(event, "Limit must be an integer.", client=self.send_client, fallback_client=self._fallback_client)
            return
        if limit <= 0:
            await _reply(event, "Limit must be > 0.", client=self.send_client, fallback_client=self._fallback_client)
            return
        chat_ids = [target.target_chat_id for target in targets]
        messages = await self._sqlite_gate.run(
            _fetch_recent_messages_from_storage,
            self.config.storage.db_path,
            user_id,
            limit,
            chat_ids,
        )
        if not messages:
            await _reply(event, "No messages stored yet.", client=self.send_client, fallback_client=self._fallback_client)
            return
        target = _target_for_user(targets, user_id)
        label = self.config.describe_user(user_id, target=target)
        lines = [f"Last {len(messages)} messages for {label}:"]
        for msg in messages:
            lines.append(_format_message_line(msg))
        await _reply(event, "\n".join(lines), client=self.send_client, fallback_client=self._fallback_client)

    async def _cmd_since(
        self,
        event: events.NewMessage.Event,
        args: Sequence[str],
        control: ControlGroupConfig,
        targets: Sequence[TargetGroupConfig],
    ) -> None:
        if not args:
            await _reply(event, "Usage: /since <Nh|Nm|ISO>", client=self.send_client, fallback_client=self._fallback_client)
            return
        try:
            since = parse_since_spec(args[0], now=utc_now())
        except ValueError as exc:
            await _reply(event, str(exc), client=self.send_client, fallback_client=self._fallback_client)
            return
        chat_ids = [target.target_chat_id for target in targets]
        counts = await self._sqlite_gate.run(
            _fetch_summary_counts_from_storage,
            self.config.storage.db_path,
            _tracked_ids_for_targets(targets),
            since,
            chat_ids,
        )
        if not counts:
            await _reply(event, "No messages in that window.", client=self.send_client, fallback_client=self._fallback_client)
            return
        target_names = ", ".join(target.name for target in targets)
        lines = [f"Summary since {since.isoformat()} (targets: {target_names})"]
        for user_id in sorted(counts):
            target = _target_for_user(targets, user_id)
            label = self.config.describe_user(user_id, target=target)
            lines.append(f"- {label}: {counts[user_id]} message(s)")
        await _reply(event, "\n".join(lines), client=self.send_client, fallback_client=self._fallback_client)

    async def _cmd_export(
        self,
        event: events.NewMessage.Event,
        args: Sequence[str],
        control: ControlGroupConfig,
        targets: Sequence[TargetGroupConfig],
    ) -> None:
        if not args:
            await _reply(event, "Usage: /export <Nh|Nm|ISO>", client=self.send_client, fallback_client=self._fallback_client)
            return
        try:
            since = parse_since_spec(args[0], now=utc_now())
        except ValueError as exc:
            await _reply(event, str(exc), client=self.send_client, fallback_client=self._fallback_client)
            return
        until = utc_now()
        for target in targets:
            messages = await self._sqlite_gate.run(
                _fetch_messages_from_storage,
                self.config.storage.db_path,
                target.tracked_user_ids,
                since,
                until,
                [target.target_chat_id],
            )
            report = generate_report(messages, self.config, since, until, target=target)
            await _send_report_bundle(
                self.send_client,
                self.config,
                control,
                target,
                messages,
                since,
                until,
                report,
                tracker=self._tracker,
                fallback_client=self._fallback_client,
            )

    async def _resolve_user(self, arg: str) -> int:
        arg = arg.strip()
        if arg.lstrip("-").isdigit():
            return int(arg)
        entity = await _with_floodwait(self.client.get_entity, arg)
        user_id = getattr(entity, "id", None)
        if user_id is None:
            raise ValueError("Cannot resolve user")
        return int(user_id)


def _fetch_recent_messages_from_storage(
    db_path: Path,
    user_id: int,
    limit: int,
    chat_ids: Sequence[int],
) -> list[DbMessage]:
    with db_session(db_path) as conn:
        return fetch_recent_messages(conn, user_id, limit, chat_ids=chat_ids)


def _fetch_summary_counts_from_storage(
    db_path: Path,
    tracked_ids: Sequence[int],
    since: datetime,
    chat_ids: Sequence[int],
) -> dict[int, int]:
    with db_session(db_path) as conn:
        return fetch_summary_counts(conn, tracked_ids, since, chat_ids=chat_ids)


def _fetch_messages_from_storage(
    db_path: Path,
    tracked_ids: Sequence[int],
    since: datetime,
    until: datetime,
    chat_ids: Sequence[int],
) -> list[DbMessage]:
    with db_session(db_path) as conn:
        return fetch_messages_between(
            conn,
            tracked_ids,
            since,
            until,
            chat_ids=chat_ids,
        )


def _format_message_line(msg: DbMessage) -> str:
    text = msg.text or "<no text>"
    text = text.replace("\n", " ")
    if len(text) > 70:
        text = text[:70] + "…"
    return f"{msg.date.isoformat()} — {text}"


def _tracked_ids_for_targets(targets: Sequence[TargetGroupConfig]) -> tuple[int, ...]:
    tracked: list[int] = []
    for target in targets:
        tracked.extend(target.tracked_user_ids)
    return tuple(sorted(set(tracked)))


def _target_for_user(
    targets: Sequence[TargetGroupConfig],
    user_id: int,
) -> TargetGroupConfig | None:
    for target in targets:
        if user_id in target.tracked_user_ids:
            return target
    return None


_HELP_TEXT = (
    "Commands:\n"
    "/help - show this help\n"
    "/last <user_id|username> [N] - last N tracked messages\n"
    "/since <Nh|Nm|ISO> - summary counts from window\n"
    "/export <Nh|Nm|ISO> - generate report for window"
)


class _SummaryLoop:
    def __init__(
        self,
        config: Config,
        target: TargetGroupConfig,
        control: ControlGroupConfig,
        client: TelegramClient,
        tracker: "_ActivityTracker",
        *,
        fallback_client: TelegramClient | None = None,
        html_only: bool = False,
        sqlite_gate: _AsyncSqliteGate | None = None,
        interval_override_minutes: int | None = None,
    ):
        self.config = config
        self.target = target
        self.control = control
        self.client = client
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_summary = utc_now()
        self._tracker = tracker
        self._fallback_client = fallback_client
        self._html_only = html_only
        self._sqlite_gate = sqlite_gate or _AsyncSqliteGate()
        self._interval_minutes = interval_override_minutes or target.summary_interval_minutes

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        interval = self._interval_minutes * 60
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                try:
                    await self._send_summary()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Summary send failed for target '%s' (chat_id=%s); "
                        "will continue next interval.",
                        self.target.name,
                        self.target.target_chat_id,
                    )
            except asyncio.CancelledError:
                break

    async def _send_summary(self) -> None:
        now = utc_now()
        since = self._last_summary
        self._last_summary = now
        messages = await self._sqlite_gate.run(
            _fetch_messages_from_storage,
            self.config.storage.db_path,
            self.target.tracked_user_ids,
            since,
            now,
            [self.target.target_chat_id],
        )
        if not messages:
            logger.info("No tracked messages since last summary.")
            return
        report = generate_report(
            messages,
            self.config,
            since,
            now,
            target=self.target,
            report_name=f"index_{self.target.target_chat_id}.html",
        )
        _purge_old_reports(
            self.config.reporting.reports_dir,
            self.config.reporting.retention_days,
        )
        if self._html_only:
            await self._send_html_report_only(messages, since, now, report)
        else:
            await _send_report_bundle(
                self.client,
                self.config,
                self.control,
                self.target,
                messages,
                since,
                now,
                report,
                tracker=self._tracker,
                bark_context=f"({_format_interval_label(self._interval_minutes)})",
                fallback_client=self._fallback_client,
            )

    async def _send_html_report_only(
        self,
        messages: Sequence[DbMessage],
        since: datetime,
        until: datetime,
        report_path: Path,
    ) -> None:
        """Send only the HTML report file (skip individual messages).

        Used in realtime mode where individual messages are already pushed
        by ``_RealtimePusher``.
        """
        skip_html = self.control.skip_html_report
        if skip_html:
            logger.info(
                "HTML report skipped for target '%s' (skip_html_report=true).",
                self.target.name,
            )
            return
        control_chat_id = self.control.control_chat_id
        if _topic_routing_enabled(self.control):
            await _send_topic_reports(
                self.client,
                self.config,
                self.control,
                self.target,
                messages,
                since,
                until,
                report_path.parent,
                fallback_client=self._fallback_client,
            )
        else:
            caption = _format_report_caption(
                "Report", len(messages), since, until, self.config,
            )
            await _send_file_with_fallback(
                self.client,
                self._fallback_client,
                control_chat_id,
                report_path,
                caption=caption,
            )
        if self._tracker:
            self._tracker.mark_activity()
        counts_text = _format_user_counts(messages, self.config, self.target)
        bark_context = f"({_format_interval_label(self._interval_minutes)})"
        title = f"Report Ready {bark_context}"
        body = counts_text or f"{len(messages)} messages"
        await send_bark_notification(
            self.config.notifications,
            title,
            body,
        )


class _HeartbeatLoop:

    def __init__(
        self,
        config: Config,
        client: TelegramClient,
        tracker: "_ActivityTracker",
        *,
        fallback_client: TelegramClient | None = None,
    ):
        self.config = config
        self.client = client
        self.tracker = tracker
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._fallback_client = fallback_client
        idle = config.notifications.heartbeat_interval_hours * 3600
        self._idle_seconds = idle
        self._check_interval = min(300, idle // 4)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._check_interval
                )
            except asyncio.TimeoutError:
                await self._maybe_send_heartbeat()
            except asyncio.CancelledError:
                break

    async def _maybe_send_heartbeat(self) -> None:
        now = utc_now()
        if not self.tracker.should_send_heartbeat(now, self._idle_seconds):
            return
        lang = self.config.effective_language
        if lang == "zh":
            msg_text = "\u76d1\u63a7\u4ecd\u5728\u8fd0\u884c\u4e2d"
            bark_title = "\u76d1\u63a7\u5fc3\u8df3"
        else:
            msg_text = "Watcher is still running"
            bark_title = "Watcher heartbeat"
        try:
            for control in self.config.control_groups.values():
                await _send_message_with_fallback(
                    self.client,
                    self._fallback_client,
                    control.control_chat_id,
                    msg_text,
                )
            self.tracker.mark_heartbeat(now)
            await send_bark_notification(
                self.config.notifications,
                bark_title,
                msg_text,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to send heartbeat: %s", exc)


class _UpdateCheckLoop:
    _CHECK_INTERVAL = 24 * 60 * 60  # 24 hours

    def __init__(
        self,
        config: Config,
        client: TelegramClient,
        *,
        fallback_client: TelegramClient | None = None,
    ):
        self.config = config
        self.client = client
        self._fallback_client = fallback_client
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        # Check immediately on startup
        await self._check()
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._CHECK_INTERVAL)
                break  # stop was set
            except asyncio.TimeoutError:
                await self._check()

    async def _check(self) -> None:
        try:
            from .update_checker import (
                check_for_update,
                should_notify,
                record_notification,
                format_notification,
                get_current_version,
            )

            current = get_current_version()
            update = await check_for_update(current)
            if update is None:
                return
            data_dir = self.config.storage.db_path.parent
            if not should_notify(data_dir, update.latest_version):
                return
            lang = self.config.effective_language
            msg = format_notification(update, lang)
            for control in self.config.control_groups.values():
                await _send_message_with_fallback(
                    self.client,
                    self._fallback_client,
                    control.control_chat_id,
                    msg,
                )
            record_notification(data_dir, update.latest_version)
            logger.info("Update notification sent for v%s", update.latest_version)
        except Exception:
            logger.debug("Update check failed; will retry next cycle.", exc_info=True)


class _ActivityTracker:
    def __init__(self) -> None:
        now = utc_now()
        self.last_activity = now
        self.last_heartbeat_sent: datetime | None = None

    def mark_activity(self) -> None:
        self.last_activity = utc_now()
        self.last_heartbeat_sent = None

    def should_send_heartbeat(self, now: datetime, idle_seconds: int) -> bool:
        if (now - self.last_activity) < timedelta(seconds=idle_seconds):
            return False
        if self.last_heartbeat_sent is None:
            return True
        return (now - self.last_heartbeat_sent) >= timedelta(seconds=idle_seconds)

    def mark_heartbeat(self, when: datetime) -> None:
        self.last_heartbeat_sent = when


async def _push_once_reports(
    client: TelegramClient,
    config: Config,
    targets: Sequence[TargetGroupConfig],
    stored_by_target: dict[str, list[DbMessage]],
    since: datetime,
    until: datetime,
    report_paths: Sequence[Path],
    *,
    bark_context: str | None = None,
    fallback_client: TelegramClient | None = None,
) -> None:
    for target, report_path in zip(targets, report_paths):
        control = config.control_groups[target.control_group or ""]
        messages = stored_by_target.get(target.name, [])
        await _send_report_bundle(
            client,
            config,
            control,
            target,
            messages,
            since,
            until,
            report_path,
            bark_context=bark_context,
            fallback_client=fallback_client,
        )


T = TypeVar("T")


async def _send_report_bundle(
    client: TelegramClient,
    config: Config,
    control: ControlGroupConfig,
    target: TargetGroupConfig,
    messages: Sequence[DbMessage],
    since: datetime,
    until: datetime | None,
    report_path: Path,
    tracker: "_ActivityTracker | None" = None,
    bark_context: str | None = None,
    fallback_client: TelegramClient | None = None,
) -> None:
    control_chat_id = control.control_chat_id
    skip_html = control.skip_html_report
    if _topic_routing_enabled(control):
        if not skip_html:
            await _send_topic_reports(
                client,
                config,
                control,
                target,
                messages,
                since,
                until,
                report_path.parent,
                fallback_client=fallback_client,
            )
        await _send_messages_to_control(
            client,
            config,
            control,
            target,
            messages,
            fallback_client=fallback_client,
        )
    else:
        if not skip_html:
            caption = _format_report_caption("Report", len(messages), since, until, config)
            await _send_file_with_fallback(
                client,
                fallback_client,
                control_chat_id,
                report_path,
                caption=caption,
            )
        await _send_messages_to_control(
            client,
            config,
            control,
            target,
            messages,
            fallback_client=fallback_client,
        )
    if tracker:
        tracker.mark_activity()
    counts_text = _format_user_counts(messages, config, target)
    title = "Report Ready"
    if bark_context:
        title = f"{title} {bark_context}"
    body = counts_text or f"{len(messages)} messages"
    await send_bark_notification(
        config.notifications,
        title,
        body,
    )


async def _send_messages_to_control(
    client: TelegramClient,
    config: Config,
    control: ControlGroupConfig,
    target: TargetGroupConfig,
    messages: Sequence[DbMessage],
    *,
    fallback_client: TelegramClient | None = None,
) -> None:
    for message in messages:
        reply_to = _topic_reply_id_for_message(control, target.target_chat_id, message)
        text = _format_control_message(message, config, target)
        await _send_message_with_fallback(
            client,
            fallback_client,
            control.control_chat_id,
            text,
            parse_mode="html",
            reply_to=reply_to,
        )
        await _send_media_for_message(
            client,
            control.control_chat_id,
            message,
            config,
            target,
            reply_to=reply_to,
            fallback_client=fallback_client,
        )


async def _send_media_for_message(
    client: TelegramClient,
    control_chat_id: int,
    message: DbMessage,
    config: Config,
    target: TargetGroupConfig,
    reply_to: int | None,
    *,
    fallback_client: TelegramClient | None = None,
) -> None:
    if not message.media:
        return
    sender_label = config.format_user_label(message.sender_id, target=target)
    for media in message.media:
        file_path = Path(media.file_path)
        if not file_path.exists():
            logger.warning("Media file missing on disk: %s", file_path)
            continue
        if media.is_reply:
            reply_label = (
                config.format_user_label(message.replied_sender_id, target=target)
                if message.replied_sender_id
                else "unknown"
            )
            caption = (
                f"Reply media for message #{message.message_id}\n"
                f"Original sender: {reply_label}"
            )
        else:
            caption = f"Media for {sender_label} — message #{message.message_id}"
        await _send_file_with_fallback(
            client,
            fallback_client,
            control_chat_id,
            file_path,
            caption=caption,
            reply_to=reply_to,
        )


def _format_head_normal(label_html: str, time_line: str, body_html: str) -> list[str]:
    return [
        label_html,
        time_line,
        f"<b>Content:</b> {body_html}",
    ]


def _format_head_minimal(label_html: str, time_line: str, body_html: str) -> list[str]:
    return [
        f"{label_html}: {body_html}",
        time_line,
    ]


def _format_control_message(
    message: DbMessage,
    config: Config,
    target: TargetGroupConfig,
) -> str:
    label = config.format_user_label(message.sender_id, target=target)
    local_ts = _format_timestamp_local(message.date, config)
    msg_link = build_message_link(message.chat_id, message.message_id)
    msg_label_text = f"MSG {message.message_id}" if message.message_id else "MSG"
    if msg_link:
        msg_label = f"<a href=\"{escape(msg_link)}\">{escape(msg_label_text)}</a>"
    else:
        msg_label = escape(msg_label_text)
    label_html = f"<b>{escape(label)}</b>"
    time_line = f"Time: {escape(local_ts)} — {msg_label}"
    body_html = escape(message.text) if message.text else "<i>no text</i>"
    if config.display.template == "minimal":
        lines = _format_head_minimal(label_html, time_line, body_html)
    else:
        lines = _format_head_normal(label_html, time_line, body_html)
    regular_media = sum(1 for media in message.media if not media.is_reply)
    reply_media = sum(1 for media in message.media if media.is_reply)
    if regular_media:
        lines.append(f"Attachments: {regular_media} file(s) to follow.")
    if reply_media:
        lines.append(f"Reply attachments: {reply_media} file(s) to follow.")
    if message.replied_sender_id:
        reply_label = config.format_user_label(message.replied_sender_id, target=target)
        reply_line = f"↩ Reply to {escape(reply_label)}"
        if message.replied_date:
            reply_line += f" at {escape(_format_timestamp_local(message.replied_date, config))}"
        raw_reply_text = (message.replied_text or "").lstrip("\n\r")
        reply_text = escape(raw_reply_text) if raw_reply_text else "<i>no text</i>"
        lines.append(f"<blockquote>{reply_line}</blockquote>")
        lines.append(f"<blockquote>{reply_text}</blockquote>")
    return "\n".join(lines)


def _topic_reply_id_for_message(
    control: ControlGroupConfig,
    target_chat_id: int,
    message: DbMessage,
) -> int | None:
    if not (control.is_forum and control.topic_routing_enabled):
        return None
    topic_id = control.topic_target_map.get(target_chat_id, {}).get(message.sender_id)
    if not topic_id or topic_id == 1:
        return None
    return topic_id


def _topic_routing_enabled(control: ControlGroupConfig) -> bool:
    return bool(control.is_forum and control.topic_routing_enabled)


def _topic_reply_id_for_user(
    control: ControlGroupConfig, target_chat_id: int, user_id: int
) -> int | None:
    topic_id = control.topic_target_map.get(target_chat_id, {}).get(user_id)
    if not topic_id or topic_id == 1:
        return None
    return topic_id


async def _send_topic_reports(
    client: TelegramClient,
    config: Config,
    control: ControlGroupConfig,
    target: TargetGroupConfig,
    messages: Sequence[DbMessage],
    since: datetime,
    until: datetime | None,
    report_dir: Path,
    *,
    fallback_client: TelegramClient | None = None,
) -> None:
    grouped: dict[int, list[DbMessage]] = {}
    for message in messages:
        grouped.setdefault(message.sender_id, []).append(message)
    for user_id, items in grouped.items():
        label = config.format_user_label(user_id, target=target)
        report_name = f"index_{target.target_chat_id}_{user_id}.html"
        report_path = generate_report(
            items,
            config,
            since,
            until,
            target=target,
            report_dir=report_dir,
            report_name=report_name,
        )
        caption = _format_report_caption(label, len(items), since, until, config)
        reply_to = _topic_reply_id_for_user(control, target.target_chat_id, user_id)
        await _send_file_with_fallback(
            client,
            fallback_client,
            control.control_chat_id,
            report_path,
            caption=caption,
            reply_to=reply_to,
        )


def _format_user_counts(
    messages: Sequence[DbMessage],
    config: Config,
    target: TargetGroupConfig,
) -> str:
    if not messages:
        return ""
    counter: dict[int, int] = {}
    for msg in messages:
        counter[msg.sender_id] = counter.get(msg.sender_id, 0) + 1
    parts = []
    for user_id, count in counter.items():
        label = config.format_user_label(
            user_id,
            include_id=config.display.show_ids,
            target=target,
        )
        suffix = "message" if count == 1 else "messages"
        parts.append(f"{label} {count} {suffix}")
    return ", ".join(parts)


def _format_report_caption(
    label: str,
    count: int,
    since: datetime,
    until: datetime | None,
    config: Config,
) -> str:
    """Build a concise two-line caption for report files sent to the control chat."""
    since_str = _format_timestamp_local(since, config)
    if until is None:
        until_str = "now"
    else:
        since_local = since.astimezone(config.reporting.timezone)
        until_local = until.astimezone(config.reporting.timezone)
        if since_local.date() == until_local.date():
            # Same day — show only the time portion for the end.
            fmt = config.display.time_format or DEFAULT_TIME_FORMAT
            # Strip date codes and leading separators to get time-only format.
            time_fmt = _extract_time_format(fmt)
            try:
                until_str = until_local.strftime(time_fmt)
            except Exception:  # pragma: no cover
                until_str = _format_timestamp_local(until, config)
        else:
            until_str = _format_timestamp_local(until, config)
    return f"\U0001f4cb {label} \u2014 {count} messages\n{since_str} \u2192 {until_str}"


def _extract_time_format(fmt: str) -> str:
    """Extract the time-only portion from a strftime format string.

    Heuristic: the time part starts at the first ``%H``, ``%I``, or ``%-H``
    token.  Everything before that (date codes and separators) is stripped.
    If no time code is found, return the full format as a fallback.
    """
    for marker in ("%H", "%I", "%-H"):
        idx = fmt.find(marker)
        if idx != -1:
            return fmt[idx:].strip()
    return fmt


def _format_timestamp_local(dt: datetime, config: Config) -> str:
    local = dt.astimezone(config.reporting.timezone)
    fmt = config.display.time_format or DEFAULT_TIME_FORMAT
    try:
        return local.strftime(fmt)
    except Exception:  # pragma: no cover - fallback for invalid format
        return local.strftime(DEFAULT_TIME_FORMAT)


def _offset_label(offset: timedelta | None) -> str:
    if offset is None:
        return "UTC"
    total_minutes = int(offset.total_seconds() // 60)
    hours, minutes = divmod(abs(total_minutes), 60)
    sign = "+" if total_minutes >= 0 else "-"
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _format_interval_label(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours}H"
    return f"{minutes}M"


async def _with_floodwait(
    func: Callable[..., Awaitable[T]],
    *args,
    on_flood_wait: Callable[[int], float] | None = None,
    **kwargs,
) -> T:
    while True:
        try:
            return await func(*args, **kwargs)
        except errors.FloodWaitError as exc:
            wait_for = exc.seconds + 1
            if on_flood_wait is not None:
                adjusted = on_flood_wait(exc.seconds)
                if isinstance(adjusted, (int, float)) and adjusted > wait_for:
                    wait_for = adjusted
            logger.warning("FloodWait: sleeping for %ss", wait_for)
            await asyncio.sleep(wait_for)


async def _send_with_backoff(
    client: TelegramClient,
    entity: int | str,
    message: str,
    on_flood_wait: Callable[[int], float] | None = None,
    **kwargs,
) -> None:
    target = await _resolve_entity(client, entity)
    await _with_floodwait(client.send_message, target, message, on_flood_wait=on_flood_wait, **kwargs)


async def _send_file_with_backoff(
    client: TelegramClient,
    entity: int | str,
    file_path: Path,
    on_flood_wait: Callable[[int], float] | None = None,
    **kwargs,
) -> None:
    target = await _resolve_entity(client, entity)
    await _with_floodwait(client.send_file, target, file=file_path, on_flood_wait=on_flood_wait, **kwargs)


async def _send_message_with_fallback(
    client: TelegramClient,
    fallback_client: TelegramClient | None,
    entity: int | str,
    message: str,
    on_flood_wait: Callable[[int], float] | None = None,
    **kwargs,
) -> None:
    try:
        await _send_with_backoff(client, entity, message, on_flood_wait=on_flood_wait, **kwargs)
        _mark_sender_fallback_recovered(client, entity)
        return
    except Exception as exc:
        if fallback_client is None or fallback_client is client:
            raise
        logger.warning("Sender failed to send message; reconnecting sender before fallback: %s", exc)
        try:
            await _reconnect_send_client(client)
            await _send_with_backoff(client, entity, message, on_flood_wait=on_flood_wait, **kwargs)
            _mark_sender_fallback_recovered(client, entity)
            return
        except Exception as retry_exc:
            logger.warning("Sender reconnect/retry failed for message; retrying with primary: %s", retry_exc)
    await _send_with_backoff(fallback_client, entity, message, on_flood_wait=on_flood_wait, **kwargs)
    await _send_sender_fallback_alert(client, fallback_client, entity, on_flood_wait=on_flood_wait)


async def _send_file_with_fallback(
    client: TelegramClient,
    fallback_client: TelegramClient | None,
    entity: int | str,
    file_path: Path,
    on_flood_wait: Callable[[int], float] | None = None,
    **kwargs,
) -> None:
    try:
        await _send_file_with_backoff(client, entity, file_path, on_flood_wait=on_flood_wait, **kwargs)
        _mark_sender_fallback_recovered(client, entity)
        return
    except Exception as exc:
        if fallback_client is None or fallback_client is client:
            raise
        logger.warning("Sender failed to send file; reconnecting sender before fallback: %s", exc)
        try:
            await _reconnect_send_client(client)
            await _send_file_with_backoff(client, entity, file_path, on_flood_wait=on_flood_wait, **kwargs)
            _mark_sender_fallback_recovered(client, entity)
            return
        except Exception as retry_exc:
            logger.warning("Sender reconnect/retry failed for file; retrying with primary: %s", retry_exc)
    await _send_file_with_backoff(fallback_client, entity, file_path, on_flood_wait=on_flood_wait, **kwargs)
    await _send_sender_fallback_alert(client, fallback_client, entity, on_flood_wait=on_flood_wait)


async def _reconnect_send_client(client: TelegramClient) -> None:
    connect = getattr(client, "connect", None)
    if connect is None:
        return
    await connect()


def _mark_sender_fallback_recovered(client: TelegramClient, entity: int | str) -> None:
    alerted = getattr(client, "_tgwatch_sender_fallback_alert_sent", None)
    if isinstance(alerted, set):
        alerted.discard(_sender_fallback_alert_key(entity))


async def _send_sender_fallback_alert(
    sender_client: TelegramClient,
    fallback_client: TelegramClient,
    entity: int | str,
    *,
    on_flood_wait: Callable[[int], float] | None = None,
) -> None:
    alert_key = _sender_fallback_alert_key(entity)
    alerted = getattr(sender_client, "_tgwatch_sender_fallback_alert_sent", None)
    if not isinstance(alerted, set):
        alerted = set()
        setattr(sender_client, "_tgwatch_sender_fallback_alert_sent", alerted)
    if alert_key in alerted:
        return
    try:
        await _send_with_backoff(
            fallback_client,
            entity,
            _SENDER_FALLBACK_ALERT,
            on_flood_wait=on_flood_wait,
        )
        alerted.add(alert_key)
    except Exception as alert_exc:
        logger.warning("Failed to send sender fallback alert: %s", alert_exc)


def _sender_fallback_alert_key(entity: int | str) -> str:
    return f"{type(entity).__name__}:{entity}"


async def _resolve_entity(
    client: TelegramClient,
    entity: int | str,
) -> object:
    if isinstance(entity, int):
        self_id = await _get_self_id(client)
        if entity == self_id:
            return await _with_floodwait(client.get_input_entity, "me")
    return await _with_floodwait(client.get_input_entity, entity)


async def _get_self_id(client: TelegramClient) -> int:
    cached = getattr(client, "_tgwatch_self_id", None)
    if cached is not None:
        return cached
    me = await _with_floodwait(client.get_me)
    cached = int(getattr(me, "id"))
    setattr(client, "_tgwatch_self_id", cached)
    return cached


async def _reply(
    event: events.NewMessage.Event,
    text: str,
    *,
    client: TelegramClient | None = None,
    fallback_client: TelegramClient | None = None,
) -> None:
    chat_id = int(getattr(event.message, "chat_id", event.chat_id))
    send_client = client or event.client
    await _send_message_with_fallback(
        send_client,
        fallback_client,
        chat_id,
        text,
        reply_to=event.message.id,
    )


def _purge_old_reports(report_dir: Path, retention_days: int) -> None:
    if retention_days <= 0:
        return
    if not report_dir.exists():
        return
    cutoff = (utc_now() - timedelta(days=retention_days)).date()
    for entry in report_dir.iterdir():
        if not entry.is_dir():
            continue
        try:
            folder_date = datetime.strptime(entry.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if folder_date <= cutoff:
            logger.info("Removing expired reports: %s", entry)
            shutil.rmtree(entry, ignore_errors=True)


async def _send_error_notification(
    client: TelegramClient,
    config: Config,
    exc: Exception,
    *,
    fallback_client: TelegramClient | None = None,
) -> None:
    summary = "".join(
        traceback.format_exception_only(type(exc), exc)
    ).strip()
    message = (
        "Watcher encountered an error and will stop:\n"
        f"{summary}"
    )
    try:
        for control in config.control_groups.values():
            await _send_message_with_fallback(
                client,
                fallback_client,
                control.control_chat_id,
                message,
            )
        await send_bark_notification(
            config.notifications,
            "Watcher error",
            summary,
        )
    except Exception as notify_exc:  # pragma: no cover
        logger.warning("Failed to send error notification: %s", notify_exc)
