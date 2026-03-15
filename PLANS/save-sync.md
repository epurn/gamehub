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
- Windows and macOS local development support are required.
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
1. M1: Complete. Freeze the shared save-sync contract surface (schema, IDs, config keys, planner action kinds, and state keys) and document the agreed API/index shape.
2. M2: Complete. Deliver the read path for download-first save sync: server save indexing, server read endpoint, CLI config surface, and planner/state support for deterministic download planning.
3. M3: Complete. Deliver execution and rollout hardening: local save-path resolution, transfer execution, bidirectional upload/conflict handling, managed shortcut lifecycle sync, and operator-ready docs.
4. M4: Complete. Add smart save resolution so reconnect does not overwrite a newer local save after an offline or unreachable launch-session upload miss.

## Story Contracts
### Completed Stories
- `SAVE-SYNC-COMMON-01`: Complete
- `SAVE-SYNC-SERVER-01`: Complete
- `SAVE-SYNC-SERVER-02`: Complete
- `SAVE-SYNC-CLI-01`: Complete
- `SAVE-SYNC-CLI-02`: Complete
- `SAVE-SYNC-CLI-03`: Complete
- `SAVE-SYNC-CLI-04`: Complete
- `SAVE-SYNC-CLI-05`: Complete
- `SAVE-SYNC-DOCS-01`: Complete

### STORY SAVE-SYNC-CLI-05
- Type: CLI
- Status: Complete
- Scope (explicit files/modules allowed): `src/gamehub_cli/sync/planner.py`, `src/gamehub_cli/sync/state.py`, `src/gamehub_cli/shortcuts/shortcut_launch.py`, `docs/config-and-state.md`, `docs/cli-sync.md`, `tests/test_planner.py`, `tests/test_shortcut_launch.py`, `tests/test_sync.py`
- Goal: Add smart save resolution so a missed upload during an offline or unreachable launch-session does not cause the next reconnect to overwrite a newer local save with an older remote copy.
- Acceptance Criteria (deterministic):
  - [x] When a managed launch cannot contact the server for a needed upload, GAMEHUB persists enough deterministic local observation data to recognize that the local save may be newer on the next connected run.
  - [x] On the next successful reconnect, planner resolution compares the current local save timestamp against the indexed remote `updated_at` timestamp and chooses the newer side deterministically.
  - [x] A newer local save becomes `upload_existing`/`upload_new` and is not overwritten by an older remote save just because the previous upload was missed.
  - [x] A newer remote save still downloads and overwrites an older local save, preserving server-to-client convergence when the server copy is actually newer.
  - [x] If timestamps are missing, unreadable, or tied after normalization, GAMEHUB falls back to the existing conflict-safe path instead of guessing.
- Non-Goals:
  - Server API changes.
  - Fuzzy matching or non-deterministic merge behavior.
  - Save-state sync.
- Tests Required (exact locations / names):
  - `tests/test_planner.py`
  - `tests/test_shortcut_launch.py`
  - `tests/test_sync.py`
- PR Title Template: `CLI: add smart save resolution for missed offline uploads`
- Rollback Risk: Medium

## Parallelization Notes
- Lane assignment:
  - Completed server lane stories: `SAVE-SYNC-SERVER-01`, `SAVE-SYNC-SERVER-02`
  - Completed CLI lane stories: `SAVE-SYNC-CLI-01`, `SAVE-SYNC-CLI-02`, `SAVE-SYNC-CLI-03`, `SAVE-SYNC-CLI-04`, `SAVE-SYNC-CLI-05`
  - Completed common lane story: `SAVE-SYNC-COMMON-01`
  - Completed docs lane story: `SAVE-SYNC-DOCS-01`
- Conflict-avoidance notes:
  - Existing save-sync contracts are already frozen; future work should treat the missed-upload timestamp resolution as shipped behavior.
  - Keep the new story inside its declared scope and avoid opportunistic edits to adjacent modules.
  - Treat shared docs as owned by the active story that declares them to avoid multi-lane overlap.
- Merge order constraints:
  - none

## Completion Criteria
- M1-M4 are complete and documented.
- Required tests are added/updated and documented for the completed stories.
- Documentation updates remain implementation-accurate.
- Save sync behavior stays deterministic and idempotent in both dry-run and non-dry-run flows.
- Conflict handling and rollout defaults remain explicitly documented and reproducible.
