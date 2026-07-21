# telegram-watch

[English](README.md) | [简体中文](docs/README.zh-Hans.md) | [繁體中文](docs/README.zh-Hant.md) | [日本語](docs/README.ja.md)

[![Release](https://img.shields.io/github/v/release/o1xhack/telegram-watch?style=for-the-badge&label=release&color=7c3aed)](https://github.com/o1xhack/telegram-watch/releases/latest)
[![Stars](https://img.shields.io/github/stars/o1xhack/telegram-watch?style=for-the-badge&label=stars&color=7c3aed)](https://github.com/o1xhack/telegram-watch/stargazers)
[![License](https://img.shields.io/github/license/o1xhack/telegram-watch?style=for-the-badge&label=license&color=7c3aed)](LICENSE)

[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-o1xhack-ea4aaa?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/o1xhack)

**Docs Version:** `v1.0.7` (release `v1.7.0`)

[Follow on X](https://x.com/o1xhack) · [Telegram EN channel](https://t.me/lalabeng) · [Telegram 中文频道](https://t.me/o1xinsight)

## Key Features

Turn noisy Telegram groups into a private, structured signal system — **fully local, no bot required**.

![telegram-watch GUI](docs/assets/tgwatch-gui-v1.png)

- **Multi-Target Monitoring**: Track multiple groups/channels at once, each with its own watchlist, aliases, and report interval.
- **Control Group Routing**: Route each target to a specific control group to separate workflows cleanly.
- **Topic Mapping Per Target**: In forum-mode control groups, map `target_chat_id + user_id` to topic IDs so the same user ID can route differently across source groups.
- **GUI-First Configuration**: Manage credentials, targets, control groups, mappings, and storage from a local web UI — auto-detects Chinese or English based on your browser language.
- **One-Click Local Launcher**: Start with Conda-first (`tgwatch`) setup and automatic `venv` fallback.
- **GUI Runner Controls**: Run once (with optional target and push), start daemon, stop daemon, and inspect live logs in one place.
- **Safe Run Guardrails**: Session prechecks, retention confirmation for long windows, and explicit in-UI error feedback.
- **Auto-Reconnect**: Daemon mode survives temporary network outages with exponential backoff and sends a recovery notification once reconnected.
- **Local Persistence by Default**: Archive messages in SQLite, keep media snapshots, and generate HTML reports for review.
- **Realtime Push Mode** *(Experimental)*: Forward tracked messages to the control chat the instant they arrive, with a 7-layer rate protection suite to prevent account restrictions.
- **Privacy by Design**: No cloud dependency, no secret logging, and sensitive runtime files excluded from git.


Perfect for: community operators, researchers, traders, or anyone who needs **signal extraction + local archiving** from Telegram.

## Quick Start

Get up and running in 5 steps. You need: **macOS with Python 3.11+** and a Telegram user account.

### 1. Get Telegram API credentials

Go to [my.telegram.org](https://my.telegram.org/), sign in with your phone number, and create an app to get your **API ID** and **API Hash**.

### 2. Clone the repository

Clone a stable release (recommended):

```bash
git clone --branch v1.7.0 https://github.com/o1xhack/telegram-watch.git
cd telegram-watch
```

> Or clone `main` for the latest code: `git clone https://github.com/o1xhack/telegram-watch.git`

### 3. Double-click the launcher

Double-click **`launch_tgwatch.command`** in Finder. It will automatically:
- Create a Python environment (Conda `tgwatch` if available, otherwise `.venv`)
- Install all dependencies
- Copy `config.example.toml` → `config.toml` if missing
- Open the GUI in your browser

### 4. Configure in the GUI

In the GUI (opens at `http://127.0.0.1:8765`):
1. Enter your **API ID** and **API Hash** in the Telegram section
2. Add one or more **Targets** (the groups/channels to monitor, with tracked user IDs)
3. Add a **Control Group** (where reports and messages will be sent)
4. Click **Save**

### 5. First login (terminal)

The first time, you must log in via terminal to enter the Telegram verification code:

```bash
# If you used the launcher, activate the same environment first:
# Conda: conda activate tgwatch
# venv:  source .venv/bin/activate

python -m tgwatch run --config config.toml
```

Enter your phone number and verification code when prompted. Once connected, the daemon is running. Press `Ctrl+C` to stop, or use the GUI's **Run daemon** / **Stop daemon** buttons for future runs.

> **Tip**: After the first login, you can start/stop everything from the GUI — no terminal needed.

## Manual Installation

<details>
<summary>For developers or if you prefer not to use the launcher</summary>

### Create a Python environment (pick one)

#### Option A: venv (recommended)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

#### Option B: Conda

```bash
conda create -n tgwatch python=3.11
conda activate tgwatch
python -m pip install -U pip
```

### Install the package

**Editable install (for development):**

```bash
pip install -e .
```

**Tagged release (stable, version-pinned):**

```bash
pip install "git+https://github.com/o1xhack/telegram-watch.git@v1.8.0"
```

### Set up config and run

```bash
cp config.example.toml config.toml
tgwatch gui          # edit config in the GUI, or edit config.toml manually
tgwatch doctor       # validate config
tgwatch once --since 2h --push   # test run
tgwatch run          # start daemon
```

</details>

## Configuration

**Use the GUI** (`tgwatch gui` or the launcher) — it covers all settings and prevents syntax errors.

If you need to edit `config.toml` manually, see the [configuration guide](docs/configuration.md) for full field documentation. Key fields:

| Section | Field | Description |
|---------|-------|-------------|
| `telegram` | `api_id`, `api_hash` | Telegram API credentials |
| `telegram` | `session_file` | Session path (default `data/tgwatch.session`) |
| `sender` | `session_file` | Optional second account for sending |
| `targets[]` | `target_chat_id`, `tracked_user_ids` | What to monitor |
| `targets[]` | `name`, `tracked_user_aliases` | Optional labels and aliases |
| `targets[]` | `summary_interval_minutes`, `control_group` | Per-target overrides |
| `control_groups.<name>` | `control_chat_id` | Where reports go |
| `control_groups.<name>` | `is_forum`, `topic_routing_enabled`, `topic_target_map` | Topic routing |
| `control_groups.<name>` | `skip_html_report` | Skip HTML file, send messages only |
| `reporting` | `reports_dir`, `summary_interval_minutes`, `timezone`, `retention_days` | Report settings |
| `storage` | `db_path`, `media_dir` | Local storage paths |
| `notifications` | `bark_key` | Optional Bark push notifications |
| `display` | `show_ids`, `time_format` | Display formatting |
| `realtime` | `push_mode` | `"interval"` (default) or `"realtime"` (experimental) |
| `realtime` | `rate_limit_per_minute`, `rate_limit_per_hour`, `rate_limit_per_day` | Rate protection limits |

Single-group configs using `[target]` + `[control]` are still supported for backwards compatibility.

### Run once for a single target

`tgwatch once` defaults to all targets. To run it for a single group, pass a target name or `target_chat_id`:

```bash
tgwatch once --config config.toml --since 2h --target group-1
tgwatch once --config config.toml --since 2h --target -1001234567890
```

### Migration from older config

If you upgrade from an older config (missing `config_version`), tgwatch will stop and prompt you to migrate.

1. The GUI shows a locked banner with a **Migrate Config** button.
2. CLI `run`/`once` show an error and ask whether to migrate.
3. Migration renames `config.toml` to `config-old-0.1.toml` and creates a new one with best-effort values.

### Bark push notifications

1. Install Bark on your phone, tap gear → copy the device key.
2. Add to config: `[notifications]` → `bark_key = "your_key_here"` (or set it in the GUI).
3. Reports, heartbeats, and errors will mirror to Bark under the "Telegram Watch" group.

### Realtime push mode *(Experimental)*

By default, tgwatch collects messages and sends periodic summaries ("interval" mode). **Realtime mode** forwards each message to the control chat the instant it arrives.

1. In the GUI, go to **Realtime Push Mode** and switch to **Realtime (Experimental)**.
2. Confirm the risk acknowledgment dialog (account restrictions are possible if rate limits are exceeded).
3. Adjust rate protection settings if needed — the defaults are conservative.

Realtime mode includes a **7-layer rate protection suite**: sliding-window limiter (20/min), jittered delay (3 s ± 1 s), media throttle (+2 s), hourly/daily caps (200/hr, 1000/day), exponential backoff on FloodWait, circuit breaker (auto-pause 30 min + Bark alert), and startup warmup (5 min @ 5/min). See the [configuration guide](docs/configuration.md) for full details.

> ⚠️ Never commit `config.toml`, session files, `data/`, or `reports/`. These contain private information.

## Usage

All commands: `python -m tgwatch <cmd>` or `tgwatch <cmd>`. Always pass `--config config.toml`.

### Doctor

Validate config + directories and ensure the SQLite schema can be created:

```bash
tgwatch doctor --config config.toml
```

### GUI (local config editor)

Launch the local UI (default: `http://127.0.0.1:8765`):

```bash
tgwatch gui
```

The GUI provides **Run once**, **Run daemon**, and **Stop daemon** buttons with a live log panel. `Run daemon` starts a background process — closing the browser won't stop it. Re-open the GUI to reattach logs.

### Once (batch report)

Fetch tracked messages from the last window, save to DB, and render HTML reports:

```bash
tgwatch once --config config.toml --since 2h
# With --push: also send report + messages to the control chat
tgwatch once --config config.toml --since 2h --push
```

### Run (daemon)

Interactive watch mode. First run prompts for Telegram login code.

```bash
tgwatch run --config config.toml
```

In daemon mode:
- Listens to each target chat and stores tracked messages (text, replies, media).
- At each interval, generates an HTML report and pushes messages to the control group.
- Supports commands from your account in the control chat: `/help`, `/last`, `/since`, `/export`.

## GitHub Actions (Automated Daily Fetch)

You can run `tgwatch once` on a daily schedule via GitHub Actions — no local daemon required. Fork this repo, set up two GitHub Secrets, and the workflow handles everything.

### Required GitHub Secrets

| Secret | Content | How to generate |
|--------|---------|-----------------|
| `TGWATCH_CONFIG_TOML` | Full contents of your `config.toml` | Copy-paste the file content |
| `TELEGRAM_SESSION_BASE64` | Base64-encoded session file | See below |

### Setup steps

1. **Log in locally once** to generate the session file:

   ```bash
   pip install -e .
   cp config.example.toml config.toml
   # Fill in api_id, api_hash, target_chat_id, tracked_user_ids, etc.
   tgwatch once --config config.toml --since 1m
   # Enter phone number and verification code when prompted
   ```

2. **Encode the session file**:

   ```bash
   # macOS
   base64 -i data/tgwatch.session
   # Linux
   base64 data/tgwatch.session
   ```

3. **Add secrets** in your fork: Settings → Secrets and variables → Actions → New repository secret.
   - `TGWATCH_CONFIG_TOML`: paste your `config.toml` contents
   - `TELEGRAM_SESSION_BASE64`: paste the base64 output

4. **Done.** The workflow runs daily at 02:00 UTC. You can also trigger it manually from the Actions tab with a custom time window (e.g., `48h`).

### How it works

- The workflow reconstructs `config.toml` and the session file from secrets at runtime
- Runs `tgwatch once --since 24h` to fetch the last 24 hours of messages
- Uploads HTML reports and the SQLite database as GitHub Actions artifacts (30-day retention)
- Cleans up sensitive files after every run

### Notes

- **Session expiration**: If your Telegram session is revoked (from Telegram's Active Sessions settings), the workflow will fail with a clear error. Re-run steps 1–3 locally to regenerate.
- **Privacy**: Config and session files are injected from secrets and never committed. Artifacts are only visible to repo collaborators.
- **No AI summarization**: This workflow collects raw messages and generates HTML reports. LLM-based summarization is a planned future feature.

## Testing

```bash
pytest
```

## Privacy & Safety

- Runs entirely on your Mac; no remote services or uploads.
- Does not log API hashes, phone numbers, or chat contents.
- Session + DB + media directories are `.gitignore`d; keep secrets local.
- Flood-wait handling/backoff is applied to Telegram API calls (sending, downloads, entity lookups).

## Changelog

Release notes live in [docs/CHANGELOG.md](docs/CHANGELOG.md).

## License

MIT. See `LICENSE`.
