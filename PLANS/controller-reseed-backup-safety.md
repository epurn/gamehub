# PLAN: controller-reseed-backup-safety

## Context
- Background: `gamehub init --reseed-profiles` and `gamehub sync --reseed-profiles` intentionally overwrite managed controller profile seeds.
- Current behavior: profile writes in `src/gamehub_cli/controllers/profiles.py` are atomic, but forced overwrites do not create backups or emit mutation audit logs.
- Trigger/problem statement: forced reseeds can erase local edits without a recoverable copy, which violates the repo's user-data mutation safety rule.

## Goals
- Back up existing managed controller profile files before forced reseed overwrites.
- Emit explicit log records for backup creation and successful profile replacement.
- Cover the forced overwrite path with targeted tests and operator docs.

## Non-Goals
- No repo-wide write-helper refactor.
- No changes to Steam, save sync, or firmware mutation paths.
- No change to non-forced profile seeding behavior.

## Constraints
- Windows-first local development support is required.
- Keep diffs minimal and conflict-resistant for parallel work.
- No dependency/lockfile/packaging changes unless explicitly required.
- No repo-wide formatting.

## Contract Surface
- Existing contracts touched: `seed_default_profiles()` forced overwrite behavior and `--reseed-profiles` operator docs.
- New/updated contract artifacts: none.
- Cross-boundary implications: none; CLI-only change.

## Milestones
1. M1: Add scoped forced-overwrite backup + logging in controller profile seeding.
2. M2: Add deterministic tests for backup creation and collision-safe backup names.
3. M3: Update docs and verify required quality gates.

## Story Contracts

### STORY CRS-1
- Type: CLI
- Goal: Make forced controller profile reseeds recoverable and auditable.
- Acceptance Criteria (deterministic):
  - [ ] Existing profile files are backed up before overwrite when `seed_default_profiles(..., force=True)` replaces them.
  - [ ] Forced overwrites emit explicit log records for the backup path and the successful write.
- Non-Goals:
  - No backups for first-time seed writes.
- Tests Required (exact locations / names):
  - `tests/test_controller_profiles.py::test_seed_default_profiles_force_creates_backup_for_existing_file`
  - `tests/test_controller_profiles.py::test_seed_default_profiles_force_uses_unique_backup_name_when_collision_exists`
- PR Title Template: `Protect forced controller profile reseeds with backups`
- Rollback Risk: Low

### STORY CRS-2
- Type: DOCS
- Goal: Document the new backup behavior for `--reseed-profiles`.
- Acceptance Criteria (deterministic):
  - [ ] `docs/cli-sync.md` states that forced reseeds create timestamped backup files before overwrite.
  - [ ] `docs/config-and-state.md` states the same behavior in the controller profile section.
- Non-Goals:
  - No broader onboarding or release note changes.
- Tests Required (exact locations / names):
  - Documentation only.
- PR Title Template: `Document controller reseed backup behavior`
- Rollback Risk: Low

## Parallelization Notes
- Lane assignment:
  - Server lane stories: none.
  - CLI lane stories: CRS-1.
  - Common lane stories: none.
  - Docs lane stories: CRS-2.
- Conflict-avoidance notes: keep the code change limited to controller profile seeding and reuse existing fs helpers.
- Merge order constraints: implement CLI change before doc wording finalization.

## Completion Criteria
- All milestone acceptance criteria are complete.
- Story contracts are implemented in scoped PRs.
- Required tests are added/updated and documented.
- Documentation updates are complete and implementation-accurate.
