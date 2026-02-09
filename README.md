# telegram-watch

[English](README.md) | [简体中文](docs/README.zh-Hans.md) | [繁體中文](docs/README.zh-Hant.md) | [日本語](docs/README.ja.md)

**Docs Version:** `v1.0.0`

[Follow on X](https://x.com/o1xhack) · [Telegram EN channel](https://t.me/lalabeng) · [Telegram 中文频道](https://t.me/o1xinsight)

## Key Features

Turn noisy Telegram groups into a private, structured signal system — **fully local, no bot required**.

![telegram-watch GUI](docs/assets/tgwatch-gui-v1.png)

- **Multi-Target Monitoring**: Track multiple groups/channels at once, each with its own watchlist, aliases, and report interval.
- **Control Group Routing**: Route each target to a specific control group to separate workflows cleanly.
- **Topic Mapping Per Target**: In forum-mode control groups, map `target_chat_id + user_id` to topic IDs so the same user ID can route differently across source groups.
- **GUI-First Configuration**: Manage credentials, targets, control groups, mappings, and storage from a local web UI.
- **One-Click Local Launcher**: Start with Conda-first (`tgwatch`) setup and automatic `venv` fallback.
- **GUI Runner Controls**: Run once (with optional target and push), start daemon, stop daemon, and inspect live logs in one place.
- **Safe Run Guardrails**: Session prechecks, retention confirmation for long windows, and explicit in-UI error feedback.
- **Local Persistence by Default**: Archive messages in SQLite, keep media snapshots, and generate HTML reports for review.
- **Privacy by Design**: No cloud dependency, no secret logging, and sensitive runtime files excluded from git.


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
pip install "git+https://github.com/o1xhack/telegram-watch.git@v1.0.0"
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

   One-click option: double-click `launch_tgwatch.command` (macOS) or `launch_tgwatch.bat` (Windows). The launcher now prefers Conda (`tgwatch` env): if Conda exists it will reuse/create `tgwatch`; if Conda is unavailable it falls back to `.venv`. It then installs dependencies, copies `config.toml` if missing, and opens the GUI. The macOS launcher is bash-compatible, and if `pip/setuptools/wheel` upgrade fails under restricted networks it will warn and continue to attempt project installation.

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

   - `config_version` (must be `1.0`)
   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file` (defaults to `data/tgwatch.session`)
   - `[sender] session_file` (optional second-account session used to send control messages so the primary account can receive notifications)
   - `targets[].name` (optional label for each target group; if omitted tgwatch labels them `group-1`, `group-2`, etc)
   - `targets[].target_chat_id` (the group/channel ID)
   - `targets[].tracked_user_ids` (list of numeric user IDs to monitor)
   - `targets[].summary_interval_minutes` (optional per-target report interval)
   - `targets[].control_group` (optional; required when multiple control groups are configured)
   - `[targets.tracked_user_aliases]` (optional ID→alias mapping for nicer reports)
   - `control_groups.<name>.control_chat_id` (where digests + commands live)
   - `control_groups.<name>.is_forum` / `control_groups.<name>.topic_routing_enabled` / `[control_groups.<name>.topic_target_map.<target_chat_id>]` (optional per-user routing to Telegram Topics)
   - `storage.db_path` & `storage.media_dir`
   - `reporting.reports_dir` & `reporting.summary_interval_minutes` (default report interval if a target does not override it)
   - `reporting.timezone` (optional, e.g., `Asia/Shanghai`, `America/Los_Angeles`, `America/New_York`, `Asia/Tokyo`)
   - `reporting.retention_days` (defaults to 30; when `run` starts, reports older than this many days are deleted. CLI prompts for confirmation when values > 180; GUI uses an in-app confirm flow.)
   - `[notifications] bark_key` (optional Bark key for mirror notifications)
   - `[display] show_ids` (default `true`) & `time_format` (strftime string) control how control-chat pushes render names/timestamps

Single-group configs using `[target]` + `[control]` are still supported for backwards compatibility.

### Run once for a single target

`tgwatch once` defaults to all targets. To run it for a single group, pass a target name or `target_chat_id`:

```bash
tgwatch once --config config.toml --since 2h --target group-1
tgwatch once --config config.toml --since 2h --target -1001234567890
```

The GUI Run once panel includes a **Push to control chat** toggle (default off).

### Migration

If you upgrade from an older config (missing `config_version`), tgwatch will stop and prompt you to migrate.

1. The GUI shows a locked banner with a **Migrate Config** button.
2. CLI `run`/`once` show a red error and ask whether to migrate.
3. Migration renames `config.toml` to `config-old-0.1.toml` and creates a new `config.toml` with best-effort values.

Review the new `config.toml` before running again. Backup files like `config-old-0.1.toml` are ignored by git.

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

The GUI also provides **Run once**, **Run daemon**, and **Stop daemon** buttons with a live log panel. `Run daemon` starts a background process, so closing the browser will not stop it; re-open the GUI to reattach logs. If no session file exists yet, run `python -m tgwatch run --config config.toml` once in a terminal to complete login before using the GUI runner.
When `retention_days > 180`, clicking **Run daemon** opens a retention confirmation block. You must check the risk acknowledgement before **Confirm & Start Run** becomes available. If a runner action fails, the Runner message panel shows the error.

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
