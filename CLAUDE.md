# Project: telegram-watch (Telegram user-account watcher)

## Non-negotiables

- This project logs in as a Telegram *user account* (MTProto), NOT a Bot.
- Must work on a single Mac (no cloud services required).
- Privacy-first: store data locally, never print secrets, never commit sessions/config with secrets.
- Keep MVP minimal: correctness > features.

## How to run

- Environment setup:
  ```
  python -m venv .venv && . .venv/bin/activate && pip install -e .
  ```
- Configure: `cp config.example.toml config.toml` and fill in api_id/api_hash, target_chat_id, tracked_user_ids, control_chat_id.
- CLI entry point: `tgwatch` (or `python -m tgwatch`)
- Commands: `doctor`, `gui`, `once`, `run`
- GUI launcher: `python -m tgwatch gui --config config.toml`

## Testing / quality gates

- Validation: `python -m tgwatch doctor --config config.toml`
- One-shot: `python -m tgwatch once --config config.toml --since 10m`
- Unit tests: `pytest tests/`

## Safety / compliance (never violate)

- Do not log PII (phone numbers, api_hash).
- Never commit `*.session`, `config.toml`, `data/`, `reports/`.
- `.gitignore` must exclude these at all times.
- Respect Telegram rate limits; implement backoff/floodwait handling.
- Keep data local by default; do not add cloud dependencies unless explicitly approved.

## Repo conventions

- Python 3.11+; type hints.
- Prefer small modules; keep async code isolated.
- Working branch: `dev`; `main` is for release-ready merges.

## README localization rule

- Any change to `README.md` must be applied (or equivalently translated) to all localized READMEs: `docs/README.zh-Hans.md`, `docs/README.zh-Hant.md`, `docs/README.ja.md`.
- Language switch links at the top must stay in sync.

## Requirements workflow (mandatory — no exceptions)

### Source of truth

- `docs/requests/` — structured requirements (active backlog)
- `docs/requests/Done/` — archived completed requirements
- `docs/inbox.md` — unstructured intake for ideas
- `docs/templates/REQ_TEMPLATE.md` — canonical template

### Before coding: pick work from Approved requests

- List `docs/requests/` and find requirements with `Status: Approved`.
- If multiple exist, choose the lowest-numbered / smallest-scope one unless the user specifies an ID.

### If there is NO Approved request

- Read `docs/inbox.md` and/or the user's latest message.
- Create ONE new Draft requirement file:
  - Path: `docs/requests/REQ-YYYYMMDD-###-slug.md`
  - Content: must follow `docs/templates/REQ_TEMPLATE.md`
  - Set `Status: Draft`
- **STOP** after creating the Draft and ask the user to approve it.
- Do NOT implement anything until the user confirms approval.

### Implementation

1. Update the chosen REQ: `Status: Approved` → `Status: Implementing`; add a short plan (2–6 bullets).
2. Implement strictly as written; avoid unrelated refactors.
3. Build order for MVP code work: `doctor` → `once` → `run`.

### Completion protocol

1. Ensure all Acceptance Criteria in the REQ and `ACCEPTANCE.md` are satisfied.
2. Tick the acceptance checkboxes in the REQ.
3. Add a "What changed" section (files touched + brief rationale).
4. Update status: `Status: Implementing` → `Status: Done`.
5. Move completed REQ to `docs/requests/Done/`.

## Versioning & changelog

- Every new request must include a "Release Impact" section proposing the SemVer bump and changelog snippet (English, App Store style).
- On completion: update version in `pyproject.toml`, prepend entry to `docs/CHANGELOG.md` (newest first).
- SemVer guidance:
  - **Patch**: backward-compatible fixes/docs.
  - **Minor**: additive features, new config surfaces.
  - **Major**: breaking schema/CLI changes.
- Pure typo/translation tweaks skip version bumps and changelog entries.
- README `pip install ...@vX.Y.Z` examples: only update after the new tag exists on GitHub (all languages together).

## Commit protocol

- Always include both a summary and a description:
  - SUMMARY: short, action-oriented, and specific.
  - DETAILS: 2–6 bullets describing key changes, ordered by importance.
