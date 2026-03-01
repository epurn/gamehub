# Save Sync Feature Plan (v1: Emulator Save Files)

## Status
- **Plan owner:** GAMEHUB core
- **Phase:** Design / PR1 planning artifact
- **Implementation intent:** Multi-PR parallelizable rollout
- **Scope decision:** **Ship emulator save files first** (battery saves, memory-card style saves, per-game save data). Defer emulator save states to a later phase.

## Why this scope first
Save files are the safest portability baseline across emulators, emulator versions, and host OSes. Save states are frequently tied to specific emulator/core builds and are easier to corrupt across machines. A save-file-first rollout gives users immediate value while preserving deterministic behavior and maintainability.

---

## Product goals
1. Seamless cross-device save continuity for managed GAMEHUB titles.
2. Deterministic, strict, schema-validated sync with no fuzzy matching.
3. Maintainable implementation that respects package boundaries and minimizes duplicated logic.
4. Safe mutation model: atomic writes, backups where needed, clear dry-run visibility.

## Non-goals (initial release)
- No generic cloud provider integration.
- No fuzzy title/save matching.
- No best-effort migration of unknown third-party save layouts.
- No save-state sync in the first release phase.

---

## Proposed user experience

### CLI/config behavior
- Save sync is **explicitly configurable** and initially defaults to safe behavior:
  - `save_sync.enabled = false` (default for initial release toggle)
  - `save_sync.mode = "download_only" | "bidirectional"`
  - `save_sync.conflict_policy = "newer_wins" | "prefer_local" | "prefer_server" | "manual"`
  - optional allow/deny system filters
- `gamehub sync --dry-run` shows save actions (download/upload/conflict/skip) with reasons.
- `--verbose` emits deterministic diagnostics for decision paths.

### Initial operational default recommendation
- Roll out with `enabled=false` by default in the first released build.
- Promote to `enabled=true` default only after telemetry/support confidence.

---

## Architecture fit (repo boundaries)

### Shared contracts (`src/gamehub_common/`)
- Add strict index model types for save artifacts (schema-first).
- Keep deterministic ID helpers in shared ID module.

### Server (`src/gamehub_server/`)
- Extend indexer to inventory server-side saves from canonical save layout.
- Add dedicated save endpoints (`/v1/saves/{save_id}`) separate from ROM endpoints.
- Preserve existing security posture (path traversal rejection, strict ID lookup from current index snapshot).

### CLI (`src/gamehub_cli/`)
- Keep orchestration in `sync/orchestrator.py`.
- Add focused save stage module(s) under `sync/` for planning/execution wiring.
- Keep emulator-specific save location logic isolated (resolver layer, not in orchestrator).
- Extend state tracking in `sync/state.py` with backward-compatible defaults.

### Docs and planning
- Update docs with exact schema/endpoints/config behavior in same implementation stories.
- Track execution slices in `kanban/stories` with explicit acceptance/test notes.

---

## Canonical data model proposal

### Index schema additions
Add `SaveArtifactSpec` and include saves in title payloads (or a top-level save list keyed by `title_id`; choose one and freeze contract before implementation):

- `save_id`: deterministic from canonical server-relative path + checksum
- `title_id`: owning title
- `system`: canonical system name
- `kind`: initially `"save_file"` (reserve `"save_state"` for future)
- `rel_path`: canonical relative server path
- `sha256`: lowercase hex
- `size_bytes`: integer
- `updated_at`: UTC timestamp from server file mtime normalization
- `portable`: bool (`true` in v1 scope)

### State file additions (`state.json`)
Add save-specific tracking with compatibility-safe defaults:

- `save_checksums`: `{save_id: sha256}`
- `save_last_sync`: `{save_id: <timestamp + direction metadata>}`
- `save_conflicts`: optional list/map for unresolved manual conflicts

Backward compatibility rule: missing keys in existing state files must load as empty defaults.

---

## Server-side design

### Canonical save layout (proposed)
- `/data/saves/<system>/<title>/...`
- Must be strict and deterministic; reject malformed/nonsensical entries during indexing with actionable errors.
- Keep matching strict to server canonical naming and title IDs (no fuzzy linkers).

### API surface
- `GET /v1/saves/{save_id}`: stream save payload.
- `PUT /v1/saves/{save_id}` (or `POST` variant): upload local-authoritative save artifact for bidirectional mode.
- Save endpoint behavior mirrors existing safety expectations:
  - index-backed ID resolution only
  - unknown IDs => 404
  - traversal-safe path resolution
  - atomic server writes for uploads

### Refresh and consistency
- Save IDs and metadata are part of `/v1/index` snapshot contract.
- Upload/write flows must define how index consistency is refreshed (e.g., invalidate/rebuild snapshot after accepted upload).

---

## Client-side design

### Planning
Planner compares server metadata, local files, and state lineage to classify each save into:
- `download`
- `upload` (bidirectional mode only)
- `conflict`
- `skip` (policy/system filter/disabled)

Decision inputs:
- content hash equality
- size mismatch
- normalized mtime/updated_at
- prior sync direction metadata
- conflict policy

### Execution
- Stream transfers via `*.part` + atomic rename (same pattern as ROM downloads).
- Preserve fail-open behavior by system/emulator: unavailable resolver path should not crash unrelated systems.
- Emit clear summary counts and conflict details.

### Emulator save path resolver strategy
Add a dedicated resolver surface that returns expected local save roots by `(system, emulator, platform, config)` and keeps platform special-casing isolated:
- RetroArch save directories
- PCSX2 memory-card / save locations
- Dolphin GC/Wii user paths
- Azahar/N3DS save locations where supported

This avoids spreading emulator-specific filesystem logic across planner/orchestrator.

---

## Conflict model (must be explicit)

### Recommended default in v1
- `download_only` mode default for first enablement phases.
- In `bidirectional`, default conflict policy `manual` or `newer_wins` (team decision required before code freeze).

### Manual conflict UX (minimum viable)
- Dry-run clearly marks conflicts and why.
- Non-dry sync with `manual` policy skips conflicting artifacts and reports exact next actions.
- Future enhancement can add explicit `gamehub save resolve ...` commands.

---

## Security and integrity requirements
- No path traversal in any save endpoint or local write target.
- All save writes are atomic; temporary files cleaned on failure where possible.
- Hash verification on transfer.
- Strict schema validation on index consumption (pydantic fail-fast).
- No fuzzy title binding.

---

## Observability and diagnostics
- Normal mode: concise progress + summary table for save operations.
- Verbose mode: deterministic reason strings for each planning decision (e.g., `hash_mismatch`, `server_newer`, `policy_manual_skip`).
- Keep low-level helpers free from ad-hoc prints; route through existing sync logging style.

---

## Parallel implementation plan (story slices)

> Goal: maximize parallel throughput with minimal merge conflicts.

### Story 1 — Shared schema + IDs
**Goal**
- Add save schema models and deterministic ID helper(s).

**Acceptance Criteria**
- Shared models validate save metadata strictly.
- Index versioning decision documented and enforced.
- Existing consumers fail fast with actionable errors when shape mismatches.

**Implementation Notes**
- Files: `src/gamehub_common/models.py`, `src/gamehub_common/ids.py`, `docs/index-schema.md`.

**Test Notes**
- Model validation positives/negatives.
- Deterministic ID stability tests.

---

### Story 2 — Server indexer save inventory
**Goal**
- Index canonical server save layout and bind save artifacts to titles.

**Acceptance Criteria**
- Save artifacts appear in `/v1/index` with stable metadata.
- Malformed save layout yields actionable index errors.

**Implementation Notes**
- Files: `src/gamehub_server/indexer.py`, server fixtures/tests.

**Test Notes**
- Valid layout indexing.
- Invalid layout rejection.
- Deterministic ordering assertions.

---

### Story 3 — Server save endpoints
**Goal**
- Provide dedicated save download/upload HTTP API.

**Acceptance Criteria**
- GET/PUT (or GET/POST) endpoints work with strict ID resolution.
- Traversal attempts rejected.
- Unknown IDs return 404.

**Implementation Notes**
- Files: `src/gamehub_server/main.py`, `docs/server-api.md`, API tests.

**Test Notes**
- Route success/failure coverage.
- Upload write atomicity behavior.

---

### Story 4 — CLI config surface
**Goal**
- Add save-sync configuration and CLI exposure.

**Acceptance Criteria**
- Config TOML supports save sync block with sane defaults.
- CLI sync command respects enabled/mode/policy controls.

**Implementation Notes**
- Files: `src/gamehub_cli/common/config.py`, `src/gamehub_cli/main.py`, docs templates and `docs/config-and-state.md`, `docs/cli-sync.md`.

**Test Notes**
- Config parse fallback and override tests.
- CLI option wiring tests.

---

### Story 5 — Planner/state enhancements
**Goal**
- Compute save download/upload/conflict actions and persist lineage.

**Acceptance Criteria**
- Planner emits deterministic save action sets.
- State tracks save checksums and last direction metadata.
- Backward compatibility with existing `state.json` maintained.

**Implementation Notes**
- Files: `src/gamehub_cli/sync/planner.py`, `src/gamehub_cli/sync/state.py`, planner tests.

**Test Notes**
- Hash equal/no-op.
- Server newer -> download.
- Local newer -> upload.
- Conflict behavior per policy.

---

### Story 6 — Save execution stage
**Goal**
- Execute planned save transfers in dedicated stage wiring.

**Acceptance Criteria**
- Dry-run performs zero writes and prints planned actions.
- Non-dry run performs atomic writes and updates state.
- Errors are isolated and reported without corrupting files.

**Implementation Notes**
- Files: `src/gamehub_cli/sync/orchestrator.py`, new `src/gamehub_cli/sync/save_stage.py` (or similar), transfer helpers.

**Test Notes**
- Dry-run idempotency.
- Atomic transfer behavior.
- Partial-failure handling semantics.

---

### Story 7 — Emulator save path resolvers
**Goal**
- Encapsulate local save path discovery per emulator/platform.

**Acceptance Criteria**
- Resolver returns stable local targets for supported emulator/system combinations.
- Platform branches are isolated and fail-open.

**Implementation Notes**
- Files likely in `src/gamehub_cli/common/` or dedicated domain module, plus resolver tests.

**Test Notes**
- Linux/Windows normalization assertions.
- Missing-path behavior assertions.

---

### Story 8 — Documentation + rollout guide
**Goal**
- Publish operator-ready docs for save sync behavior and rollout.

**Acceptance Criteria**
- Docs cover schema, API, config, dry-run interpretation, and conflict handling.
- Release notes include migration/default behavior callouts.

**Implementation Notes**
- Files: `docs/index-schema.md`, `docs/server-api.md`, `docs/config-and-state.md`, `docs/cli-sync.md`, release notes template as needed.

**Test Notes**
- Copy/paste command sanity checks in docs.

---

## Interface freeze checklist (for parallel implementation)
Before stories start in parallel, freeze these contracts:
1. index field names (`save_id`, `kind`, `updated_at`, etc.)
2. endpoint names/methods (`GET/PUT /v1/saves/{save_id}`)
3. conflict policy enum values
4. planner action kind constants
5. state file key names

Any change to frozen contract requires an explicit mini-RFC note in `kanban/notes/`.

---

## Rollout phases

### Phase 0 (this PR)
- Planning artifact only (this file).

### Phase 1
- Schema + server read-only support (`GET` endpoint, download-only client planning).

### Phase 2
- Local save resolver + download execution + state tracking.

### Phase 3
- Bidirectional uploads + conflict policies.

### Phase 4
- Hardening, doc polish, release guard checks, optional enable-by-default decision.

---

## Definition of done for save-sync GA
- All acceptance criteria across stories are complete.
- Cross-platform tests updated and passing in CI.
- Docs updated and accurate.
- Dry-run and non-dry paths both deterministic and idempotent.
- Conflict handling behavior explicitly documented and reproducible.

---

## Open decisions requiring team sign-off
1. Final canonical server save layout details (`<title>` keying rules, nested allowances).
2. Index version bump strategy and compatibility window.
3. Default conflict policy for first bidirectional release.
4. Upload endpoint method (`PUT` vs `POST`) and snapshot refresh semantics.
5. Whether manual conflict resolution commands are required pre-GA or can ship post-GA.

---

## Suggested follow-up implementation order
1. Story 1 (schema/IDs)
2. Stories 2 + 3 (server inventory + API)
3. Story 4 (config controls)
4. Story 5 (planner/state)
5. Stories 6 + 7 (execution + resolver abstraction)
6. Story 8 (docs hardening)

This order minimizes churn while unlocking parallel workstreams after contract freeze.
