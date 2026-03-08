# GAMEHUB agent rules

`AGENTS.md` is the single rule file for AI contributors in this repo.

It applies equally to web, IDE, and any future agent surface.

The goal is strict repo safety with minimal process overhead:

- be strict on architecture, contracts, safety, and quality gates
- be flexible on workflow and implementation details
- optimize for fast, correct, reviewable diffs

## Fast orientation

GAMEHUB is a Docker-first home server plus local CLI for deterministic emulator library sync.

Core packages:

- `src/gamehub_server/`
  - FastAPI server
  - owns indexing, API responses, and server-side library writes
- `src/gamehub_cli/`
  - Typer CLI
  - owns config, planning, transfers, Steam integration, controller flows
- `src/gamehub_common/`
  - shared contracts only
  - owns models, IDs, and cross-boundary schemas

Support directories:

- `tests/`
- `docs/`
- `PLANS/`

Never add runtime code outside `src/`.

## Product invariants

These stay true unless the task explicitly changes them.

- The server index is canonical.
- The client validates server contracts strictly and fails fast on drift.
- `title_id`, `file_id`, `asset_id`, and `save_id` are deterministic.
- No fuzzy title matching.
- No “best effort” heuristics to make bad data pass.
- Sync behavior should be deterministic and idempotent.
- Steam mutation is safety-first.
- Save sync covers indexed save artifacts only unless a plan explicitly expands scope.

## Hard boundaries

These are non-negotiable.

- `gamehub_server` must never import `gamehub_cli`.
- `gamehub_cli` must never import `gamehub_server`.
- Cross-boundary changes must freeze contracts in `gamehub_common` first.
- `gamehub_cli/common/` is for reusable low-level helpers only.
- Do not move orchestration or domain policy into `common/`.

Preferred ownership:

- server indexing/API:
  - `src/gamehub_server/indexer.py`
  - `src/gamehub_server/main.py`
- sync orchestration/planning:
  - `src/gamehub_cli/sync/orchestrator.py`
  - `src/gamehub_cli/sync/planner.py`
  - `src/gamehub_cli/sync/steam_stage.py`
- Steam-specific logic:
  - `src/gamehub_cli/steam/*.py`
- controller launch-time logic:
  - `src/gamehub_cli/controllers/*.py`
- low-level shared helpers:
  - `src/gamehub_cli/common/*.py`

Prefer extending an existing domain module over creating a new cross-domain file.

## Code standards

Favor maintainability over cleverness.

- Prefer small modules with clear boundaries.
- Keep module responsibilities narrow.
- Orchestration modules should coordinate, not own parsing or mutation details.
- Avoid copy-pasting business logic.
- If logic is reused, extract the narrowest shared helper that fits.
- Remove dead branches, abandoned fallback paths, and failed experiments as you go.

Good rule of thumb:

- same domain helper first
- `common/` only if the helper is truly low-level and reused

Do not add process-heavy ceremony that slows the task down unless safety requires it.

Python execution rule:

- Always run Python commands with the repo-local virtual environment in `./venv`.
- Do not rely on a system/global Python interpreter.

## File mutation rules

Every user-data mutation must be:

- backed up
- atomic
- logged

This includes:

- local save overwrites
- server-side save overwrites
- Steam config writes
- state writes
- firmware deploy writes
- controller profile/config writes

Minimum pattern:

1. Back up the existing file when replacing non-ephemeral user data.
2. Write to a temp file first.
3. Flush/fsync where appropriate for the write path.
4. Replace atomically.
5. Emit an explicit log record.

Do not silently fall back to in-place overwrite.

## Logging and operator UX

Diagnostics must be intentional.

- `--verbose` should emit structured debug-oriented output.
- audit/debug pathways should be explicit.
- normal mode should stay readable:
  - progress
  - warnings
  - final summary

Do not add unconditional `print()` calls in low-level helpers.

Low-level helpers should return data or raise errors.
Command/orchestration layers decide what to print.

## Platform rules

New platform-specific logic must be isolated and fail-open.

- Development regularly moves between macOS and Windows.
- Do not assume one default host OS for commands or paths.
- Agent behavior must remain cross-platform unless a task explicitly scopes to one OS.
- gate platform branches behind explicit detection
- preserve non-target platform behavior
- do not regress existing platforms as collateral damage

When adding platform branches, add both positive and negative-path tests.

## Planning and execution

Use `PLANS/` for non-trivial work.

Expected shape:

`Plan -> Milestones -> Story Contracts -> PR`

Before coding:

1. Briefly state what will change.
2. Name the main files/modules you expect to touch.
3. Then implement.

There is no approval gate between orientation and edits.

Keep scope tight:

- touch only what the task requires
- avoid unrelated refactors
- avoid dependency or packaging churn unless required

## Testing and quality gates

If behavior changes, update tests.

Tests should verify behavior, not just happy paths:

- positive and negative paths
- idempotency where config or files are mutated
- platform-specific branches when added

Required quality gates before calling work done:

Run with the repo-local virtual environment interpreter:

```bash
./venv/bin/python -m ruff format --check .
./venv/bin/python -m ruff check .
./venv/bin/python -m mypy src
./venv/bin/python -m pytest . -p no:cacheprovider
```

```powershell
.\venv\Scripts\python.exe -m ruff format --check .
.\venv\Scripts\python.exe -m ruff check .
.\venv\Scripts\python.exe -m mypy src
.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider
```

If a gate is intentionally deferred, document why.

## Documentation rules

Update docs whenever contracts, behavior, or operator flows change.

Common targets:

- `docs/index-schema.md`
- `docs/server-api.md`
- `docs/config-and-state.md`
- `docs/cli-sync.md`
- release notes for migrations or operator-visible changes

Docs should be concise, accurate, and runnable where commands are shown.

## Definition of done

A task is done only when:

- the implementation matches the request
- repo boundaries still hold
- tests/docs were updated where needed
- `ruff`, `mypy`, and `pytest` pass
- the diff is focused and reviewable

If any of those are not true, the task is not complete.
