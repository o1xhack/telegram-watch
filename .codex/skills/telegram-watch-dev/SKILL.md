---
name: telegram-watch-dev
description: Develop telegram-watch using a requirements-first workflow (Draft -> Approved -> Implementing -> Done) with minimal, testable changes.
metadata:
  short-description: telegram-watch workflow-first development
---

When using this skill, ALWAYS follow this workflow:

0) Requirements workflow is mandatory (no exceptions)
- Source of truth: `docs/requests/`
- Intake: `docs/inbox.md`
- Template: `docs/templates/REQ_TEMPLATE.md`

1) Before coding: pick work from Approved requests
- List `docs/requests/` and find requirements with `Status: Approved`.
- If multiple exist, choose the lowest-numbered / smallest-scope one unless the user specifies an ID.

2) If there is NO Approved request
- Read `docs/inbox.md` (if present) and/or the user’s latest message.
- Create ONE new Draft requirement file:
  - Path: `docs/requests/REQ-YYYYMMDD-###-slug.md`
  - Content: must follow `docs/templates/REQ_TEMPLATE.md`
  - Set `Status: Draft`
- STOP after creating the Draft and ask the user to approve it.
- Do NOT implement anything until the user confirms approval (Status becomes Approved).

3) When starting implementation of an Approved request
- Update the chosen REQ:
  - `Status: Approved` -> `Status: Implementing`
  - Add a short plan in the REQ (2–6 bullets max).
- Implement the request strictly as written; avoid unrelated refactors.

4) Build order for MVP code work
- Implement in this order: `doctor` -> `once` -> `run`.

4.1) README localization rule
- Any time you add or update content in `README.md`, you must apply the same change (or equivalent translation) to every localized README (`README.zh-Hans.md`, `README.zh-Hant.md`, `README.ja.md`). Language switch links at the top must also stay in sync.

5) After each change set, run validations
- python -m telegram_watch doctor --config config.toml
- python -m telegram_watch once --config config.toml --since 10m

6) Completion protocol
- Ensure all Acceptance Criteria in the REQ and `ACCEPTANCE.md` are satisfied.
- Update the REQ:
  - Tick the acceptance checkboxes
  - Add “What changed” (files touched + brief rationale)
  - `Status: Implementing` -> `Status: Done`

7) Security / open-source hygiene (never violate)
- Never print or commit secrets (api_hash, phone, session).
- Ensure `.gitignore` excludes: `config.toml`, `*.session`, `data/`, `reports/`.
- Keep data local by default; do not add cloud dependencies unless explicitly approved.
