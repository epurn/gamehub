# PLAN: save-doctor-phase1-and-codex-setup

## Context
- Background:
  GAMEHUB already persists save-sync conflict state and binding-root learning state, and the repo ships a Codex worktree bootstrap script.
- Current behavior:
  The CLI exposes doctor flows for controllers, ROMs, firmware, and `all`, but no save-focused doctor command; the Codex environment file leaves the default `[setup]` script blank.
- Trigger/problem statement:
  Save-sync issues require raw `state.json` inspection, and some Codex surfaces may miss worktree bootstrap because the fallback setup entry is empty.

## Goals
- Add a read-only phase-1 save doctor surfaced directly and through `doctor all`.
- Make the default Codex environment setup entry usable without changing the existing platform-specific commands.
- Cover both changes with focused tests and concise docs.

## Non-Goals
- No conflict-resolution write path for save sync in this story.
- No changes to save planner policy or persisted state schema.
- No packaging or dependency changes.

## Constraints
- Windows and macOS local development support are required.
- Keep diffs minimal and conflict-resistant for parallel work.
- No dependency/lockfile/packaging changes unless explicitly required.
- No repo-wide formatting.

## Contract Surface
- Existing contracts touched:
  CLI doctor command surface, sync diagnostics output, Codex environment bootstrap config, operator docs.
- New/updated contract artifacts:
  `doctor saves` command and `doctor all` save-audit inclusion.
- Cross-boundary implications:
  None; this remains CLI/docs only.

## Milestones
1. M1: Add save-diagnostics reporting and CLI wiring.
2. M2: Fix the default Codex environment setup entry.
3. M3: Add tests and docs for both surfaces.

## Story Contracts

### STORY GH-261
- Type: CLI
- Goal:
  Add a read-only save doctor that exposes persisted conflicts and current non-benign save actions.
- Acceptance Criteria (deterministic):
  - [ ] `gamehub doctor saves` returns the same snapshot-driven diagnostics style as other doctor commands.
  - [ ] `gamehub doctor all` runs controller, save, firmware, and ROM audits in one pass.
  - [ ] Save-doctor output distinguishes persisted conflict records from current planned save actions.
- Non-Goals:
  - No write-based conflict resolution.
- Tests Required (exact locations / names):
  - `tests/test_cli_commands.py`
  - `tests/test_sync_doctor.py`
- PR Title Template:
  - `[GH-261] Add phase-1 save doctor diagnostics`
- Rollback Risk: Low

### STORY GH-262
- Type: DOCS
- Goal:
  Ensure Codex setup fallback and save-doctor usage are documented and regression-tested.
- Acceptance Criteria (deterministic):
  - [ ] `.codex/environments/environment.toml` has a non-empty default setup script.
  - [ ] Docs mention the save-doctor command and the Codex setup fallback behavior.
  - [ ] A test guards the checked-in Codex environment configuration.
- Non-Goals:
  - No changes to the bootstrap script behavior itself.
- Tests Required (exact locations / names):
  - `tests/test_codex_environment.py`
- PR Title Template:
  - `[GH-262] Fix Codex setup fallback and docs`
- Rollback Risk: Low

## Parallelization Notes
- Lane assignment:
  - Server lane stories:
  - CLI lane stories: `GH-261`
  - Common lane stories:
  - Docs lane stories: `GH-262`
- Conflict-avoidance notes:
  Keep save-doctor work in CLI diagnostics/main/tests and keep setup changes limited to `.codex/`, docs, and one config test.
- Merge order constraints:
  None inside this scoped patch.

## Completion Criteria
- All milestone acceptance criteria are complete.
- Story contracts are implemented in scoped PRs.
- Required tests are added/updated and documented.
- Documentation updates are complete and implementation-accurate.
