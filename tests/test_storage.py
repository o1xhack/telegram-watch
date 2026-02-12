from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram_watch import storage


def test_schema_creation_and_persist(tmp_path):
    db_path = tmp_path / "tgwatch.sqlite3"
    conn = storage.connect(db_path)
    storage.ensure_schema(conn)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    msg = storage.StoredMessage(
        chat_id=-1001,
        message_id=1,
        sender_id=123,
        date=now,
        text="hello",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
    )
    media_file = tmp_path / "media" / "photo.jpg"
    media_file.parent.mkdir()
    media_file.write_bytes(b"123")
    media = [
        storage.StoredMedia(
            chat_id=-1001,
            message_id=1,
            file_path=str(media_file),
            mime_type="image/jpeg",
            file_size=3,
            media_index=0,
            is_reply=False,
        )
    ]
    storage.persist_message(conn, msg, media)

    rows = storage.fetch_messages_between(conn, [123], now, now)
    assert len(rows) == 1
    assert rows[0].media
    assert Path(rows[0].media[0].file_path) == media_file
    assert rows[0].media[0].is_reply is False

    summary = storage.fetch_summary_counts(conn, [123], now)
    assert summary[123] == 1


def test_reply_media_flag(tmp_path):
    db_path = tmp_path / "tgwatch.sqlite3"
    conn = storage.connect(db_path)
    storage.ensure_schema(conn)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    msg = storage.StoredMessage(
        chat_id=-1001,
        message_id=5,
        sender_id=999,
        date=now,
        text="reply container",
        reply_to_msg_id=3,
        replied_sender_id=111,
        replied_date=now,
        replied_text="original",
    )
    media_file = tmp_path / "media" / "reply.jpg"
    media_file.parent.mkdir(exist_ok=True)
    media_file.write_bytes(b"456")
    reply_media = [
        storage.StoredMedia(
            chat_id=-1001,
            message_id=5,
            file_path=str(media_file),
            mime_type="image/jpeg",
            file_size=3,
            media_index=0,
            is_reply=True,
        )
    ]
    storage.persist_message(conn, msg, reply_media)
    rows = storage.fetch_messages_between(conn, [999], now, now)
    assert rows[0].media[0].is_reply is True


def test_fetch_summary_counts_filters_by_chat_id(tmp_path):
    db_path = tmp_path / "tgwatch.sqlite3"
    conn = storage.connect(db_path)
    storage.ensure_schema(conn)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    msg_a = storage.StoredMessage(
        chat_id=1,
        message_id=1,
        sender_id=123,
        date=now,
        text="hello",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
    )
    msg_b = storage.StoredMessage(
        chat_id=2,
        message_id=2,
        sender_id=123,
        date=now,
        text="world",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
    )
    storage.persist_message(conn, msg_a, [])
    storage.persist_message(conn, msg_b, [])

    since = now - timedelta(minutes=1)
    counts = storage.fetch_summary_counts(
        conn,
        [123],
        since,
        chat_ids=[1],
    )
    assert counts == {123: 1}


def test_fetch_messages_between_filters_by_chat_id(tmp_path):
    db_path = tmp_path / "tgwatch.sqlite3"
    conn = storage.connect(db_path)
    storage.ensure_schema(conn)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    msg_a = storage.StoredMessage(
        chat_id=1,
        message_id=1,
        sender_id=123,
        date=now,
        text="hello",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
    )
    msg_b = storage.StoredMessage(
        chat_id=2,
        message_id=2,
        sender_id=123,
        date=now,
        text="world",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
    )
    storage.persist_message(conn, msg_a, [])
    storage.persist_message(conn, msg_b, [])

    rows = storage.fetch_messages_between(
        conn,
        [123],
        now - timedelta(minutes=1),
        now + timedelta(minutes=1),
        chat_ids=[1],
    )
    assert len(rows) == 1
    assert rows[0].chat_id == 1


def test_fetch_recent_messages_filters_by_chat_id(tmp_path):
    db_path = tmp_path / "tgwatch.sqlite3"
    conn = storage.connect(db_path)
    storage.ensure_schema(conn)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    msg_a = storage.StoredMessage(
        chat_id=1,
        message_id=1,
        sender_id=123,
        date=now,
        text="hello",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
    )
    msg_b = storage.StoredMessage(
        chat_id=2,
        message_id=2,
        sender_id=123,
        date=now,
        text="world",
        reply_to_msg_id=None,
        replied_sender_id=None,
        replied_date=None,
        replied_text=None,
    )
    storage.persist_message(conn, msg_a, [])
    storage.persist_message(conn, msg_b, [])

    rows = storage.fetch_recent_messages(
        conn,
        123,
        10,
        chat_ids=[2],
    )
    assert len(rows) == 1
    assert rows[0].chat_id == 2


def test_reply_snapshot_candidate_and_cleanup(tmp_path):
    db_path = tmp_path / "tgwatch.sqlite3"
    conn = storage.connect(db_path)
    storage.ensure_schema(conn)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    msg = storage.StoredMessage(
        chat_id=1,
        message_id=9,
        sender_id=321,
        date=now,
        text="topic linkage",
        reply_to_msg_id=100,
        replied_sender_id=777,
        replied_date=now,
        replied_text="quoted",
    )
    media_file = tmp_path / "media" / "payload.jpg"
    media_file.parent.mkdir(exist_ok=True)
    media_file.write_bytes(b"123")
    media = [
        storage.StoredMedia(
            chat_id=1,
            message_id=9,
            file_path=str(media_file),
            mime_type="image/jpeg",
            file_size=3,
            media_index=0,
            is_reply=False,
        ),
        storage.StoredMedia(
            chat_id=1,
            message_id=9,
            file_path=str(media_file),
            mime_type="image/jpeg",
            file_size=3,
            media_index=1,
            is_reply=True,
        ),
    ]
    storage.persist_message(conn, msg, media)

    candidates = storage.fetch_reply_snapshot_candidates(conn)
    assert candidates == [(1, 9)]

    cleared_messages, cleared_media = storage.clear_reply_snapshots(conn, candidates)
    assert cleared_messages == 1
    assert cleared_media == 1

    rows = storage.fetch_messages_between(
        conn,
        [321],
        now - timedelta(minutes=1),
        now + timedelta(minutes=1),
    )
    assert len(rows) == 1
    cleaned = rows[0]
    assert cleaned.reply_to_msg_id == 100
    assert cleaned.replied_sender_id is None
    assert cleaned.replied_date is None
    assert cleaned.replied_text is None
    assert len(cleaned.media) == 1
    assert cleaned.media[0].is_reply is False
