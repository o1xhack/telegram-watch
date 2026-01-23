"""HTML report generation and digest formatting."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Sequence
import os

from .config import Config
from .storage import DbMessage
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
) -> Path:
    """Generate HTML report and return the file path."""
    now = utc_now()
    report_dir = (
        config.reporting.reports_dir
        / now.strftime("%Y-%m-%d")
        / now.strftime("%H%M")
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    html = _render_html(messages, config, since, until, report_dir)
    path = report_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


def build_digest(
    messages: Sequence[DbMessage],
    config: Config,
    since: datetime,
    until: datetime | None,
) -> str:
    """Build a compact digest for control chat."""
    grouped = _group_by_user(messages)
    headline = f"Tracked messages {since.isoformat()} → {(until.isoformat() if until else 'now')}"
    lines = [headline]
    for sender_id, items in grouped.items():
        previews = []
        for msg in items[:3]:
            preview = _short_preview(msg)
            previews.append(f"- {preview}")
        label = config.describe_user(sender_id)
        lines.append(f"{label}: {len(items)} msgs")
        lines.extend(previews)
    if len(lines) == 1:
        lines.append("No tracked messages in this window.")
    return "\n".join(lines)


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
    header = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>telegram-watch report</title>
        <style>{CSS}</style>
    </head>
    <body>
        <h1>telegram-watch report</h1>
        <div class="meta">Window: {escape(since.isoformat())} → {escape(until_text)} ({escape(humanize_timedelta(duration))})</div>
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
            "</div>"
        )
    media_block = ""
    if message.media:
        figures = []
        for media in message.media:
            abs_path = Path(media.file_path).resolve()
            rel_url = os.path.relpath(abs_path, report_dir)
            figures.append(f'<img src="{escape(rel_url)}" alt="media {media.media_index}">')
        media_block = '<div class="media-gallery">' + "".join(figures) + "</div>"
    return (
        '<div class="message">'
        f'<div class="timestamp">{escape(message.date.isoformat())} — message #{message.message_id}</div>'
        f"{text_html}"
        f"{reply_block}"
        f"{media_block}"
        "</div>"
    )


def _group_by_user(messages: Sequence[DbMessage]) -> dict[int, list[DbMessage]]:
    grouped: dict[int, list[DbMessage]] = defaultdict(list)
    for msg in messages:
        grouped[msg.sender_id].append(msg)
    return grouped


def _short_preview(message: DbMessage) -> str:
    text = message.text or "<no text>"
    text = text.replace("\n", " ")
    if len(text) > 90:
        text = text[:90] + "…"
    return f"{message.date.isoformat()} — {text}"
