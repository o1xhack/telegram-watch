"""SQLite helpers for optional full-message archive storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3

REQUIRED_SHARD_INDEXES = (
    "idx_archive_messages_scope_date",
    "idx_archive_messages_chat_date",
    "idx_archive_messages_sender_date",
    "idx_archive_messages_tracked_ref",
    "idx_archive_tracked_links_tracked",
)
ADDITIVE_MANIFEST_TABLES = ("tracked_db_links",)
CORE_SHARD_TABLES = ("archive_messages", "archive_tracked_links")
ADDITIVE_SHARD_TABLES = ("archive_media", "archive_senders")
ARCHIVE_CONTEXT_MEDIA_ID_CHUNK_SIZE = 500
_ARCHIVE_GROUP_DIRECTORY_RE = re.compile(r"group_-?[1-9][0-9]*")
_ARCHIVE_SHARD_FILENAME_RE = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>0[1-9]|1[0-2])"
    r"(?:-(?P<sequence>[0-9]{3,}))?\.sqlite3"
)


@dataclass(frozen=True)
class ArchiveMessage:
    chat_id: int
    message_id: int
    topic_id: int | None
    sender_id: int | None
    date: datetime
    text: str | None
    raw_text: str | None
    message_kind: str
    reply_to_msg_id: int | None
    reply_to_top_id: int | None
    is_forum_topic_link: bool
    has_media: bool
    media: tuple["ArchiveMedia", ...] = ()


@dataclass(frozen=True)
class ArchiveMedia:
    media_index: int
    media_kind: str
    mime_type: str | None
    file_size: int | None
    file_name: str | None


@dataclass(frozen=True)
class ArchiveSender:
    sender_id: int
    username: str | None
    display_name: str | None
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class ArchiveSenderCandidate:
    sender_id: int
    chat_id: int
    message_id: int
    first_seen_at: datetime
    last_seen_at: datetime
    shard_paths: tuple[Path, ...]
    existing_sender: ArchiveSender | None = None


@dataclass(frozen=True)
class ArchiveShard:
    shard_id: str
    chat_id: int
    path: Path
    starts_at: datetime
    ends_at: datetime
    sequence: int


@dataclass(frozen=True)
class ArchiveMessagePersistResult:
    payload_mode: str
    created: bool


@dataclass
class DbArchiveMessage:
    chat_id: int
    message_id: int
    topic_id: int | None
    sender_id: int | None
    date: datetime
    text: str | None
    raw_text: str | None
    message_kind: str
    reply_to_msg_id: int | None
    reply_to_top_id: int | None
    is_forum_topic_link: bool
    has_media: bool
    tracked_db_path: str | None
    tracked_message_chat_id: int | None
    tracked_message_id: int | None
    payload_mode: str


@dataclass(frozen=True)
class ArchiveContextMessage:
    chat_id: int
    message_id: int
    topic_id: int | None
    sender_id: int | None
    date: datetime
    text: str | None
    effective_text: str | None
    payload_mode: str
    tracked_text: str | None
    tracked_replied_text: str | None
    tracked_row_found: bool
    tracked_db_matches_current: bool
    tracked_message_chat_id: int | None
    tracked_message_id: int | None
    reply_to_msg_id: int | None = None
    reply_to_top_id: int | None = None
    media: tuple[ArchiveMedia, ...] = ()
    sender: ArchiveSender | None = None


@dataclass(frozen=True)
class ArchiveContextResult:
    messages: tuple[ArchiveContextMessage, ...]
    skipped_shards: tuple[str, ...]
    errors: tuple[str, ...]
    target_archived: bool = False
    target_archived_topic_id: int | None = None


@dataclass(frozen=True)
class ArchiveShardStatus:
    shard_id: str
    chat_id: int
    path: Path
    exists: bool
    status: str
    manifest_message_count: int
    manifest_file_size_bytes: int
    actual_message_count: int
    archive_row_count: int
    tracked_ref_count: int
    link_count: int
    media_metadata_count: int
    actual_file_size_bytes: int
    missing_indexes: tuple[str, ...] = ()
    missing_schema_tables: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class ArchiveStatusReport:
    root_dir: Path
    manifest_path: Path
    manifest_exists: bool
    shard_count: int
    missing_shard_count: int
    manifest_message_count: int
    actual_message_count: int
    archive_row_count: int
    tracked_ref_count: int
    link_count: int
    media_metadata_count: int
    tracked_db_link_count: int
    file_size_bytes: int
    missing_index_count: int
    missing_schema_table_count: int
    errors: tuple[str, ...]
    shards: tuple[ArchiveShardStatus, ...]
    current_tracked_db_linked: bool | None = None
    current_tracked_db_readable: bool | None = None

    @property
    def degraded(self) -> bool:
        return bool(
            self.errors
            or self.missing_shard_count
            or self.missing_index_count
            or self.missing_schema_table_count
        )


@dataclass(frozen=True)
class ArchiveRepairReport:
    root_dir: Path
    manifest_path: Path
    manifest_exists: bool
    dry_run: bool
    checked_shards: int
    repaired_shards: int
    repaired_indexes: int
    repaired_schema_tables: int
    repaired_manifest_metadata: int
    repaired_link_rows: int
    repaired_stale_payload_rows: int
    repaired_stale_media_rows: int
    pruned_missing_shards: int
    skipped_shards: int
    skipped_reasons: tuple[str, ...]
    errors: tuple[str, ...]


def only_archive_sender_schema_missing(report: ArchiveStatusReport) -> bool:
    """Return whether the sender table is the archive's only health issue."""
    expected_errors = tuple(
        f"{shard.shard_id}: missing schema table(s): archive_senders"
        for shard in report.shards
        if shard.missing_schema_tables == ("archive_senders",)
    )
    return bool(expected_errors) and bool(
        report.missing_shard_count == 0
        and report.missing_index_count == 0
        and report.missing_schema_table_count == len(expected_errors)
        and report.errors == expected_errors
    )


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    if journal_mode != "wal":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def ensure_manifest_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS archive_shards (
            shard_id TEXT PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            topic_id INTEGER,
            path TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            ends_at TEXT,
            message_count INTEGER NOT NULL DEFAULT 0,
            file_size_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            closed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_archive_shards_scope_time
            ON archive_shards(chat_id, topic_id, starts_at);

        CREATE TABLE IF NOT EXISTS tracked_db_links (
            link_id TEXT PRIMARY KEY,
            tracked_db_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_checked_at TEXT,
            status TEXT NOT NULL DEFAULT 'active'
        );
        """
    )


def record_tracked_db_link(
    conn: sqlite3.Connection,
    tracked_db_path: Path,
    *,
    archive_root_dir: Path | None = None,
) -> None:
    ensure_manifest_schema(conn)
    now = _serialize_dt(_utc_now())
    tracked_path = _tracked_db_path_value(archive_root_dir, tracked_db_path)
    link_id = tracked_path
    with conn:
        conn.execute(
            """
            INSERT INTO tracked_db_links (
                link_id, tracked_db_path, created_at, last_checked_at, status
            ) VALUES (?, ?, ?, ?, 'active')
            ON CONFLICT(link_id) DO UPDATE SET
                tracked_db_path=excluded.tracked_db_path,
                last_checked_at=excluded.last_checked_at,
                status='active'
            """,
            (link_id, tracked_path, now, now),
        )


def ensure_shard_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS archive_messages (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            topic_id INTEGER,
            sender_id INTEGER,
            date TEXT NOT NULL,
            text TEXT,
            raw_text TEXT,
            message_kind TEXT NOT NULL DEFAULT 'message',
            reply_to_msg_id INTEGER,
            reply_to_top_id INTEGER,
            is_forum_topic_link INTEGER NOT NULL DEFAULT 0,
            has_media INTEGER NOT NULL DEFAULT 0,
            tracked_db_path TEXT,
            tracked_message_chat_id INTEGER,
            tracked_message_id INTEGER,
            payload_mode TEXT NOT NULL DEFAULT 'archive',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (chat_id, message_id)
        );

        CREATE INDEX IF NOT EXISTS idx_archive_messages_scope_date
            ON archive_messages(chat_id, topic_id, date);

        CREATE INDEX IF NOT EXISTS idx_archive_messages_chat_date
            ON archive_messages(chat_id, date);

        CREATE INDEX IF NOT EXISTS idx_archive_messages_sender_date
            ON archive_messages(sender_id, date);

        CREATE INDEX IF NOT EXISTS idx_archive_messages_tracked_ref
            ON archive_messages(tracked_message_chat_id, tracked_message_id);

        CREATE TABLE IF NOT EXISTS archive_tracked_links (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            tracked_db_path TEXT NOT NULL,
            tracked_chat_id INTEGER NOT NULL,
            tracked_message_id INTEGER NOT NULL,
            linked_at TEXT NOT NULL,
            PRIMARY KEY (chat_id, message_id, tracked_db_path),
            FOREIGN KEY (chat_id, message_id)
                REFERENCES archive_messages(chat_id, message_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_archive_tracked_links_tracked
            ON archive_tracked_links(tracked_chat_id, tracked_message_id);

        CREATE TABLE IF NOT EXISTS archive_media (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            media_index INTEGER NOT NULL,
            media_kind TEXT NOT NULL,
            mime_type TEXT,
            file_size INTEGER,
            file_name TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (chat_id, message_id, media_index),
            FOREIGN KEY (chat_id, message_id)
                REFERENCES archive_messages(chat_id, message_id)
                ON DELETE CASCADE
        );

        """
    )
    ensure_archive_sender_table(conn)
    ensure_shard_indexes(conn)


def ensure_archive_sender_table(conn: sqlite3.Connection) -> None:
    """Create only the additive sender table without repairing other schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_senders (
            sender_id INTEGER PRIMARY KEY,
            username TEXT,
            display_name TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """
    )


def ensure_shard_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_archive_messages_scope_date
            ON archive_messages(chat_id, topic_id, date);

        CREATE INDEX IF NOT EXISTS idx_archive_messages_chat_date
            ON archive_messages(chat_id, date);

        CREATE INDEX IF NOT EXISTS idx_archive_messages_sender_date
            ON archive_messages(sender_id, date);

        CREATE INDEX IF NOT EXISTS idx_archive_messages_tracked_ref
            ON archive_messages(tracked_message_chat_id, tracked_message_id);

        CREATE INDEX IF NOT EXISTS idx_archive_tracked_links_tracked
            ON archive_tracked_links(tracked_chat_id, tracked_message_id);
        """
    )


def persist_archive_sender(
    conn: sqlite3.Connection,
    sender: ArchiveSender,
) -> None:
    """Upsert a local sender display snapshot without erasing known names."""
    ensure_shard_schema(conn)
    with conn:
        _persist_archive_sender_in_transaction(conn, sender)


def fetch_archive_sender(
    conn: sqlite3.Connection,
    sender_id: int,
) -> ArchiveSender | None:
    """Return a sender snapshot from one shard."""
    ensure_shard_schema(conn)
    row = conn.execute(
        """
        SELECT sender_id, username, display_name, first_seen_at, last_seen_at
        FROM archive_senders
        WHERE sender_id = ?
        """,
        (sender_id,),
    ).fetchone()
    return _row_to_archive_sender(row) if row is not None else None


def format_archive_sender_label(
    sender: ArchiveSender | None,
    *,
    alias: str | None = None,
    anonymous_label: str = "Anonymous sender",
) -> str:
    """Format a sender label without exposing the raw Telegram sender ID."""
    safe_alias = _normalize_optional_text(alias)
    if safe_alias:
        return safe_alias
    if sender is not None:
        display_name = _normalize_optional_text(sender.display_name)
        username = _normalize_username(sender.username)
        if display_name and username:
            return f"{display_name} (@{username})"
        if display_name:
            return display_name
        if username:
            return f"@{username}"
    return anonymous_label


def list_archive_sender_candidates(
    root_dir: Path,
    *,
    limit: int | None = None,
) -> tuple[ArchiveSenderCandidate, ...]:
    """List distinct senders that still need a usable snapshot in any shard."""
    if limit is not None and limit < 0:
        raise ValueError("archive sender backfill limit must be >= 0")
    if limit == 0:
        return ()
    manifest_path = root_dir / "manifest.sqlite3"
    if not manifest_path.exists():
        return ()

    manifest = connect_readonly(manifest_path)
    try:
        shard_rows = manifest.execute(
            "SELECT path FROM archive_shards ORDER BY starts_at ASC, shard_id ASC"
        ).fetchall()
    finally:
        manifest.close()

    aggregate: dict[int, dict[str, object]] = {}
    for shard_row in shard_rows:
        shard_path = _resolve_manifest_shard_path(root_dir, shard_row["path"])
        if not shard_path.exists():
            continue
        try:
            shard = connect_readonly(shard_path)
        except sqlite3.Error:
            continue
        try:
            if "archive_messages" in _missing_core_shard_tables(shard):
                continue
            has_sender_table = _table_exists(shard, "archive_senders")
            sender_select = (
                "s.username, s.display_name, s.first_seen_at AS sender_first_seen_at, "
                "s.last_seen_at AS sender_last_seen_at"
                if has_sender_table
                else (
                    "NULL AS username, NULL AS display_name, "
                    "NULL AS sender_first_seen_at, NULL AS sender_last_seen_at"
                )
            )
            sender_join = (
                "LEFT JOIN archive_senders AS s ON s.sender_id = r.sender_id"
                if has_sender_table
                else ""
            )
            rows = shard.execute(
                f"""
                WITH ranked AS (
                    SELECT sender_id, chat_id, message_id, date,
                           MIN(date) OVER (PARTITION BY sender_id) AS first_seen_at,
                           MAX(date) OVER (PARTITION BY sender_id) AS last_seen_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY sender_id
                               ORDER BY date DESC, message_id DESC
                           ) AS sender_rank
                    FROM archive_messages
                    WHERE sender_id IS NOT NULL
                )
                SELECT r.sender_id, r.chat_id, r.message_id,
                       r.first_seen_at, r.last_seen_at, {sender_select}
                FROM ranked AS r
                {sender_join}
                WHERE r.sender_rank = 1
                """
            ).fetchall()
        finally:
            shard.close()

        for row in rows:
            sender_id = int(row["sender_id"])
            first_seen_at = _deserialize_dt(row["first_seen_at"])
            last_seen_at = _deserialize_dt(row["last_seen_at"])
            entry = aggregate.get(sender_id)
            if entry is None:
                entry = {
                    "chat_id": int(row["chat_id"]),
                    "message_id": int(row["message_id"]),
                    "first_seen_at": first_seen_at,
                    "last_seen_at": last_seen_at,
                    "shard_paths": [],
                    "existing_sender": None,
                    "all_shards_resolved": True,
                }
                aggregate[sender_id] = entry
            else:
                entry["first_seen_at"] = min(
                    entry["first_seen_at"],
                    first_seen_at,
                )
                if last_seen_at > entry["last_seen_at"]:
                    entry["last_seen_at"] = last_seen_at
                    entry["chat_id"] = int(row["chat_id"])
                    entry["message_id"] = int(row["message_id"])
            entry["shard_paths"].append(shard_path)

            username = _normalize_username(row["username"])
            display_name = _normalize_optional_text(row["display_name"])
            if not username and not display_name:
                entry["all_shards_resolved"] = False
            elif entry["existing_sender"] is None:
                snapshot_first = (
                    _deserialize_dt(row["sender_first_seen_at"])
                    if row["sender_first_seen_at"] is not None
                    else first_seen_at
                )
                snapshot_last = (
                    _deserialize_dt(row["sender_last_seen_at"])
                    if row["sender_last_seen_at"] is not None
                    else last_seen_at
                )
                entry["existing_sender"] = ArchiveSender(
                    sender_id=sender_id,
                    username=username,
                    display_name=display_name,
                    first_seen_at=snapshot_first,
                    last_seen_at=snapshot_last,
                )

    candidates: list[ArchiveSenderCandidate] = []
    for sender_id, entry in aggregate.items():
        if entry["all_shards_resolved"]:
            continue
        existing = entry["existing_sender"]
        if existing is not None:
            existing = ArchiveSender(
                sender_id=sender_id,
                username=existing.username,
                display_name=existing.display_name,
                first_seen_at=entry["first_seen_at"],
                last_seen_at=entry["last_seen_at"],
            )
        candidates.append(
            ArchiveSenderCandidate(
                sender_id=sender_id,
                chat_id=entry["chat_id"],
                message_id=entry["message_id"],
                first_seen_at=entry["first_seen_at"],
                last_seen_at=entry["last_seen_at"],
                shard_paths=tuple(dict.fromkeys(entry["shard_paths"])),
                existing_sender=existing,
            )
        )
    candidates.sort(key=lambda candidate: candidate.sender_id)
    if limit is not None:
        candidates = candidates[:limit]
    return tuple(candidates)


def persist_archive_sender_to_shards(
    sender: ArchiveSender,
    shard_paths: tuple[Path, ...],
) -> int:
    """Persist one resolved sender snapshot to each shard that references it."""
    written = 0
    for shard_path in dict.fromkeys(shard_paths):
        shard = connect(shard_path)
        try:
            persist_archive_sender(shard, sender)
        finally:
            shard.close()
        written += 1
    return written


def ensure_archive_sender_schema(root_dir: Path) -> int:
    """Create the additive sender table in registered shards that lack it."""
    manifest_path = root_dir / "manifest.sqlite3"
    if not manifest_path.exists():
        return 0
    manifest = connect_readonly(manifest_path)
    try:
        rows = manifest.execute(
            "SELECT path FROM archive_shards ORDER BY starts_at ASC, shard_id ASC"
        ).fetchall()
    finally:
        manifest.close()

    updated = 0
    for row in rows:
        shard_path = _resolve_manifest_shard_path(root_dir, row["path"])
        if not shard_path.exists():
            continue
        shard = connect(shard_path)
        try:
            if _table_exists(shard, "archive_senders"):
                continue
            ensure_archive_sender_table(shard)
            shard.commit()
            updated += 1
        finally:
            shard.close()
    return updated


def select_shard(
    conn: sqlite3.Connection,
    root_dir: Path,
    *,
    chat_id: int,
    message_date: datetime,
    max_messages_per_shard: int,
    max_shard_size_bytes: int,
) -> ArchiveShard:
    """Return an active group-month shard, creating/rotating as needed."""
    ensure_manifest_schema(conn)
    starts_at, ends_at = _month_bounds(message_date)
    starts_raw = _serialize_dt(starts_at)
    rows = conn.execute(
        """
        SELECT *
        FROM archive_shards
        WHERE chat_id = ?
          AND topic_id IS NULL
          AND starts_at = ?
        ORDER BY shard_id ASC
        """,
        (chat_id, starts_raw),
    ).fetchall()
    for row in rows:
        path = _resolve_manifest_shard_path(root_dir, row["path"])
        file_size = (
            _sqlite_file_size_bytes(path)
            if path.exists()
            else int(row["file_size_bytes"])
        )
        if (
            str(row["status"]) == "active"
            and int(row["message_count"]) < max_messages_per_shard
            and file_size < max_shard_size_bytes
        ):
            return _row_to_shard(row, root_dir)
        if str(row["status"]) == "active":
            conn.execute(
                """
                UPDATE archive_shards
                SET status = 'closed',
                    closed_at = ?,
                    file_size_bytes = ?
                WHERE shard_id = ?
                """,
                (_serialize_dt(_utc_now()), file_size, row["shard_id"]),
            )

    max_sequence = max(
        (_row_to_shard(row, root_dir).sequence for row in rows),
        default=0,
    )
    sequence = max_sequence + 1
    shard = _build_shard(root_dir, chat_id, starts_at, ends_at, sequence)
    shard.path.parent.mkdir(parents=True, exist_ok=True)
    now = _serialize_dt(_utc_now())
    with conn:
        conn.execute(
            """
            INSERT INTO archive_shards (
                shard_id, chat_id, topic_id, path, starts_at, ends_at,
                message_count, file_size_bytes, status, created_at, closed_at
            ) VALUES (?, ?, NULL, ?, ?, ?, 0, 0, 'active', ?, NULL)
            """,
            (
                shard.shard_id,
                shard.chat_id,
                _manifest_shard_path_value(root_dir, shard.path),
                _serialize_dt(shard.starts_at),
                _serialize_dt(shard.ends_at),
                now,
            ),
        )
    return shard


def record_shard_write(
    conn: sqlite3.Connection,
    shard: ArchiveShard,
) -> None:
    file_size = _sqlite_file_size_bytes(shard.path)
    with conn:
        conn.execute(
            """
            UPDATE archive_shards
            SET message_count = message_count + 1,
                file_size_bytes = ?
            WHERE shard_id = ?
            """,
            (file_size, shard.shard_id),
        )


def persist_archive_message(
    conn: sqlite3.Connection,
    message: ArchiveMessage,
    *,
    tracked_db_path: Path | None = None,
    archive_root_dir: Path | None = None,
) -> str:
    """Persist an archive message and return its payload mode."""
    result = persist_archive_message_with_result(
        conn,
        message,
        tracked_db_path=tracked_db_path,
        archive_root_dir=archive_root_dir,
    )
    return result.payload_mode


def persist_archive_message_with_result(
    conn: sqlite3.Connection,
    message: ArchiveMessage,
    *,
    tracked_db_path: Path | None = None,
    archive_root_dir: Path | None = None,
    sender: ArchiveSender | None = None,
) -> ArchiveMessagePersistResult:
    """Persist an archive message and report whether it inserted a new row."""
    ensure_shard_schema(conn)
    started_transaction = not conn.in_transaction
    if started_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            """
            SELECT payload_mode, tracked_db_path, tracked_message_chat_id,
                   tracked_message_id
            FROM archive_messages
            WHERE chat_id = ? AND message_id = ?
            LIMIT 1
            """,
            (message.chat_id, message.message_id),
        ).fetchone()
        created = existing is None
        result = _persist_archive_message_in_transaction(
            conn,
            message,
            existing=existing,
            tracked_db_path=tracked_db_path,
            archive_root_dir=archive_root_dir,
            created=created,
        )
        if sender is not None:
            _persist_archive_sender_in_transaction(conn, sender)
    except Exception:
        if started_transaction:
            conn.rollback()
        raise
    if started_transaction:
        conn.commit()
    return result


def _persist_archive_sender_in_transaction(
    conn: sqlite3.Connection,
    sender: ArchiveSender,
) -> None:
    first_seen_at = _ensure_utc(sender.first_seen_at)
    last_seen_at = _ensure_utc(sender.last_seen_at)
    if last_seen_at < first_seen_at:
        first_seen_at, last_seen_at = last_seen_at, first_seen_at
    username = _normalize_username(sender.username)
    display_name = _normalize_optional_text(sender.display_name)
    conn.execute(
        """
        INSERT INTO archive_senders (
            sender_id, username, display_name, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(sender_id) DO UPDATE SET
            username=COALESCE(excluded.username, archive_senders.username),
            display_name=COALESCE(excluded.display_name, archive_senders.display_name),
            first_seen_at=MIN(archive_senders.first_seen_at, excluded.first_seen_at),
            last_seen_at=MAX(archive_senders.last_seen_at, excluded.last_seen_at)
        """,
        (
            sender.sender_id,
            username,
            display_name,
            _serialize_dt(first_seen_at),
            _serialize_dt(last_seen_at),
        ),
    )


def _persist_archive_message_in_transaction(
    conn: sqlite3.Connection,
    message: ArchiveMessage,
    *,
    existing: sqlite3.Row | None,
    tracked_db_path: Path | None,
    archive_root_dir: Path | None,
    created: bool,
) -> ArchiveMessagePersistResult:
    tracked_path = (
        _tracked_db_path_value(archive_root_dir, tracked_db_path)
        if tracked_db_path
        else None
    )
    tracked_exists = (
        tracked_db_path is not None
        and _tracked_message_exists(tracked_db_path, message.chat_id, message.message_id)
    )
    preserve_tracked_ref = (
        not tracked_exists
        and existing is not None
        and existing["payload_mode"] == "tracked_ref"
    )
    payload_mode = "tracked_ref" if tracked_exists or preserve_tracked_ref else "archive"
    text = None if payload_mode == "tracked_ref" else message.text
    raw_text = None if payload_mode == "tracked_ref" else message.raw_text
    if tracked_exists:
        tracked_chat_id = message.chat_id
        tracked_message_id = message.message_id
    elif preserve_tracked_ref:
        tracked_path = existing["tracked_db_path"]
        tracked_chat_id = existing["tracked_message_chat_id"]
        tracked_message_id = existing["tracked_message_id"]
    else:
        tracked_chat_id = None
        tracked_message_id = None
    now = _serialize_dt(_utc_now())
    values = (
        message.chat_id,
        message.message_id,
        message.topic_id,
        message.sender_id,
        _serialize_dt(_ensure_utc(message.date)),
        text,
        raw_text,
        message.message_kind,
        message.reply_to_msg_id,
        message.reply_to_top_id,
        1 if message.is_forum_topic_link else 0,
        1 if message.has_media else 0,
        tracked_path if payload_mode == "tracked_ref" else None,
        tracked_chat_id,
        tracked_message_id,
        payload_mode,
        now,
        now,
    )
    conn.execute(
        """
        INSERT INTO archive_messages (
            chat_id, message_id, topic_id, sender_id, date, text, raw_text,
            message_kind, reply_to_msg_id, reply_to_top_id, is_forum_topic_link,
            has_media, tracked_db_path, tracked_message_chat_id,
            tracked_message_id, payload_mode, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, message_id) DO UPDATE SET
            topic_id=excluded.topic_id,
            sender_id=excluded.sender_id,
            date=excluded.date,
            text=excluded.text,
            raw_text=excluded.raw_text,
            message_kind=excluded.message_kind,
            reply_to_msg_id=excluded.reply_to_msg_id,
            reply_to_top_id=excluded.reply_to_top_id,
            is_forum_topic_link=excluded.is_forum_topic_link,
            has_media=excluded.has_media,
            tracked_db_path=excluded.tracked_db_path,
            tracked_message_chat_id=excluded.tracked_message_chat_id,
            tracked_message_id=excluded.tracked_message_id,
            payload_mode=excluded.payload_mode,
            updated_at=excluded.updated_at
        """,
        values,
    )
    if payload_mode == "tracked_ref":
        conn.execute(
            """
            DELETE FROM archive_media
            WHERE chat_id = ? AND message_id = ?
            """,
            (message.chat_id, message.message_id),
        )
        if (
            tracked_path is not None
            and tracked_chat_id is not None
            and tracked_message_id is not None
        ):
            conn.execute(
                """
                INSERT INTO archive_tracked_links (
                    chat_id, message_id, tracked_db_path, tracked_chat_id,
                    tracked_message_id, linked_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id, tracked_db_path) DO UPDATE SET
                    tracked_chat_id=excluded.tracked_chat_id,
                    tracked_message_id=excluded.tracked_message_id,
                    linked_at=excluded.linked_at
                """,
                (
                    message.chat_id,
                    message.message_id,
                    tracked_path,
                    tracked_chat_id,
                    tracked_message_id,
                    now,
                ),
            )
    else:
        conn.execute(
            """
            DELETE FROM archive_tracked_links
            WHERE chat_id = ? AND message_id = ?
            """,
            (message.chat_id, message.message_id),
        )
        conn.execute(
            """
            DELETE FROM archive_media
            WHERE chat_id = ? AND message_id = ?
            """,
            (message.chat_id, message.message_id),
        )
        for media in message.media:
            conn.execute(
                """
                INSERT INTO archive_media (
                    chat_id, message_id, media_index, media_kind, mime_type,
                    file_size, file_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id, media_index) DO UPDATE SET
                    media_kind=excluded.media_kind,
                    mime_type=excluded.mime_type,
                    file_size=excluded.file_size,
                    file_name=excluded.file_name,
                    updated_at=excluded.updated_at
                """,
                (
                    message.chat_id,
                    message.message_id,
                    media.media_index,
                    media.media_kind,
                    media.mime_type,
                    media.file_size,
                    media.file_name,
                    now,
                    now,
                ),
            )
    return ArchiveMessagePersistResult(payload_mode=payload_mode, created=created)


def archive_message_exists(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    message_id: int,
) -> bool:
    ensure_shard_schema(conn)
    row = conn.execute(
        """
        SELECT 1
        FROM archive_messages
        WHERE chat_id = ? AND message_id = ?
        LIMIT 1
        """,
        (chat_id, message_id),
    ).fetchone()
    return row is not None


def find_shard_for_message(
    conn: sqlite3.Connection,
    root_dir: Path,
    *,
    chat_id: int,
    message_date: datetime,
    message_id: int,
) -> ArchiveShard | None:
    ensure_manifest_schema(conn)
    starts_at, _ = _month_bounds(message_date)
    rows = conn.execute(
        """
        SELECT *
        FROM archive_shards
        WHERE chat_id = ?
          AND topic_id IS NULL
          AND starts_at = ?
        ORDER BY shard_id ASC
        """,
        (chat_id, _serialize_dt(starts_at)),
    ).fetchall()
    for row in rows:
        path = _resolve_manifest_shard_path(root_dir, row["path"])
        if not path.exists():
            continue
        shard_conn = connect(path)
        try:
            if archive_message_exists(
                shard_conn,
                chat_id=chat_id,
                message_id=message_id,
            ):
                return _row_to_shard(row, root_dir)
        finally:
            shard_conn.close()
    return None


def fetch_messages_between(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    since: datetime,
    until: datetime,
    topic_id: int | None = None,
) -> list[DbArchiveMessage]:
    """Fetch archived messages in a time window.

    Omitting ``topic_id`` returns the whole group timeline. Passing a topic ID
    narrows the result to that topic.
    """
    params: list[object] = [
        chat_id,
        _serialize_dt(_ensure_utc(since)),
        _serialize_dt(_ensure_utc(until)),
    ]
    query = """
        SELECT *
        FROM archive_messages
        WHERE chat_id = ?
          AND date >= ?
          AND date <= ?
    """
    if topic_id is not None:
        query += " AND topic_id = ?"
        params.append(topic_id)
    query += " ORDER BY date ASC, message_id ASC"
    return [_row_to_message(row) for row in conn.execute(query, params).fetchall()]


def find_tracked_message_date(
    tracked_db_path: Path,
    *,
    chat_id: int,
    message_id: int,
) -> datetime | None:
    """Return a tracked message timestamp without creating the tracked DB."""
    if not tracked_db_path.exists():
        return None
    try:
        conn = connect_readonly(tracked_db_path)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            """
            SELECT date
            FROM messages
            WHERE chat_id = ? AND message_id = ?
            LIMIT 1
            """,
            (chat_id, message_id),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if row is None:
        return None
    return _deserialize_dt(row["date"])


def tracked_message_date_lookup_error(tracked_db_path: Path) -> str | None:
    """Return why a tracked DB cannot locate a target message timestamp."""
    return _tracked_db_schema_error(
        tracked_db_path,
        required_columns={"chat_id", "message_id", "date"},
    )


def fetch_context_messages(
    root_dir: Path,
    tracked_db_path: Path,
    *,
    chat_id: int,
    since: datetime,
    until: datetime,
    topic_id: int | None = None,
) -> list[ArchiveContextMessage]:
    """Fetch archived context rows and resolve tracked_ref text via ATTACH."""
    return list(
        fetch_context_result(
            root_dir,
            tracked_db_path,
            chat_id=chat_id,
            since=since,
            until=until,
            topic_id=topic_id,
        ).messages
    )


def fetch_context_result(
    root_dir: Path,
    tracked_db_path: Path,
    *,
    chat_id: int,
    since: datetime,
    until: datetime,
    topic_id: int | None = None,
    target_message_id: int | None = None,
) -> ArchiveContextResult:
    """Fetch archived context rows plus skipped shard diagnostics."""
    manifest_path = root_dir / "manifest.sqlite3"
    if not manifest_path.exists():
        return ArchiveContextResult(messages=(), skipped_shards=(), errors=())
    since = _ensure_utc(since)
    until = _ensure_utc(until)
    try:
        manifest = connect_readonly(manifest_path)
    except sqlite3.Error:
        return ArchiveContextResult(
            messages=(),
            skipped_shards=(),
            errors=("manifest unreadable",),
        )
    try:
        shard_rows = manifest.execute(
            """
            SELECT *
            FROM archive_shards
            WHERE chat_id = ?
              AND starts_at <= ?
              AND (ends_at IS NULL OR ends_at >= ?)
            ORDER BY starts_at ASC, shard_id ASC
            """,
            (chat_id, _serialize_dt(until), _serialize_dt(since)),
        ).fetchall()
    except sqlite3.Error as exc:
        return ArchiveContextResult(
            messages=(),
            skipped_shards=(),
            errors=(f"manifest schema unreadable: {exc}",),
        )
    finally:
        manifest.close()

    messages: list[ArchiveContextMessage] = []
    skipped: list[str] = []
    errors: list[str] = []
    target_archived = False
    target_archived_topic_id: int | None = None
    tracked_db_error = _tracked_db_context_error(tracked_db_path)
    for shard_row in shard_rows:
        shard_id = str(shard_row["shard_id"])
        shard_path = _resolve_manifest_shard_path(root_dir, shard_row["path"])
        if not shard_path.exists():
            skipped.append(f"{shard_id}: missing shard file")
            continue
        try:
            shard = connect_readonly(shard_path)
        except sqlite3.Error as exc:
            reason = f"{shard_id}: unreadable shard: {exc}"
            skipped.append(reason)
            errors.append(reason)
            continue
        try:
            missing_core_tables = _missing_core_shard_tables(shard)
            if missing_core_tables:
                reason = (
                    f"{shard_id}: missing required table(s): "
                    + ", ".join(missing_core_tables)
                )
                skipped.append(reason)
                errors.append(reason)
                continue
            missing_schema_tables = _missing_additive_shard_tables(shard)
            if missing_schema_tables:
                errors.append(
                    f"{shard_id}: missing schema table(s): "
                    + ", ".join(missing_schema_tables)
                )
            if target_message_id is not None and not target_archived:
                target_found, target_topic_id = _fetch_target_archive_topic_from_shard(
                    shard,
                    chat_id=chat_id,
                    message_id=target_message_id,
                )
                if target_found:
                    target_archived = True
                    target_archived_topic_id = target_topic_id
            shard_messages = _fetch_context_messages_from_shard(
                shard,
                root_dir,
                tracked_db_path,
                chat_id=chat_id,
                since=since,
                until=until,
                topic_id=topic_id,
            )
            unresolved_tracked_refs = sum(
                1
                for row in shard_messages
                if row.payload_mode == "tracked_ref"
                and row.tracked_db_matches_current
                and not row.tracked_row_found
            )
            unreadable_tracked_refs = sum(
                1
                for row in shard_messages
                if row.payload_mode == "tracked_ref"
                and row.tracked_db_matches_current
            )
            if tracked_db_error and unreadable_tracked_refs:
                errors.append(
                    f"{shard_id}: {unreadable_tracked_refs} tracked_ref row(s) "
                    f"could not read current tracked DB ({tracked_db_error})"
                )
            elif unresolved_tracked_refs:
                errors.append(
                    f"{shard_id}: {unresolved_tracked_refs} tracked_ref row(s) "
                    "could not resolve tracked DB row"
                )
            mismatched_tracked_refs = sum(
                1
                for row in shard_messages
                if row.payload_mode == "tracked_ref"
                and not row.tracked_db_matches_current
            )
            if mismatched_tracked_refs:
                errors.append(
                    f"{shard_id}: {mismatched_tracked_refs} tracked_ref row(s) "
                    "point to a different tracked DB"
                )
            messages.extend(shard_messages)
        except sqlite3.Error as exc:
            reason = f"{shard_id}: context query failed: {exc}"
            skipped.append(reason)
            errors.append(reason)
            continue
        finally:
            shard.close()
    return ArchiveContextResult(
        messages=tuple(sorted(messages, key=lambda row: (row.date, row.message_id))),
        skipped_shards=tuple(skipped),
        errors=tuple(errors),
        target_archived=target_archived,
        target_archived_topic_id=target_archived_topic_id,
    )


def inspect_archive_status(
    root_dir: Path,
    *,
    tracked_db_path: Path | None = None,
) -> ArchiveStatusReport:
    """Read manifest and shard health without creating or modifying files."""
    manifest_path = root_dir / "manifest.sqlite3"
    if not manifest_path.exists():
        orphaned_shards = _orphaned_shard_files(root_dir)
        errors = _orphaned_shard_errors(orphaned_shards)
        return ArchiveStatusReport(
            root_dir=root_dir,
            manifest_path=manifest_path,
            manifest_exists=False,
            shard_count=0,
            missing_shard_count=0,
            manifest_message_count=0,
            actual_message_count=0,
            archive_row_count=0,
            tracked_ref_count=0,
            link_count=0,
            media_metadata_count=0,
            tracked_db_link_count=0,
            file_size_bytes=sum(_sqlite_file_size_bytes(path) for path in orphaned_shards),
            missing_index_count=0,
            missing_schema_table_count=0,
            errors=errors,
            shards=(),
        )

    errors: list[str] = []
    shard_statuses: list[ArchiveShardStatus] = []
    try:
        manifest = connect_readonly(manifest_path)
    except sqlite3.Error as exc:
        return ArchiveStatusReport(
            root_dir=root_dir,
            manifest_path=manifest_path,
            manifest_exists=True,
            shard_count=0,
            missing_shard_count=0,
            manifest_message_count=0,
            actual_message_count=0,
            archive_row_count=0,
            tracked_ref_count=0,
            link_count=0,
            media_metadata_count=0,
            tracked_db_link_count=0,
            file_size_bytes=manifest_path.stat().st_size,
            missing_index_count=0,
            missing_schema_table_count=0,
            errors=(f"manifest unreadable: {exc}",),
            shards=(),
        )
    try:
        missing_manifest_schema_tables = _missing_additive_manifest_tables(manifest)
        rows = manifest.execute(
            """
            SELECT shard_id, chat_id, path, message_count, file_size_bytes, status
            FROM archive_shards
            ORDER BY chat_id ASC, starts_at ASC, shard_id ASC
            """
        ).fetchall()
        tracked_db_link_count = _manifest_tracked_db_link_count(manifest)
        current_tracked_db_linked = (
            _manifest_tracked_db_link_exists(manifest, root_dir, tracked_db_path)
            if tracked_db_path is not None
            else None
        )
    except sqlite3.Error as exc:
        return ArchiveStatusReport(
            root_dir=root_dir,
            manifest_path=manifest_path,
            manifest_exists=True,
            shard_count=0,
            missing_shard_count=0,
            manifest_message_count=0,
            actual_message_count=0,
            archive_row_count=0,
            tracked_ref_count=0,
            link_count=0,
            media_metadata_count=0,
            tracked_db_link_count=0,
            file_size_bytes=manifest_path.stat().st_size,
            missing_index_count=0,
            missing_schema_table_count=0,
            errors=(f"manifest schema unreadable: {exc}",),
            shards=(),
        )
    finally:
        manifest.close()

    if missing_manifest_schema_tables:
        errors.append(
            "manifest: missing schema table(s): "
            + ", ".join(missing_manifest_schema_tables)
        )
    registered_shard_paths = tuple(
        _resolve_manifest_shard_path(root_dir, row["path"]) for row in rows
    )
    unregistered_shards = _unregistered_shard_files(root_dir, registered_shard_paths)
    if unregistered_shards:
        errors += list(_unregistered_shard_errors(unregistered_shards))

    current_tracked_db_readable: bool | None = None
    if tracked_db_path is not None:
        current_tracked_db_readable = _tracked_db_is_readable(tracked_db_path)
        if tracked_db_link_count > 0 and not current_tracked_db_linked:
            errors.append("current tracked DB is not registered in archive manifest")
        if current_tracked_db_linked and not current_tracked_db_readable:
            errors.append("current tracked DB is not readable")

    for row in rows:
        shard_path = _resolve_manifest_shard_path(root_dir, row["path"])
        exists = shard_path.exists()
        manifest_count = int(row["message_count"] or 0)
        manifest_size = int(row["file_size_bytes"] or 0)
        actual_size = _sqlite_file_size_bytes(shard_path) if exists else 0
        actual_count = 0
        archive_count = 0
        tracked_ref_count = 0
        incomplete_tracked_ref_count = 0
        tracked_ref_payload_count = 0
        tracked_ref_media_count = 0
        link_count = 0
        media_count = 0
        missing_indexes: tuple[str, ...] = ()
        missing_schema_tables: tuple[str, ...] = ()
        link_repair_delta = 0
        error: str | None = None
        if not exists:
            error = "missing shard file"
        else:
            try:
                shard_conn = connect_readonly(shard_path)
                try:
                    missing_core_tables = _missing_core_shard_tables(shard_conn)
                    if missing_core_tables:
                        raise sqlite3.DatabaseError(
                            "missing required table(s): "
                            + ", ".join(missing_core_tables)
                        )
                    missing_schema_tables = _missing_additive_shard_tables(shard_conn)
                    counts = shard_conn.execute(
                        """
                        SELECT
                            COUNT(*) AS actual_message_count,
                            SUM(CASE WHEN payload_mode = 'archive' THEN 1 ELSE 0 END)
                                AS archive_row_count,
                            SUM(CASE WHEN payload_mode = 'tracked_ref' THEN 1 ELSE 0 END)
                                AS tracked_ref_count
                        FROM archive_messages
                        """
                    ).fetchone()
                    links = shard_conn.execute(
                        "SELECT COUNT(*) AS link_count FROM archive_tracked_links"
                    ).fetchone()
                    if _table_exists(shard_conn, "archive_media"):
                        media = shard_conn.execute(
                            "SELECT COUNT(*) AS media_count FROM archive_media"
                        ).fetchone()
                        media_count = int(media["media_count"] or 0)
                        tracked_ref_media_count = (
                            _tracked_ref_archive_media_count(shard_conn)
                        )
                    missing_indexes = _missing_required_indexes(shard_conn)
                    actual_count = int(counts["actual_message_count"] or 0)
                    archive_count = int(counts["archive_row_count"] or 0)
                    tracked_ref_count = int(counts["tracked_ref_count"] or 0)
                    incomplete_tracked_ref_count = (
                        _incomplete_tracked_ref_metadata_count(shard_conn)
                    )
                    tracked_ref_payload_count = (
                        _tracked_ref_archive_payload_count(shard_conn)
                    )
                    link_count = int(links["link_count"] or 0)
                    if tracked_ref_count == link_count:
                        link_repair_delta = _tracked_link_repair_delta(shard_conn)
                finally:
                    shard_conn.close()
            except sqlite3.Error as exc:
                error = f"unreadable shard: {exc}"
        if missing_schema_tables:
            errors.append(
                f"{row['shard_id']}: missing schema table(s): "
                + ", ".join(missing_schema_tables)
            )
        if missing_indexes:
            errors.append(
                f"{row['shard_id']}: missing required index(es): "
                + ", ".join(missing_indexes)
            )
        if exists and error is None and manifest_count != actual_count:
            errors.append(
                f"{row['shard_id']}: message count mismatch "
                f"(manifest={manifest_count}, actual={actual_count})"
            )
        if exists and error is None and incomplete_tracked_ref_count:
            errors.append(
                f"{row['shard_id']}: incomplete tracked_ref metadata "
                f"(rows={incomplete_tracked_ref_count})"
            )
        if exists and error is None and tracked_ref_payload_count:
            errors.append(
                f"{row['shard_id']}: tracked_ref archive text payload "
                f"should be cleared (rows={tracked_ref_payload_count})"
            )
        if exists and error is None and tracked_ref_media_count:
            errors.append(
                f"{row['shard_id']}: tracked_ref archive media metadata "
                f"should be removed (rows={tracked_ref_media_count})"
            )
        if exists and error is None and tracked_ref_count != link_count:
            errors.append(
                f"{row['shard_id']}: tracked_ref/link count mismatch "
                f"(tracked_ref={tracked_ref_count}, links={link_count})"
            )
        if (
            exists
            and error is None
            and tracked_ref_count == link_count
            and link_repair_delta
        ):
            errors.append(
                f"{row['shard_id']}: tracked_ref/link content mismatch "
                f"(rows_to_repair={link_repair_delta})"
            )
        if error:
            errors.append(f"{row['shard_id']}: {error}")
        shard_statuses.append(
            ArchiveShardStatus(
                shard_id=str(row["shard_id"]),
                chat_id=int(row["chat_id"]),
                path=shard_path,
                exists=exists,
                status=str(row["status"]),
                manifest_message_count=manifest_count,
                manifest_file_size_bytes=manifest_size,
                actual_message_count=actual_count,
                archive_row_count=archive_count,
                tracked_ref_count=tracked_ref_count,
                link_count=link_count,
                media_metadata_count=media_count,
                actual_file_size_bytes=actual_size,
                missing_indexes=missing_indexes,
                missing_schema_tables=missing_schema_tables,
                error=error,
            )
        )

    manifest_message_count = sum(
        shard.manifest_message_count for shard in shard_statuses
    )
    actual_message_count = sum(shard.actual_message_count for shard in shard_statuses)
    if tracked_db_link_count == 0 and (
        manifest_message_count > 0 or actual_message_count > 0
    ):
        errors.append("archive manifest has messages but no tracked DB link")

    return ArchiveStatusReport(
        root_dir=root_dir,
        manifest_path=manifest_path,
        manifest_exists=True,
        shard_count=len(shard_statuses),
        missing_shard_count=sum(1 for shard in shard_statuses if not shard.exists),
        manifest_message_count=manifest_message_count,
        actual_message_count=actual_message_count,
        archive_row_count=sum(shard.archive_row_count for shard in shard_statuses),
        tracked_ref_count=sum(shard.tracked_ref_count for shard in shard_statuses),
        link_count=sum(shard.link_count for shard in shard_statuses),
        media_metadata_count=sum(
            shard.media_metadata_count for shard in shard_statuses
        ),
        tracked_db_link_count=tracked_db_link_count,
        file_size_bytes=manifest_path.stat().st_size
        + sum(shard.actual_file_size_bytes for shard in shard_statuses)
        + sum(_sqlite_file_size_bytes(path) for path in unregistered_shards),
        missing_index_count=sum(len(shard.missing_indexes) for shard in shard_statuses),
        missing_schema_table_count=len(missing_manifest_schema_tables)
        + sum(len(shard.missing_schema_tables) for shard in shard_statuses),
        errors=tuple(errors),
        shards=tuple(shard_statuses),
        current_tracked_db_linked=current_tracked_db_linked,
        current_tracked_db_readable=current_tracked_db_readable,
    )


def repair_archive_metadata(
    root_dir: Path,
    *,
    apply: bool = False,
    prune_missing_shards: bool = False,
) -> ArchiveRepairReport:
    """Repair missing shard indexes. Dry-run by default."""
    manifest_path = root_dir / "manifest.sqlite3"
    if not manifest_path.exists():
        orphaned_shards = _orphaned_shard_files(root_dir)
        errors = _orphaned_shard_errors(orphaned_shards)
        return ArchiveRepairReport(
            root_dir=root_dir,
            manifest_path=manifest_path,
            manifest_exists=False,
            dry_run=not apply,
            checked_shards=0,
            repaired_shards=0,
            repaired_indexes=0,
            repaired_schema_tables=0,
            repaired_manifest_metadata=0,
            repaired_link_rows=0,
            repaired_stale_payload_rows=0,
            repaired_stale_media_rows=0,
            pruned_missing_shards=0,
            skipped_shards=len(orphaned_shards),
            skipped_reasons=errors,
            errors=errors,
        )

    errors: list[str] = []
    try:
        manifest = connect(manifest_path) if apply else connect_readonly(manifest_path)
    except sqlite3.Error as exc:
        return ArchiveRepairReport(
            root_dir=root_dir,
            manifest_path=manifest_path,
            manifest_exists=True,
            dry_run=not apply,
            checked_shards=0,
            repaired_shards=0,
            repaired_indexes=0,
            repaired_schema_tables=0,
            repaired_manifest_metadata=0,
            repaired_link_rows=0,
            repaired_stale_payload_rows=0,
            repaired_stale_media_rows=0,
            pruned_missing_shards=0,
            skipped_shards=0,
            skipped_reasons=(),
            errors=(f"manifest unreadable: {exc}",),
        )
    try:
        rows = manifest.execute(
            """
            SELECT shard_id, path, message_count, file_size_bytes
            FROM archive_shards
            ORDER BY chat_id ASC, starts_at ASC, shard_id ASC
            """
        ).fetchall()
    except sqlite3.Error as exc:
        manifest.close()
        return ArchiveRepairReport(
            root_dir=root_dir,
            manifest_path=manifest_path,
            manifest_exists=True,
            dry_run=not apply,
            checked_shards=0,
            repaired_shards=0,
            repaired_indexes=0,
            repaired_schema_tables=0,
            repaired_manifest_metadata=0,
            repaired_link_rows=0,
            repaired_stale_payload_rows=0,
            repaired_stale_media_rows=0,
            pruned_missing_shards=0,
            skipped_shards=0,
            skipped_reasons=(),
            errors=(f"manifest schema unreadable: {exc}",),
        )

    checked = 0
    repaired_shards = 0
    repaired_indexes = 0
    repaired_schema_tables = 0
    repaired_manifest_metadata = 0
    repaired_link_rows = 0
    repaired_stale_payload_rows = 0
    repaired_stale_media_rows = 0
    pruned_missing_shards = 0
    skipped = 0
    skipped_reasons: list[str] = []
    try:
        missing_manifest_schema_tables = _missing_additive_manifest_tables(manifest)
        if missing_manifest_schema_tables:
            repaired_schema_tables += len(missing_manifest_schema_tables)
            if apply:
                ensure_manifest_schema(manifest)
        registered_shard_paths = tuple(
            _resolve_manifest_shard_path(root_dir, row["path"]) for row in rows
        )
        unregistered_shards = _unregistered_shard_files(root_dir, registered_shard_paths)
        if unregistered_shards:
            unregistered_errors = _unregistered_shard_errors(unregistered_shards)
            skipped += len(unregistered_shards)
            skipped_reasons.extend(unregistered_errors)
            errors.extend(unregistered_errors)
        for row in rows:
            shard_id = str(row["shard_id"])
            shard_path = _resolve_manifest_shard_path(root_dir, row["path"])
            if not shard_path.exists():
                if prune_missing_shards:
                    pruned_missing_shards += 1
                    if apply:
                        manifest.execute(
                            "DELETE FROM archive_shards WHERE shard_id = ?",
                            (shard_id,),
                        )
                    continue
                skipped += 1
                skipped_reasons.append(f"{shard_id}: missing shard file")
                continue
            try:
                conn = connect(shard_path) if apply else connect_readonly(shard_path)
            except sqlite3.Error as exc:
                skipped += 1
                reason = f"{shard_id}: unreadable shard: {exc}"
                skipped_reasons.append(reason)
                errors.append(reason)
                continue
            try:
                missing_core_tables = _missing_core_shard_tables(conn)
                if missing_core_tables:
                    skipped += 1
                    reason = (
                        f"{shard_id}: required shard table(s) are missing: "
                        + ", ".join(missing_core_tables)
                    )
                    skipped_reasons.append(reason)
                    errors.append(reason)
                    continue
                checked += 1
                missing_schema_tables = _missing_additive_shard_tables(conn)
                missing_indexes = _missing_required_indexes(conn)
                if apply and missing_schema_tables:
                    ensure_shard_schema(conn)
                elif apply and missing_indexes:
                    ensure_shard_indexes(conn)
                incomplete_tracked_refs = _incomplete_tracked_ref_metadata_count(conn)
                if incomplete_tracked_refs:
                    skipped += 1
                    reason = (
                        f"{shard_id}: incomplete tracked_ref metadata "
                        f"(rows={incomplete_tracked_refs}); cannot repair links"
                    )
                    skipped_reasons.append(reason)
                    errors.append(reason)
                    continue
                stale_payload_rows = _tracked_ref_archive_payload_count(conn)
                if apply and stale_payload_rows:
                    _clear_tracked_ref_archive_payload(conn)
                stale_media_rows = _tracked_ref_archive_media_count(conn)
                if apply and stale_media_rows:
                    _delete_tracked_ref_archive_media(conn)
                link_repair_delta = _tracked_link_repair_delta(conn)
                if apply and link_repair_delta:
                    _rebuild_archive_tracked_links(conn)
                actual_count = _shard_message_count(conn)
                actual_size = _sqlite_file_size_bytes(shard_path)
                manifest_count = int(row["message_count"] or 0)
                manifest_size = int(row["file_size_bytes"] or 0)
                needs_manifest_sync = (
                    manifest_count != actual_count or manifest_size != actual_size
                )
                if (
                    missing_schema_tables
                    or missing_indexes
                    or needs_manifest_sync
                    or link_repair_delta
                    or stale_payload_rows
                    or stale_media_rows
                ):
                    repaired_shards += 1
                if missing_schema_tables:
                    repaired_schema_tables += len(missing_schema_tables)
                if missing_indexes:
                    repaired_indexes += len(missing_indexes)
                if link_repair_delta:
                    repaired_link_rows += link_repair_delta
                if stale_payload_rows:
                    repaired_stale_payload_rows += stale_payload_rows
                if stale_media_rows:
                    repaired_stale_media_rows += stale_media_rows
                if needs_manifest_sync:
                    repaired_manifest_metadata += 1
                    if apply:
                        manifest.execute(
                            """
                            UPDATE archive_shards
                            SET message_count = ?,
                                file_size_bytes = ?
                            WHERE shard_id = ?
                            """,
                            (actual_count, actual_size, shard_id),
                        )
            except sqlite3.Error as exc:
                skipped += 1
                reason = f"{shard_id}: repair failed: {exc}"
                skipped_reasons.append(reason)
                errors.append(reason)
            finally:
                conn.close()
        if apply:
            manifest.commit()
    finally:
        manifest.close()

    return ArchiveRepairReport(
        root_dir=root_dir,
        manifest_path=manifest_path,
        manifest_exists=True,
        dry_run=not apply,
        checked_shards=checked,
        repaired_shards=repaired_shards,
        repaired_indexes=repaired_indexes,
        repaired_schema_tables=repaired_schema_tables,
        repaired_manifest_metadata=repaired_manifest_metadata,
        repaired_link_rows=repaired_link_rows,
        repaired_stale_payload_rows=repaired_stale_payload_rows,
        repaired_stale_media_rows=repaired_stale_media_rows,
        pruned_missing_shards=pruned_missing_shards,
        skipped_shards=skipped,
        skipped_reasons=tuple(skipped_reasons),
        errors=tuple(errors),
    )


def _tracked_link_repair_delta(conn: sqlite3.Connection) -> int:
    expected = _expected_archive_tracked_links(conn)
    actual = _actual_archive_tracked_links(conn)
    return len(expected.symmetric_difference(actual))


def _orphaned_shard_files(root_dir: Path) -> tuple[Path, ...]:
    shards_dir = root_dir / "shards"
    if not shards_dir.is_dir():
        return ()
    candidates: list[Path] = []
    for group_dir in shards_dir.iterdir():
        if (
            group_dir.is_symlink()
            or not group_dir.is_dir()
            or _ARCHIVE_GROUP_DIRECTORY_RE.fullmatch(group_dir.name) is None
        ):
            continue
        for path in group_dir.iterdir():
            match = _ARCHIVE_SHARD_FILENAME_RE.fullmatch(path.name)
            if match is None or not path.is_file():
                continue
            if int(match.group("year")) == 0:
                continue
            sequence = match.group("sequence")
            if sequence is not None and int(sequence) < 2:
                continue
            candidates.append(path)
    return tuple(sorted(candidates))


def _orphaned_shard_errors(orphaned_shards: tuple[Path, ...]) -> tuple[str, ...]:
    if not orphaned_shards:
        return ()
    return (
        "archive root has shard file(s) but no manifest "
        f"(count={len(orphaned_shards)})",
    )


def _unregistered_shard_files(
    root_dir: Path,
    registered_shard_paths: tuple[Path, ...],
) -> tuple[Path, ...]:
    registered = {_normalized_path_key(path) for path in registered_shard_paths}
    return tuple(
        path
        for path in _orphaned_shard_files(root_dir)
        if _normalized_path_key(path) not in registered
    )


def _unregistered_shard_errors(
    unregistered_shards: tuple[Path, ...],
) -> tuple[str, ...]:
    if not unregistered_shards:
        return ()
    return (
        "archive root has unregistered shard file(s) "
        f"(count={len(unregistered_shards)})",
    )


def _normalized_path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _incomplete_tracked_ref_metadata_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS incomplete_count
        FROM archive_messages
        WHERE payload_mode = 'tracked_ref'
          AND (
              tracked_db_path IS NULL
              OR tracked_message_chat_id IS NULL
              OR tracked_message_id IS NULL
          )
        """
    ).fetchone()
    return int(row["incomplete_count"] or 0) if row is not None else 0


def _tracked_ref_archive_media_count(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "archive_media"):
        return 0
    row = conn.execute(
        """
        SELECT COUNT(*) AS stale_media_count
        FROM archive_media AS media
        INNER JOIN archive_messages AS message
          ON message.chat_id = media.chat_id
         AND message.message_id = media.message_id
        WHERE message.payload_mode = 'tracked_ref'
        """
    ).fetchone()
    return int(row["stale_media_count"] or 0) if row is not None else 0


def _tracked_ref_archive_payload_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS stale_payload_count
        FROM archive_messages
        WHERE payload_mode = 'tracked_ref'
          AND (text IS NOT NULL OR raw_text IS NOT NULL)
        """
    ).fetchone()
    return int(row["stale_payload_count"] or 0) if row is not None else 0


def _clear_tracked_ref_archive_payload(conn: sqlite3.Connection) -> None:
    now = _serialize_dt(_utc_now())
    with conn:
        conn.execute(
            """
            UPDATE archive_messages
            SET text = NULL,
                raw_text = NULL,
                updated_at = ?
            WHERE payload_mode = 'tracked_ref'
              AND (text IS NOT NULL OR raw_text IS NOT NULL)
            """,
            (now,),
        )


def _delete_tracked_ref_archive_media(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute(
            """
            DELETE FROM archive_media
            WHERE EXISTS (
                SELECT 1
                FROM archive_messages AS message
                WHERE message.chat_id = archive_media.chat_id
                  AND message.message_id = archive_media.message_id
                  AND message.payload_mode = 'tracked_ref'
            )
            """
        )


def _rebuild_archive_tracked_links(conn: sqlite3.Connection) -> None:
    expected = _expected_archive_tracked_links(conn)
    now = _serialize_dt(_utc_now())
    with conn:
        conn.execute("DELETE FROM archive_tracked_links")
        conn.executemany(
            """
            INSERT INTO archive_tracked_links (
                chat_id, message_id, tracked_db_path, tracked_chat_id,
                tracked_message_id, linked_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chat_id,
                    message_id,
                    tracked_db_path,
                    tracked_chat_id,
                    tracked_message_id,
                    now,
                )
                for (
                    chat_id,
                    message_id,
                    tracked_db_path,
                    tracked_chat_id,
                    tracked_message_id,
                ) in sorted(expected)
            ],
        )


def _expected_archive_tracked_links(
    conn: sqlite3.Connection,
) -> set[tuple[int, int, str, int, int]]:
    rows = conn.execute(
        """
        SELECT
            chat_id,
            message_id,
            tracked_db_path,
            tracked_message_chat_id,
            tracked_message_id
        FROM archive_messages
        WHERE payload_mode = 'tracked_ref'
          AND tracked_db_path IS NOT NULL
          AND tracked_message_chat_id IS NOT NULL
          AND tracked_message_id IS NOT NULL
        """
    ).fetchall()
    return {
        (
            int(row["chat_id"]),
            int(row["message_id"]),
            str(row["tracked_db_path"]),
            int(row["tracked_message_chat_id"]),
            int(row["tracked_message_id"]),
        )
        for row in rows
    }


def _actual_archive_tracked_links(
    conn: sqlite3.Connection,
) -> set[tuple[int, int, str, int, int]]:
    rows = conn.execute(
        """
        SELECT
            chat_id,
            message_id,
            tracked_db_path,
            tracked_chat_id,
            tracked_message_id
        FROM archive_tracked_links
        """
    ).fetchall()
    return {
        (
            int(row["chat_id"]),
            int(row["message_id"]),
            str(row["tracked_db_path"]),
            int(row["tracked_chat_id"]),
            int(row["tracked_message_id"]),
        )
        for row in rows
    }


def _missing_required_indexes(conn: sqlite3.Connection) -> tuple[str, ...]:
    existing = {
        str(row["name"])
        for row in conn.execute("PRAGMA index_list(archive_messages)").fetchall()
    }
    existing.update(
        str(row["name"])
        for row in conn.execute("PRAGMA index_list(archive_tracked_links)").fetchall()
    )
    return tuple(index for index in REQUIRED_SHARD_INDEXES if index not in existing)


def _missing_additive_manifest_tables(conn: sqlite3.Connection) -> tuple[str, ...]:
    existing = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    return tuple(table for table in ADDITIVE_MANIFEST_TABLES if table not in existing)


def _manifest_tracked_db_link_count(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS link_count FROM tracked_db_links WHERE status = 'active'"
        ).fetchone()
    except sqlite3.Error:
        return 0
    return int(row["link_count"] or 0) if row is not None else 0


def _manifest_tracked_db_link_exists(
    conn: sqlite3.Connection,
    root_dir: Path,
    tracked_db_path: Path,
) -> bool:
    tracked_path_values = _tracked_db_path_values(root_dir, tracked_db_path)
    placeholders = ", ".join("?" for _ in tracked_path_values)
    try:
        row = conn.execute(
            f"""
            SELECT 1
            FROM tracked_db_links
            WHERE status = 'active' AND tracked_db_path IN ({placeholders})
            LIMIT 1
            """,
            tracked_path_values,
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _tracked_db_is_readable(tracked_db_path: Path) -> bool:
    return _tracked_db_context_error(tracked_db_path) is None


def _tracked_db_context_error(tracked_db_path: Path) -> str | None:
    return _tracked_db_schema_error(
        tracked_db_path,
        required_columns={"chat_id", "message_id", "date", "text", "replied_text"},
    )


def _tracked_db_schema_error(
    tracked_db_path: Path,
    *,
    required_columns: set[str],
) -> str | None:
    if not tracked_db_path.exists():
        return "missing tracked DB"
    try:
        conn = connect_readonly(tracked_db_path)
    except sqlite3.Error:
        return "unreadable tracked DB"
    try:
        rows = conn.execute("PRAGMA table_info(messages)").fetchall()
    except sqlite3.Error:
        return "tracked DB messages schema unreadable"
    finally:
        conn.close()
    columns = {str(row["name"]) for row in rows}
    missing_columns = sorted(required_columns.difference(columns))
    if missing_columns:
        if not columns:
            return "tracked DB missing messages table"
        return "tracked DB messages table missing column(s): " + ", ".join(
            missing_columns
        )
    return None


def _shard_message_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS message_count FROM archive_messages").fetchone()
    return int(row["message_count"] or 0) if row is not None else 0


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        LIMIT 1
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _missing_core_shard_tables(conn: sqlite3.Connection) -> tuple[str, ...]:
    existing = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    return tuple(table for table in CORE_SHARD_TABLES if table not in existing)


def _missing_additive_shard_tables(conn: sqlite3.Connection) -> tuple[str, ...]:
    existing = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    return tuple(table for table in ADDITIVE_SHARD_TABLES if table not in existing)


def _fetch_context_messages_from_shard(
    conn: sqlite3.Connection,
    root_dir: Path,
    tracked_db_path: Path,
    *,
    chat_id: int,
    since: datetime,
    until: datetime,
    topic_id: int | None,
) -> list[ArchiveContextMessage]:
    params: list[object] = [
        chat_id,
        _serialize_dt(since),
        _serialize_dt(until),
    ]
    topic_clause = ""
    if topic_id is not None:
        topic_clause = " AND a.topic_id = ?"
        params.append(topic_id)

    tracked_attached = False
    tracked_path_values = _tracked_db_path_values(root_dir, tracked_db_path)
    tracked_path_placeholders = ", ".join("?" for _ in tracked_path_values)
    tracked_path_match = f"a.tracked_db_path IN ({tracked_path_placeholders})"
    if _tracked_db_context_error(tracked_db_path) is None:
        try:
            conn.execute(
                "ATTACH DATABASE ? AS tracked",
                (f"{tracked_db_path.resolve().as_uri()}?mode=ro",),
            )
            tracked_attached = True
        except sqlite3.Error:
            tracked_attached = False

    if tracked_attached:
        tracked_select = f"""
            t.text AS tracked_text,
            t.replied_text AS tracked_replied_text,
            CASE WHEN t.chat_id IS NULL THEN 0 ELSE 1 END AS tracked_row_found,
            CASE
              WHEN {tracked_path_match} THEN 1
              ELSE 0
            END AS tracked_db_matches_current
        """
        tracked_join = f"""
            LEFT JOIN tracked.messages AS t
              ON t.chat_id = a.tracked_message_chat_id
             AND t.message_id = a.tracked_message_id
             AND {tracked_path_match}
        """
        query_params = [*tracked_path_values, *tracked_path_values, *params]
    else:
        tracked_select = f"""
            NULL AS tracked_text,
            NULL AS tracked_replied_text,
            0 AS tracked_row_found,
            CASE
              WHEN {tracked_path_match} THEN 1
              ELSE 0
            END AS tracked_db_matches_current
        """
        tracked_join = ""
        query_params = [*tracked_path_values, *params]

    if _table_exists(conn, "archive_senders"):
        sender_select = """
            s.username AS sender_username,
            s.display_name AS sender_display_name,
            s.first_seen_at AS sender_first_seen_at,
            s.last_seen_at AS sender_last_seen_at
        """
        sender_join = "LEFT JOIN archive_senders AS s ON s.sender_id = a.sender_id"
    else:
        sender_select = """
            NULL AS sender_username,
            NULL AS sender_display_name,
            NULL AS sender_first_seen_at,
            NULL AS sender_last_seen_at
        """
        sender_join = ""

    try:
        rows = conn.execute(
            f"""
            SELECT a.*, {tracked_select}, {sender_select}
            FROM archive_messages AS a
            {tracked_join}
            {sender_join}
            WHERE a.chat_id = ?
              AND a.date >= ?
              AND a.date <= ?
              {topic_clause}
            ORDER BY a.date ASC, a.message_id ASC
            """,
            query_params,
        ).fetchall()
    finally:
        if tracked_attached:
            conn.execute("DETACH DATABASE tracked")
    media_by_message = _fetch_archive_media_for_rows(conn, rows)
    return [
        _row_to_context_message(
            row,
            media=media_by_message.get(
                (int(row["chat_id"]), int(row["message_id"])),
                (),
            ),
        )
        for row in rows
    ]


def _fetch_target_archive_topic_from_shard(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    message_id: int,
) -> tuple[bool, int | None]:
    row = conn.execute(
        """
        SELECT topic_id
        FROM archive_messages
        WHERE chat_id = ? AND message_id = ?
        LIMIT 1
        """,
        (chat_id, message_id),
    ).fetchone()
    if row is None:
        return False, None
    topic_id = row["topic_id"]
    return True, int(topic_id) if topic_id is not None else None


def _build_shard(
    root_dir: Path,
    chat_id: int,
    starts_at: datetime,
    ends_at: datetime,
    sequence: int,
) -> ArchiveShard:
    month = starts_at.strftime("%Y-%m")
    filename = f"{month}.sqlite3" if sequence == 1 else f"{month}-{sequence:03d}.sqlite3"
    path = root_dir / "shards" / f"group_{chat_id}" / filename
    shard_id = f"{chat_id}:{month}:{sequence:03d}"
    return ArchiveShard(
        shard_id=shard_id,
        chat_id=chat_id,
        path=path,
        starts_at=starts_at,
        ends_at=ends_at,
        sequence=sequence,
    )


def _manifest_shard_path_value(root_dir: Path, shard_path: Path) -> str:
    try:
        return str(shard_path.relative_to(root_dir))
    except ValueError:
        return str(shard_path)


def _tracked_db_path_value(root_dir: Path | None, tracked_db_path: Path) -> str:
    if root_dir is None:
        return str(tracked_db_path)
    try:
        return os.path.relpath(tracked_db_path, root_dir)
    except ValueError:
        return str(tracked_db_path)


def _tracked_db_path_values(root_dir: Path, tracked_db_path: Path) -> tuple[str, ...]:
    values = (
        str(tracked_db_path),
        _tracked_db_path_value(root_dir, tracked_db_path),
    )
    return tuple(dict.fromkeys(values))


def _resolve_manifest_shard_path(root_dir: Path, stored_path: object) -> Path:
    shard_path = Path(str(stored_path))
    if shard_path.is_absolute():
        return shard_path
    return root_dir / shard_path


def _sqlite_file_size_bytes(path: Path) -> int:
    total = path.stat().st_size if path.exists() else 0
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            total += sidecar.stat().st_size
    return total


def _row_to_shard(row: sqlite3.Row, root_dir: Path) -> ArchiveShard:
    _, _, sequence_raw = str(row["shard_id"]).rpartition(":")
    return ArchiveShard(
        shard_id=str(row["shard_id"]),
        chat_id=int(row["chat_id"]),
        path=_resolve_manifest_shard_path(root_dir, row["path"]),
        starts_at=_deserialize_dt(row["starts_at"]),
        ends_at=_deserialize_dt(row["ends_at"]),
        sequence=int(sequence_raw),
    )


def _row_to_message(row: sqlite3.Row) -> DbArchiveMessage:
    return DbArchiveMessage(
        chat_id=int(row["chat_id"]),
        message_id=int(row["message_id"]),
        topic_id=int(row["topic_id"]) if row["topic_id"] is not None else None,
        sender_id=int(row["sender_id"]) if row["sender_id"] is not None else None,
        date=_deserialize_dt(row["date"]),
        text=row["text"],
        raw_text=row["raw_text"],
        message_kind=row["message_kind"],
        reply_to_msg_id=(
            int(row["reply_to_msg_id"]) if row["reply_to_msg_id"] is not None else None
        ),
        reply_to_top_id=(
            int(row["reply_to_top_id"]) if row["reply_to_top_id"] is not None else None
        ),
        is_forum_topic_link=bool(row["is_forum_topic_link"]),
        has_media=bool(row["has_media"]),
        tracked_db_path=row["tracked_db_path"],
        tracked_message_chat_id=(
            int(row["tracked_message_chat_id"])
            if row["tracked_message_chat_id"] is not None
            else None
        ),
        tracked_message_id=(
            int(row["tracked_message_id"])
            if row["tracked_message_id"] is not None
            else None
        ),
        payload_mode=row["payload_mode"],
    )


def _fetch_archive_media_for_rows(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
) -> dict[tuple[int, int], tuple[ArchiveMedia, ...]]:
    if not rows or not _table_exists(conn, "archive_media"):
        return {}
    media_by_message: dict[tuple[int, int], list[ArchiveMedia]] = {}
    message_ids_by_chat: dict[int, set[int]] = {}
    for row in rows:
        message_ids_by_chat.setdefault(int(row["chat_id"]), set()).add(
            int(row["message_id"])
        )
    for chat_id, message_ids in message_ids_by_chat.items():
        sorted_ids = sorted(message_ids)
        for start in range(0, len(sorted_ids), ARCHIVE_CONTEXT_MEDIA_ID_CHUNK_SIZE):
            chunk = sorted_ids[start : start + ARCHIVE_CONTEXT_MEDIA_ID_CHUNK_SIZE]
            placeholders = ", ".join("?" for _ in chunk)
            media_rows = conn.execute(
                f"""
                SELECT chat_id, message_id, media_index, media_kind, mime_type,
                       file_size, file_name
                FROM archive_media
                WHERE chat_id = ?
                  AND message_id IN ({placeholders})
                ORDER BY chat_id ASC, message_id ASC, media_index ASC
                """,
                [chat_id, *chunk],
            ).fetchall()
            for media_row in media_rows:
                key = (int(media_row["chat_id"]), int(media_row["message_id"]))
                media_by_message.setdefault(key, []).append(
                    ArchiveMedia(
                        media_index=int(media_row["media_index"]),
                        media_kind=str(media_row["media_kind"]),
                        mime_type=media_row["mime_type"],
                        file_size=(
                            int(media_row["file_size"])
                            if media_row["file_size"] is not None
                            else None
                        ),
                        file_name=media_row["file_name"],
                    )
                )
    return {key: tuple(value) for key, value in media_by_message.items()}


def _row_to_context_message(
    row: sqlite3.Row,
    *,
    media: tuple[ArchiveMedia, ...] = (),
) -> ArchiveContextMessage:
    tracked_text = row["tracked_text"]
    text = row["text"]
    tracked_row_found = bool(row["tracked_row_found"])
    tracked_db_matches_current = bool(row["tracked_db_matches_current"])
    if row["payload_mode"] == "tracked_ref":
        effective_text = (
            tracked_text
            if tracked_row_found and tracked_db_matches_current
            else None
        )
        media = ()
    else:
        effective_text = text
    sender = None
    if row["sender_first_seen_at"] is not None and row["sender_id"] is not None:
        sender = ArchiveSender(
            sender_id=int(row["sender_id"]),
            username=_normalize_username(row["sender_username"]),
            display_name=_normalize_optional_text(row["sender_display_name"]),
            first_seen_at=_deserialize_dt(row["sender_first_seen_at"]),
            last_seen_at=_deserialize_dt(row["sender_last_seen_at"]),
        )
    return ArchiveContextMessage(
        chat_id=int(row["chat_id"]),
        message_id=int(row["message_id"]),
        topic_id=int(row["topic_id"]) if row["topic_id"] is not None else None,
        sender_id=int(row["sender_id"]) if row["sender_id"] is not None else None,
        date=_deserialize_dt(row["date"]),
        text=text,
        effective_text=effective_text,
        payload_mode=row["payload_mode"],
        tracked_text=tracked_text,
        tracked_replied_text=row["tracked_replied_text"],
        tracked_row_found=tracked_row_found,
        tracked_db_matches_current=tracked_db_matches_current,
        tracked_message_chat_id=(
            int(row["tracked_message_chat_id"])
            if row["tracked_message_chat_id"] is not None
            else None
        ),
        tracked_message_id=(
            int(row["tracked_message_id"])
            if row["tracked_message_id"] is not None
            else None
        ),
        reply_to_msg_id=(
            int(row["reply_to_msg_id"]) if row["reply_to_msg_id"] is not None else None
        ),
        reply_to_top_id=(
            int(row["reply_to_top_id"]) if row["reply_to_top_id"] is not None else None
        ),
        media=media,
        sender=sender,
    )


def _tracked_message_exists(db_path: Path, chat_id: int, message_id: int) -> bool:
    if not db_path.exists():
        return False
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM messages
            WHERE chat_id = ? AND message_id = ?
            LIMIT 1
            """,
            (chat_id, message_id),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _month_bounds(dt: datetime) -> tuple[datetime, datetime]:
    dt = _ensure_utc(dt)
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _serialize_dt(dt: datetime) -> str:
    return _ensure_utc(dt).isoformat()


def _deserialize_dt(raw: str | None) -> datetime:
    if raw is None:
        raise ValueError("datetime value is missing")
    return datetime.fromisoformat(raw).astimezone(timezone.utc)


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized or None


def _normalize_username(value: object) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    normalized = normalized.lstrip("@").strip()
    return normalized or None


def _row_to_archive_sender(row: sqlite3.Row) -> ArchiveSender:
    return ArchiveSender(
        sender_id=int(row["sender_id"]),
        username=_normalize_username(row["username"]),
        display_name=_normalize_optional_text(row["display_name"]),
        first_seen_at=_deserialize_dt(row["first_seen_at"]),
        last_seen_at=_deserialize_dt(row["last_seen_at"]),
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
