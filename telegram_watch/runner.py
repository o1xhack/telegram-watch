"""Async runners for `once` and `run` commands."""

from __future__ import annotations

import asyncio
import logging
import shutil
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Awaitable, Callable, Sequence, TypeVar

from telethon import TelegramClient, events, errors
from telethon.tl.custom import message as custom_message

from .config import (
    Config,
    ControlGroupConfig,
    DEFAULT_TIME_FORMAT,
    TargetGroupConfig,
)
from .links import build_message_link
from .notifications import send_bark_notification
from .reporting import generate_report
from .storage import (
    DbMessage,
    StoredMedia,
    StoredMessage,
    db_session,
    fetch_messages_between,
    fetch_recent_messages,
    fetch_summary_counts,
    persist_message,
)
from .timeutils import parse_since_spec, utc_now

logger = logging.getLogger(__name__)


def _role_label(role: str) -> str:
    if role == "primary":
        return "primary account (A)"
    if role == "sender":
        return "sender account (B)"
    return "account"


def _phone_prompt(role: str) -> str:
    label = _role_label(role)
    print(f"Next: log in {label}.")
    return input(f"{label} phone (or bot token): ")


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
    for target in targets:
        report_path = generate_report(
            stored_by_target.get(target.name, []),
            config,
            since,
            until,
            target=target,
        )
        report_paths.append(report_path)
    if push:
        sender_client = await _start_sender_client(config)
        send_client = sender_client
        sender_active = sender_client is not None
        if send_client is None:
            send_client = _build_client(config)
            await _start_client(send_client, "primary")
        try:
            await _push_once_reports(
                send_client,
                config,
                stored_by_target,
                since,
                until,
                report_paths,
                bark_context=(f"(since {since_label})" if since_label else None),
            )
        except Exception:
            if sender_active:
                logger.warning("Sender account failed; retrying report push with primary account.")
                await send_client.disconnect()
                primary = _build_client(config)
                await primary.start()
                try:
                    await _push_once_reports(
                        primary,
                        config,
                        stored_by_target,
                        since,
                        until,
                        report_paths,
                        bark_context=(f"(since {since_label})" if since_label else None),
                    )
                finally:
                    await primary.disconnect()
                return report_paths
            raise
        finally:
            await send_client.disconnect()
    return report_paths


async def run_daemon(config: Config) -> None:
    _purge_old_reports(
        config.reporting.reports_dir,
        config.reporting.retention_days,
    )
    """Run watcher daemon."""
    client = _build_client(config)
    activity_tracker = _ActivityTracker()
    await _start_client(client, "primary")
    sender_client = await _start_sender_client(config)
    send_client = sender_client or client
    fallback_client = client if sender_client else None
    me = await client.get_me()
    self_user_id = int(me.id)
    logger.info("Logged in as %s", getattr(me, "username", self_user_id))

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
        )
        loop.start()
        summary_loops.append(loop)

    heartbeat_loop = _HeartbeatLoop(config, send_client, activity_tracker, fallback_client=fallback_client)
    control_handler = _ControlHandler(
        config,
        client,
        send_client,
        self_user_id,
        activity_tracker,
        fallback_client=fallback_client,
    )

    for target in config.targets:
        target_handler = _TargetHandler(config, client, target)
        client.add_event_handler(
            target_handler.handle,
            events.NewMessage(chats=[target.target_chat_id]),
        )
    client.add_event_handler(
        control_handler.handle,
        events.NewMessage(chats=list(config.control_by_chat_id.keys())),
    )

    heartbeat_loop.start()
    try:
        await client.run_until_disconnected()
    except Exception as exc:
        await _send_error_notification(send_client, config, exc, fallback_client=fallback_client)
        raise
    finally:
        await heartbeat_loop.stop()
        for loop in summary_loops:
            await loop.stop()
        if sender_client:
            await sender_client.disconnect()
        await client.disconnect()


def _build_client(config: Config) -> TelegramClient:
    session_path = config.telegram.session_file
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(session_path),
        config.telegram.api_id,
        config.telegram.api_hash,
    )


def _build_sender_client(config: Config) -> TelegramClient | None:
    if config.sender is None:
        return None
    session_path = config.sender.session_file
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(session_path),
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


async def _get_reply_snapshot(
    client: TelegramClient,
    media_dir: Path,
    message: custom_message.Message,
    chat_id: int,
) -> ReplySnapshot | None:
    if not message.is_reply:
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
    def __init__(self, config: Config, client: TelegramClient, target: TargetGroupConfig):
        self.config = config
        self.client = client
        self.target = target
        self._tracked = set(target.tracked_user_ids)

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
        with db_session(self.config.storage.db_path) as conn:
            persist_message(conn, message, media)
        logger.info(
            "Captured message %s from %s",
            message.message_id,
            self.config.describe_user(int(message.sender_id), target=self.target),
        )


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
    ):
        self.config = config
        self.client = client
        self.send_client = send_client
        self.owner_id = owner_id
        self._tracker = tracker
        self._fallback_client = fallback_client

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
        with db_session(self.config.storage.db_path) as conn:
            messages = fetch_recent_messages(conn, user_id, limit, chat_ids=chat_ids)
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
        with db_session(self.config.storage.db_path) as conn:
            counts = fetch_summary_counts(
                conn,
                _tracked_ids_for_targets(targets),
                since,
                chat_ids=chat_ids,
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
        with db_session(self.config.storage.db_path) as conn:
            for target in targets:
                messages = fetch_messages_between(
                    conn,
                    target.tracked_user_ids,
                    since,
                    until,
                    chat_ids=[target.target_chat_id],
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
        interval = self.target.summary_interval_minutes * 60
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                await self._send_summary()
            except asyncio.CancelledError:
                break

    async def _send_summary(self) -> None:
        now = utc_now()
        since = self._last_summary
        self._last_summary = now
        with db_session(self.config.storage.db_path) as conn:
            messages = fetch_messages_between(
                conn,
                self.target.tracked_user_ids,
                since,
                now,
                chat_ids=[self.target.target_chat_id],
            )
        if not messages:
            logger.info("No tracked messages since last summary.")
            return
        report = generate_report(messages, self.config, since, now, target=self.target)
        _purge_old_reports(
            self.config.reporting.reports_dir,
            self.config.reporting.retention_days,
        )
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
            bark_context=f"({_format_interval_label(self.target.summary_interval_minutes)})",
            fallback_client=self._fallback_client,
        )


class _HeartbeatLoop:
    _CHECK_INTERVAL = 300  # seconds
    _IDLE_SECONDS = 2 * 60 * 60

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
                    self._stop.wait(), timeout=self._CHECK_INTERVAL
                )
            except asyncio.TimeoutError:
                await self._maybe_send_heartbeat()
            except asyncio.CancelledError:
                break

    async def _maybe_send_heartbeat(self) -> None:
        now = utc_now()
        if not self.tracker.should_send_heartbeat(now, self._IDLE_SECONDS):
            return
        try:
            for control in self.config.control_groups.values():
                await _send_message_with_fallback(
                    self.client,
                    self._fallback_client,
                    control.control_chat_id,
                    "Watcher is still running",
                )
            self.tracker.mark_heartbeat(now)
            await send_bark_notification(
                self.config.notifications,
                "Watcher heartbeat",
                "Watcher is still running",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to send heartbeat: %s", exc)


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
    stored_by_target: dict[str, list[DbMessage]],
    since: datetime,
    until: datetime,
    report_paths: Sequence[Path],
    *,
    bark_context: str | None = None,
    fallback_client: TelegramClient | None = None,
) -> None:
    for target, report_path in zip(config.targets, report_paths):
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
    window = f"{since.isoformat()} → {(until.isoformat() if until else 'now')}"
    control_chat_id = control.control_chat_id
    if _topic_routing_enabled(control):
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
        caption = f"tgwatch report\nWindow: {window}\nMessages: {len(messages)}"
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
                config.format_user_label(message.replied_sender_id)
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
    lines = [
        f"<b>{escape(label)}</b>",
        f"Time: {escape(local_ts)} — {msg_label}",
    ]
    body_text = escape(message.text) if message.text else "<i>no text</i>"
    lines.append(f"<b>Content:</b> {body_text}")
    quote_blocks: list[str] = []
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
        quote_blocks.append(f"<blockquote>{reply_line}</blockquote>")
        quote_blocks.append(f"<blockquote>{reply_text}</blockquote>")
    lines.extend(quote_blocks)
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
    window = f"{since.isoformat()} → {(until.isoformat() if until else 'now')}"
    for user_id, items in grouped.items():
        label = config.format_user_label(user_id, target=target)
        report_name = f"index_{user_id}.html"
        report_path = generate_report(
            items,
            config,
            since,
            until,
            target=target,
            report_dir=report_dir,
            report_name=report_name,
        )
        caption = (
            "tgwatch report\n"
            f"User: {label}\n"
            f"Window: {window}\n"
            f"Messages: {len(items)}"
        )
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
    **kwargs,
) -> T:
    while True:
        try:
            return await func(*args, **kwargs)
        except errors.FloodWaitError as exc:
            wait_for = exc.seconds + 1
            logger.warning("FloodWait: sleeping for %ss", wait_for)
            await asyncio.sleep(wait_for)


async def _send_with_backoff(
    client: TelegramClient,
    entity: int | str,
    message: str,
    **kwargs,
) -> None:
    target = await _resolve_entity(client, entity)
    await _with_floodwait(client.send_message, target, message, **kwargs)


async def _send_file_with_backoff(
    client: TelegramClient,
    entity: int | str,
    file_path: Path,
    **kwargs,
) -> None:
    target = await _resolve_entity(client, entity)
    await _with_floodwait(client.send_file, target, file=file_path, **kwargs)


async def _send_message_with_fallback(
    client: TelegramClient,
    fallback_client: TelegramClient | None,
    entity: int | str,
    message: str,
    **kwargs,
) -> None:
    try:
        await _send_with_backoff(client, entity, message, **kwargs)
        return
    except Exception as exc:
        if fallback_client is None or fallback_client is client:
            raise
        logger.warning("Sender failed to send message; retrying with primary: %s", exc)
    await _send_with_backoff(fallback_client, entity, message, **kwargs)


async def _send_file_with_fallback(
    client: TelegramClient,
    fallback_client: TelegramClient | None,
    entity: int | str,
    file_path: Path,
    **kwargs,
) -> None:
    try:
        await _send_file_with_backoff(client, entity, file_path, **kwargs)
        return
    except Exception as exc:
        if fallback_client is None or fallback_client is client:
            raise
        logger.warning("Sender failed to send file; retrying with primary: %s", exc)
    await _send_file_with_backoff(fallback_client, entity, file_path, **kwargs)


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
