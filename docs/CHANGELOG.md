# Changelog

> Entries are arranged from newest to oldest so the latest release notes stay at the top. Each bullet references the requirement(s) that introduced the change.

## 0.2.0 — 2026-01-25
- Added optional forum topic routing so tracked users can be mapped to specific control-group topics while preserving the default General-topic push behavior (REQ-20260125-002-topic-routing).
- Restored reply blockquote formatting in control-chat pushes to avoid extra blank lines between reply header and quoted text (REQ-20260125-003-reply-blockquote-regression).
- Refreshed README highlights and feature list to reflect current capabilities including topic routing (REQ-20260125-004-readme-refresh).
- Archived completed request documents under `docs/requests/Done/` to keep the active backlog concise (REQ-20260125-005-archive-done-requests).

## 0.1.2 — 2026-01-24
- Fixed the `run`-mode summary loop so it once again passes the activity tracker and Bark interval label to `_send_report_bundle`, restoring Bark/control-chat notifications and the “Watcher is still running” heartbeat stream (REQ-20260124-024-run-notify-regression).
- Added an async regression test to ensure future changes keep forwarding the tracker/bark context when scheduling run summaries (REQ-20260124-024-run-notify-regression).

## 0.1.1 — 2026-01-24
- Introduced the release-management workflow: every request chooses a semantic version bump, updates the changelog, and links the notes from README (REQ-20260124-023-versioning-log).

## 0.1.0 — 2026-01-23
- Delivered the telegram-watch MVP: Telethon-based watcher with login, tracked-user filtering, SQLite persistence, media archiving, and HTML reports streamed to the control chat (REQ-20260117-001-mvp-bootstrap).
- Added the `doctor`/`once`/`run` CLI trio plus FloodWait handling, Bark notifications, retention pruning, and reply context capture for reports (REQ-20260117-001-mvp-bootstrap).
- Published the detailed configuration guide (README + `docs/configuration.md`) covering API credentials, chat IDs, local paths, and privacy safeguards so users can fill `config.toml` end-to-end (REQ-20260117-002-config-docs).
