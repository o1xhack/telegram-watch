# SPEC: tgwatch MVP

## Core concept
- The program runs as a Telegram user client (Telethon).
- It monitors ONE target group chat (target_chat_id).
- It tracks N users by stable numeric user_id (tracked_user_ids).
- It uses ONE control chat (control_chat_id) where:
  - It posts periodic digests
  - It listens to your commands (from your own account) and replies with results

## Data to capture per message (tracked users only)
- chat_id, message_id, date (timezone-aware), sender_id
- text (raw)
- reply_to_msg_id (if any) and a cached snapshot of the replied message:
  - replied_sender_id, replied_date, replied_text (truncate to 280 chars)
- media:
  - if photo/document exists, download to local media folder and record file path
  - support multiple media per message if Telegram provides it

## Storage
- SQLite file (default: data/tgwatch.sqlite3)
- Tables: messages, media
- Must be idempotent: re-running should not duplicate rows

## Reporting
- Every `summary_interval_minutes` (default 120):
  - Generate HTML report under reports/YYYY-MM-DD/HHMM/index.html
  - Include message list grouped by tracked user
  - Show reply context inline (replied snapshot)
  - Show images via <img src="../media/..."> (relative paths)
- Also send a short digest message to control_chat_id:
  - For each tracked user: count + first 3 messages preview + link to local report path

## Telegram "command interface" (in control chat)
- /help -> list commands
- /last <user_id|@username|name> <N> -> return last N captured messages (text only + timestamps)
- /since <Nh|Nm> -> return summary counts per user for that window
- /export <Nh|date> -> generate a report and reply with local path

## Operational modes
- `run` (daemon): listens for new messages + schedules periodic summary
- `once` (batch): fetches messages since a time window and generates report, then exits
- `doctor`: validates environment/config

## Config file
TOML keys (config.toml):
- telegram.api_id (int)
- telegram.api_hash (string)
- telegram.session_file (string, default: data/session.session)
- target.target_chat_id (int)
- target.tracked_user_ids (array of int)
- control.control_chat_id (int)
- storage.db_path (string)
- storage.media_dir (string)
- reporting.reports_dir (string)
- reporting.summary_interval_minutes (int)
