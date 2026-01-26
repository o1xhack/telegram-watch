# WORKFLOW — telegram-watch Requirements & Delivery Process

This repository uses a lightweight, file-based requirements workflow designed for Codex CLI execution with minimal repeated prompting.

## Goals

* Ensure every change is traceable to a written requirement.
* Require explicit approval before implementation.
* Keep changes small, reviewable, and testable.
* Make the workflow friendly for open-source contributors.

## Source of Truth

* `docs/requests/` is the authoritative backlog of structured requirements.
* Completed requirements live under `docs/requests/Done/` to keep the active backlog small.
* `docs/inbox.md` is an unstructured intake area for ideas and notes.

## Directory Layout

* `docs/inbox.md` — quick capture of ideas (no format required)
* `docs/templates/REQ_TEMPLATE.md` — the canonical requirement template
* `docs/requests/REQ-YYYYMMDD-###-slug.md` — structured requirements (tracked and status-driven)
* `docs/requests/Done/REQ-YYYYMMDD-###-slug.md` — archived requirements with `Status: Done`

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
3. When a request is completed, move it to `docs/requests/Done/`.
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

## Release Impact, Versioning, and Changelog

Semantic Versioning (MAJOR.MINOR.PATCH) is now part of every requirement:

* **While drafting a request**
  * Add a `## Release Impact` section (see the template) that states the proposed version bump (e.g., `0.1.0 → 0.1.1`) and a short changelog blurb.
  * Discuss the rationale before the request is Approved so reviewers can agree on the bump size.
* **During implementation**
  * Keep the planned version top of mind; if scope changes, update the `Release Impact` section and get reconfirmed.
  * Prepare the changelog entry text in English and keep it concise (“App Store” style bullet list).
* **Completion**
  * Update the canonical version string in `pyproject.toml` (and anywhere else we mirror it).
  * Append the new entry to `docs/CHANGELOG.md`, keeping the list in reverse chronological order (newest release at the top).
  * Link back to the requirement ID inside the changelog entry.
  * Keep README install snippets pointing to the latest published tag. Only bump the `pip install ...@vX.Y.Z` examples after the new tag exists on the remote.

### Choosing the right bump

Use classic SemVer guidance plus past requests as references:

* **Patch (0.1.x → 0.1.x+1)** — Backwards-compatible fixes or documentation that materially change how users operate the current release. Examples: documentation improvements that unblock setup (REQ-20260117-002) or formatting refinements to existing features (REQ-20260123-011).
* **Minor (0.1.x → 0.2.0)** — Additive functionality or new configuration surfaces that expand behavior while remaining compatible, such as the control-chat display toggles from REQ-20260124-022 or new notification channels.
* **Major (1.x.y)** — Breaking behavioral changes (schema resets, CLI flag removal, incompatible config). None have shipped yet; treat with extra review.

Purely editorial changes (typo fixes, localization wording tweaks, or notes confined to `docs/inbox.md`) generally **do not** bump the version or touch the changelog; they still need normal review but stay out of release notes.

### Release checklist (maintainers)

1. Ensure the requirement is `Done`, changelog entry committed, and `pyproject.toml` (plus any mirrored version strings) updated.
2. From the release commit (usually `main`), create and push the tag (e.g., `git tag v0.1.2 && git push origin v0.1.2`).
3. Update README (all languages) “Option 0 / tagged release” snippets to reference that new tag only **after** it is published, and mention that those commands always point to the latest release.
4. Publish release notes if needed (GitHub Releases, etc.).

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

* Every PR should reference one requirement file in `docs/requests/` (or `docs/requests/Done/` if already archived).
* PRs should be small and scoped to the requirement’s “Scope (MVP)” section.
* Changes that expand scope require either:

  * a new requirement file, or
  * an explicit edit to the existing requirement with maintainer approval.

## Quick Start for Maintainers

* Add ideas to `docs/inbox.md`.
* Convert to `docs/requests/REQ-...md` using the template (Status: Draft).
* Move completed requests to `docs/requests/Done/`.
* Approve by changing to `Status: Approved`.
* Implement via Codex; finish with `Status: Done` + checked acceptance items.
