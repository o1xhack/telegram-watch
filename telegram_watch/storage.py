"""SQLite storage helpers."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator, Sequence


@dataclass
class StoredMedia:
    chat_id: int
    message_id: int
    file_path: str
    mime_type: str | None
    file_size: int | None
    media_index: int


@dataclass
class StoredMessage:
    chat_id: int
    message_id: int
    sender_id: int
    date: datetime
    text: str | None
    reply_to_msg_id: int | None
    replied_sender_id: int | None
    replied_date: datetime | None
    replied_text: str | None


@dataclass
class DbMedia:
    media_index: int
    file_path: str
    mime_type: str | None
    file_size: int | None


@dataclass
class DbMessage:
    chat_id: int
    message_id: int
    sender_id: int
    date: datetime
    text: str | None
    reply_to_msg_id: int | None
    replied_sender_id: int | None
    replied_date: datetime | None
    replied_text: str | None
    media: list[DbMedia]


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS messages (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            text TEXT,
            reply_to_msg_id INTEGER,
            replied_sender_id INTEGER,
            replied_date TEXT,
            replied_text TEXT,
            PRIMARY KEY (chat_id, message_id)
        );

        CREATE TABLE IF NOT EXISTS media (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            media_index INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            mime_type TEXT,
            file_size INTEGER,
            PRIMARY KEY (chat_id, message_id, media_index),
            FOREIGN KEY (chat_id, message_id) REFERENCES messages(chat_id, message_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_sender_date
            ON messages(sender_id, date);
        CREATE INDEX IF NOT EXISTS idx_messages_date
            ON messages(date);
        """
    )


def persist_message(
    conn: sqlite3.Connection,
    message: StoredMessage,
    media_items: Sequence[StoredMedia],
) -> None:
    values = (
        message.chat_id,
        message.message_id,
        message.sender_id,
        _serialize_dt(message.date),
        message.text,
        message.reply_to_msg_id,
        message.replied_sender_id,
        _serialize_dt(message.replied_date) if message.replied_date else None,
        message.replied_text,
    )
    with conn:
        conn.execute(
            """
            INSERT INTO messages (
                chat_id, message_id, sender_id, date, text,
                reply_to_msg_id, replied_sender_id, replied_date, replied_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                sender_id=excluded.sender_id,
                date=excluded.date,
                text=excluded.text,
                reply_to_msg_id=excluded.reply_to_msg_id,
                replied_sender_id=excluded.replied_sender_id,
                replied_date=excluded.replied_date,
                replied_text=excluded.replied_text
            """,
            values,
        )
        conn.execute(
            "DELETE FROM media WHERE chat_id = ? AND message_id = ?",
            (message.chat_id, message.message_id),
        )
        for media in media_items:
            conn.execute(
                """
                INSERT INTO media (
                    chat_id, message_id, media_index, file_path, mime_type, file_size
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    media.chat_id,
                    media.message_id,
                    media.media_index,
                    media.file_path,
                    media.mime_type,
                    media.file_size,
                ),
            )


def fetch_messages_between(
    conn: sqlite3.Connection,
    sender_ids: Iterable[int],
    since: datetime,
    until: datetime | None,
) -> list[DbMessage]:
    sender_ids = tuple(sender_ids)
    placeholders = ",".join("?" for _ in sender_ids)
    if not placeholders:
        return []
    params: list[object] = list(sender_ids)
    query = """
        SELECT *
        FROM messages
        WHERE sender_id IN ({senders})
          AND date >= ?
    """
    params.append(_serialize_dt(since))
    if until:
        query += " AND date <= ?"
        params.append(_serialize_dt(until))
    query += " ORDER BY date ASC"
    rows = conn.execute(query.format(senders=placeholders), params).fetchall()
    messages = [_row_to_db_message(row) for row in rows]
    _attach_media(conn, messages)
    return messages


def fetch_recent_messages(
    conn: sqlite3.Connection,
    sender_id: int,
    limit: int,
) -> list[DbMessage]:
    rows = conn.execute(
        """
        SELECT * FROM messages
        WHERE sender_id = ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (sender_id, limit),
    ).fetchall()
    messages = [_row_to_db_message(row) for row in rows]
    _attach_media(conn, messages)
    return list(reversed(messages))


def fetch_summary_counts(
    conn: sqlite3.Connection,
    sender_ids: Iterable[int],
    since: datetime,
) -> dict[int, int]:
    sender_ids = tuple(sender_ids)
    placeholders = ",".join("?" for _ in sender_ids)
    if not placeholders:
        return {}
    params: list[object] = list(sender_ids)
    params.append(_serialize_dt(since))
    rows = conn.execute(
        f"""
        SELECT sender_id, COUNT(*) as cnt
        FROM messages
        WHERE sender_id IN ({placeholders})
          AND date >= ?
        GROUP BY sender_id
        """,
        params,
    ).fetchall()
    return {int(row["sender_id"]): int(row["cnt"]) for row in rows}


def _attach_media(conn: sqlite3.Connection, messages: list[DbMessage]) -> None:
    if not messages:
        return
    key_pairs = [(msg.chat_id, msg.message_id) for msg in messages]
    placeholders = ",".join("(?, ?)" for _ in key_pairs)
    params: list[object] = []
    for chat_id, msg_id in key_pairs:
        params.extend([chat_id, msg_id])
    rows = conn.execute(
        f"""
        SELECT *
        FROM media
        WHERE (chat_id, message_id) IN (VALUES {placeholders})
        ORDER BY media_index ASC
        """,
        params,
    ).fetchall()
    media_by_key: dict[tuple[int, int], list[DbMedia]] = {}
    for row in rows:
        key = (int(row["chat_id"]), int(row["message_id"]))
        media = DbMedia(
            media_index=int(row["media_index"]),
            file_path=row["file_path"],
            mime_type=row["mime_type"],
            file_size=row["file_size"],
        )
        media_by_key.setdefault(key, []).append(media)
    for message in messages:
        message.media = media_by_key.get((message.chat_id, message.message_id), [])


def _row_to_db_message(row: sqlite3.Row) -> DbMessage:
    return DbMessage(
        chat_id=int(row["chat_id"]),
        message_id=int(row["message_id"]),
        sender_id=int(row["sender_id"]),
        date=_deserialize_dt(row["date"]),
        text=row["text"],
        reply_to_msg_id=row["reply_to_msg_id"],
        replied_sender_id=row["replied_sender_id"],
        replied_date=_deserialize_dt(row["replied_date"]) if row["replied_date"] else None,
        replied_text=row["replied_text"],
        media=[],
    )


def _serialize_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _deserialize_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


@contextmanager
def db_session(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        yield conn
    finally:
        conn.close()
