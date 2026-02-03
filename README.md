# telegram-watch

[English](README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

[Follow on X](https://x.com/o1xhack) · [Telegram EN channel](https://t.me/lalabeng) · [Telegram 中文频道](https://t.me/o1xinsight)

## Key Features

Turn noisy Telegram groups into a personal, searchable signal feed — **fully local, no Bot required**.

- **Follow the signal, not the noise**: Track a strict watchlist of high-value accounts inside large groups (filtered by user ID).
- **Your Chat is the Dashboard**: Receive digests and live alerts in a private "Control Chat". Query anytime with `/last`, `/since`, or `/export` directly from your own account.
- **Scheduled Digests + Live Stream**: Get auto-generated HTML reports with media context, plus a real-time stream of tracked messages linking back to the source (`MSG` link).
- **Permanent Evidence Trail**: Messages and replies are archived in SQLite; media snapshots are saved locally for offline review.
- **Auto-Organized via Topics**: Automatically route tracked users into their own Telegram Topics (forum mode) to keep conversations distinct.
- **Set & Forget Reliability**: Built for the long haul with auto-retention cleanup, heartbeat alerts, and smart FloodWait handling.
- **Privacy-First Architecture**: Runs 100% on your machine — no cloud, no third-party collectors, no data leakage.
- **Cross-Platform Alerts**: Optional Bark mirroring to push summaries and errors to your phone outside of Telegram.


Perfect for: community operators, researchers, traders, or anyone who needs **signal extraction + local archiving** from Telegram. 

The sections below cover installation, configuration, and usage.

## Prerequisites

- macOS with Python 3.11+
- Telegram API ID + hash from [my.telegram.org](https://my.telegram.org/) (user account access)
- Local storage only (no cloud services required)
- A Mac that can stay online for long periods if you run the daemon (a Mac mini or any always-on machine works best)

## Installation

This project is not published as a PyPI package yet, so installation is done via Git (tagged release) or editable mode.

### Step 1 — Install the package (recommended: tagged release)

**Recommended (stable & reproducible): install a tagged release**

> Use this if you just want to run `tgwatch` and keep your version pinned to a release tag.

```bash
pip install "git+https://github.com/o1xhack/telegram-watch.git@v0.3.1"
python -m tgwatch --help
```

**For development: editable install**

> Use this if you're hacking on the code locally.

```bash
pip install -e .
python -m tgwatch --help
```

### Step 2 — Create a Python environment (pick one)

You can use either a built-in `venv` or a Conda environment. Both work as long as Python ≥ 3.11 is active.

#### Option A: `python -m venv` (recommended)

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
```

#### Option B: Conda

```bash
conda create -n tgwatch python=3.11
conda activate tgwatch
python -m pip install -U pip
```

> Tip: keep exactly one environment active when running commands. The prompt should show either `(.venv)` or `(tgwatch)` before `python -m tgwatch ...`.

### Step 3 — Continue with the same steps

Once installed and your environment is active, the rest is the same for everyone:

1) copy `config.example.toml` → `config.toml`  
2) run `tgwatch doctor`  
3) run `tgwatch once --since 2h --push` to test  
4) run `tgwatch run` for daemon mode

## Configuration

1. Copy the example config.

   ```bash
   cp config.example.toml config.toml
   ```

   Tip: launch the local GUI to edit config without touching the file:

   ```bash
   tgwatch gui
   ```

2. Launch the local GUI (recommended) to edit config:

   ```bash
   tgwatch gui
   ```

   Directly editing `config.toml` is still supported, but discouraged because it is easier to make mistakes.

3. If you choose to edit the file manually, fill:

   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file` (defaults to `data/tgwatch.session`)
   - `[sender] session_file` (optional second-account session used to send control messages so the primary account can receive notifications)
   - `targets[].name` (a label for each target group)
   - `targets[].target_chat_id` (the group/channel ID)
   - `targets[].tracked_user_ids` (list of numeric user IDs to monitor)
   - `targets[].summary_interval_minutes` (optional per-target report interval)
   - `targets[].control_group` (optional; required when multiple control groups are configured)
   - `[targets.tracked_user_aliases]` (optional ID→alias mapping for nicer reports)
   - `control_groups.<name>.control_chat_id` (where digests + commands live)
   - `control_groups.<name>.is_forum` / `control_groups.<name>.topic_routing_enabled` / `[control_groups.<name>.topic_user_map]` (optional per-user routing to Telegram Topics)
   - `storage.db_path` & `storage.media_dir`
   - `reporting.reports_dir` & `reporting.summary_interval_minutes` (default report interval if a target does not override it)
   - `reporting.timezone` (optional, e.g., `Asia/Shanghai`, `America/Los_Angeles`, `America/New_York`, `Asia/Tokyo`)
   - `reporting.retention_days` (defaults to 30; when `run` starts, reports older than this many days are deleted. Values > 180 prompt for confirmation.)
   - `[notifications] bark_key` (optional Bark key for mirror notifications)
   - `[display] show_ids` (default `true`) & `time_format` (strftime string) control how control-chat pushes render names/timestamps

Single-group configs using `[target]` + `[control]` are still supported for backwards compatibility.

### Bark key quick guide

1. Install the Bark app on your phone and open it. Tap the gear icon → “复制设备码 (Copy Key)” to copy the device key (looks like `abc1234567890abcdef`).

2. Paste the key into `config.toml`:

   ```toml
   [notifications]
   bark_key = "your_bark_key_here"
   ```

3. Run `tgwatch run ...` as usual. Reports/heartbeats/errors will mirror to Bark under the “Telegram Watch” group.

   See [docs/configuration.md](docs/configuration.md) for step-by-step instructions on gathering Telegram IDs (including private groups without invite links), filling the credential fields, and choosing safe local storage paths.

> ⚠️ Never commit `config.toml`, session files, `data/`, or `reports/`. These contain private information.

## Usage

All commands work either through the module runner (`python -m tgwatch ...`) or the CLI entry point (`tgwatch ...`). Always pass your config path.

### Doctor

Validate config + directories and ensure the SQLite schema can be created:

```bash
python -m tgwatch doctor --config config.toml
```

### GUI (local config editor)

Launch the local UI (default: `http://127.0.0.1:8765`) to manage targets/control groups. The browser opens automatically:

```bash
tgwatch gui
```

### Once (batch report)

Fetch tracked messages from the last window (e.g., 2 hours), save them to the DB, and render one HTML report per target under `reports/YYYY-MM-DD/HHMM/index.html`:

```bash
python -m tgwatch once --config config.toml --since 2h
# With --push the report and messages will be pushed to the control chat (and Bark if configured)
python -m tgwatch once --config config.toml --since 2h --push
```

### Run (daemon)

Interactive watch mode. First run will prompt for the Telegram login code in the terminal.

```bash
python -m tgwatch run --config config.toml
```

Run mode:

- Listens to each target chat; when tracked users send messages, stores them (text, replies, media snapshots).
- Captures reply context, including quoted text and media snapshots, so reports show the referenced content.
- At each target’s `summary_interval_minutes` window (or the global default), it generates the HTML report, uploads the file to the mapped control group, then sequentially pushes every tracked message (text + reply info + media) from that window.
- Reports embed images directly in the HTML (Base64) so they display anywhere; if a file can’t be read, it falls back to a relative file path.
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
- Flood-wait handling/backoff is applied to Telegram API calls (sending, downloads, entity lookups).

## Changelog

Release notes (newest at the top, older entries further down) live in [docs/CHANGELOG.md](docs/CHANGELOG.md). Each entry links to the request ID so you can see which features or fixes landed in a given version.

## License

MIT. See `LICENSE`.
