# telegram-watch

[English](README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

[Follow on X](https://x.com/o1xhack) · [Telegram EN channel](https://t.me/lalabeng) · [Telegram 中文频道](https://t.me/o1xinsight)

## Highlights

Fully local Telegram watcher powered by Telethon. Key highlights:

- **User-level monitoring** – logs in with your own account (not a Bot) and watches a target supergroup/channel for a fixed list of tracked user IDs.
- **Rich capture** – stores text, reply chains, and media snapshots into SQLite plus a local media folder.
- **Automated reporting** – on each configurable window (5–120 minutes, etc.) it builds a full HTML report, pushes the file to the control chat, then streams every tracked message (with clickable `MSG` links back to Telegram).
- **Inline media preview** – HTML embeds images as Base64, so reports opened inside Telegram or on mobile still show pictures.
- **Heartbeat + alerts** – if no activity occurs for 2 hours the control chat receives “Watcher is still running”; unhandled exceptions trigger an error notification before exit.
- **Retention controls** – `reporting.retention_days` (default 30) keeps report/media folders in check and purges old ones; values >180 prompt for confirmation.
- **Optional Bark push** – configure your Bark key to mirror report/heartbeat/error notifications to your phone (grouped under “Telegram Watch”).

The sections below cover installation, configuration, and usage.

## Prerequisites

- macOS with Python 3.11+
- Telegram API ID + hash from [my.telegram.org](https://my.telegram.org/) (user account access)
- Local storage only (no cloud services required)

## Installation

Choose **either** a built-in `venv` or a Conda environment; both work as long as Python ≥ 3.11 is active.

### Option A: `python -m venv`

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e .
```

### Option B: Conda

```bash
conda create -n tgwatch python=3.11
conda activate tgwatch
python -m pip install -e .
```

> Tip: keep exactly one environment active when running commands. The prompt should show either `(.venv)` or `(tgwatch)` before `python -m tgwatch ...`.

## Configuration

1. Copy the example config.

   ```bash
   cp config.example.toml config.toml
   ```

2. Edit `config.toml` and fill:

   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file` (defaults to `data/tgwatch.session`)
   - `target.target_chat_id` (the group/channel ID)
   - `target.tracked_user_ids` (list of numeric user IDs to monitor)
   - `[target.tracked_user_aliases]` (optional ID→alias mapping for nicer reports)
   - `control.control_chat_id` (where digests + commands live)
   - `storage.db_path` & `storage.media_dir`
   - `reporting.reports_dir` & `reporting.summary_interval_minutes` (controls how often reports are delivered)
   - `reporting.timezone` (optional, e.g., `Asia/Shanghai`, `America/Los_Angeles`, `America/New_York`, `Asia/Tokyo`)
   - `reporting.retention_days` (defaults to 30; when `run` starts, reports older than this many days are deleted. Values > 180 prompt for confirmation.)
   - `[notifications] bark_key` (optional Bark key for mirror notifications)

### Bark key quick guide

1. Install the Bark app on your phone and open it. Tap the gear icon → “复制设备码 (Copy Key)” to copy the device key (looks like `abc1234567890abcdef`).
2. Paste the key into `config.toml`:

   ```toml
   [notifications]
   bark_key = "your_bark_key_here"
   ```

3. Run `tgwatch run ...` as usual. Reports/heartbeats/errors will mirror to Bark under the “Telegram Watch” group.

   See `docs/configuration.md` for step-by-step instructions on gathering Telegram IDs (including private groups without invite links), filling the credential fields, and choosing safe local storage paths.

> ⚠️ Never commit `config.toml`, session files, `data/`, or `reports/`. These contain private information.

## Usage

All commands work either through the module runner (`python -m tgwatch ...`) or the CLI entry point (`tgwatch ...`). Always pass your config path.

### Doctor

Validate config + directories and ensure the SQLite schema can be created:

```bash
python -m tgwatch doctor --config config.toml
```

### Once (batch report)

Fetch tracked messages from the last window (e.g., 2 hours), save them to the DB, and render an HTML report under `reports/YYYY-MM-DD/HHMM/index.html`:

```bash
python -m tgwatch once --config config.toml --since 2h
# 加上 --push 可以把同一窗口的报告和消息推送到控制聊天，便于测试
python -m tgwatch once --config config.toml --since 2h --push
```

### Run (daemon)

Interactive watch mode. First run will prompt for the Telegram login code in the terminal.

```bash
python -m tgwatch run --config config.toml
```

Run mode:

- Listens to the target chat; when tracked users send messages, stores them (text, replies, media snapshots).
- Captures reply context, including quoted text and media, so reports show the referenced screenshots.
- At each `summary_interval_minutes` window (30 min, 120 min, etc.), it generates the HTML report, uploads the file to the control chat, then sequentially pushes every tracked message (text + reply info + media) from that window.
- Reports embed media as Base64 data URIs so the file stays self-contained when opened in Telegram (files grow with large images).
- Listens for commands **from your own account** inside the control chat:
  - `/help`
  - `/last <user_id|@username> [N]`
  - `/since <10m|2h|ISO>`
  - `/export <10m|2h|ISO>`

## Testing

Minimal unit tests cover config parsing and database schema creation:

```bash
pytest
```

## Privacy & Safety

- Runs entirely on your Mac; no remote services or uploads.
- Does not log API hashes, phone numbers, or chat contents.
- Session + DB + media directories are `.gitignore`d; keep secrets local.
- Flood-wait handling/backoff is included for login, downloads, and bot responses.

## License

MIT. See `LICENSE`.
