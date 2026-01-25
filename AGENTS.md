# Project: telegram-watch (Telegram user-account watcher)

## Non-negotiables
- This project logs in as a Telegram *user account* (MTProto), NOT a Bot added to the monitored group.
- Must work on a single Mac (no cloud services required).
- Default mode is privacy-first: store data locally, never print secrets, never commit sessions/config with secrets.
- Keep MVP minimal: correctness > features.

## How to run (must be true after implementation)
- Create venv + install:
  - python -m venv .venv
  - . .venv/bin/activate
  - pip install -e .
- Configure:
  - cp config.example.toml config.toml
  - edit config.toml (api_id/api_hash, target_chat_id, tracked_user_ids, control_chat_id)
- First login (interactive):
  - python -m tgwatch run --config config.toml
- One-shot report:
  - python -m tgwatch once --config config.toml --since 2h

## Testing / quality gates
- Provide a "doctor" command:
  - python -m tgwatch doctor --config config.toml
  - It validates config fields, DB path writable, media/report directories creatable.
- Provide minimal unit tests for config parsing and DB schema creation.

## Safety / compliance
- Do not log PII (phone numbers, api_hash).
- Never commit *.session, config.toml, data/, reports/.
- Respect Telegram rate limits; implement backoff/floodwait handling where needed.

## Repo conventions
- Python 3.11+; type hints.
- Prefer small modules; keep async code isolated.
- Default working branch for feature development is `dev`; reserve `main` for release-ready merges.

## Requirements workflow (default behavior)
- The source of truth for work is `docs/requests/`.
- New user ideas go into `docs/inbox.md`.
- When the user describes a new need, FIRST convert it into a new file:
  - `docs/requests/REQ-YYYYMMDD-###-slug.md`
  - using `docs/templates/REQ_TEMPLATE.md`
  - set Status: Draft
- After creating the Draft, STOP and ask for approval (user confirms).
- Only implement requests with Status: Approved.
- When starting implementation:
  - set Status: Implementing
  - create a short plan inside the REQ
- When finished and acceptance commands pass:
  - set Status: Done
  - tick the Acceptance Criteria checkboxes
  - add a brief "What changed" section at the bottom of the REQ
- If multiple Approved requests exist:
  - pick the smallest/lowest-numbered first unless user specifies an ID.

## Versioning & changelog expectations
- Every new request must include a “Release Impact” section that proposes the semantic version bump (MAJOR.MINOR.PATCH) and drafts the changelog snippet (English, App Store style).
- Once implementation finishes, update the canonical version in `pyproject.toml`, append the request entry to `docs/CHANGELOG.md` (newest entries at top), and ensure README links to the changelog stay accurate.
- Use SemVer heuristics:
  - Patch (`0.1.x → 0.1.x+1`): backward-compatible fixes/docs that adjust existing flows (e.g., REQ-20260123-011).
  - Minor (`0.1.x → 0.2.0`): additive features like new config toggles or notification paths (e.g., REQ-20260124-022).
  - Major: breaking schema/CLI changes (none so far).
- Pure typo/translation tweaks or updates confined to `docs/inbox.md` usually skip version bumps and changelog entries; log them via git notes/commits only.
- README “tagged release” commands must always reference the latest published tag. Do **not** change `pip install ...@vX.Y.Z` until the new tag exists on GitHub (update all languages together).
