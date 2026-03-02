# PLAN: save-sync

## Context
- Background: Add cross-device sync for emulator save files (battery saves, memory-card style saves, per-game save data) for managed GAMEHUB titles. Save states are intentionally out of scope for the first release because they are less portable across emulator/core versions and carry a higher corruption risk.
- Current behavior: GAMEHUB sync handles ROMs, firmware, artwork, and Steam mutations, but it has no save artifact schema, no save endpoints, no planner actions for saves, and no save-specific state lineage.
- Trigger/problem statement: Managed titles need deterministic save continuity across devices without fuzzy matching, unsafe writes, or cross-boundary implementation drift.

## Goals
- Add explicit, deterministic save-file sync for managed GAMEHUB titles.
- Keep the feature schema-first with strict IDs, strict validation, and no fuzzy title/save matching.
- Support a safe rollout with config toggles, dry-run visibility, and explicit conflict behavior.
- Preserve package boundaries so the feature can ship as scoped, parallelizable story PRs.

## Non-Goals
- Generic cloud provider integration.
- Fuzzy title/save matching.
- Best-effort migration of unknown third-party save layouts.
- Save-state sync in the initial release phase.

## Constraints
- Windows-first local development support is required.
- Keep diffs minimal and conflict-resistant for parallel work.
- No dependency/lockfile/packaging changes unless explicitly required.
- No repo-wide formatting.
- Save sync must preserve deterministic behavior, strict matching, atomic writes, and fail-fast schema validation.
- Initial rollout should default to safe behavior: `save_sync.enabled = false`, with launch-session bidirectional upload only when explicitly enabled and used through managed shortcuts.

## Contract Surface
- Existing contracts touched:
  - `/v1/index` server-to-client schema
  - CLI TOML config parsing and defaults
  - `state.json` persistence keys and backward-compatible loading
  - Sync planner action classification and dry-run reporting
- New/updated contract artifacts:
  - Save artifact schema with `save_id`, `title_id`, `system`, `kind`, `rel_path`, `sha256`, `size_bytes`, `updated_at`, and `portable`
  - Dedicated save endpoints at `/v1/saves/{save_id}` for deterministic download and upload
  - Save-specific config keys: `save_sync.enabled`, `save_sync.mode`, `save_sync.conflict_policy`, plus optional system filters
  - Save-specific state keys for checksums, last-sync lineage, and unresolved conflicts
  - Emulator save-path resolver interface for stable local save roots
- Cross-boundary implications:
  - Common schema and field names must freeze before server and CLI stories proceed in parallel.
  - Server upload semantics and index refresh behavior must remain aligned with the client lineage contract.
  - Documentation must land in the same work item as any contract or behavior change.

## Milestones
1. M1: Freeze the shared save-sync contract surface (schema, IDs, config keys, planner action kinds, and state keys) and document the agreed API/index shape.
2. M2: Deliver the read path for download-first save sync: server save indexing, server read endpoint, CLI config surface, and planner/state support for deterministic download planning.
3. M3: Deliver execution and rollout hardening: local save-path resolution, transfer execution, bidirectional upload/conflict handling, managed shortcut lifecycle sync, and operator-ready docs.

## Story Contracts

### STORY SAVE-SYNC-COMMON-01
- Type: COMMON
- Scope (explicit files/modules allowed): `src/gamehub_common/models.py`, `src/gamehub_common/ids.py`, `docs/index-schema.md`
- Goal: Define and freeze the shared save artifact schema and deterministic save ID contract.
- Acceptance Criteria (deterministic):
  - [ ] Save artifact models validate strict required fields, enums, and types for index payload consumption.
  - [ ] A deterministic `save_id` helper is added and documented using the canonical server-relative path only.
  - [ ] Field names and any index versioning expectations are documented in `docs/index-schema.md`.
- Non-Goals:
  - Server indexing or HTTP route implementation.
  - CLI planner or transfer execution changes.
- Tests Required (exact locations / names):
  - `tests/test_save_contracts.py`
- PR Title Template: `COMMON: freeze save-sync schema and save_id contract`
- Rollback Risk: Low

### STORY SAVE-SYNC-SERVER-01
- Type: SERVER
- Scope (explicit files/modules allowed): `src/gamehub_server/indexer.py`, `src/gamehub_server/index_repository.py`, `tests/test_indexer.py`
- Goal: Index the canonical server save layout and attach save artifacts to the index snapshot with stable metadata.
- Acceptance Criteria (deterministic):
  - [ ] Server indexing discovers save artifacts under the frozen canonical save layout and emits stable, ordered metadata.
  - [ ] Malformed save layout entries are rejected with actionable indexing errors.
  - [ ] Save artifacts bind to titles using strict canonical identifiers only.
- Non-Goals:
  - Save download/upload HTTP routes.
  - Client-side planner or state changes.
- Tests Required (exact locations / names):
  - `tests/test_indexer.py`
- PR Title Template: `SERVER: index canonical save artifacts in /v1/index`
- Rollback Risk: Medium

### STORY SAVE-SYNC-SERVER-02
- Type: SERVER
- Scope (explicit files/modules allowed): `src/gamehub_server/main.py`, `src/gamehub_server/index_repository.py`, `docs/server-api.md`, `tests/test_server_api.py`
- Goal: Add the dedicated save API surface for downloading saves and executing uploads for bidirectional sync.
- Acceptance Criteria (deterministic):
  - [ ] `GET /v1/saves/{save_id}` resolves IDs from the active index snapshot only and streams the matching save artifact.
  - [ ] Unknown IDs return `404` and traversal-style targets are rejected through ID-based lookup only.
  - [ ] `PUT /v1/saves/{save_id}` writes atomically, refreshes the snapshot, and returns refreshed `SaveSpec` metadata.
- Non-Goals:
  - Local save discovery or client upload execution.
  - Non-save API refactors.
- Tests Required (exact locations / names):
  - `tests/test_server_api.py`
- PR Title Template: `SERVER: add save download/upload API contract`
- Rollback Risk: Medium

### STORY SAVE-SYNC-CLI-01
- Type: CLI
- Scope (explicit files/modules allowed): `src/gamehub_cli/common/config.py`, `src/gamehub_cli/main.py`, `docs/config-and-state.md`, `docs/cli-sync.md`, `tests/test_cli_config_state.py`
- Goal: Expose save-sync configuration and CLI wiring with safe defaults and deterministic user-facing knobs.
- Acceptance Criteria (deterministic):
  - [ ] Config parsing supports `save_sync.enabled`, `save_sync.mode`, `save_sync.conflict_policy`, and any frozen system filter keys with backward-compatible defaults.
  - [ ] Default rollout behavior keeps save sync disabled unless explicitly enabled.
  - [ ] `gamehub sync --dry-run` can surface save-sync planning output once save planning is available.
- Non-Goals:
  - Save action planning logic.
  - Save transfer execution.
- Tests Required (exact locations / names):
  - `tests/test_cli_config_state.py`
- PR Title Template: `CLI: add save-sync config surface and safe defaults`
- Rollback Risk: Low

### STORY SAVE-SYNC-CLI-02
- Type: CLI
- Scope (explicit files/modules allowed): `src/gamehub_cli/sync/planner.py`, `src/gamehub_cli/sync/state.py`, `docs/config-and-state.md`, `tests/test_planner.py`, `tests/test_cli_config_state.py`
- Goal: Extend the planner and state tracking to classify save actions and persist save lineage deterministically.
- Acceptance Criteria (deterministic):
  - [ ] Planner classifies each save as `download`, `upload`, `conflict`, or `skip` using the frozen decision inputs and policy rules.
  - [ ] `state.json` loads missing save keys as empty defaults and persists save checksums plus last-sync lineage metadata.
  - [ ] Dry-run planning emits deterministic reasons for each save decision path.
- Non-Goals:
  - Network transfer execution.
  - Emulator-specific path discovery.
- Tests Required (exact locations / names):
  - `tests/test_planner.py`
  - `tests/test_cli_config_state.py`
- PR Title Template: `CLI: add deterministic save planning and state lineage`
- Rollback Risk: Medium

### STORY SAVE-SYNC-CLI-03
- Type: CLI
- Scope (explicit files/modules allowed): `src/gamehub_cli/sync/orchestrator.py`, `src/gamehub_cli/sync/save_stage.py`, `src/gamehub_cli/sync/transfer.py`, `tests/test_sync.py`, `tests/test_downloads.py`
- Goal: Execute planned save transfers in a dedicated sync stage with atomic writes, dry-run safety, clear error isolation, and managed shortcut session upload support.
- Acceptance Criteria (deterministic):
  - [ ] Dry-run performs zero save writes while reporting planned save actions.
  - [ ] Non-dry runs stream save transfers through temporary files and commit with atomic rename semantics.
  - [ ] Bidirectional mode executes real uploads and clears or records conflict state deterministically.
  - [ ] State updates happen only after successful save writes, and partial failures do not corrupt existing save files.
- Non-Goals:
  - Save path discovery rules for specific emulators.
  - Changes to ROM transfer behavior outside the save stage.
- Tests Required (exact locations / names):
  - `tests/test_sync.py`
  - `tests/test_downloads.py`
- PR Title Template: `CLI: add atomic save transfer stage`
- Rollback Risk: Medium

### STORY SAVE-SYNC-CLI-04
- Type: CLI
- Scope (explicit files/modules allowed): `src/gamehub_cli/emulators/`, `src/gamehub_cli/common/paths.py`, `tests/test_emulators.py`, `tests/test_paths.py`
- Goal: Isolate local save-path resolution per emulator/platform behind a stable resolver surface used by save planning, execution, and managed shortcut launches.
- Acceptance Criteria (deterministic):
  - [ ] Supported emulator/system combinations resolve stable local save roots through a dedicated resolver interface.
  - [ ] Save planning targets emulator-native save destinations instead of writing under `<gamehub_dir>/saves`.
  - [ ] Platform-specific branches remain isolated and fail open when the expected runtime path is unavailable.
  - [ ] Path normalization remains deterministic across native Windows and Linux test runs.
- Non-Goals:
  - Sync planner policy changes.
  - Server-side save indexing or API changes.
- Tests Required (exact locations / names):
  - `tests/test_emulators.py`
  - `tests/test_paths.py`
- PR Title Template: `CLI: add emulator save-path resolvers`
- Rollback Risk: Medium

### STORY SAVE-SYNC-DOCS-01
- Type: DOCS
- Scope (explicit files/modules allowed): `docs/index-schema.md`, `docs/server-api.md`, `docs/config-and-state.md`, `docs/cli-sync.md`, `docs/release-notes-template.md`
- Goal: Publish operator-ready documentation for save-sync schema, API behavior, rollout defaults, dry-run interpretation, and conflict handling.
- Acceptance Criteria (deterministic):
  - [ ] Docs describe the frozen save schema, endpoint behavior, config keys, and state semantics accurately.
  - [ ] Docs cover rollout defaults, dry-run output expectations, and conflict-handling behavior for both download-only and bidirectional modes.
  - [ ] Release-note guidance calls out the disabled-by-default rollout and any migration implications.
- Non-Goals:
  - Runtime code changes.
  - New planning artifacts outside this plan.
- Tests Required (exact locations / names):
  - `docs/cli-sync.md` copy/paste command review
  - `docs/config-and-state.md` copy/paste command review
- PR Title Template: `DOCS: publish save-sync rollout and contract guide`
- Rollback Risk: Low

## Parallelization Notes
- Lane assignment:
  - Server lane stories: `SAVE-SYNC-SERVER-01`, `SAVE-SYNC-SERVER-02`
  - CLI lane stories: `SAVE-SYNC-CLI-01`, `SAVE-SYNC-CLI-02`, `SAVE-SYNC-CLI-03`, `SAVE-SYNC-CLI-04`
  - Common lane stories: `SAVE-SYNC-COMMON-01`
  - Docs lane stories: `SAVE-SYNC-DOCS-01`
- Conflict-avoidance notes:
  - `SAVE-SYNC-COMMON-01` freezes schema and field names before parallel server/CLI work starts.
  - Keep each story inside its declared scope and avoid opportunistic edits to adjacent modules.
  - Treat shared docs as owned by the story that declares them to avoid multi-lane overlap.
  - Freeze endpoint method, planner action constants, and state key names before any bidirectional work begins.
- Merge order constraints:
  - Merge `SAVE-SYNC-COMMON-01` first.
  - `SAVE-SYNC-SERVER-01` and `SAVE-SYNC-CLI-01` can start after M1 contract freeze.
  - `SAVE-SYNC-SERVER-02` depends on `SAVE-SYNC-SERVER-01`.
  - `SAVE-SYNC-CLI-02` depends on `SAVE-SYNC-COMMON-01` and the config keys from `SAVE-SYNC-CLI-01`.
  - `SAVE-SYNC-CLI-03` depends on `SAVE-SYNC-CLI-02`.
  - `SAVE-SYNC-CLI-04` can run in parallel with `SAVE-SYNC-CLI-02` if the resolver interface is frozen first.
  - `SAVE-SYNC-DOCS-01` lands after runtime contracts are stable.

## Completion Criteria
- All milestone acceptance criteria are complete.
- Story contracts are implemented in scoped PRs.
- Required tests are added/updated and documented.
- Documentation updates are complete and implementation-accurate.
- Save sync behavior is deterministic and idempotent in both dry-run and non-dry-run flows.
- Conflict handling and rollout defaults are explicitly documented and reproducible.
