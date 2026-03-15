# PLAN: macos-controller-hardening

## Context
- Background: a final audit of the macOS controller/runtime work found one safety regression in the Azahar quit path and one heuristic fallback in SDL mapping resolution that can silently produce the wrong bindings.
- Current behavior: the macOS Azahar quit hook can fall back to killing all matching Azahar PIDs if it cannot distinguish a newly launched process, and guidless SDL mapping lookup can choose an unrelated embedded mapping when there is no actual identity match.
- Trigger/problem statement: we need a focused hardening pass before the PR into `mac-support` so the branch stays safety-first, deterministic, and aligned with repo standards.

## Goals
- Make macOS Azahar quit handling fail open instead of killing pre-existing Azahar sessions.
- Use the existing mapping-aware macOS controller selector path in the live quit monitor when it is available.
- Make macOS embedded SDL mapping lookup return `None` when identity evidence is insufficient instead of guessing a controller entry.

## Non-Goals
- Expanding supported controller families beyond the current branch scope.
- Refactoring unrelated controller/profile/runtime modules.
- Changing non-macOS controller behavior.

## Constraints
- Windows and macOS local development support are required.
- Keep diffs minimal and conflict-resistant for parallel work.
- No dependency/lockfile/packaging changes.
- No repo-wide formatting.

## Contract Surface
- Existing contracts touched:
  - macOS Azahar shortcut exit-hook behavior
  - macOS embedded SDL mapping fallback behavior
- New/updated contract artifacts:
  - none
- Cross-boundary implications:
  - none

## Milestones
1. M1: Remove unsafe process-kill fallback for pre-existing macOS Azahar sessions.
2. M2: Wire the mapping-aware macOS combo selector path into the live quit monitor.
3. M3: Tighten SDL mapping selection and cover the new fail-open paths with tests/docs.

## Story Contracts

### STORY MACOS-HARDEN-01
- Type: CLI
- Status: Complete
- Goal: harden macOS controller/quit-hook behavior without widening feature scope.
- Acceptance Criteria (deterministic):
  - [x] macOS Azahar quit fallback only targets newly launched Azahar processes when one can be identified.
  - [x] macOS quit monitoring uses the resolved controller port/button mapping when native selector polling is available.
  - [x] macOS embedded SDL mapping lookup returns `None` when there is no exact identity or exact-name match.
  - [x] targeted controller/quit-hook tests cover the new fail-open behavior.
- Non-Goals:
  - changing Windows/Linux controller flows
  - broad controller support policy changes
- Tests Required (exact locations / names):
  - `tests/test_azahar_exit_hook.py`
  - `tests/test_controller_detection.py`
  - `tests/test_shortcut_runtime.py`
- PR Title Template: `CLI: harden macOS controller mapping and Azahar exit hook`
- Rollback Risk: Medium

## Parallelization Notes
- Lane assignment:
  - CLI lane stories: `MACOS-HARDEN-01`
  - Docs lane stories: `MACOS-HARDEN-01`
- Conflict-avoidance notes:
  - keep changes scoped to macOS controller/runtime helpers and related docs/tests
- Merge order constraints:
  - none

## Completion Criteria
- The unsafe macOS process-kill fallback is removed.
- Mapping-aware selector polling is live or explicitly fail-open.
- Unknown controller identities no longer receive guessed embedded SDL mappings.
- Required tests and affected docs are updated and accurate.
- Story `MACOS-HARDEN-01` is complete on this branch.
