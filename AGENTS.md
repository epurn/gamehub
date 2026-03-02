# GAMEHUB — unified agent rules

`AGENTS.md` is the single source of truth for AI contributors in this repository.

It applies equally to Codex Web, Codex in the IDE, and any future agent surface.

Do not create or rely on separate workflow-specific rule files. If guidance changes, update this file.

## Project snapshot

GAMEHUB is a Docker-first home server plus local CLI for deterministic emulator library sync.

The server hosts the canonical library and exposes strict APIs:

- `/v1/index`
- `/v1/files/{file_id}`
- `/v1/assets/{asset_id}`
- `/v1/firmware/{system}/{filename}`
- `/v1/saves/{save_id}`

The CLI manages:

- `init`
- `sync`
- `doctor`

Current supported systems:

- `GB`
- `GBA`
- `GBC`
- `GEN_MD`
- `N64`
- `NDS`
- `N3DS`
- `NES`
- `PSX`
- `SNES`
- `GC`
- `Wii`
- `PS2`

Core product constraints:

- no fuzzy title matching
- no ROM/BIOS downloads from third-party sources
- deterministic IDs and repeatable sync behavior
- safety-first writes for local user data and Steam integration

## Architecture map

Runtime code lives only under `src/`.

- `src/gamehub_server/`
  - FastAPI server
  - owns indexing, API responses, and server-side file writes
- `src/gamehub_cli/`
  - Typer CLI
  - owns config loading, planning, transfers, Steam mutation, controller/profile logic
- `src/gamehub_common/`
  - shared contracts only
  - owns models, IDs, and stable cross-boundary schemas
- `tests/`
  - unit and integration coverage for Windows and Linux behavior
- `docs/`
  - operator docs, schemas, release notes, templates
- `PLANS/`
  - planning artifacts and story contracts

Never introduce new runtime code outside `src/`.

## Hard boundaries

These are release-blocking rules, not preferences.

- `gamehub_server` must never import `gamehub_cli`.
- `gamehub_cli` must never import `gamehub_server`.
- Cross-boundary contracts belong in `gamehub_common` first.
- `gamehub_cli/common/` is for reusable low-level helpers only.
- Do not turn `common/` into a grab bag for orchestration or business logic.
- Prefer extending existing domain modules over inventing new cross-domain files.

Preferred module ownership:

- server indexing and API:
  - `src/gamehub_server/indexer.py`
  - `src/gamehub_server/main.py`
- sync orchestration and planning:
  - `src/gamehub_cli/sync/orchestrator.py`
  - `src/gamehub_cli/sync/planner.py`
  - `src/gamehub_cli/sync/steam_stage.py`
- Steam-specific IO/lifecycle:
  - `src/gamehub_cli/steam/*.py`
- controller launch-time behavior:
  - `src/gamehub_cli/controllers/*.py`
- reusable low-level helpers:
  - `src/gamehub_cli/common/*.py`

## Product invariants

These behaviors must stay true unless a task explicitly changes them.

- The server index is canonical and strictly validated by the client.
- `title_id`, `file_id`, `asset_id`, and `save_id` are deterministic.
- Clients must never fall back to fuzzy matching.
- Save sync is limited to indexed save artifacts. Save states are out of scope unless explicitly planned.
- Managed shortcut launches may use hidden internal wrapper commands, but user-facing behavior must remain deterministic and documented.
- Steam writes are safety-gated:
  - detect Steam
  - close Steam before mutation
  - back up Steam files
  - write atomically
  - relaunch only after successful mutation flow

## File mutation rules

Every file operation that mutates user data must be:

- backed up
- atomic
- logged

This applies to:

- local save overwrites
- Steam config writes
- state file writes
- firmware deploy writes
- controller profile/config writes
- server-side save overwrites

Minimum acceptable pattern:

1. If replacing existing user-managed content, create a timestamped backup unless the file is explicitly ephemeral.
2. Write new content to a temporary file first.
3. Flush/fsync where appropriate for the write path.
4. Replace the destination atomically.
5. Emit an explicit log entry for the mutation path.

Do not silently downgrade a mutating write to a direct in-place overwrite.

## Logging and operator UX

Diagnostics must be intentional.

- `--verbose` should emit structured debug-oriented logs.
- audit pathways should be explicit (`--audit`, verbose diagnostics, dedicated doctor flows).
- normal mode should stay user-oriented:
  - progress reporting
  - clear warnings
  - final summary

Do not add unconditional `print()` calls inside low-level helpers.

Low-level helpers may return data or raise errors.
Orchestration layers decide what to print.

If a task requires new diagnostics:

- add them in the orchestration or command path
- keep output deterministic
- avoid noisy per-file logs in normal mode unless the operation is user-visible

## Coding standards

Maintainability is a release requirement.

- Prefer small modules with clear boundaries.
- Keep module responsibilities narrow.
- Remove dead branches, failed experiments, and temporary fallback code as you go.
- Avoid copy-pasting business logic across modules.
- If logic is reused in more than one runtime path, extract a focused shared helper.
- Shared helpers belong in the narrowest valid place:
  - same domain module first
  - `common/` only when the helper is truly low-level and cross-cutting

Orchestration modules should:

- coordinate calls
- sequence stages
- handle top-level user messaging

Orchestration modules should not:

- own parsing details
- own deep file mutation logic
- duplicate policy logic that belongs in a helper

Prefer deterministic behavior over implicit side effects.

- no hidden fallback behavior unless it is explicitly designed, tested, and documented
- no “best effort” fuzzy matching to make bad inputs pass
- fail fast on schema or contract drift

Platform-specific logic must be isolated and fail-open.

- gate branches behind explicit platform detection
- preserve non-target platform behavior
- add both positive and negative-path tests for platform branches

## Planning and execution model

Use `PLANS/` for non-trivial work.

Expected flow:

`Plan -> Milestones -> Story Contracts -> PR`

Before coding:

1. Briefly state what will change.
2. Name the modules/files you expect to touch.
3. Then implement.

There is no approval gate between orientation and edits.

Scope discipline:

- touch only files needed for the task
- avoid opportunistic refactors
- avoid dependency or packaging churn unless the task requires it
- if a task crosses server/client boundaries, freeze the contract in `gamehub_common` first

## Sync pipeline contract

The default sync sequence is:

`load config/state -> validate bootstrap -> fetch index -> ensure emulators/cores/firmware -> build plan -> fetch artwork -> download/apply content -> deploy firmware -> converge controllers -> update Steam -> save state`

Changes to sync behavior must preserve:

- deterministic planning
- idempotent repeat runs
- explicit dry-run support
- safe failure behavior when a stage errors

## Emulators and launch expectations

Default runtime ownership:

- RetroArch for cartridge-era systems
- PCSX2 for PS2
- Dolphin for GC/Wii
- Azahar for N3DS

Launch strings stay simple:

- emulator executable + ROM path

Launch-time controller configuration belongs in `controllers/`.

Do not push controller profile logic into generic sync helpers.

## Testing rules

Tests must verify behavior, not just happy paths.

Required when behavior changes:

- update or add tests in the relevant domain
- cover positive and negative paths
- add idempotency assertions for file/config mutation where practical
- cover platform-specific branches when introduced

Minimum quality gates for touched work:

```powershell
.\venv\Scripts\python.exe -m ruff format --check .
.\venv\Scripts\python.exe -m ruff check .
.\venv\Scripts\python.exe -m mypy src
.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider
```

If a quality gate is intentionally deferred, document the reason in the plan or task notes.

## Documentation rules

Update docs whenever behavior, contracts, or operator-facing flows change.

Required doc updates when applicable:

- `docs/index-schema.md` for schema changes
- `docs/server-api.md` for endpoint behavior changes
- `docs/config-and-state.md` for config/state changes
- `docs/cli-sync.md` for sync or launch behavior changes
- release notes for migrations and operator-visible changes

Docs should be:

- concise
- accurate
- copy-paste runnable where commands are shown

## Definition of done

A task is done only when:

- implementation matches the requested behavior
- boundaries and repo rules are still respected
- tests were added or updated as needed
- docs were updated if behavior changed
- `ruff`, `mypy`, and `pytest` pass
- the diff is focused and reviewable

If any of those are not true, the task is not complete.
