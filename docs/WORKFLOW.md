# WORKFLOW — telegram-watch Requirements & Delivery Process

This repository uses a lightweight, file-based requirements workflow designed for Codex CLI execution with minimal repeated prompting.

## Goals

* Ensure every change is traceable to a written requirement.
* Require explicit approval before implementation.
* Keep changes small, reviewable, and testable.
* Make the workflow friendly for open-source contributors.

## Source of Truth

* `docs/requests/` is the authoritative backlog of structured requirements.
* `docs/inbox.md` is an unstructured intake area for ideas and notes.

## Directory Layout

* `docs/inbox.md` — quick capture of ideas (no format required)
* `docs/templates/REQ_TEMPLATE.md` — the canonical requirement template
* `docs/requests/REQ-YYYYMMDD-###-slug.md` — structured requirements (tracked and status-driven)

## Requirement File Naming

All structured requirements must be created under `docs/requests/` using:

`REQ-YYYYMMDD-###-slug.md`

* `YYYYMMDD` **must match the actual calendar date when the file is first created.**
* `###` is a zero-padded sequence number for that day (start at 001 and increment per new request).

Example: `REQ-20260123-001-track-users-digest.md`

## Status Lifecycle (Required)

Each requirement file must include a `Status:` line near the top. The allowed statuses are:

* `Draft` — created and awaiting maintainer approval
* `Approved` — approved for implementation
* `Implementing` — currently being worked on
* `Done` — completed and verified

Rules:

* Only `Approved` requirements may be implemented.
* When implementation starts, status must be updated to `Implementing`.
* When work is complete and acceptance checks pass, status must be updated to `Done`.

## Intake → Draft (How New Requests Enter the System)

1. New ideas are added to `docs/inbox.md` (freeform).
2. When a request is ready to be formalized, create a new file in `docs/requests/` using `docs/templates/REQ_TEMPLATE.md`.
3. Set `Status: Draft`.
4. Stop and request explicit approval before any coding begins.

## Approval

* A maintainer reviews the `Draft` requirement and edits it as needed.
* When approved, change `Status: Draft` to `Status: Approved`.

## Implementation (Codex)

For each `Approved` requirement:

1. Update `Status: Approved` → `Status: Implementing`.
2. Implement the scope strictly as written (avoid unrelated refactors).
3. Maintain open-source hygiene:

   * Never commit secrets (`config.toml`, `*.session`, `data/`, `reports/`).
   * Keep changes minimal and reviewable.
4. Run the acceptance commands listed in the requirement (and in `ACCEPTANCE.md`).

## Completion

When work is complete:

1. Ensure acceptance criteria are met (commands pass, outputs generated as required).
2. Tick the acceptance checkboxes in the requirement file.
3. Add a short “What changed” section (files touched + brief rationale).
4. Update status to `Done`.

## Prioritization Policy

Unless a maintainer specifies otherwise:

* Implement the smallest/lowest-numbered `Approved` requirement first.
* If multiple `Approved` items exist, prefer the one with the smallest scope / least risk.

## Pull Request / Contribution Notes (Open Source)

* Every PR should reference one requirement file in `docs/requests/`.
* PRs should be small and scoped to the requirement’s “Scope (MVP)” section.
* Changes that expand scope require either:

  * a new requirement file, or
  * an explicit edit to the existing requirement with maintainer approval.

## Quick Start for Maintainers

* Add ideas to `docs/inbox.md`.
* Convert to `docs/requests/REQ-...md` using the template (Status: Draft).
* Approve by changing to `Status: Approved`.
* Implement via Codex; finish with `Status: Done` + checked acceptance items.
