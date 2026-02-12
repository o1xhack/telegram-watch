# Changelog

[English](CHANGELOG.md) | [简体中文](CHANGELOG.zh-Hans.md) | [繁體中文](CHANGELOG.zh-Hant.md) | [日本語](CHANGELOG.ja.md)

> Entries are arranged from newest to oldest so the latest release notes stay at the top. Each bullet references the requirement(s) that introduced the change.

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
