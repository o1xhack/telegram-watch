"""HTML report generation and digest formatting."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from base64 import b64encode
from html import escape
from pathlib import Path
from typing import Sequence
import os

from .config import Config
from .storage import DbMessage, DbMedia
from .links import build_message_link
from .timeutils import humanize_timedelta, utc_now


CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; }
h1 { margin-bottom: 0; }
.meta { color: #555; margin-bottom: 1rem; }
.user-section { margin-top: 2rem; }
.message { border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
.timestamp { color: #666; font-size: 0.9rem; }
.reply { background: #f7f7f7; padding: 0.5rem; border-left: 3px solid #999; margin-top: 0.75rem; }
.media-gallery { margin-top: 0.75rem; display: flex; flex-wrap: wrap; gap: 0.5rem; }
.media-gallery img { max-width: 280px; border-radius: 4px; border: 1px solid #ccc; }
pre { white-space: pre-wrap; }
"""


def generate_report(
    messages: Sequence[DbMessage],
    config: Config,
    since: datetime,
    until: datetime | None,
    report_dir: Path | None = None,
    report_name: str = "index.html",
) -> Path:
    """Generate HTML report and return the file path."""
    if report_dir is None:
        now = utc_now()
        report_dir = (
            config.reporting.reports_dir
            / now.strftime("%Y-%m-%d")
            / now.strftime("%H%M")
        )
    report_dir.mkdir(parents=True, exist_ok=True)
    html = _render_html(messages, config, since, until, report_dir)
    path = report_dir / report_name
    path.write_text(html, encoding="utf-8")
    return path


def _render_html(
    messages: Sequence[DbMessage],
    config: Config,
    since: datetime,
    until: datetime | None,
    report_dir: Path,
) -> str:
    grouped = _group_by_user(messages)
    until_text = until.isoformat() if until else "now"
    duration = until - since if until else utc_now() - since
    tz = config.reporting.timezone
    since_local = _format_timestamp(since, tz)
    until_local = _format_timestamp(until or utc_now(), tz)
    header = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>telegram-watch report</title>
        <style>{CSS}</style>
    </head>
    <body>
        <h1>telegram-watch report</h1>
        <div class="meta">Window: {escape(since_local)} → {escape(until_local)} ({escape(humanize_timedelta(duration))})</div>
    """
    body_parts = [header]
    if not grouped:
        body_parts.append("<p>No tracked messages.</p>")
    for sender_id, items in grouped.items():
        label = config.describe_user(sender_id)
        body_parts.append(f'<div class="user-section">')
        body_parts.append(f"<h2>{escape(label)}</h2>")
        for msg in items:
            body_parts.append(_render_message(msg, config, report_dir))
        body_parts.append("</div>")
    body_parts.append("</body></html>")
    return "\n".join(body_parts)


def _render_message(message: DbMessage, config: Config, report_dir: Path) -> str:
    text_html = (
        f"<pre>{escape(message.text)}</pre>" if message.text is not None else "<em>No text</em>"
    )
    reply_block = ""
    reply_media = [media for media in message.media if media.is_reply]
    if message.replied_sender_id:
        reply_text = (
            escape(message.replied_text or "")
            if message.replied_text
            else "<em>no text</em>"
        )
        replied_to = (
            config.describe_user(int(message.replied_sender_id))
            if message.replied_sender_id is not None
            else "unknown user"
        )
        reply_block = (
            '<div class="reply">'
            f"Reply to {escape(replied_to)} at {escape(message.replied_date.isoformat() if message.replied_date else 'unknown')}"
            f"<div>{reply_text}</div>"
            f"{_render_media_gallery(reply_media, report_dir) if reply_media else ''}"
            "</div>"
        )
    regular_media = [media for media in message.media if not media.is_reply]
    media_block = _render_media_gallery(regular_media, report_dir)
    local_ts = _format_timestamp(message.date, config.reporting.timezone)
    msg_link = build_message_link(config.target.target_chat_id, message.message_id)
    msg_label = f"MSG {message.message_id}"
    if msg_link:
        msg_label = f'<a href="{escape(msg_link)}" target="_blank">{escape(msg_label)}</a>'
    return (
        '<div class="message">'
        f'<div class="timestamp">{escape(local_ts)} — {msg_label}</div>'
        f"{text_html}"
        f"{reply_block}"
        f"{media_block}"
        "</div>"
    )


def _render_media_gallery(media_items: list[DbMedia], report_dir: Path) -> str:
    if not media_items:
        return ""
    figures = []
    for media in media_items:
        abs_path = Path(media.file_path).resolve()
        data_uri = _media_to_data_uri(abs_path, media.mime_type)
        if not data_uri:
            rel_url = escape(os.path.relpath(abs_path, report_dir))
            figures.append(f'<img src="{rel_url}" alt="media {media.media_index}">')
        else:
            figures.append(f'<img src="{data_uri}" alt="media {media.media_index}">')
    return '<div class="media-gallery">' + "".join(figures) + "</div>"


def _format_timestamp(dt: datetime, tz: timezone) -> str:
    local = dt.astimezone(tz)
    tzname = local.tzname() or _offset_label(local.utcoffset())
    return local.strftime("%Y.%m.%d %H:%M:%S ") + f"({tzname})"


def _offset_label(offset: timedelta | None) -> str:
    if offset is None:
        return "UTC"
    total_minutes = int(offset.total_seconds() // 60)
    hours, minutes = divmod(abs(total_minutes), 60)
    sign = "+" if total_minutes >= 0 else "-"
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _media_to_data_uri(path: Path, mime_type: str | None) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    mime = mime_type or _guess_mime(path)
    if not mime or not mime.startswith("image/"):
        return None
    encoded = b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _guess_mime(path: Path) -> str | None:
    try:
        import mimetypes
    except ImportError:  # pragma: no cover - stdlib always available
        return None
    mime, _ = mimetypes.guess_type(str(path))
    return mime


def _group_by_user(messages: Sequence[DbMessage]) -> dict[int, list[DbMessage]]:
    grouped: dict[int, list[DbMessage]] = defaultdict(list)
    for msg in messages:
        grouped[msg.sender_id].append(msg)
    return grouped
