# Save-sync branch audit vs main

Date: 2026-03-02
Baseline compared: `main` tip at merge-base parent `084beb2` (from merge commit `b093987`)

## Scope

Audit focus requested:

- modern Python aligned with repo patterns
- minimal code duplication
- production readiness for a home-server environment
- no drift between runtime behavior, tests, and docs

Historical note:

- This document reflects an earlier branch checkpoint and is no longer the current source of truth for save-sync rollout behavior.
- Save uploads are now implemented, and the managed shortcut wrapper has been renamed to `shortcut-launch`.
- Use the current runtime docs ([server-api.md](./server-api.md), [cli-sync.md](./cli-sync.md), [config-and-state.md](./config-and-state.md)) for active behavior.

## What was reviewed

- Runtime deltas under `src/` for save-sync (`gamehub_common`, `gamehub_server`, `gamehub_cli`).
- Save-sync tests (`tests/test_sync.py`, `tests/test_planner.py`, `tests/test_save_contracts.py`, `tests/test_server_api.py`, related coverage).
- Save-sync docs ([docs/cli-sync.md](./cli-sync.md), [docs/config-and-state.md](./config-and-state.md), [docs/index-schema.md](./index-schema.md), [docs/server-api.md](./server-api.md)).
- Style/lint posture via Ruff.

## Findings

### 1) Save upload decisions were being counted as completed uploads even though upload transport was not implemented

- In `apply_save_stage`, actions with `decision == "upload"` incremented `uploaded` and continued without any transfer.
- This could report successful upload progress and leave state perception ahead of reality.

**Risk:** medium (operator trust and state/accounting correctness).

**Historical fix note:** this finding has since been superseded by real upload execution and server-side `PUT /v1/saves/{save_id}` support.

## Other audit observations

- Treat the rest of this file as historical context only; several rollout details were intentionally changed after this audit.
- Branch remains lint-clean at rule level; repo-wide format drift exists outside this scope and should be addressed in a dedicated formatting PR.
- Full-suite validation should run in Python 3.12 `venv/` to match repository runtime contract.

## Historical follow-up notes

The open items from this checkpoint are intentionally retired here.

- Server-side `PUT /v1/saves/{save_id}` upload support and related validation have since landed.
- Use current planning docs, runtime docs, and release checklists for active follow-up work instead of this historical checkpoint.
