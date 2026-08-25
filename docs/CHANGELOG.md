# Changelog

[English](CHANGELOG.md) | [简体中文](CHANGELOG.zh-Hans.md) | [繁體中文](CHANGELOG.zh-Hant.md) | [日本語](CHANGELOG.ja.md)

> Entries are arranged from newest to oldest so the latest release notes stay at the top. Each bullet references the requirement(s) that introduced the change.

## 1.8.1 — 2026-08-24
- Prevent unrelated SQLite files from disabling Full Archive capture by recognizing only canonical archive shard paths, while preserving fail-closed handling for genuine orphaned shards and showing actual archive runtime health plus privacy-safe configuration drift in the daemon heartbeat and GUI.

## 1.8.0 — 2026-07-15
- Prevent long-running forwarding stalls by serializing all daemon SQLite work off the asyncio event loop and avoiding redundant WAL mode changes on routine connections.
- Add a daemon health heartbeat so the GUI can distinguish a responsive runner from a live PID with a stalled event loop or SQLite queue.
- Add optional full-message archive storage: telegram-watch can now keep a local whole-group or selected-Topic context copy in a separate SQLite manifest/shard set while leaving tracked-user notifications and reports unchanged.
- Link full-archive rows back to the existing tracked database with `tracked_ref` records, avoiding duplicate tracked message text/media metadata while preserving enough timeline context for later `archive-context` queries.
- Add the full-archive operational surface: `archive-backfill`, `archive-status`, `archive-repair`, `archive-context`, `list-topics`, and `archive-qa-init`, with default-off config, degraded-state startup gating, repair diagnostics, and a gitignored real Telegram QA evidence template.
- Capture local sender display snapshots during live full-archive writes and add `archive-senders-backfill` for existing shards, resolving each sender from the Telethon session cache before Telegram history with FloodWait handling. Archive-facing labels prefer configured aliases, then display name/username, and never expose raw sender IDs.
- Reconnect the configured sender account before falling back to the primary account, and post a control-chat warning if primary fallback is used, so a temporary sender disconnect does not silently switch bridge messages to the primary account for the rest of the daemon run.
- Restore compatibility with Telegram's `message#3ae56482` response schema using the tested Telethon 1.44.0 parser, and make existing launcher environments refresh stale Telethon installs without deleting sessions.

## 1.7.0 — 2026-04-14
- Add a global message template selector with `Normal` / `Minimal` layouts for individual messages forwarded to the control chat. The selector applies in both interval mode (per-message forwards after each digest) and realtime mode (instant push) — wherever messages appear one-per-Telegram-message in the control chat. Minimal collapses sender and content onto the first line and moves the time to the second line, while Normal preserves the existing multi-line layout. A live preview in the GUI shows the current layout at a glance. Existing ID display, time format, and language preferences apply on top of the chosen template, and configs missing the new `display.template` key default to `normal` with no migration needed.
- Reorganize the Display & Notifications panel into clearer subgroups — Message Template, Message Fields, Language, and Notifications — so related controls stay together.

## 1.6.1 — 2026-03-30
- Fix update checker reporting stale version (e.g. 1.0.4 instead of 1.6.0) when package metadata is outdated. Now reads version from pyproject.toml first, falling back to importlib.metadata only in frozen environments.

## 1.6.0 — 2026-03-27
- [EXPERIMENTAL] Add real-time push mode: forward tracked messages to the control chat instantly on arrival, with a separate configurable interval for HTML report aggregation. Includes a 7-layer rate protection suite (sliding window, jittered delay, media throttle, hourly/daily caps, exponential backoff, circuit breaker with Bark alerts, and startup warmup) to prevent Telegram account restrictions (REQ-20260320-001-realtime-push-mode).
- Enable WAL mode and busy_timeout on all SQLite databases (app DB and Telethon session) for cloud-sync resilience. Add automatic retry on transient I/O errors, and warn in `doctor` and GUI when data files reside in cloud-synced directories (REQ-20260321-001-sqlite-wal-retry).
- Add GUI internationalization (i18n) with auto language detection and manual toggle button; Chinese (zh-CN) or English.
- Add automatic update checker: daemon queries GitHub Releases on startup and every 24 hours, pushing up to 3 notifications per new version to all control groups (REQ-20260327-001-update-check-heartbeat-language).
- Make heartbeat interval configurable via `notifications.heartbeat_interval_hours` (default 2 hours, set to 0 to disable). Heartbeat message follows the language setting (REQ-20260327-001-update-check-heartbeat-language).
- Add `display.language` setting (`"auto"` / `"zh"` / `"en"`) to control the language of all backend push messages (REQ-20260327-001-update-check-heartbeat-language).
- Suppress repeated experimental-mode warning during GUI status polling.

## 1.5.0 — 2026-03-11
- Add per-control-group `skip_html_report` option to send only individual messages without the HTML report file when pushing to the control chat (REQ-20260310-001-skip-html-report-option).
- Add GitHub Actions workflow for scheduled daily message fetching with artifact-based report storage, plus non-interactive mode support for CI environments (REQ-20260310-001-github-actions-daily-summary).
- Add automatic reconnection with exponential backoff when network drops during daemon mode. The watcher now survives temporary network outages instead of crashing, and sends a recovery notification to the control chat once reconnected (REQ-20260304-001-daemon-reconnect-on-network-loss).

## 1.2.1 — 2026-02-13
- Simplified report file captions in the control chat from verbose ISO timestamps to a concise two-line format with user-configured time formatting (REQ-20260213-001-humanize-report-caption).

## 1.2.0 — 2026-02-12
- Replaced the free-text time format input in GUI with a structured builder featuring dropdowns for year, month, day, hour, minute, second, date separator, and timezone display, with live preview and custom-format fallback (REQ-20260212-006-gui-time-format-builder).

## 1.1.0 — 2026-02-12
- Added a GUI timezone dropdown with common presets across China, Japan, Korea, US, and major Europe zones, while keeping `config.toml` values as IANA timezone strings and preserving existing non-preset values as custom selections (REQ-20260212-005-gui-timezone-presets).

## 1.0.4 — 2026-02-12
- Standardized the user-facing command surface on `tgwatch` by aligning CLI help output and command templates, removing mixed `telegram_watch` execution instructions from active docs/templates and adding parser coverage (REQ-20260212-004-command-surface-unify-tgwatch).

## 1.0.3 — 2026-02-12
- Added a one-time `cleanup-replies` workflow to scan forum targets, remove false historical reply snapshots caused by topic linkage, preserve true explicit replies, and emit dry-run/apply stats with optional DB backup (REQ-20260212-003-historical-reply-backfill-cleanup).

## 1.0.2 — 2026-02-12
- Improved forum reply detection so topic-linkage messages are no longer mislabeled as `Reply to`, while explicit replies in topics and non-forum reply behavior remain intact with new regression tests (REQ-20260212-002-forum-topic-reply-disambiguation).

## 1.0.1 — 2026-02-11
- Hardened summary-loop resilience: transient send failures no longer terminate periodic summary scheduling, and added regression coverage to keep the loop alive after send errors (REQ-20260211-001-summary-loop-resilience).

## 1.0.0 — 2026-02-04
- Published the `v1.0.0` git tag and synchronized README install examples across all locales to point to `@v1.0.0` (REQ-20260208-001-release-tag-100-readme-sync).
- Shipped multi-target monitoring with control-group routing and a local GUI, including improved control-group mapping UX (REQ-20260202-001-multi-admin-monitoring, REQ-20260203-001-config-gui-design, REQ-20260204-003-gui-control-mapping-ux).
- Added one-click launchers and GUI runner controls (run/once, background logs, Stop GUI), plus fixed a GUI startup crash (REQ-20260203-002-gui-launcher-and-runner, REQ-20260204-001-gui-launcher-loglevel-fix, REQ-20260204-002-gui-stop-button).
- Enforced config version 1.0 with per-target topic mapping (target_chat_id + user_id) and an in-app migration flow (REQ-20260204-004-topic-mapping-per-target, REQ-20260204-006-config-migration-flow).
- Audited tests and refreshed docs for config migration and target naming defaults (REQ-20260205-001-audit-tests-docs).
- Simplified migration to only keep `config-old-0.1.toml` backups (REQ-20260205-002-drop-config-sample).
- Added single-target filtering for run-once in CLI and GUI (REQ-20260205-003-once-target-filter).
- Ignored `config-old-*.toml` migration backups in git (REQ-20260205-004-ignore-old-configs).
- Added GUI run-once push toggle and log view limits (REQ-20260205-005-gui-once-push-toggle).
- Added GUI pre-run guards: missing-session warning with disabled Run/Once buttons, plus retention confirmation for `retention_days > 180` without terminal y/n blocking (REQ-20260205-006-gui-run-guards).
- Refined GUI retention UX: Run daemon stays clickable and now opens a click-to-confirm flow (checkbox-gated confirm button) before starting long-retention runs (REQ-20260205-007-gui-retention-click-confirm-flow).
- Added GUI `Stop daemon` control and fixed retention confirmation dismissal after run starts, so daemon lifecycle can be managed directly in the Runner panel (REQ-20260205-008-gui-run-stop-and-confirm-dismiss).
- Hardened GUI runner error handling paths and synchronized documentation for run/stop/retention confirmation behavior before push (REQ-20260205-009-pre-push-calibration-audit).
- Updated launcher scripts to prefer Conda (`tgwatch`) with automatic fallback to `venv`, and aligned setup docs across locales (REQ-20260205-010-launcher-conda-prefer-fallback-venv).
- Improved launcher robustness: macOS launcher now runs on bash-compatible systems and installer bootstrap tolerates pip-tool upgrade failures with clear warnings (REQ-20260205-011-launcher-shell-and-bootstrap-robustness).

## 0.3.0 — 2026-01-29
- Added dual-account bridging so a sender account can post control-group updates and restore notifications for the primary account (REQ-20260129-002-bridge-implementation).
- Clarified login prompts so primary vs sender accounts are labeled during dual-account setup (REQ-20260129-003-sender-login-prompt).
- Made dual-account login prompts user-friendly and clearly labeled in the terminal (REQ-20260129-004-friendly-login-prompts).

## 0.2.0 — 2026-01-25
- Added optional forum topic routing so tracked users can be mapped to specific control-group topics while preserving the default General-topic push behavior (REQ-20260125-002-topic-routing).
- Restored reply blockquote formatting in control-chat pushes to avoid extra blank lines between reply header and quoted text (REQ-20260125-003-reply-blockquote-regression).
- Refreshed README highlights and feature list to reflect current capabilities including topic routing (REQ-20260125-004-readme-refresh).
- Archived completed request documents under `docs/requests/Done/` to keep the active backlog concise (REQ-20260125-005-archive-done-requests).
- Fixed heartbeat scheduling so run-mode “Watcher is still running” repeats on the expected idle interval (REQ-20260125-006-heartbeat-repeat).
- Split HTML report delivery by user when topic routing is enabled, sending each report to its mapped forum topic (REQ-20260125-007-topic-report-split).
- Updated README install tags and config hints for v0.2.0 (REQ-20260125-008-readme-release-tag).

## 0.1.2 — 2026-01-24
- Fixed the `run`-mode summary loop so it once again passes the activity tracker and Bark interval label to `_send_report_bundle`, restoring Bark/control-chat notifications and the “Watcher is still running” heartbeat stream (REQ-20260124-024-run-notify-regression).
- Added an async regression test to ensure future changes keep forwarding the tracker/bark context when scheduling run summaries (REQ-20260124-024-run-notify-regression).

## 0.1.1 — 2026-01-24
- Introduced the release-management workflow: every request chooses a semantic version bump, updates the changelog, and links the notes from README (REQ-20260124-023-versioning-log).

## 0.1.0 — 2026-01-23
- Delivered the telegram-watch MVP: Telethon-based watcher with login, tracked-user filtering, SQLite persistence, media archiving, and HTML reports streamed to the control chat (REQ-20260117-001-mvp-bootstrap).
- Added the `doctor`/`once`/`run` CLI trio plus FloodWait handling, Bark notifications, retention pruning, and reply context capture for reports (REQ-20260117-001-mvp-bootstrap).
- Published the detailed configuration guide (README + `docs/configuration.md`) covering API credentials, chat IDs, local paths, and privacy safeguards so users can fill `config.toml` end-to-end (REQ-20260117-002-config-docs).
