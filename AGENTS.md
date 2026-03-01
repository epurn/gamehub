# GAMEHUB — AGENTS.md (Codex Rules)

This repo is "GAMEHUB": a Docker-first home-server + client CLI that syncs emulator libraries and injects them into Steam as non-Steam games with correct artwork and automatic system collections.

## Core goals (v1)
- Server (Docker): hosts canonical ROM library, firmware, and artwork; exposes an index + file endpoints.
- Client (CLI): `gamehub sync` pulls missing/updated items, installs firmware (raw files), updates Steam shortcuts + collections, copies artwork, and restarts Steam (close -> modify -> reopen).
- Supported systems in v1: `GB`, `GBA`, `GBC`, `GEN_MD`, `N64`, `NDS`, `NES`, `PSX`, `SNES`, `GC`, `Wii`, `PS2`.
- ROM/firmware are server-first; artwork strategy may include SteamGridDB API-based fetching with user key.
- Deterministic + safe: atomic writes, backups, and clear dry-run behavior.

## Non-negotiables
- Do NOT require Steam ROM Manager (SRM) in v1.
- Must support auto-categories: collections named exactly by system (e.g., "PS2", "Wii", "NES").
- CLI must close Steam, apply changes, then reopen Steam.
- Firmware handling is system-level. If firmware is missing locally, skip titles for that system and report; retry next sync.
- No internet fetching of ROMs/BIOS. Artwork may be fetched via SteamGridDB when configured.
- "Strict matching": server naming is canonical; client does not try fuzzy title matching.

## ROM layout rule (current)
- Server ROM layout is flat per system:
  - `/data/roms/<system>/<title.ext>`
- Nested title directories under a system are invalid in current indexing behavior.

## Repo structure (current, post-refactor)
- `src/gamehub_server/` FastAPI server package (`main.py`, `indexer.py`)
- `src/gamehub_cli/` Typer CLI package, split by domain:
  - `common/`, `sync/`, `steam/`, `controllers/`, `firmware/`, `emulators/`
- `src/gamehub_common/` shared models and ID helpers
- `tests/` cross-platform unit/integration tests
- `scripts/` release/readiness/util scripts
- `docs/` schemas, templates, and integration notes
- `PLANS/` AI-first planning artifacts (plan files + story contracts)
- `kanban/` deprecated legacy planning artifacts (read-only; do not add new work)
- `docker/` container assets for server/runtime flows

Refactor guardrail:
- Do not reintroduce legacy pre-refactor layout patterns (`apps/*`, `shared/*`) for new runtime code.
- Keep new code inside the package-first `src/gamehub_*` architecture unless a migration task explicitly requires otherwise.
- Keep the `src/` layout as the single source of truth for runtime imports and packaging metadata.

## Package boundary rules (post-refactor)
- Keep orchestration in `src/gamehub_cli/sync/orchestrator.py`; stage modules should stay focused (`index`, `transfer`, `steam`, `artwork`).
- Keep Steam-specific logic in `src/gamehub_cli/steam/` and avoid recreating monolithic wrappers.
- Keep controller launch/apply logic in `src/gamehub_cli/controllers/`; avoid spreading controller mutations into sync/steam modules.
- Keep reusable primitives in `src/gamehub_cli/common/` and avoid cross-domain helper duplication.
- Keep `__init__.py` exports minimal and intentional; do not expose internal helpers as public API unless required.
- Do not add new root-level legacy-style modules under `src/gamehub_cli/` that duplicate package domains.

## AI-first planning workflow (authoritative)
- All new planning artifacts live in `PLANS/`.
- Flow is mandatory and deterministic: `Plan -> Milestones -> Story Contracts -> PR`.
- Story Contracts must be executable, independently mergeable, and scoped for minimal diff overlap.
- Domain isolation is required by default:
  - `SERVER` stories touch server code/docs only.
  - `CLI` stories touch CLI code/docs only.
  - `COMMON` stories touch shared package/docs only.
  - `DOCS` stories touch docs/process files only.
  - touching both server and CLI requires a `CROSS-BOUNDARY` contract.
- Parallel conflict avoidance is mandatory:
  - keep diffs minimal and scoped to story contract files
  - no dependency/lockfile/packaging version bumps unless the story explicitly requires them
  - no repo-wide formatting in story PRs
- Contract-first rule for cross-boundary changes:
  - define and freeze the contract surface before implementation changes
  - implement boundary participants in separate, reviewable commits when practical
- Orientation pass is required before edits:
  - list intended files/directories to create or modify
  - explain approach, risks, and planned validation commands
  - only begin edits after orientation output is complete
- Keep stories junior-dev readable, deterministic, and explicit about acceptance criteria and tests.

For daily work: read `docs/codex.md` and implement STORY IDs from `PLANS/*.md`. Prompts should be one-liners.

## Technical stack (v1)
- Python 3.12+
- Server: FastAPI + Uvicorn
- CLI: Typer + Rich + httpx + platformdirs
- Models: Pydantic (`src/gamehub_common/models.py`)
- Config: TOML (client), ENV vars (server)
- Packaging/locking: `uv` preferred

## Environment rule
- A local virtual environment exists at `venv/`.
- Always activate and use `venv/` for all Python commands in this repo.
- Preferred command form on Windows:
  - `.\venv\Scripts\python.exe -m <module>`
  - `.\venv\Scripts\python.exe -m pytest`
  - `.\venv\Scripts\pip.exe install -e .[dev]`

## Documentation rule
- Any behavior or schema change must be reflected in `docs/` in the same work item.
- Keep docs concise, implementation-accurate, and runnable with copy/paste commands.

## Release and distribution rules (v1.0.3)
- Server release channel is GHCR image tags:
  - `ghcr.io/<org>/gamehub-server:vX.Y.Z`
  - `ghcr.io/<org>/gamehub-server:latest`
- GitHub Release assets are for client + deploy convenience:
  - Linux wheel
  - Windows executable
  - `gamehub-server-deploy-vX.Y.Z.zip` (compose/env template/docs/verify script bundle)
  - `checksums.txt`
- Keep server deployment docs aligned with this model:
  - production users should pull and run GHCR images via `docker compose`
  - `--build` is for source/dev paths, not the default release consumption flow

## Steam integration rules (critical)
- Steam non-Steam shortcuts live in `userdata/<steamid>/config/shortcuts.vdf` (binary VDF). Use a proven VDF lib; do not hand-roll binary parsing.
- Collections are written to:
  - `userdata/<steamid>/config/localconfig.vdf` (`user-collections`)
  - `userdata/<steamid>/config/cloudstorage/cloud-storage-namespace-1.json` (`user-collections.*` entries)
- Before writing Steam config:
  - Detect Steam running; close it.
  - Backup `shortcuts.vdf`, `localconfig.vdf`, and cloud storage JSON (when present) with timestamp suffix.
  - Write updates atomically (write temp file, fsync, rename).
- After writing:
  - Copy artwork into `userdata/<steamid>/config/grid/` using the shortcut appid read back from `shortcuts.vdf`.
  - Reopen Steam.

## Sync behavior rules
- Downloads:
  - Stream downloads to `*.part`, then rename.
  - Verify checksum only on download by default.
  - `--verify` may rehash local files; keep it off by default.
- State:
  - Maintain a `state.json` (or `state.sqlite` later) tracking downloaded file_ids, checksums, and last sync.
  - Track tombstones (local deletions) but default behavior is re-download.
- Updates:
  - If server checksum differs, re-download and update Steam shortcut launch targets and artwork.

## Index contract (server -> client)
- Server generates `/v1/index` with stable IDs:
  - `title_id` deterministic from `system + server_relative_title_path`
  - `file_id` deterministic from `server_relative_path + sha256`
- Index includes:
  - systems (firmware requirements, rom extensions, default emulator)
  - titles (rom rel_path, sha256, emulator launch template, system name for collection; assets may be empty pending artwork workflow)
- Client must validate index schema strictly (pydantic) and fail fast with actionable errors.

## Emulator strategy (v1)
- RetroArch for most cartridge-era systems.
- PCSX2 for PS2.
- Dolphin (standalone) for GC/Wii.
- Launch is "emulator exe + rom path" (no frontends).

## Dolphin runtime rules (v1 hardening)
- On Linux flatpak-preferred flows, Dolphin is treated as Flatpak-required (`org.DolphinEmu.dolphin-emu`).
- Dolphin shortcuts should pass `-u <dolphin-user-path>` so launch and config bootstrap target the same runtime user dir.
- Bootstrap writes Dolphin runtime config for fullscreen/input and controller-exit hotkeys; avoid Windows-only device tokens on Linux.
- Keep compatibility with legacy Dolphin CLI parser behavior by probing support before injecting parser-dependent args.

## Coding standards
- Prefer small modules with clear boundaries:
  - `src/gamehub_server/indexer.py`, `src/gamehub_server/main.py`
  - `src/gamehub_cli/sync/orchestrator.py`, `src/gamehub_cli/sync/planner.py`, `src/gamehub_cli/sync/steam_stage.py`
  - `src/gamehub_cli/steam/*.py` for Steam-specific read/write/lifecycle logic
  - `src/gamehub_cli/controllers/*.py` for launch-time controller profile logic
  - `src/gamehub_cli/common/*.py` for reusable low-level helpers only
- Prefer extending existing domain modules over creating new cross-domain files.
- Every file operation that mutates user data must be:
  - backed up
  - atomic
  - logged
- Logging:
  - `--verbose` prints structured debug logs.
  - Normal mode shows progress bars + summary table.

## Code quality guardrails (repo-wide)
- Treat maintainability as a release requirement, not a cleanup task:
  - avoid copy/pasting business logic across modules
  - extract shared helpers in `common/` when logic is used in more than one runtime path
  - remove failed/experimental attempts as you go; do not leave dead fallback/fix branches for later cleanup
- Keep module responsibilities narrow:
  - orchestration modules should coordinate calls, not own parsing/mutation details
  - parsing/mutation logic should live in dedicated helpers with focused unit tests
- Prefer deterministic behavior over implicit side effects:
  - no unconditional `print()` calls from low-level library helpers
  - diagnostics should be routed through explicit verbose/audit pathways
- New platform-specific logic must be isolated and fail-open:
  - gate platform branches behind explicit detection helpers
  - preserve non-target platform behavior unless the story explicitly changes it
- Quality checks are part of "done":
  - run lint/type checks for touched modules before merge (`ruff`, `mypy`)
  - if a quality gate is intentionally deferred, document why in the story/Test Notes
- Tests should verify behavior, not just happy paths:
  - add both positive and negative-path assertions for new platform branches
  - include idempotency assertions when mutating emulator or Steam config files

## Testing standards (v1)
- Unit tests for:
  - index generation (given fixture FS tree -> stable index)
  - diff planner (state + index -> plan)
  - steam file writer (round-trip read/write, minimal diffs)
- Integration test harness:
  - use a temp "fake Steam userdata" directory fixture.
- Codex execution policy for this repo:
  - do not run test suites from the agent environment; always provide the exact test commands for the user to run locally
  - treat user-provided test output as the source of truth for pass/fail
- Pytest execution rule:
  - preferred local invocation from an activated venv: `pytest . -p no:cacheprovider`
  - always disable pytest cache provider (`-p no:cacheprovider`)
  - keep pytest temp artifacts ignored by git so local cleanup is not required each run
  - run commands directly in the active shell; avoid nested quoted wrappers that can leave shells waiting on unterminated quotes
- Cross-platform test reliability rule (dev + CI):
  - tests must pass on native Windows and native Linux hosts; do not write assertions that depend on the host OS path separator when mocking a different runtime platform
  - for path-like assertion values, normalize separators (and optional wrapping quotes) before asserting
  - when simulating platform branches, patch `module.sys.platform` instead of replacing the module `sys` object
  - prefer repo-local tempdir helpers (for example `.pytest_tmp_local/...`) over brittle assumptions about pytest temp internals in reduced-plugin runs
- Local pre-public audit rule:
  - run `.\venv\Scripts\python.exe scripts/audit_repo_readiness.py` before tagging releases
  - treat `FAIL` as release-blocking; `WARN` requires explicit acknowledgement (for current known rotated-history secret case)

## Definition of done (for any story)
- Acceptance criteria met
- Tests added/updated
- Docs updated if touching schemas or Steam behavior
- Story contract and PR notes updated with outcome notes

## Implementation baseline (evergreen)
- Server:
  - Flat ROM indexing at `roms/<system>/<title.ext>` with strict validation.
  - API surface includes `/health`, `/v1/index`, `/v1/files/{file_id}`, `/v1/assets/{asset_id}`, `/v1/firmware/{system}/{filename}`.
  - Firmware endpoint rejects traversal-style targets and returns clean `404` for invalid/missing paths.
- Client:
  - Sync pipeline includes config/state loading, diff planning, streamed downloads, firmware deploy, SGDB artwork flow, and Steam apply stages.
  - Steam mutations are safety-first (close/wait/backup/atomic write/reopen) with `--require-steam-closed` and `--skip-steam` support.
  - Managed shortcuts/collections/artwork are idempotent across repeat sync runs.
- Release packaging:
  - Tag-triggered workflows publish GHCR server images plus client release assets and checksums.
  - Deploy bundle zip (`gamehub-server-deploy-vX.Y.Z.zip`) is published for server deployment convenience.
- Validation baseline:
  - Full test suite target is `.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider`.
  - Server smoke check target is `GET /v1/index` returning `200`.
