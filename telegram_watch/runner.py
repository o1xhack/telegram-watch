"""Async runners for `once` and `run` commands."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Sequence, TypeVar

from telethon import TelegramClient, events, errors
from telethon.tl.custom import message as custom_message

from .config import Config
from .reporting import build_digest, generate_report
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


async def run_once(config: Config, since: datetime) -> Path:
    """Fetch messages for a window, store them, and return report path."""
    client = _build_client(config)
    await client.start()
    try:
        captures = await _collect_window(client, config, since)
    finally:
        await client.disconnect()
    until = utc_now()
    with db_session(config.storage.db_path) as conn:
        for message, media in captures:
            persist_message(conn, message, media)
        stored = fetch_messages_between(conn, config.target.tracked_user_ids, since, until)
    report_path = generate_report(stored, config, since, until)
    return report_path


async def run_daemon(config: Config) -> None:
    """Run watcher daemon."""
    client = _build_client(config)
    await client.start()
    me = await client.get_me()
    self_user_id = int(me.id)
    logger.info("Logged in as %s", getattr(me, "username", self_user_id))

    summary_loop = _SummaryLoop(config, client)
    target_handler = _TargetHandler(config, client)
    control_handler = _ControlHandler(config, client, self_user_id)

    client.add_event_handler(
        target_handler.handle,
        events.NewMessage(chats=[config.target.target_chat_id]),
    )
    client.add_event_handler(
        control_handler.handle,
        events.NewMessage(chats=[config.control.control_chat_id]),
    )

    summary_loop.start()
    try:
        await client.run_until_disconnected()
    finally:
        await summary_loop.stop()
        await client.disconnect()


def _build_client(config: Config) -> TelegramClient:
    session_path = config.telegram.session_file
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(session_path),
        config.telegram.api_id,
        config.telegram.api_hash,
    )


async def _collect_window(
    client: TelegramClient,
    config: Config,
    since: datetime,
) -> list[tuple[StoredMessage, list[StoredMedia]]]:
    tracked = set(config.target.tracked_user_ids)
    captures: list[tuple[StoredMessage, list[StoredMedia]]] = []
    async for msg in client.iter_messages(config.target.target_chat_id):
        if msg.date is None:
            continue
        msg_dt = _ensure_tz(msg.date)
        if msg_dt < since:
            break
        sender_id = getattr(msg, "sender_id", None)
        if sender_id is None or int(sender_id) not in tracked:
            continue
        capture = await _capture_message(client, config, msg)
        if capture:
            captures.append(capture)
    captures.reverse()
    return captures


async def _capture_message(
    client: TelegramClient,
    config: Config,
    message: custom_message.Message,
) -> tuple[StoredMessage, list[StoredMedia]] | None:
    sender_id = getattr(message, "sender_id", None)
    if sender_id is None:
        return None
    chat_id = int(getattr(message, "chat_id", config.target.target_chat_id))
    msg_dt = _ensure_tz(message.date)
    reply_info = await _get_reply_snapshot(message)
    media_items = await _download_media(client, config.storage.media_dir, message, chat_id)
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


async def _get_reply_snapshot(message: custom_message.Message) -> ReplySnapshot | None:
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
    return ReplySnapshot(
        sender_id=getattr(reply, "sender_id", None),
        text=text,
        date=_ensure_tz(reply.date) if reply.date else None,
    )


async def _download_media(
    client: TelegramClient,
    media_dir: Path,
    message: custom_message.Message,
    chat_id: int,
) -> list[StoredMedia]:
    if not message.media:
        return []
    target_dir = media_dir / str(chat_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"{message.id}"
    downloaded_path = await _with_floodwait(
        client.download_media,
        message,
        file=target_dir / base_name,
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
            message_id=int(message.id),
            file_path=str(path),
            mime_type=mime,
            file_size=stat.st_size,
            media_index=0,
        )
    ]


def _ensure_tz(dt: datetime) -> datetime:
    if dt.tzinfo:
        return dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=timezone.utc)


class _TargetHandler:
    def __init__(self, config: Config, client: TelegramClient):
        self.config = config
        self.client = client
        self._tracked = set(config.target.tracked_user_ids)

    async def handle(self, event: events.NewMessage.Event) -> None:
        msg = event.message
        sender_id = getattr(msg, "sender_id", None)
        if sender_id is None or int(sender_id) not in self._tracked:
            return
        capture = await _capture_message(self.client, self.config, msg)
        if not capture:
            return
        message, media = capture
        with db_session(self.config.storage.db_path) as conn:
            persist_message(conn, message, media)
        logger.info(
            "Captured message %s from %s", message.message_id, message.sender_id
        )


class _ControlHandler:
    def __init__(self, config: Config, client: TelegramClient, owner_id: int):
        self.config = config
        self.client = client
        self.owner_id = owner_id

    async def handle(self, event: events.NewMessage.Event) -> None:
        if int(getattr(event.message, "sender_id", 0)) != self.owner_id:
            return
        text = (event.message.raw_text or "").strip()
        if not text.startswith("/"):
            return
        parts = text.split()
        command = parts[0]
        if command == "/help":
            await _reply(event, _HELP_TEXT)
            return
        if command == "/last":
            await self._cmd_last(event, parts[1:])
            return
        if command == "/since":
            await self._cmd_since(event, parts[1:])
            return
        if command == "/export":
            await self._cmd_export(event, parts[1:])
            return
        await _reply(event, "Unknown command. Use /help")

    async def _cmd_last(self, event: events.NewMessage.Event, args: Sequence[str]) -> None:
        if not args:
            await _reply(event, "Usage: /last <user_id> [N]")
            return
        try:
            user_id = await self._resolve_user(args[0])
        except ValueError as exc:
            await _reply(event, f"Cannot resolve user: {exc}")
            return
        if user_id not in self.config.target.tracked_user_ids:
            await _reply(event, f"User {user_id} not in tracked list.")
            return
        try:
            limit = int(args[1]) if len(args) > 1 else 5
        except ValueError:
            await _reply(event, "Limit must be an integer.")
            return
        if limit <= 0:
            await _reply(event, "Limit must be > 0.")
            return
        with db_session(self.config.storage.db_path) as conn:
            messages = fetch_recent_messages(conn, user_id, limit)
        if not messages:
            await _reply(event, "No messages stored yet.")
            return
        lines = [f"Last {len(messages)} messages for {user_id}:"]
        for msg in messages:
            lines.append(_format_message_line(msg))
        await _reply(event, "\n".join(lines))

    async def _cmd_since(self, event: events.NewMessage.Event, args: Sequence[str]) -> None:
        if not args:
            await _reply(event, "Usage: /since <Nh|Nm|ISO>")
            return
        try:
            since = parse_since_spec(args[0], now=utc_now())
        except ValueError as exc:
            await _reply(event, str(exc))
            return
        with db_session(self.config.storage.db_path) as conn:
            counts = fetch_summary_counts(conn, self.config.target.tracked_user_ids, since)
        if not counts:
            await _reply(event, "No messages in that window.")
            return
        lines = [f"Summary since {since.isoformat()}"]
        for user_id in sorted(counts):
            lines.append(f"- {user_id}: {counts[user_id]} message(s)")
        await _reply(event, "\n".join(lines))

    async def _cmd_export(self, event: events.NewMessage.Event, args: Sequence[str]) -> None:
        if not args:
            await _reply(event, "Usage: /export <Nh|Nm|ISO>")
            return
        try:
            since = parse_since_spec(args[0], now=utc_now())
        except ValueError as exc:
            await _reply(event, str(exc))
            return
        until = utc_now()
        with db_session(self.config.storage.db_path) as conn:
            messages = fetch_messages_between(
                conn, self.config.target.tracked_user_ids, since, until
            )
        report = generate_report(messages, self.config, since, until)
        await _reply(event, f"Export ready: {report}")

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


_HELP_TEXT = (
    "Commands:\n"
    "/help - show this help\n"
    "/last <user_id|username> [N] - last N tracked messages\n"
    "/since <Nh|Nm|ISO> - summary counts from window\n"
    "/export <Nh|Nm|ISO> - generate report for window"
)


class _SummaryLoop:
    def __init__(self, config: Config, client: TelegramClient):
        self.config = config
        self.client = client
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_summary = utc_now()

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
        interval = self.config.reporting.summary_interval_minutes * 60
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
                conn, self.config.target.tracked_user_ids, since, now
            )
        if not messages:
            logger.info("No tracked messages since last summary.")
            return
        report = generate_report(messages, self.config, since, now)
        digest = build_digest(messages, since, now)
        await _send_with_backoff(
            self.client,
            self.config.control.control_chat_id,
            f"{digest}\nReport: {report}",
        )


T = TypeVar("T")


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
    await _with_floodwait(client.send_message, entity, message, **kwargs)


async def _reply(event: events.NewMessage.Event, text: str) -> None:
    chat_id = int(getattr(event.message, "chat_id", event.chat_id))
    await _send_with_backoff(
        event.client,
        chat_id,
        text,
        reply_to=event.message.id,
    )
