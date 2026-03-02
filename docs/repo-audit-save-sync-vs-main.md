# Save-sync branch audit vs main

Date: 2026-03-02
Baseline compared: `main` tip at merge-base parent `084beb2` (from merge commit `b093987`)

## Scope

Audit focus requested:

- modern Python aligned with repo patterns
- minimal code duplication
- production readiness for a home-server environment
- no drift between runtime behavior, tests, and docs

## What was reviewed

- Runtime deltas under `src/` for save-sync (`gamehub_common`, `gamehub_server`, `gamehub_cli`).
- Save-sync tests (`tests/test_sync.py`, `tests/test_planner.py`, `tests/test_save_contracts.py`, `tests/test_server_api.py`, related coverage).
- Save-sync docs ([docs/cli-sync.md](./cli-sync.md), [docs/config-and-state.md](./config-and-state.md), [docs/index-schema.md](./index-schema.md), [docs/server-api.md](./server-api.md)).
- Style/lint posture via Ruff.

## Findings

### 1) Save upload decisions were being counted as completed uploads even though upload transport is not implemented

- In `apply_save_stage`, actions with `decision == "upload"` incremented `uploaded` and continued without any transfer.
- This could report successful upload progress and leave state perception ahead of reality.

**Risk:** medium (operator trust and state/accounting correctness).

**Fix applied:** non-dry-run upload actions now fail the stage with `upload-not-implemented`; dry-run still reports planned upload actions for visibility.

## Other audit observations

- Save-sync schema, planner behavior, and docs are generally aligned on rollout semantics (download implemented, upload staged for later contract completion).
- Branch remains lint-clean at rule level; repo-wide format drift exists outside this scope and should be addressed in a dedicated formatting PR.
- Full-suite validation should run in Python 3.12 `venv/` to match repository runtime contract.

## Suggested follow-up fixes (not part of this patch)

1. Add end-to-end tests for future server-side save upload once `/v1/saves/{save_id}` PUT is implemented.
2. Add explicit CLI output hint when upload actions are planned in dry-run mode (e.g., "planned upload; upload API not active yet").
3. Run a dedicated repo-wide formatting pass to remove pre-existing Ruff format drift.
