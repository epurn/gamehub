# PLAN: save-conflict-resolution-phase2

## Context
- Background:
  Phase 1 added `gamehub doctor saves` so operators can inspect persisted save conflicts and current save drift without opening `state.json`.
- Current behavior:
  Save conflicts are visible, but operators still need to rely on a full sync run or direct file/state editing to force a chosen winner.
- Trigger/problem statement:
  We need an explicit, narrow phase-2 write path that resolves one indexed save at a time without turning `doctor saves` into a broad sync substitute.

## Goals
- Add explicit operator-driven resolution commands for one save at a time.
- Reuse existing safe download/upload/state-write paths instead of inventing a parallel mutation stack.
- Keep binding-root ambiguity out of scope for this pass.

## Non-Goals
- No bulk/batch conflict resolution.
- No binding-root ambiguity repair flow.
- No changes to planner policy or server-side contracts.

## Constraints
- Windows and macOS local development support are required.
- Keep diffs minimal and conflict-resistant for parallel work.
- No dependency/lockfile/packaging changes unless explicitly required.
- No repo-wide formatting.

## Contract Surface
- Existing contracts touched:
  `gamehub doctor saves` CLI surface, save diagnostics flow, save transfer/state mutation path, operator docs.
- New/updated contract artifacts:
  `gamehub doctor saves --keep-local <save_id>` and `gamehub doctor saves --keep-server <save_id>`.
- Cross-boundary implications:
  None; client-only flow built on existing server API endpoints.

## Milestones
1. M1: Add single-save resolution orchestration on top of current save/index/binding/state helpers.
2. M2: Expose the operator-facing CLI flags on `doctor saves`.
3. M3: Add focused tests and docs for dry-run and real resolution paths.

## Story Contracts

### STORY GH-263
- Type: CLI
- Goal:
  Let operators resolve a single indexed save by explicitly choosing the local or server copy.
- Acceptance Criteria (deterministic):
  - [ ] `gamehub doctor saves --keep-local <save_id>` uploads the local file, updates save lineage/checksum state, and clears the unresolved conflict on success.
  - [ ] `gamehub doctor saves --keep-server <save_id>` downloads the remote file, updates save lineage/checksum state, and clears the unresolved conflict on success.
  - [ ] `--dry-run` previews the chosen action without mutating local files or `state.json`.
- Non-Goals:
  - No multi-save resolution.
  - No binding ambiguity repair.
- Tests Required (exact locations / names):
  - `tests/test_cli_commands.py`
  - `tests/test_save_resolution.py`
- PR Title Template:
  - `[GH-263] Add explicit save conflict resolution commands`
- Rollback Risk: Medium

### STORY GH-264
- Type: DOCS
- Goal:
  Document how operators should use the new explicit resolution flags and what remains manual.
- Acceptance Criteria (deterministic):
  - [ ] CLI docs show both resolution commands and dry-run usage.
  - [ ] State/config docs explain that resolution is per-save and does not cover binding ambiguity.
- Non-Goals:
  - No release-note update in this story.
- Tests Required (exact locations / names):
  - `tests/test_sync_doctor.py`
- PR Title Template:
  - `[GH-264] Document phase-2 save conflict resolution`
- Rollback Risk: Low

## Parallelization Notes
- Lane assignment:
  - Server lane stories:
  - CLI lane stories: `GH-263`
  - Common lane stories:
  - Docs lane stories: `GH-264`
- Conflict-avoidance notes:
  Keep the write path under `src/gamehub_cli/sync/` and avoid changing save planner policy.
- Merge order constraints:
  `GH-263` before `GH-264` if split.

## Completion Criteria
- All milestone acceptance criteria are complete.
- Story contracts are implemented in scoped PRs.
- Required tests are added/updated and documented.
- Documentation updates are complete and implementation-accurate.
