from datetime import datetime, timezone
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
