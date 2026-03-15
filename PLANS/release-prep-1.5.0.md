# PLAN: release-prep-1.5.0

## Context
- Background: `main` now includes the full Apple Silicon macOS feature set that was tracked in `PLANS/mac-support.md`.
- Current behavior: the runtime version is still `1.4.0`, and several release-facing docs still describe macOS as a release target or contract instead of a supported platform.
- Trigger/problem statement: prepare the repo for the `v1.5.0` release by bumping version metadata and aligning documentation with the shipped macOS support story.

## Goals
- Bump the shared package/server version to `1.5.0`.
- Update release-facing docs so Apple Silicon macOS is described as supported in this release.
- Add the `v1.5.0` release notes and a release-specific manual checklist.

## Non-Goals
- Runtime behavior changes beyond the version constant.
- Server/API/schema changes.
- Packaging or dependency changes.

## Constraints
- Windows and macOS local development support are required.
- Keep diffs minimal and conflict-resistant for parallel work.
- No dependency/lockfile/packaging changes unless explicitly required.
- No repo-wide formatting.

## Contract Surface
- Existing contracts touched:
  - `src/gamehub_common/version.py`
  - release/operator documentation under `README.md`, `docs/`, and `PLANS/`
- New/updated contract artifacts:
  - `docs/release-notes-v1.5.0.md`
  - `docs/release-manual-checklist-v1.5.0.md`
- Cross-boundary implications:
  - None; docs only, plus shared version metadata consumed by both CLI and server.

## Milestones
1. M1: Capture the `1.5.0` version bump in shared metadata.
2. M2: Align platform/install/config docs with Apple Silicon macOS release support.
3. M3: Add/update release notes and release-validation docs for `v1.5.0`.

## Story Contracts

### STORY REL-1.5.0-DOCS
- Type: DOCS
- Goal: prepare the repo for the `v1.5.0` release with current version metadata and release-accurate documentation.
- Acceptance Criteria (deterministic):
  - [x] `src/gamehub_common/version.py` reports `1.5.0`.
  - [x] README and platform/config/install docs describe Apple Silicon macOS as supported in this release.
  - [x] `docs/release-notes-v1.5.0.md` exists and summarizes the macOS release milestone plus release artifacts.
  - [x] `docs/release-manual-checklist-v1.5.0.md` exists and the release validation playbook points to it.
- Non-Goals:
  - Runtime implementation changes.
  - Historical release-note rewrites.
- Tests Required (exact locations / names):
  - Repo quality gates from `AGENTS.md`:
    - `./venv/bin/python -m ruff format --check .`
    - `./venv/bin/python -m ruff check .`
    - `./venv/bin/python -m mypy src`
    - `./venv/bin/python -m pytest . -p no:cacheprovider`
- PR Title Template:
  - `[REL-1.5.0-DOCS] Release prep and macOS docs alignment`
- Rollback Risk: Low

## Parallelization Notes
- Lane assignment:
  - Docs lane stories: `REL-1.5.0-DOCS`
- Conflict-avoidance notes:
  - Keep scope to version metadata plus release/operator docs.
- Merge order constraints:
  - none

## Completion Criteria
- All milestone acceptance criteria are complete.
- Story contracts are implemented in scoped PRs.
- Required tests are added/updated and documented.
- Documentation updates are complete and implementation-accurate.
