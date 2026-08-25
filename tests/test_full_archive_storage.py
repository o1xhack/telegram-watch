from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import sqlite3
from time import perf_counter

import pytest

from telegram_watch import storage as tracked_storage
from telegram_watch import full_archive_storage as archive_storage


def archive_message(
    message_id: int,
    *,
    chat_id: int = -1001,
    topic_id: int | None = None,
    sender_id: int | None = 123,
    date: datetime | None = None,
    text: str | None = "hello",
    reply_to_msg_id: int | None = None,
    reply_to_top_id: int | None = None,
    media: tuple[archive_storage.ArchiveMedia, ...] = (),
) -> archive_storage.ArchiveMessage:
    effective_reply_to_top_id = reply_to_top_id if reply_to_top_id is not None else topic_id
    return archive_storage.ArchiveMessage(
        chat_id=chat_id,
        message_id=message_id,
        topic_id=topic_id,
        sender_id=sender_id,
        date=date or datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        text=text,
        raw_text=text,
        message_kind="message",
        reply_to_msg_id=reply_to_msg_id,
        reply_to_top_id=effective_reply_to_top_id,
        is_forum_topic_link=topic_id is not None,
        has_media=bool(media),
        media=media,
    )


def test_manifest_and_shard_schema_are_idempotent(tmp_path):
    manifest = archive_storage.connect(tmp_path / "manifest.sqlite3")
    archive_storage.ensure_manifest_schema(manifest)
    archive_storage.ensure_manifest_schema(manifest)

    shard = archive_storage.connect(tmp_path / "shard.sqlite3")
    archive_storage.ensure_shard_schema(shard)
    archive_storage.ensure_shard_schema(shard)

    assert manifest.execute("SELECT COUNT(*) FROM archive_shards").fetchone()[0] == 0
    assert shard.execute("SELECT COUNT(*) FROM archive_messages").fetchone()[0] == 0
    assert shard.execute("SELECT COUNT(*) FROM archive_media").fetchone()[0] == 0


def test_archive_sender_upsert_preserves_seen_range_and_known_fields(tmp_path):
    shard = archive_storage.connect(tmp_path / "shard.sqlite3")
    first = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    last = first + timedelta(days=2)
    try:
        archive_storage.persist_archive_sender(
            shard,
            archive_storage.ArchiveSender(
                sender_id=123,
                username="alice",
                display_name="Alice Old",
                first_seen_at=first + timedelta(hours=1),
                last_seen_at=last - timedelta(hours=1),
            ),
        )
        archive_storage.persist_archive_sender(
            shard,
            archive_storage.ArchiveSender(
                sender_id=123,
                username=None,
                display_name="Alice New",
                first_seen_at=first,
                last_seen_at=last,
            ),
        )
        sender = archive_storage.fetch_archive_sender(shard, 123)
    finally:
        shard.close()

    assert sender == archive_storage.ArchiveSender(
        sender_id=123,
        username="alice",
        display_name="Alice New",
        first_seen_at=first,
        last_seen_at=last,
    )


def test_archive_sender_label_never_falls_back_to_raw_id() -> None:
    sender = archive_storage.ArchiveSender(
        sender_id=987654321,
        username="alice",
        display_name="Alice",
        first_seen_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )

    assert archive_storage.format_archive_sender_label(sender, alias="Core analyst") == "Core analyst"
    assert archive_storage.format_archive_sender_label(sender) == "Alice (@alice)"
    assert archive_storage.format_archive_sender_label(None) == "Anonymous sender"
    assert "987654321" not in archive_storage.format_archive_sender_label(None)


def test_archive_sender_candidates_reuse_snapshot_across_shards(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    may = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    june = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    shard_paths = []
    try:
        for message_id, message_date in ((1, may), (2, june)):
            shard_meta = archive_storage.select_shard(
                manifest,
                root_dir,
                chat_id=-1001,
                message_date=message_date,
                max_messages_per_shard=500_000,
                max_shard_size_bytes=1024 * 1024,
            )
            shard_paths.append(shard_meta.path)
            shard = archive_storage.connect(shard_meta.path)
            try:
                sender = None
                if message_id == 1:
                    sender = archive_storage.ArchiveSender(
                        sender_id=123,
                        username="alice",
                        display_name="Alice",
                        first_seen_at=may,
                        last_seen_at=may,
                    )
                archive_storage.persist_archive_message_with_result(
                    shard,
                    archive_message(message_id, date=message_date),
                    sender=sender,
                )
                archive_storage.record_shard_write(manifest, shard_meta)
            finally:
                shard.close()
    finally:
        manifest.close()

    candidates = archive_storage.list_archive_sender_candidates(root_dir)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.sender_id == 123
    assert candidate.first_seen_at == may
    assert candidate.last_seen_at == june
    assert candidate.existing_sender is not None
    assert candidate.existing_sender.display_name == "Alice"
    assert set(candidate.shard_paths) == set(shard_paths)

    snapshot = archive_storage.ArchiveSender(
        sender_id=123,
        username=candidate.existing_sender.username,
        display_name=candidate.existing_sender.display_name,
        first_seen_at=candidate.first_seen_at,
        last_seen_at=candidate.last_seen_at,
    )
    assert archive_storage.persist_archive_sender_to_shards(
        snapshot,
        candidate.shard_paths,
    ) == 2
    assert archive_storage.list_archive_sender_candidates(root_dir) == ()


def test_ensure_archive_sender_schema_updates_registered_shards_without_senders(
    tmp_path,
):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    message_date = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    try:
        shard_meta = archive_storage.select_shard(
            manifest,
            root_dir,
            chat_id=-1001,
            message_date=message_date,
            max_messages_per_shard=500_000,
            max_shard_size_bytes=1024 * 1024,
        )
        shard = archive_storage.connect(shard_meta.path)
        try:
            archive_storage.persist_archive_message(
                shard,
                archive_message(1, sender_id=None, date=message_date),
            )
            shard.execute("DROP TABLE archive_senders")
            shard.commit()
            archive_storage.record_shard_write(manifest, shard_meta)
        finally:
            shard.close()
    finally:
        manifest.close()

    assert archive_storage.ensure_archive_sender_schema(root_dir) == 1
    assert archive_storage.ensure_archive_sender_schema(root_dir) == 0
    shard = archive_storage.connect_readonly(shard_meta.path)
    try:
        sender_table = shard.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("archive_senders",),
        ).fetchone()
    finally:
        shard.close()

    assert sender_table is not None
    assert archive_storage.list_archive_sender_candidates(root_dir) == ()


def test_deleting_archive_root_does_not_affect_tracked_db(tmp_path):
    root_dir = tmp_path / "data" / "full_archive"
    tracked_db_path = tmp_path / "data" / "tgwatch.sqlite3"
    message_date = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    tracked = tracked_storage.connect(tracked_db_path)
    try:
        tracked_storage.ensure_schema(tracked)
        tracked_storage.persist_message(
            tracked,
            tracked_storage.StoredMessage(
                chat_id=-1001,
                message_id=1,
                sender_id=123,
                date=message_date,
                text="tracked payload survives archive deletion",
                reply_to_msg_id=None,
                replied_sender_id=None,
                replied_date=None,
                replied_text=None,
            ),
            [],
        )
    finally:
        tracked.close()

    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    try:
        shard_meta = archive_storage.select_shard(
            manifest,
            root_dir,
            chat_id=-1001,
            message_date=message_date,
            max_messages_per_shard=500_000,
            max_shard_size_bytes=1024 * 1024,
        )
        shard = archive_storage.connect(shard_meta.path)
        try:
            archive_storage.persist_archive_message(
                shard,
                archive_message(1, date=message_date, text="duplicate archive text"),
                tracked_db_path=tracked_db_path,
                archive_root_dir=root_dir,
            )
            archive_storage.record_shard_write(manifest, shard_meta)
            archive_storage.record_tracked_db_link(
                manifest,
                tracked_db_path,
                archive_root_dir=root_dir,
            )
        finally:
            shard.close()
    finally:
        manifest.close()

    shutil.rmtree(root_dir)

    reopened = tracked_storage.connect(tracked_db_path)
    try:
        rows = tracked_storage.fetch_messages_between(
            reopened,
            [123],
            message_date,
            message_date,
            chat_ids=[-1001],
        )
    finally:
        reopened.close()

    assert not root_dir.exists()
    assert [row.text for row in rows] == ["tracked payload survives archive deletion"]


def test_archive_connections_enable_wal_and_busy_timeout(tmp_path):
    db_path = tmp_path / "archive.sqlite3"
    conn = archive_storage.connect(db_path)
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    finally:
        conn.close()

    readonly = archive_storage.connect_readonly(db_path)
    try:
        readonly_busy_timeout = readonly.execute("PRAGMA busy_timeout").fetchone()[0]
    finally:
        readonly.close()

    assert str(journal_mode).lower() == "wal"
    assert busy_timeout == 5000
    assert readonly_busy_timeout == 5000


def test_inspect_archive_status_without_manifest_is_empty_and_readonly(tmp_path):
    root_dir = tmp_path / "full_archive"

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.manifest_exists is False
    assert report.shard_count == 0
    assert report.errors == ()
    assert not root_dir.exists()


def test_inspect_archive_status_degrades_orphaned_shards_without_manifest(tmp_path):
    root_dir = tmp_path / "full_archive"
    orphaned_shard = root_dir / "shards" / "group_-1001" / "2026-05.sqlite3"
    orphaned_shard.parent.mkdir(parents=True)
    sqlite3.connect(orphaned_shard).close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.manifest_exists is False
    assert report.shard_count == 0
    assert report.errors == (
        "archive root has shard file(s) but no manifest (count=1)",
    )
    assert str(orphaned_shard) not in " ".join(report.errors)
    assert report.degraded is True


@pytest.mark.parametrize("manifest_exists", [False, True])
@pytest.mark.parametrize(
    "relative_path",
    [
        "tgwatch.sqlite3",
        "group_-1001/tgwatch.sqlite3",
        "group_-1001/2026-00.sqlite3",
        "group_-1001/2026-13.sqlite3",
        "group_-1001/2026-05-001.sqlite3",
        "group_-1001/2026-05-0002.sqlite3",
        "group_-1001/2026-05-01000.sqlite3",
        "group_-1001/nested/2026-05.sqlite3",
        "group_invalid/2026-05.sqlite3",
        "backup/2026-05.sqlite3",
    ],
)
def test_inspect_archive_status_ignores_non_shard_sqlite_files(
    tmp_path,
    manifest_exists,
    relative_path,
):
    root_dir = tmp_path / "full_archive"
    unrelated_sqlite = root_dir / "shards" / relative_path
    unrelated_sqlite.parent.mkdir(parents=True)
    unrelated_sqlite.touch()
    if manifest_exists:
        manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
        try:
            archive_storage.ensure_manifest_schema(manifest)
        finally:
            manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.manifest_exists is manifest_exists
    assert report.errors == ()
    assert report.degraded is False


@pytest.mark.parametrize("sequence", ["002", "1000"])
def test_inspect_archive_status_preserves_zero_byte_canonical_orphan(
    tmp_path,
    sequence,
):
    root_dir = tmp_path / "full_archive"
    orphaned_shard = (
        root_dir / "shards" / "group_-1001" / f"2026-05-{sequence}.sqlite3"
    )
    orphaned_shard.parent.mkdir(parents=True)
    orphaned_shard.touch()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.errors == (
        "archive root has shard file(s) but no manifest (count=1)",
    )
    assert report.degraded is True


def test_inspect_archive_status_degrades_unregistered_shards_with_manifest(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    registered = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(registered.path)
    archive_storage.ensure_shard_schema(shard)
    shard.close()
    manifest.close()
    unregistered_shard = root_dir / "shards" / "group_-1001" / "2026-05-999.sqlite3"
    sqlite3.connect(unregistered_shard).close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.errors == (
        "archive root has unregistered shard file(s) (count=1)",
    )
    assert str(unregistered_shard) not in " ".join(report.errors)
    assert report.degraded is True


def test_archive_status_report_degraded_uses_structured_health_counts(tmp_path):
    report = archive_storage.ArchiveStatusReport(
        root_dir=tmp_path,
        manifest_path=tmp_path / "manifest.sqlite3",
        manifest_exists=True,
        shard_count=1,
        missing_shard_count=0,
        manifest_message_count=0,
        actual_message_count=0,
        archive_row_count=0,
        tracked_ref_count=0,
        link_count=0,
        media_metadata_count=0,
        tracked_db_link_count=0,
        file_size_bytes=0,
        missing_index_count=1,
        missing_schema_table_count=0,
        errors=(),
        shards=(),
    )

    assert report.degraded is True


def test_select_shard_uses_group_month_and_rotates_by_month(tmp_path):
    manifest = archive_storage.connect(tmp_path / "manifest.sqlite3")
    root_dir = tmp_path / "full_archive"

    first = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    same_month = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 20, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    next_month = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )

    assert same_month == first
    assert first.path.name == "2026-05.sqlite3"
    assert next_month.path.name == "2026-06.sqlite3"


def test_relative_shard_paths_survive_archive_root_move(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    stored_path = manifest.execute(
        "SELECT path FROM archive_shards WHERE shard_id = ?",
        (shard_meta.shard_id,),
    ).fetchone()[0]
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(shard, archive_message(1, text="context"))
    archive_storage.record_shard_write(manifest, shard_meta)
    archive_storage.record_tracked_db_link(manifest, tmp_path / "tracked.sqlite3")
    shard.close()
    manifest.close()

    moved_root = tmp_path / "restored_full_archive"
    root_dir.rename(moved_root)

    moved_manifest = archive_storage.connect(moved_root / "manifest.sqlite3")
    try:
        found_shard = archive_storage.find_shard_for_message(
            moved_manifest,
            moved_root,
            chat_id=-1001,
            message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
            message_id=1,
        )
    finally:
        moved_manifest.close()
    status = archive_storage.inspect_archive_status(moved_root)
    context = archive_storage.fetch_context_result(
        moved_root,
        tmp_path / "tracked.sqlite3",
        chat_id=-1001,
        since=datetime(2026, 5, 1, 11, 59, tzinfo=timezone.utc),
        until=datetime(2026, 5, 1, 12, 1, tzinfo=timezone.utc),
    )
    repair = archive_storage.repair_archive_metadata(moved_root, apply=False)

    assert Path(stored_path) == Path("shards") / "group_-1001" / "2026-05.sqlite3"
    assert found_shard is not None
    assert found_shard.path == moved_root / stored_path
    assert status.missing_shard_count == 0
    assert status.actual_message_count == 1
    assert status.errors == ()
    assert [message.text for message in context.messages] == ["context"]
    assert context.skipped_shards == ()
    assert context.errors == ()
    assert repair.checked_shards == 1
    assert repair.skipped_shards == 0


def test_absolute_manifest_shard_paths_remain_compatible(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(shard, archive_message(1, text="context"))
    archive_storage.record_shard_write(manifest, shard_meta)
    archive_storage.record_tracked_db_link(manifest, tmp_path / "tracked.sqlite3")
    manifest.execute(
        "UPDATE archive_shards SET path = ? WHERE shard_id = ?",
        (str(shard_meta.path), shard_meta.shard_id),
    )
    manifest.commit()
    shard.close()
    manifest.close()

    reopened_manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    try:
        found_shard = archive_storage.find_shard_for_message(
            reopened_manifest,
            root_dir,
            chat_id=-1001,
            message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
            message_id=1,
        )
    finally:
        reopened_manifest.close()
    status = archive_storage.inspect_archive_status(root_dir)
    context = archive_storage.fetch_context_result(
        root_dir,
        tmp_path / "tracked.sqlite3",
        chat_id=-1001,
        since=datetime(2026, 5, 1, 11, 59, tzinfo=timezone.utc),
        until=datetime(2026, 5, 1, 12, 1, tzinfo=timezone.utc),
    )
    repair = archive_storage.repair_archive_metadata(root_dir, apply=False)

    assert found_shard is not None
    assert found_shard.path == shard_meta.path
    assert status.missing_shard_count == 0
    assert status.actual_message_count == 1
    assert status.errors == ()
    assert [message.text for message in context.messages] == ["context"]
    assert context.skipped_shards == ()
    assert context.errors == ()
    assert repair.checked_shards == 1
    assert repair.skipped_shards == 0


def test_select_shard_rotates_by_message_count(tmp_path):
    manifest = archive_storage.connect(tmp_path / "manifest.sqlite3")
    root_dir = tmp_path / "full_archive"
    first = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=1,
        max_shard_size_bytes=1024 * 1024,
    )
    manifest.execute(
        "UPDATE archive_shards SET message_count = 1 WHERE shard_id = ?",
        (first.shard_id,),
    )

    second = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 2, tzinfo=timezone.utc),
        max_messages_per_shard=1,
        max_shard_size_bytes=1024 * 1024,
    )

    assert second.sequence == 2
    assert second.path.name == "2026-05-002.sqlite3"


def test_select_shard_allocates_after_max_existing_sequence(tmp_path):
    manifest = archive_storage.connect(tmp_path / "manifest.sqlite3")
    root_dir = tmp_path / "full_archive"
    for day in (1, 2, 3):
        shard = archive_storage.select_shard(
            manifest,
            root_dir,
            chat_id=-1001,
            message_date=datetime(2026, 5, day, tzinfo=timezone.utc),
            max_messages_per_shard=1,
            max_shard_size_bytes=1024 * 1024,
        )
        manifest.execute(
            "UPDATE archive_shards SET message_count = 1 WHERE shard_id = ?",
            (shard.shard_id,),
        )
    manifest.execute(
        "DELETE FROM archive_shards WHERE shard_id = ?",
        ("-1001:2026-05:002",),
    )

    next_shard = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 4, tzinfo=timezone.utc),
        max_messages_per_shard=1,
        max_shard_size_bytes=1024 * 1024,
    )

    assert next_shard.sequence == 4
    assert next_shard.shard_id == "-1001:2026-05:004"
    assert next_shard.path.name == "2026-05-004.sqlite3"


def test_select_shard_rotates_by_file_size(tmp_path):
    manifest = archive_storage.connect(tmp_path / "manifest.sqlite3")
    root_dir = tmp_path / "full_archive"
    first = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=5,
    )
    first.path.write_bytes(b"exceeds")

    second = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 2, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=5,
    )

    assert second.sequence == 2
    assert second.path.name == "2026-05-002.sqlite3"


def test_select_shard_rotates_by_wal_sidecar_size(tmp_path):
    manifest = archive_storage.connect(tmp_path / "manifest.sqlite3")
    root_dir = tmp_path / "full_archive"
    first = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=5,
    )
    first.path.write_bytes(b"db")
    Path(f"{first.path}-wal").write_bytes(b"exceeds")

    second = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 2, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=5,
    )

    assert second.sequence == 2
    assert second.path.name == "2026-05-002.sqlite3"


def test_inspect_archive_status_counts_wal_sidecar_size(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(shard, archive_message(1, text="context"))
    archive_storage.record_shard_write(manifest, shard_meta)
    archive_storage.record_tracked_db_link(manifest, tmp_path / "tracked.sqlite3")
    shard.close()
    manifest.close()
    Path(f"{shard_meta.path}-wal").write_bytes(b"wal-bytes")

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.shards[0].actual_file_size_bytes >= (
        shard_meta.path.stat().st_size + len(b"wal-bytes")
    )
    assert report.file_size_bytes >= (
        (root_dir / "manifest.sqlite3").stat().st_size
        + shard_meta.path.stat().st_size
        + len(b"wal-bytes")
    )


def test_persist_archive_message_and_fetch_context_window(tmp_path):
    shard = archive_storage.connect(tmp_path / "archive.sqlite3")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

    archive_storage.persist_archive_message(
        shard,
        archive_message(2, topic_id=20, date=base + timedelta(minutes=2), text="b"),
    )
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, topic_id=10, date=base + timedelta(minutes=1), text="a"),
    )
    archive_storage.persist_archive_message(
        shard,
        archive_message(3, topic_id=None, date=base + timedelta(minutes=3), text="c"),
    )

    all_rows = archive_storage.fetch_messages_between(
        shard,
        chat_id=-1001,
        since=base,
        until=base + timedelta(minutes=5),
    )
    topic_rows = archive_storage.fetch_messages_between(
        shard,
        chat_id=-1001,
        since=base,
        until=base + timedelta(minutes=5),
        topic_id=10,
    )

    assert [row.message_id for row in all_rows] == [1, 2, 3]
    assert [row.message_id for row in topic_rows] == [1]


def test_fetch_context_result_reports_target_topic_outside_filter(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=base,
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    try:
        archive_storage.persist_archive_message(
            shard,
            archive_message(10, topic_id=None, date=base, text="target in general"),
        )
        archive_storage.record_shard_write(manifest, shard_meta)
        archive_storage.persist_archive_message(
            shard,
            archive_message(
                11,
                topic_id=77,
                date=base + timedelta(seconds=30),
                text="requested topic context",
            ),
        )
        archive_storage.record_shard_write(manifest, shard_meta)
    finally:
        shard.close()
        manifest.close()

    result = archive_storage.fetch_context_result(
        root_dir,
        tmp_path / "tracked.sqlite3",
        chat_id=-1001,
        since=base - timedelta(minutes=1),
        until=base + timedelta(minutes=1),
        topic_id=77,
        target_message_id=10,
    )

    assert [row.message_id for row in result.messages] == [11]
    assert result.target_archived is True
    assert result.target_archived_topic_id is None


def test_persist_archive_message_upserts_existing_row(tmp_path):
    shard = archive_storage.connect(tmp_path / "archive.sqlite3")

    archive_storage.persist_archive_message(shard, archive_message(1, text="before"))
    archive_storage.persist_archive_message(shard, archive_message(1, text="after"))

    rows = archive_storage.fetch_messages_between(
        shard,
        chat_id=-1001,
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0].text == "after"


def test_persist_archive_message_with_result_reports_created_state(tmp_path):
    shard = archive_storage.connect(tmp_path / "archive.sqlite3")

    first = archive_storage.persist_archive_message_with_result(
        shard,
        archive_message(1, text="before"),
    )
    second = archive_storage.persist_archive_message_with_result(
        shard,
        archive_message(1, text="after"),
    )

    assert first.payload_mode == "archive"
    assert first.created is True
    assert second.payload_mode == "archive"
    assert second.created is False


def test_tracked_message_is_stored_as_link_without_duplicate_text(tmp_path):
    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            text="tracked payload",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()

    shard = archive_storage.connect(tmp_path / "archive.sqlite3")
    mode = archive_storage.persist_archive_message(
        shard,
        archive_message(1, text="duplicate payload"),
        tracked_db_path=tracked_db_path,
    )

    row = shard.execute(
        """
        SELECT text, raw_text, payload_mode, tracked_db_path, tracked_message_chat_id,
               tracked_message_id
        FROM archive_messages
        WHERE chat_id = ? AND message_id = ?
        """,
        (-1001, 1),
    ).fetchone()
    link_count = shard.execute("SELECT COUNT(*) FROM archive_tracked_links").fetchone()[0]

    assert mode == "tracked_ref"
    assert row["text"] is None
    assert row["raw_text"] is None
    assert row["payload_mode"] == "tracked_ref"
    assert row["tracked_db_path"] == str(tracked_db_path)
    assert row["tracked_message_chat_id"] == -1001
    assert row["tracked_message_id"] == 1
    assert link_count == 1


def test_fetch_context_messages_resolves_tracked_ref_text_with_attach(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, date=base, text="question", reply_to_msg_id=10),
    )

    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=2,
            sender_id=123,
            date=base + timedelta(minutes=1),
            text="tracked answer",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text="tracked reply snapshot",
        ),
        [],
    )
    tracked.close()
    archive_storage.persist_archive_message(
        shard,
        archive_message(2, date=base + timedelta(minutes=1), text="duplicate"),
        tracked_db_path=tracked_db_path,
    )
    shard.close()
    manifest.close()

    rows = archive_storage.fetch_context_messages(
        root_dir,
        tracked_db_path,
        chat_id=-1001,
        since=base - timedelta(minutes=1),
        until=base + timedelta(minutes=2),
    )

    assert [row.message_id for row in rows] == [1, 2]
    assert rows[0].effective_text == "question"
    assert rows[0].reply_to_msg_id == 10
    assert rows[0].reply_to_top_id is None
    assert rows[1].text is None
    assert rows[1].tracked_text == "tracked answer"
    assert rows[1].tracked_replied_text == "tracked reply snapshot"
    assert rows[1].tracked_db_matches_current is True
    assert rows[1].effective_text == "tracked answer"


def test_relative_tracked_db_paths_survive_project_root_move(tmp_path):
    project_dir = tmp_path / "project"
    root_dir = project_dir / "data" / "full_archive"
    tracked_db_path = project_dir / "data" / "tgwatch.sqlite3"
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=now,
            text="tracked payload",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=now,
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, date=now, text="duplicate"),
        tracked_db_path=tracked_db_path,
        archive_root_dir=root_dir,
    )
    archive_storage.record_shard_write(manifest, shard_meta)
    archive_storage.record_tracked_db_link(
        manifest,
        tracked_db_path,
        archive_root_dir=root_dir,
    )
    stored_message_path = shard.execute(
        "SELECT tracked_db_path FROM archive_messages WHERE message_id = 1"
    ).fetchone()["tracked_db_path"]
    stored_link_path = manifest.execute(
        "SELECT tracked_db_path FROM tracked_db_links WHERE status = 'active'"
    ).fetchone()["tracked_db_path"]
    shard.close()
    manifest.close()

    moved_project = tmp_path / "restored-project"
    project_dir.rename(moved_project)
    moved_root = moved_project / "data" / "full_archive"
    moved_tracked_db_path = moved_project / "data" / "tgwatch.sqlite3"

    status = archive_storage.inspect_archive_status(
        moved_root,
        tracked_db_path=moved_tracked_db_path,
    )
    context = archive_storage.fetch_context_result(
        moved_root,
        moved_tracked_db_path,
        chat_id=-1001,
        since=now - timedelta(minutes=1),
        until=now + timedelta(minutes=1),
    )

    assert stored_message_path == ".." + os.sep + "tgwatch.sqlite3"
    assert stored_link_path == ".." + os.sep + "tgwatch.sqlite3"
    assert status.current_tracked_db_linked is True
    assert status.current_tracked_db_readable is True
    assert status.errors == ()
    assert [message.effective_text for message in context.messages] == [
        "tracked payload"
    ]
    assert context.messages[0].tracked_db_matches_current is True
    assert context.errors == ()


def test_fetch_context_messages_includes_archive_media_metadata(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    archive_storage.persist_archive_message(
        shard,
        archive_message(
            1,
            date=base,
            text="chart",
            media=(
                archive_storage.ArchiveMedia(
                    media_index=0,
                    media_kind="MessageMediaPhoto",
                    mime_type="image/jpeg",
                    file_size=12345,
                    file_name="chart.jpg",
                ),
            ),
        ),
    )
    shard.close()
    manifest.close()

    rows = archive_storage.fetch_context_messages(
        root_dir,
        tmp_path / "tracked.sqlite3",
        chat_id=-1001,
        since=base - timedelta(minutes=1),
        until=base + timedelta(minutes=1),
    )

    assert len(rows) == 1
    assert rows[0].media == (
        archive_storage.ArchiveMedia(
            media_index=0,
            media_kind="MessageMediaPhoto",
            mime_type="image/jpeg",
            file_size=12345,
            file_name="chart.jpg",
        ),
    )


def test_fetch_context_messages_chunks_large_media_metadata_lookup(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.ensure_shard_schema(shard)
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    message_rows = []
    media_rows = []
    for index in range(1_100):
        timestamp = (base + timedelta(seconds=index)).isoformat()
        message_id = index + 1
        message_rows.append(
            (
                -1001,
                message_id,
                None,
                123,
                timestamp,
                f"text {index}",
                f"text {index}",
                "message",
                None,
                None,
                0,
                1,
                None,
                None,
                None,
                "archive",
                timestamp,
                timestamp,
            )
        )
        media_rows.append(
            (
                -1001,
                message_id,
                0,
                "MessageMediaPhoto",
                "image/jpeg",
                index,
                f"{message_id}.jpg",
                timestamp,
                timestamp,
            )
        )
    with shard:
        shard.executemany(
            """
            INSERT INTO archive_messages (
                chat_id, message_id, topic_id, sender_id, date, text, raw_text,
                message_kind, reply_to_msg_id, reply_to_top_id, is_forum_topic_link,
                has_media, tracked_db_path, tracked_message_chat_id,
                tracked_message_id, payload_mode, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            message_rows,
        )
        shard.executemany(
            """
            INSERT INTO archive_media (
                chat_id, message_id, media_index, media_kind, mime_type,
                file_size, file_name, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            media_rows,
        )
    shard.close()
    manifest.close()

    rows = archive_storage.fetch_context_messages(
        root_dir,
        tmp_path / "tracked.sqlite3",
        chat_id=-1001,
        since=base,
        until=base + timedelta(seconds=1_099),
    )

    assert len(rows) == 1_100
    assert rows[0].media[0].file_name == "1.jpg"
    assert rows[-1].media[0].file_name == "1100.jpg"


def test_persist_archive_message_stores_lightweight_media_metadata(tmp_path):
    shard = archive_storage.connect(tmp_path / "shard.sqlite3")

    archive_storage.persist_archive_message(
        shard,
        archive_message(
            1,
            media=(
                archive_storage.ArchiveMedia(
                    media_index=0,
                    media_kind="MessageMediaPhoto",
                    mime_type="image/jpeg",
                    file_size=12345,
                    file_name="chart.jpg",
                ),
            ),
        ),
    )

    row = shard.execute(
        """
        SELECT media_index, media_kind, mime_type, file_size, file_name
        FROM archive_media
        WHERE chat_id = ? AND message_id = ?
        """,
        (-1001, 1),
    ).fetchone()
    message = shard.execute(
        "SELECT has_media FROM archive_messages WHERE chat_id = ? AND message_id = ?",
        (-1001, 1),
    ).fetchone()
    shard.close()

    assert tuple(row) == (0, "MessageMediaPhoto", "image/jpeg", 12345, "chart.jpg")
    assert message["has_media"] == 1


def test_tracked_ref_relink_removes_archive_media_metadata(tmp_path):
    shard = archive_storage.connect(tmp_path / "shard.sqlite3")
    tracked_db_path = tmp_path / "tracked.sqlite3"

    archive_storage.persist_archive_message(
        shard,
        archive_message(
            1,
            media=(
                archive_storage.ArchiveMedia(
                    media_index=0,
                    media_kind="MessageMediaDocument",
                    mime_type="application/pdf",
                    file_size=100,
                    file_name="notes.pdf",
                ),
            ),
        ),
    )
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            text="tracked payload",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()

    archive_storage.persist_archive_message(
        shard,
        archive_message(
            1,
            media=(
                archive_storage.ArchiveMedia(
                    media_index=0,
                    media_kind="MessageMediaDocument",
                    mime_type="application/pdf",
                    file_size=100,
                    file_name="notes.pdf",
                ),
            ),
        ),
        tracked_db_path=tracked_db_path,
    )

    media_count = shard.execute("SELECT COUNT(*) FROM archive_media").fetchone()[0]
    payload_mode = shard.execute(
        "SELECT payload_mode FROM archive_messages WHERE chat_id = ? AND message_id = ?",
        (-1001, 1),
    ).fetchone()["payload_mode"]
    shard.close()

    assert media_count == 0
    assert payload_mode == "tracked_ref"


def test_tracked_ref_is_not_downgraded_when_tracked_db_is_unavailable(tmp_path):
    shard = archive_storage.connect(tmp_path / "shard.sqlite3")
    tracked_db_path = tmp_path / "tracked.sqlite3"

    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            text="tracked payload",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, text="duplicate payload"),
        tracked_db_path=tracked_db_path,
    )
    tracked_db_path.unlink()

    mode = archive_storage.persist_archive_message(
        shard,
        archive_message(
            1,
            text="should not be stored",
            media=(
                archive_storage.ArchiveMedia(
                    media_index=0,
                    media_kind="MessageMediaPhoto",
                    mime_type="image/jpeg",
                    file_size=123,
                    file_name="duplicate.jpg",
                ),
            ),
        ),
        tracked_db_path=tracked_db_path,
    )

    row = shard.execute(
        """
        SELECT text, raw_text, payload_mode, tracked_db_path,
               tracked_message_chat_id, tracked_message_id
        FROM archive_messages
        WHERE chat_id = ? AND message_id = ?
        """,
        (-1001, 1),
    ).fetchone()
    link_count = shard.execute("SELECT COUNT(*) FROM archive_tracked_links").fetchone()[0]
    media_count = shard.execute("SELECT COUNT(*) FROM archive_media").fetchone()[0]
    shard.close()

    assert mode == "tracked_ref"
    assert row["text"] is None
    assert row["raw_text"] is None
    assert row["payload_mode"] == "tracked_ref"
    assert row["tracked_db_path"] == str(tracked_db_path)
    assert row["tracked_message_chat_id"] == -1001
    assert row["tracked_message_id"] == 1
    assert link_count == 1
    assert media_count == 0


def test_fetch_context_result_allows_tracked_ref_with_null_tracked_text(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=now,
            text=None,
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, date=now, text="duplicate"),
        tracked_db_path=tracked_db_path,
    )
    shard.execute(
        """
        UPDATE archive_messages
        SET text = ?, raw_text = ?
        WHERE chat_id = ? AND message_id = ?
        """,
        ("stale archive payload", "stale archive payload", -1001, 1),
    )
    shard.commit()
    shard.close()
    manifest.close()

    result = archive_storage.fetch_context_result(
        root_dir,
        tracked_db_path,
        chat_id=-1001,
        since=now - timedelta(minutes=1),
        until=now + timedelta(minutes=1),
    )

    assert result.errors == ()
    assert [row.message_id for row in result.messages] == [1]
    assert result.messages[0].payload_mode == "tracked_ref"
    assert result.messages[0].tracked_row_found is True
    assert result.messages[0].tracked_text is None
    assert result.messages[0].text == "stale archive payload"
    assert result.messages[0].effective_text is None


def test_fetch_context_result_ignores_stale_archive_media_for_tracked_ref(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=now,
            text="tracked payload",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, date=now, text="duplicate"),
        tracked_db_path=tracked_db_path,
    )
    shard.execute(
        """
        INSERT INTO archive_media (
            chat_id, message_id, media_index, media_kind, mime_type,
            file_size, file_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            -1001,
            1,
            0,
            "MessageMediaPhoto",
            "image/jpeg",
            12345,
            "stale.jpg",
            now.isoformat(),
            now.isoformat(),
        ),
    )
    shard.commit()
    shard.close()
    manifest.close()

    result = archive_storage.fetch_context_result(
        root_dir,
        tracked_db_path,
        chat_id=-1001,
        since=now - timedelta(minutes=1),
        until=now + timedelta(minutes=1),
    )

    assert result.errors == ()
    assert [row.message_id for row in result.messages] == [1]
    assert result.messages[0].payload_mode == "tracked_ref"
    assert result.messages[0].effective_text == "tracked payload"
    assert result.messages[0].media == ()


def test_fetch_context_result_reports_unresolved_tracked_refs(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    archive_storage.ensure_shard_schema(shard)
    with shard:
        shard.execute(
            """
            INSERT INTO archive_messages (
                chat_id, message_id, topic_id, sender_id, date, text, raw_text,
                message_kind, reply_to_msg_id, reply_to_top_id, is_forum_topic_link,
                has_media, tracked_db_path, tracked_message_chat_id,
                tracked_message_id, payload_mode, created_at, updated_at
            ) VALUES (?, ?, NULL, ?, ?, NULL, NULL, 'message', NULL, NULL, 0, 0,
                      ?, ?, ?, 'tracked_ref', ?, ?)
            """,
            (
                -1001,
                1,
                123,
                now.isoformat(),
                str(tmp_path / "missing-tracked.sqlite3"),
                -1001,
                1,
                now.isoformat(),
                now.isoformat(),
            ),
        )
    shard.close()
    manifest.close()

    result = archive_storage.fetch_context_result(
        root_dir,
        tmp_path / "missing-tracked.sqlite3",
        chat_id=-1001,
        since=now - timedelta(minutes=1),
        until=now + timedelta(minutes=1),
    )

    assert [row.message_id for row in result.messages] == [1]
    assert result.messages[0].effective_text is None
    assert result.errors == (
        "-1001:2026-05:001: 1 tracked_ref row(s) "
        "could not read current tracked DB (missing tracked DB)",
    )


def test_fetch_context_result_reports_tracked_db_schema_errors_without_skipping_archive_rows(
    tmp_path,
):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    tracked_db_path = tmp_path / "old-tracked.sqlite3"
    tracked = sqlite3.connect(tracked_db_path)
    try:
        tracked.execute(
            "CREATE TABLE messages (chat_id INTEGER, message_id INTEGER, date TEXT)"
        )
        tracked.execute(
            "INSERT INTO messages (chat_id, message_id, date) VALUES (?, ?, ?)",
            (-1001, 2, now.isoformat()),
        )
        tracked.commit()
    finally:
        tracked.close()
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, date=now - timedelta(seconds=5), text="context"),
    )
    archive_storage.persist_archive_message(
        shard,
        archive_message(2, date=now, text="duplicate"),
        tracked_db_path=tracked_db_path,
        archive_root_dir=root_dir,
    )
    shard.close()
    manifest.close()

    result = archive_storage.fetch_context_result(
        root_dir,
        tracked_db_path,
        chat_id=-1001,
        since=now - timedelta(minutes=1),
        until=now + timedelta(minutes=1),
    )

    assert [row.message_id for row in result.messages] == [1, 2]
    assert result.messages[0].effective_text == "context"
    assert result.messages[1].payload_mode == "tracked_ref"
    assert result.messages[1].effective_text is None
    assert result.skipped_shards == ()
    assert result.errors == (
        "-1001:2026-05:001: 1 tracked_ref row(s) could not read current "
        "tracked DB (tracked DB messages table missing column(s): replied_text, text)",
    )


def test_fetch_context_result_refuses_to_resolve_tracked_ref_from_different_db(
    tmp_path,
):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

    original_tracked_db_path = tmp_path / "original-tracked.sqlite3"
    original = tracked_storage.connect(original_tracked_db_path)
    tracked_storage.ensure_schema(original)
    tracked_storage.persist_message(
        original,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=now,
            text="original tracked payload",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    original.close()
    current_tracked_db_path = tmp_path / "current-tracked.sqlite3"
    current = tracked_storage.connect(current_tracked_db_path)
    tracked_storage.ensure_schema(current)
    tracked_storage.persist_message(
        current,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=now,
            text="wrong current payload",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    current.close()
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, date=now, text="duplicate"),
        tracked_db_path=original_tracked_db_path,
    )
    shard.close()
    manifest.close()

    result = archive_storage.fetch_context_result(
        root_dir,
        current_tracked_db_path,
        chat_id=-1001,
        since=now - timedelta(minutes=1),
        until=now + timedelta(minutes=1),
    )

    assert [row.message_id for row in result.messages] == [1]
    assert result.messages[0].tracked_db_matches_current is False
    assert result.messages[0].tracked_row_found is False
    assert result.messages[0].tracked_text is None
    assert result.messages[0].effective_text is None
    assert result.errors == (
        "-1001:2026-05:001: 1 tracked_ref row(s) point to a different tracked DB",
    )


def test_fetch_context_result_merges_multiple_shards_in_time_order(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    may = datetime(2026, 5, 31, 23, 59, tzinfo=timezone.utc)
    june = datetime(2026, 6, 1, 0, 1, tzinfo=timezone.utc)
    may_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=may,
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    june_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=june,
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    may_shard = archive_storage.connect(may_meta.path)
    june_shard = archive_storage.connect(june_meta.path)
    archive_storage.persist_archive_message(
        june_shard,
        archive_message(2, date=june, text="after"),
    )
    archive_storage.persist_archive_message(
        may_shard,
        archive_message(1, date=may, text="before"),
    )
    may_shard.close()
    june_shard.close()
    manifest.close()

    result = archive_storage.fetch_context_result(
        root_dir,
        tmp_path / "tracked.sqlite3",
        chat_id=-1001,
        since=may - timedelta(minutes=1),
        until=june + timedelta(minutes=1),
    )

    assert [row.message_id for row in result.messages] == [1, 2]
    assert result.skipped_shards == ()
    assert result.errors == ()


def test_fetch_context_result_reports_missing_shards(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    manifest.close()

    result = archive_storage.fetch_context_result(
        root_dir,
        tmp_path / "tracked.sqlite3",
        chat_id=-1001,
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )

    assert result.messages == ()
    assert result.skipped_shards == ("-1001:2026-05:001: missing shard file",)
    assert result.errors == ()


def test_fetch_context_result_reports_missing_additive_schema_tables(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=base,
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, date=base, text="context"),
    )
    archive_storage.record_shard_write(manifest, shard_meta)
    shard.execute("DROP TABLE archive_media")
    shard.close()
    manifest.close()

    result = archive_storage.fetch_context_result(
        root_dir,
        tmp_path / "tracked.sqlite3",
        chat_id=-1001,
        since=base - timedelta(minutes=1),
        until=base + timedelta(minutes=1),
    )

    assert [row.message_id for row in result.messages] == [1]
    assert result.messages[0].effective_text == "context"
    assert result.skipped_shards == ()
    assert result.errors == (
        "-1001:2026-05:001: missing schema table(s): archive_media",
    )


def test_fetch_context_result_skips_shards_missing_core_schema_tables(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=base,
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, date=base, text="context"),
    )
    archive_storage.record_shard_write(manifest, shard_meta)
    shard.execute("DROP TABLE archive_tracked_links")
    shard.close()
    manifest.close()

    result = archive_storage.fetch_context_result(
        root_dir,
        tmp_path / "tracked.sqlite3",
        chat_id=-1001,
        since=base - timedelta(minutes=1),
        until=base + timedelta(minutes=1),
    )

    assert result.messages == ()
    assert result.skipped_shards == (
        "-1001:2026-05:001: missing required table(s): archive_tracked_links",
    )
    assert result.errors == result.skipped_shards


def test_context_window_query_uses_index_and_stays_fast_with_10k_rows(tmp_path):
    shard = archive_storage.connect(tmp_path / "archive.sqlite3")
    archive_storage.ensure_shard_schema(shard)
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    rows = []
    for index in range(10_000):
        dt = base + timedelta(seconds=index)
        raw_dt = dt.isoformat()
        rows.append(
            (
                -1001,
                index + 1,
                10 if index % 2 == 0 else 20,
                100 + (index % 5),
                raw_dt,
                f"text {index}",
                f"text {index}",
                "message",
                None,
                None,
                0,
                0,
                None,
                None,
                None,
                "archive",
                raw_dt,
                raw_dt,
            )
        )
    with shard:
        shard.executemany(
            """
            INSERT INTO archive_messages (
                chat_id, message_id, topic_id, sender_id, date, text, raw_text,
                message_kind, reply_to_msg_id, reply_to_top_id, is_forum_topic_link,
                has_media, tracked_db_path, tracked_message_chat_id,
                tracked_message_id, payload_mode, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    since = base + timedelta(seconds=5_000 - 600)
    until = base + timedelta(seconds=5_000 + 600)
    plan = shard.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT *
        FROM archive_messages
        WHERE chat_id = ?
          AND date >= ?
          AND date <= ?
        ORDER BY date ASC, message_id ASC
        """,
        (-1001, since.isoformat(), until.isoformat()),
    ).fetchall()
    topic_plan = shard.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT *
        FROM archive_messages
        WHERE chat_id = ?
          AND date >= ?
          AND date <= ?
          AND topic_id = ?
        ORDER BY date ASC, message_id ASC
        """,
        (-1001, since.isoformat(), until.isoformat(), 10),
    ).fetchall()

    started = perf_counter()
    result = archive_storage.fetch_messages_between(
        shard,
        chat_id=-1001,
        since=since,
        until=until,
    )
    elapsed = perf_counter() - started

    assert any("idx_archive_messages_chat_date" in str(row[3]) for row in plan)
    assert any("idx_archive_messages_scope_date" in str(row[3]) for row in topic_plan)
    assert len(result) == 1201
    assert elapsed < 0.2


def test_find_tracked_message_date_is_readonly_for_missing_db(tmp_path):
    missing = tmp_path / "missing.sqlite3"

    assert (
        archive_storage.find_tracked_message_date(
            missing,
            chat_id=-1001,
            message_id=1,
        )
        is None
    )
    assert not missing.exists()


def test_tracked_message_date_lookup_error_reports_missing_target_schema(tmp_path):
    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = sqlite3.connect(tracked_db_path)
    try:
        tracked.execute("CREATE TABLE messages (chat_id INTEGER, message_id INTEGER)")
        tracked.commit()
    finally:
        tracked.close()

    assert archive_storage.tracked_message_date_lookup_error(tracked_db_path) == (
        "tracked DB messages table missing column(s): date"
    )


def test_tracked_message_date_lookup_error_does_not_create_missing_db(tmp_path):
    missing = tmp_path / "missing.sqlite3"

    assert archive_storage.tracked_message_date_lookup_error(missing) == (
        "missing tracked DB"
    )
    assert not missing.exists()


def test_inspect_archive_status_counts_shards_rows_and_links(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(
        shard,
        archive_message(
            1,
            text="context",
            media=(
                archive_storage.ArchiveMedia(
                    media_index=0,
                    media_kind="MessageMediaPhoto",
                    mime_type="image/jpeg",
                    file_size=123,
                    file_name=None,
                ),
            ),
        ),
    )
    archive_storage.record_shard_write(manifest, shard_meta)

    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=2,
            sender_id=123,
            date=datetime(2026, 5, 1, 12, 2, tzinfo=timezone.utc),
            text="tracked",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()
    archive_storage.persist_archive_message(
        shard,
        archive_message(2, text="duplicate"),
        tracked_db_path=tracked_db_path,
    )
    archive_storage.record_tracked_db_link(manifest, tracked_db_path)
    archive_storage.record_shard_write(manifest, shard_meta)
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.manifest_exists is True
    assert report.shard_count == 1
    assert report.missing_shard_count == 0
    assert report.manifest_message_count == 2
    assert report.actual_message_count == 2
    assert report.archive_row_count == 1
    assert report.tracked_ref_count == 1
    assert report.link_count == 1
    assert report.media_metadata_count == 1
    assert report.tracked_db_link_count == 1
    assert report.current_tracked_db_linked is None
    assert report.current_tracked_db_readable is None
    assert report.missing_index_count == 0
    assert report.errors == ()
    assert report.degraded is False


def test_inspect_archive_status_reports_missing_manifest_schema_tables(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest_path = root_dir / "manifest.sqlite3"
    manifest_path.parent.mkdir(parents=True)
    manifest = sqlite3.connect(manifest_path)
    try:
        manifest.execute(
            """
            CREATE TABLE archive_shards (
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
            )
            """
        )
        manifest.commit()
    finally:
        manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.manifest_exists is True
    assert report.shard_count == 0
    assert report.missing_schema_table_count == 1
    assert report.errors == (
        "manifest: missing schema table(s): tracked_db_links",
    )
    assert report.degraded is True


def test_inspect_archive_status_degrades_when_tracked_ref_link_count_mismatches(
    tmp_path,
):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            text="tracked",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, text="duplicate"),
        tracked_db_path=tracked_db_path,
    )
    shard.execute(
        "DELETE FROM archive_tracked_links WHERE chat_id = ? AND message_id = ?",
        (-1001, 1),
    )
    shard.commit()
    archive_storage.record_tracked_db_link(manifest, tracked_db_path)
    archive_storage.record_shard_write(manifest, shard_meta)
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.tracked_ref_count == 1
    assert report.link_count == 0
    assert report.errors == (
        "-1001:2026-05:001: tracked_ref/link count mismatch "
        "(tracked_ref=1, links=0)",
    )
    assert report.degraded is True


def test_inspect_archive_status_degrades_when_tracked_ref_link_content_mismatches(
    tmp_path,
):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            text="tracked",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, text="duplicate"),
        tracked_db_path=tracked_db_path,
        archive_root_dir=root_dir,
    )
    shard.execute(
        """
        UPDATE archive_tracked_links
        SET tracked_message_id = ?
        WHERE chat_id = ? AND message_id = ?
        """,
        (999, -1001, 1),
    )
    shard.commit()
    archive_storage.record_tracked_db_link(manifest, tracked_db_path)
    archive_storage.record_shard_write(manifest, shard_meta)
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)
    repair = archive_storage.repair_archive_metadata(root_dir, apply=True)
    repaired_report = archive_storage.inspect_archive_status(root_dir)

    assert report.tracked_ref_count == 1
    assert report.link_count == 1
    assert report.errors == (
        "-1001:2026-05:001: tracked_ref/link content mismatch "
        "(rows_to_repair=2)",
    )
    assert report.degraded is True
    assert repair.repaired_link_rows == 2
    assert repaired_report.errors == ()
    assert repaired_report.degraded is False


def test_archive_status_and_repair_handle_stale_tracked_ref_media_metadata(
    tmp_path,
):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            text="tracked",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, text="duplicate"),
        tracked_db_path=tracked_db_path,
        archive_root_dir=root_dir,
    )
    shard.execute(
        """
        INSERT INTO archive_media (
            chat_id, message_id, media_index, media_kind, mime_type,
            file_size, file_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            -1001,
            1,
            0,
            "MessageMediaPhoto",
            "image/jpeg",
            123,
            "stale.jpg",
            datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat(),
            datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat(),
        ),
    )
    shard.commit()
    archive_storage.record_tracked_db_link(
        manifest,
        tracked_db_path,
        archive_root_dir=root_dir,
    )
    archive_storage.record_shard_write(manifest, shard_meta)
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)
    dry_run = archive_storage.repair_archive_metadata(root_dir, apply=False)
    repair = archive_storage.repair_archive_metadata(root_dir, apply=True)
    repaired_report = archive_storage.inspect_archive_status(root_dir)

    assert report.media_metadata_count == 1
    assert report.errors == (
        "-1001:2026-05:001: tracked_ref archive media metadata "
        "should be removed (rows=1)",
    )
    assert report.degraded is True
    assert dry_run.repaired_stale_media_rows == 1
    assert repair.repaired_stale_media_rows == 1
    assert repair.repaired_shards == 1
    assert repaired_report.media_metadata_count == 0
    assert repaired_report.errors == ()
    assert repaired_report.degraded is False


def test_archive_status_and_repair_clear_stale_tracked_ref_text_payload(
    tmp_path,
):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            text="tracked",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, text="duplicate"),
        tracked_db_path=tracked_db_path,
        archive_root_dir=root_dir,
    )
    shard.execute(
        """
        UPDATE archive_messages
        SET text = ?, raw_text = ?
        WHERE chat_id = ? AND message_id = ?
        """,
        ("stale text", "stale raw text", -1001, 1),
    )
    shard.commit()
    archive_storage.record_tracked_db_link(
        manifest,
        tracked_db_path,
        archive_root_dir=root_dir,
    )
    archive_storage.record_shard_write(manifest, shard_meta)
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)
    dry_run = archive_storage.repair_archive_metadata(root_dir, apply=False)
    repair = archive_storage.repair_archive_metadata(root_dir, apply=True)
    repaired_report = archive_storage.inspect_archive_status(root_dir)
    shard = archive_storage.connect(shard_meta.path)
    try:
        payload = shard.execute(
            """
            SELECT text, raw_text
            FROM archive_messages
            WHERE chat_id = ? AND message_id = ?
            """,
            (-1001, 1),
        ).fetchone()
    finally:
        shard.close()

    assert report.errors == (
        "-1001:2026-05:001: tracked_ref archive text payload "
        "should be cleared (rows=1)",
    )
    assert report.degraded is True
    assert dry_run.repaired_stale_payload_rows == 1
    assert repair.repaired_stale_payload_rows == 1
    assert repair.repaired_shards == 1
    assert tuple(payload) == (None, None)
    assert repaired_report.errors == ()
    assert repaired_report.degraded is False


def test_inspect_archive_status_reports_incomplete_tracked_ref_metadata(
    tmp_path,
):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            text="tracked",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, text="duplicate"),
        tracked_db_path=tracked_db_path,
        archive_root_dir=root_dir,
    )
    shard.execute(
        """
        UPDATE archive_messages
        SET tracked_db_path = NULL
        WHERE chat_id = ? AND message_id = ?
        """,
        (-1001, 1),
    )
    shard.execute(
        "DELETE FROM archive_tracked_links WHERE chat_id = ? AND message_id = ?",
        (-1001, 1),
    )
    shard.commit()
    archive_storage.record_tracked_db_link(manifest, tracked_db_path)
    archive_storage.record_shard_write(manifest, shard_meta)
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)
    repair = archive_storage.repair_archive_metadata(root_dir, apply=True)
    repaired_report = archive_storage.inspect_archive_status(root_dir)

    assert report.errors == (
        "-1001:2026-05:001: incomplete tracked_ref metadata (rows=1)",
        "-1001:2026-05:001: tracked_ref/link count mismatch "
        "(tracked_ref=1, links=0)",
    )
    assert report.degraded is True
    assert repair.checked_shards == 1
    assert repair.skipped_shards == 1
    assert repair.skipped_reasons == (
        "-1001:2026-05:001: incomplete tracked_ref metadata "
        "(rows=1); cannot repair links",
    )
    assert repair.errors == repair.skipped_reasons
    assert repair.repaired_link_rows == 0
    assert repaired_report.errors == report.errors
    assert repaired_report.degraded is True


def test_inspect_archive_status_reports_current_tracked_db_link_health(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    archive_storage.ensure_manifest_schema(manifest)
    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked.close()
    archive_storage.record_tracked_db_link(manifest, tracked_db_path)
    manifest.close()

    report = archive_storage.inspect_archive_status(
        root_dir,
        tracked_db_path=tracked_db_path,
    )

    assert report.tracked_db_link_count == 1
    assert report.current_tracked_db_linked is True
    assert report.current_tracked_db_readable is True
    assert report.errors == ()
    assert report.degraded is False


def test_inspect_archive_status_degrades_when_archive_messages_have_no_tracked_db_link(
    tmp_path,
):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(shard, archive_message(1, text="context"))
    archive_storage.record_shard_write(manifest, shard_meta)
    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked.close()
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(
        root_dir,
        tracked_db_path=tracked_db_path,
    )

    assert report.tracked_db_link_count == 0
    assert report.current_tracked_db_linked is False
    assert report.current_tracked_db_readable is True
    assert report.errors == ("archive manifest has messages but no tracked DB link",)
    assert str(tracked_db_path) not in " ".join(report.errors)
    assert report.degraded is True


def test_inspect_archive_status_degrades_without_current_tracked_db_link_context(
    tmp_path,
):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(shard, archive_message(1, text="context"))
    archive_storage.record_shard_write(manifest, shard_meta)
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.tracked_db_link_count == 0
    assert report.current_tracked_db_linked is None
    assert report.current_tracked_db_readable is None
    assert report.errors == ("archive manifest has messages but no tracked DB link",)
    assert report.degraded is True


def test_inspect_archive_status_degrades_when_current_tracked_db_not_linked(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    archive_storage.ensure_manifest_schema(manifest)
    linked_db_path = tmp_path / "old-tracked.sqlite3"
    current_db_path = tmp_path / "current-tracked.sqlite3"
    linked = tracked_storage.connect(linked_db_path)
    tracked_storage.ensure_schema(linked)
    linked.close()
    current = tracked_storage.connect(current_db_path)
    tracked_storage.ensure_schema(current)
    current.close()
    archive_storage.record_tracked_db_link(manifest, linked_db_path)
    manifest.close()

    report = archive_storage.inspect_archive_status(
        root_dir,
        tracked_db_path=current_db_path,
    )

    assert report.tracked_db_link_count == 1
    assert report.current_tracked_db_linked is False
    assert report.current_tracked_db_readable is True
    assert report.errors == ("current tracked DB is not registered in archive manifest",)
    assert str(current_db_path) not in " ".join(report.errors)
    assert report.degraded is True


def test_inspect_archive_status_degrades_when_current_tracked_db_unreadable(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    archive_storage.ensure_manifest_schema(manifest)
    tracked_db_path = tmp_path / "missing-tracked.sqlite3"
    archive_storage.record_tracked_db_link(manifest, tracked_db_path)
    manifest.close()

    report = archive_storage.inspect_archive_status(
        root_dir,
        tracked_db_path=tracked_db_path,
    )

    assert report.tracked_db_link_count == 1
    assert report.current_tracked_db_linked is True
    assert report.current_tracked_db_readable is False
    assert report.errors == ("current tracked DB is not readable",)
    assert str(tracked_db_path) not in " ".join(report.errors)
    assert not tracked_db_path.exists()
    assert report.degraded is True


def test_inspect_archive_status_degrades_when_tracked_db_schema_missing(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    archive_storage.ensure_manifest_schema(manifest)
    tracked_db_path = tmp_path / "empty-tracked.sqlite3"
    empty = sqlite3.connect(tracked_db_path)
    empty.close()
    archive_storage.record_tracked_db_link(manifest, tracked_db_path)
    manifest.close()

    report = archive_storage.inspect_archive_status(
        root_dir,
        tracked_db_path=tracked_db_path,
    )

    assert report.tracked_db_link_count == 1
    assert report.current_tracked_db_linked is True
    assert report.current_tracked_db_readable is False
    assert report.errors == ("current tracked DB is not readable",)
    assert str(tracked_db_path) not in " ".join(report.errors)
    assert tracked_db_path.exists()
    assert report.degraded is True


def test_inspect_archive_status_degrades_when_tracked_db_schema_incomplete(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    archive_storage.ensure_manifest_schema(manifest)
    tracked_db_path = tmp_path / "partial-tracked.sqlite3"
    partial = sqlite3.connect(tracked_db_path)
    partial.execute(
        """
        CREATE TABLE messages (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            text TEXT,
            PRIMARY KEY (chat_id, message_id)
        )
        """
    )
    partial.close()
    archive_storage.record_tracked_db_link(manifest, tracked_db_path)
    manifest.close()

    report = archive_storage.inspect_archive_status(
        root_dir,
        tracked_db_path=tracked_db_path,
    )

    assert report.tracked_db_link_count == 1
    assert report.current_tracked_db_linked is True
    assert report.current_tracked_db_readable is False
    assert report.errors == ("current tracked DB is not readable",)
    assert str(tracked_db_path) not in " ".join(report.errors)
    assert tracked_db_path.exists()
    assert report.degraded is True


def test_inspect_archive_status_reports_missing_required_indexes(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.ensure_shard_schema(shard)
    shard.execute("DROP INDEX idx_archive_messages_chat_date")
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.missing_index_count == 1
    assert report.shards[0].missing_indexes == ("idx_archive_messages_chat_date",)
    assert report.errors == (
        "-1001:2026-05:001: missing required index(es): "
        "idx_archive_messages_chat_date",
    )
    assert report.degraded is True


def test_inspect_archive_status_reports_missing_additive_schema_tables(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.ensure_shard_schema(shard)
    shard.execute("DROP TABLE archive_media")
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.missing_schema_table_count == 1
    assert report.shards[0].missing_schema_tables == ("archive_media",)
    assert report.errors == (
        "-1001:2026-05:001: missing schema table(s): archive_media",
    )
    assert report.degraded is True


def test_inspect_archive_status_reports_message_count_mismatch(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(shard, archive_message(1, text="context"))
    archive_storage.record_tracked_db_link(manifest, tmp_path / "tracked.sqlite3")
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.manifest_message_count == 0
    assert report.actual_message_count == 1
    assert report.errors == (
        "-1001:2026-05:001: message count mismatch (manifest=0, actual=1)",
    )
    assert report.degraded is True


def test_inspect_archive_status_does_not_degrade_on_file_size_mismatch(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(shard, archive_message(1, text="context"))
    archive_storage.record_shard_write(manifest, shard_meta)
    archive_storage.record_tracked_db_link(manifest, tmp_path / "tracked.sqlite3")
    manifest.execute(
        "UPDATE archive_shards SET file_size_bytes = 1 WHERE shard_id = ?",
        (shard_meta.shard_id,),
    )
    manifest.commit()
    shard.close()
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.manifest_message_count == report.actual_message_count == 1
    assert report.shards[0].manifest_file_size_bytes == 1
    assert report.shards[0].actual_file_size_bytes == shard_meta.path.stat().st_size
    assert report.errors == ()
    assert report.degraded is False


def test_repair_archive_metadata_dry_run_does_not_modify_shard(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.ensure_shard_schema(shard)
    shard.execute("DROP INDEX idx_archive_messages_chat_date")
    shard.close()
    manifest.close()

    repair = archive_storage.repair_archive_metadata(root_dir, apply=False)
    status = archive_storage.inspect_archive_status(root_dir)

    assert repair.dry_run is True
    assert repair.checked_shards == 1
    assert repair.repaired_shards == 1
    assert repair.repaired_indexes == 1
    assert repair.repaired_schema_tables == 0
    assert repair.repaired_manifest_metadata == 1
    assert repair.errors == ()
    assert status.missing_index_count == 1


def test_repair_archive_metadata_apply_restores_missing_indexes(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.ensure_shard_schema(shard)
    shard.execute("DROP INDEX idx_archive_messages_chat_date")
    shard.close()
    manifest.close()

    repair = archive_storage.repair_archive_metadata(root_dir, apply=True)
    status = archive_storage.inspect_archive_status(root_dir)

    assert repair.dry_run is False
    assert repair.checked_shards == 1
    assert repair.repaired_shards == 1
    assert repair.repaired_indexes == 1
    assert repair.repaired_schema_tables == 0
    assert repair.repaired_manifest_metadata == 1
    assert repair.errors == ()
    assert status.missing_index_count == 0
    assert status.errors == ()


def test_repair_archive_metadata_restores_missing_additive_schema_tables(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.ensure_shard_schema(shard)
    shard.execute("DROP TABLE archive_media")
    shard.close()
    manifest.close()

    dry_run = archive_storage.repair_archive_metadata(root_dir, apply=False)
    dry_run_status = archive_storage.inspect_archive_status(root_dir)
    applied = archive_storage.repair_archive_metadata(root_dir, apply=True)
    status = archive_storage.inspect_archive_status(root_dir)

    assert dry_run.dry_run is True
    assert dry_run.repaired_shards == 1
    assert dry_run.repaired_schema_tables == 1
    assert dry_run_status.missing_schema_table_count == 1
    assert applied.dry_run is False
    assert applied.checked_shards == 1
    assert applied.repaired_shards == 1
    assert applied.repaired_schema_tables == 1
    assert status.missing_schema_table_count == 0
    assert status.errors == ()
    shard = archive_storage.connect_readonly(shard_meta.path)
    try:
        count = shard.execute("SELECT COUNT(*) FROM archive_media").fetchone()[0]
    finally:
        shard.close()
    assert count == 0


def test_repair_archive_metadata_restores_missing_manifest_schema_tables(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest_path = root_dir / "manifest.sqlite3"
    manifest_path.parent.mkdir(parents=True)
    manifest = sqlite3.connect(manifest_path)
    try:
        manifest.execute(
            """
            CREATE TABLE archive_shards (
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
            )
            """
        )
        manifest.commit()
    finally:
        manifest.close()

    dry_run = archive_storage.repair_archive_metadata(root_dir, apply=False)
    dry_run_status = archive_storage.inspect_archive_status(root_dir)
    applied = archive_storage.repair_archive_metadata(root_dir, apply=True)
    status = archive_storage.inspect_archive_status(root_dir)

    assert dry_run.dry_run is True
    assert dry_run.checked_shards == 0
    assert dry_run.repaired_shards == 0
    assert dry_run.repaired_schema_tables == 1
    assert dry_run.errors == ()
    assert dry_run_status.missing_schema_table_count == 1
    assert applied.dry_run is False
    assert applied.checked_shards == 0
    assert applied.repaired_schema_tables == 1
    assert applied.errors == ()
    assert status.missing_schema_table_count == 0
    assert status.errors == ()
    repaired_manifest = archive_storage.connect_readonly(manifest_path)
    try:
        count = repaired_manifest.execute(
            "SELECT COUNT(*) FROM tracked_db_links"
        ).fetchone()[0]
    finally:
        repaired_manifest.close()
    assert count == 0


def test_repair_archive_metadata_skips_missing_core_schema_tables(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.ensure_shard_schema(shard)
    shard.execute("DROP TABLE archive_tracked_links")
    shard.close()
    manifest.close()

    repair = archive_storage.repair_archive_metadata(root_dir, apply=True)

    assert repair.checked_shards == 0
    assert repair.repaired_shards == 0
    assert repair.repaired_schema_tables == 0
    assert repair.skipped_shards == 1
    assert repair.skipped_reasons == (
        "-1001:2026-05:001: required shard table(s) are missing: "
        "archive_tracked_links",
    )


def test_repair_archive_metadata_dry_run_reports_manifest_count_mismatch(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(shard, archive_message(1, text="context"))
    archive_storage.record_tracked_db_link(manifest, tmp_path / "tracked.sqlite3")
    shard.close()
    manifest.close()

    repair = archive_storage.repair_archive_metadata(root_dir, apply=False)
    status = archive_storage.inspect_archive_status(root_dir)

    assert repair.dry_run is True
    assert repair.checked_shards == 1
    assert repair.repaired_shards == 1
    assert repair.repaired_indexes == 0
    assert repair.repaired_schema_tables == 0
    assert repair.repaired_manifest_metadata == 1
    assert repair.errors == ()
    assert status.manifest_message_count == 0
    assert status.actual_message_count == 1
    assert status.degraded is True


def test_repair_archive_metadata_apply_restores_manifest_counts(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(shard, archive_message(1, text="context"))
    archive_storage.record_tracked_db_link(manifest, tmp_path / "tracked.sqlite3")
    shard.close()
    manifest.close()

    repair = archive_storage.repair_archive_metadata(root_dir, apply=True)
    status = archive_storage.inspect_archive_status(root_dir)

    assert repair.dry_run is False
    assert repair.checked_shards == 1
    assert repair.repaired_shards == 1
    assert repair.repaired_indexes == 0
    assert repair.repaired_schema_tables == 0
    assert repair.repaired_manifest_metadata == 1
    assert repair.errors == ()
    assert status.manifest_message_count == 1
    assert status.actual_message_count == 1
    assert status.errors == ()


def test_repair_archive_metadata_rebuilds_tracked_links(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    shard_meta = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    tracked_db_path = tmp_path / "tracked.sqlite3"
    tracked = tracked_storage.connect(tracked_db_path)
    tracked_storage.ensure_schema(tracked)
    tracked_storage.persist_message(
        tracked,
        tracked_storage.StoredMessage(
            chat_id=-1001,
            message_id=1,
            sender_id=123,
            date=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            text="tracked payload",
            reply_to_msg_id=None,
            replied_sender_id=None,
            replied_date=None,
            replied_text=None,
        ),
        [],
    )
    tracked.close()
    shard = archive_storage.connect(shard_meta.path)
    archive_storage.persist_archive_message(
        shard,
        archive_message(1, text="duplicate payload"),
        tracked_db_path=tracked_db_path,
        archive_root_dir=root_dir,
    )
    shard.execute(
        "DELETE FROM archive_tracked_links WHERE chat_id = ? AND message_id = ?",
        (-1001, 1),
    )
    shard.commit()
    archive_storage.record_tracked_db_link(manifest, tracked_db_path)
    archive_storage.record_shard_write(manifest, shard_meta)
    shard.close()
    manifest.close()

    dry_run = archive_storage.repair_archive_metadata(root_dir, apply=False)
    dry_run_status = archive_storage.inspect_archive_status(root_dir)
    applied = archive_storage.repair_archive_metadata(root_dir, apply=True)
    status = archive_storage.inspect_archive_status(root_dir)

    assert dry_run.dry_run is True
    assert dry_run.checked_shards == 1
    assert dry_run.repaired_shards == 1
    assert dry_run.repaired_link_rows == 1
    assert dry_run_status.link_count == 0
    assert dry_run_status.degraded is True
    assert applied.dry_run is False
    assert applied.checked_shards == 1
    assert applied.repaired_shards == 1
    assert applied.repaired_link_rows == 1
    assert status.tracked_ref_count == 1
    assert status.link_count == 1
    assert status.errors == ()
    assert status.degraded is False


def test_repair_archive_metadata_missing_manifest_is_noop(tmp_path):
    root_dir = tmp_path / "full_archive"

    repair = archive_storage.repair_archive_metadata(root_dir, apply=True)

    assert repair.manifest_exists is False
    assert repair.checked_shards == 0
    assert repair.repaired_indexes == 0
    assert repair.repaired_schema_tables == 0
    assert repair.repaired_manifest_metadata == 0
    assert repair.skipped_shards == 0
    assert repair.skipped_reasons == ()
    assert not root_dir.exists()


def test_repair_archive_metadata_reports_orphaned_shards_without_manifest(tmp_path):
    root_dir = tmp_path / "full_archive"
    orphaned_shard = root_dir / "shards" / "group_-1001" / "2026-05.sqlite3"
    orphaned_shard.parent.mkdir(parents=True)
    sqlite3.connect(orphaned_shard).close()

    repair = archive_storage.repair_archive_metadata(root_dir, apply=True)

    assert repair.manifest_exists is False
    assert repair.checked_shards == 0
    assert repair.repaired_shards == 0
    assert repair.skipped_shards == 1
    assert repair.skipped_reasons == (
        "archive root has shard file(s) but no manifest (count=1)",
    )
    assert repair.errors == repair.skipped_reasons
    assert orphaned_shard.exists()


def test_repair_archive_metadata_reports_unregistered_shards_with_manifest(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    registered = archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    shard = archive_storage.connect(registered.path)
    archive_storage.ensure_shard_schema(shard)
    shard.close()
    manifest.close()
    unregistered_shard = root_dir / "shards" / "group_-1001" / "2026-05-999.sqlite3"
    sqlite3.connect(unregistered_shard).close()

    repair = archive_storage.repair_archive_metadata(root_dir, apply=True)

    assert repair.checked_shards == 1
    assert repair.skipped_shards == 1
    assert repair.skipped_reasons == (
        "archive root has unregistered shard file(s) (count=1)",
    )
    assert repair.errors == repair.skipped_reasons
    assert unregistered_shard.exists()


def test_repair_archive_metadata_reports_missing_shards_without_creating_them(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    manifest.close()

    repair = archive_storage.repair_archive_metadata(root_dir, apply=True)

    assert repair.checked_shards == 0
    assert repair.repaired_shards == 0
    assert repair.pruned_missing_shards == 0
    assert repair.skipped_shards == 1
    assert repair.skipped_reasons == ("-1001:2026-05:001: missing shard file",)
    assert repair.errors == ()
    assert not (root_dir / "shards" / "group_-1001" / "2026-05.sqlite3").exists()


def test_repair_archive_metadata_dry_run_prune_missing_shards_keeps_manifest(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    manifest.close()

    repair = archive_storage.repair_archive_metadata(
        root_dir,
        apply=False,
        prune_missing_shards=True,
    )
    status = archive_storage.inspect_archive_status(root_dir)

    assert repair.checked_shards == 0
    assert repair.repaired_shards == 0
    assert repair.pruned_missing_shards == 1
    assert repair.skipped_shards == 0
    assert repair.skipped_reasons == ()
    assert repair.errors == ()
    assert status.shard_count == 1
    assert status.missing_shard_count == 1
    assert not (root_dir / "shards" / "group_-1001" / "2026-05.sqlite3").exists()


def test_repair_archive_metadata_apply_prunes_missing_shard_records(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    manifest.close()

    repair = archive_storage.repair_archive_metadata(
        root_dir,
        apply=True,
        prune_missing_shards=True,
    )
    status = archive_storage.inspect_archive_status(root_dir)

    assert repair.checked_shards == 0
    assert repair.repaired_shards == 0
    assert repair.pruned_missing_shards == 1
    assert repair.skipped_shards == 0
    assert repair.skipped_reasons == ()
    assert repair.errors == ()
    assert status.shard_count == 0
    assert status.missing_shard_count == 0


def test_inspect_archive_status_reports_missing_shards(tmp_path):
    root_dir = tmp_path / "full_archive"
    manifest = archive_storage.connect(root_dir / "manifest.sqlite3")
    archive_storage.select_shard(
        manifest,
        root_dir,
        chat_id=-1001,
        message_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        max_messages_per_shard=500_000,
        max_shard_size_bytes=1024 * 1024,
    )
    manifest.close()

    report = archive_storage.inspect_archive_status(root_dir)

    assert report.shard_count == 1
    assert report.missing_shard_count == 1
    assert report.errors == ("-1001:2026-05:001: missing shard file",)
    assert report.degraded is True
