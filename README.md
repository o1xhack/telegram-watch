# telegram-watch

Telegram user-account watcher built with Telethon. The tool logs in with your own account (not a Bot) and watches a single target chat for a fixed list of tracked user IDs. Messages, media, and reply context are stored in a local SQLite database and rendered into HTML reports on a configurable schedule.

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
   - `reporting.reports_dir` & `reporting.summary_interval_minutes`

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
```

### Run (daemon)

Interactive watch mode. First run will prompt for the Telegram login code in the terminal.

```bash
python -m tgwatch run --config config.toml
```

Run mode:

- Listens to the target chat; when tracked users send messages, stores them (text, replies, media snapshots).
- Schedules a periodic summary (default every 120 minutes) that posts a digest + local report path to the `control_chat_id`.
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
