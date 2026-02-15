# V1 Fix Backlog (Implementation-Ready)

## `server-index`

### FB-SRV-001 (from GH-AUD-001, `P1`)
- Goal: remove forced full index rebuild from every API read path.
- Files:
  - `apps/server/gamehub_server/main.py`
  - `apps/server/gamehub_server/indexer.py` (if refresh metadata needed)
  - `tests/test_server_api.py`
- Implementation:
  1. Extend `IndexRepository` with cached snapshot metadata (`loaded_at`, optional `source_mtime` hash).
  2. Change `/v1/index`, `/v1/files/{file_id}`, `/v1/assets/{asset_id}` to use cached load by default.
  3. Add explicit refresh mechanism:
     - default TTL-based refresh using env var (example: `GAMEHUB_INDEX_REFRESH_SECONDS`, default `0` = startup-only),
     - optional `?refresh=1` query param on `/v1/index` for manual refresh.
  4. Keep current strict behavior for missing files and invalid IDs.
- Acceptance criteria:
  - Repeated `/v1/index` calls do not invoke index rebuild unless TTL expired or refresh requested.
  - `/v1/files` and `/v1/assets` serve from current cached map.
  - Existing API semantics remain unchanged.
- Tests:
  - Add tests for cached hits, TTL refresh path, and manual refresh path.
  - Keep `tests/test_server_api.py` existing scenarios green.
- Docs:
  - `docs/server-api.md`, `docs/deployment-server.md`.

## `docs`

### FB-DOC-001 (from GH-AUD-002, `P1`)
- Goal: make production template defaults portable and explicit.
- Files:
  - `.env.production.template`
  - `docker/compose.yaml`
  - `docs/deployment-server.md`
  - `docs/runbook.md`
- Implementation:
  1. Replace host path default with a placeholder (no user-specific path semantics).
  2. Remove hardcoded `linux/amd64` from default compose path, or gate it behind explicit env override.
  3. Document architecture expectations and override examples.
- Acceptance criteria:
  - Template is platform-neutral out of the box.
  - Compose can run on standard x64/arm64 hosts without manual file edits (unless user intentionally pins platform).
- Tests:
  - Add CI/script step running `docker compose -f docker/compose.yaml --env-file .env.production.template config`.
- Docs:
  - Must include concrete examples for Windows/Linux path values.

### FB-DOC-002 (from GH-AUD-008, `P2`)
- Goal: enforce env-first secret handling in docs and release flow.
- Files:
  - `docs/config-and-state.md`
  - `docs/release-process.md`
- Implementation:
  1. Mark `sgdb.api_key` inline config usage as fallback only.
  2. Add release checklist step for secret scanning tracked files.
  3. Add key-rotation instruction for accidentally exposed tokens.
- Acceptance criteria:
  - Docs no longer encourage persistent plaintext secrets as primary path.

## `cli-linux`

### FB-LNX-001 (from GH-AUD-003, `P2`)
- Goal: eliminate duplicated Linux/Flatpak/path detection helpers.
- New module:
  - `apps/cli/gamehub_cli/platform_paths.py`
- Function move list:
  - Move from `apps/cli/gamehub_cli/firmware_deploy.py`:
    - `_linux_flatpak_retroarch_root`
    - `_linux_flatpak_pcsx2_root`
    - `_linux_flatpak_dolphin_root`
    - `_is_flatpak_command`
    - `_unique_paths`
    - `_parse_simple_kv_config`
    - `_retroarch_cfg_candidates`
  - Move/adapt from `apps/cli/gamehub_cli/retroarch_cores.py`:
    - `_linux_flatpak_retroarch_root` (dedupe)
    - `_retroarch_cfg_candidates` (dedupe)
    - `_parse_cfg` (use shared parser)
  - Replace local `apps/cli/gamehub_cli/sync.py:_is_flatpak_command` with shared helper.
- Ownership boundary:
  - `platform_paths.py` owns platform-specific path/candidate resolution primitives only.
  - Feature modules (`sync`, `firmware_deploy`, `retroarch_cores`) own behavior, not path heuristics.
- Acceptance criteria:
  - Single implementation for flatpak command matching and RetroArch cfg candidate discovery.
  - All callers import shared utilities; no duplicated helper variants remain.
- Tests:
  - New unit tests for shared path resolver behaviors on Linux/Windows branch logic.
  - Existing Linux tests remain green.

### FB-LNX-002 (from GH-AUD-005, `P2`)
- Goal: improve Ubuntu compatibility in Linux emulator auto-install.
- Files:
  - `apps/cli/gamehub_cli/emulators.py`
  - `tests/test_emulators.py`
  - `docs/cli-sync.md`
  - `docs/client-install.md`
- Implementation:
  1. Add `apt` backend (`apt-get install -y`) with sudo handling.
  2. Extend `auto` backend logic:
     - Fedora + `dnf` => dnf path
     - Debian/Ubuntu + `apt-get` => apt path
     - Else flatpak => flatpak path
     - Else configured command.
  3. Keep `command` and `none` behavior unchanged.
- Acceptance criteria:
  - Ubuntu path is supported without requiring manual command backend when apt is available.
- Tests:
  - Add/extend tests for Ubuntu dist-id + apt binary presence.

### FB-LNX-003 (from GH-AUD-007, `P2`)
- Goal: centralize env override resolution for Linux-related settings.
- Files:
  - `apps/cli/gamehub_cli/config.py`
  - `apps/cli/gamehub_cli/firmware_deploy.py`
  - `apps/cli/gamehub_cli/emulators.py`
  - `apps/cli/gamehub_cli/retroarch_cores.py`
  - `apps/cli/gamehub_cli/steam.py`
  - `tests/test_cli_config_state.py`
- Implementation:
  1. Expand `GamehubConfig`/`LinuxConfig` to include currently ad-hoc env-driven overrides.
  2. Remove direct `os.environ.get(...)` calls from feature modules where possible.
  3. Keep one exception list only for truly process-local runtime controls (if any).
- Acceptance criteria:
  - Precedence model is uniform and testable from config loader.
- Tests:
  - Add matrix tests validating CLI flag/config/env/default precedence per setting.

## `cli-steam`

### FB-STM-001 (from GH-AUD-006, `P2`)
- Goal: avoid no-op writes to Steam localconfig collections payload.
- Files:
  - `apps/cli/gamehub_cli/steam.py`
  - `tests/test_steam.py`
- Implementation:
  1. Compare existing serialized payload vs next payload before writing.
  2. Only call `_atomic_write_text` when material changes exist.
  3. Preserve current update counts and behavior for changed payloads.
- Acceptance criteria:
  - Collection no-op update path does not touch file mtime/content.
- Tests:
  - Add test asserting no write on unchanged collection state.

### FB-STM-002 (from GH-AUD-011, `P3`)
- Goal: split `steam.py` into responsibility-focused modules without behavior changes.
- New modules:
  - `apps/cli/gamehub_cli/steam_lifecycle.py`
  - `apps/cli/gamehub_cli/steam_shortcuts.py`
  - `apps/cli/gamehub_cli/steam_collections.py`
  - `apps/cli/gamehub_cli/steam_artwork.py`
  - `apps/cli/gamehub_cli/steam.py` (thin facade exports)
- Function move list:
  - `steam_lifecycle.py`:
    - `_run_process_best_effort`
    - `_candidate_userdata_dirs`
    - `steam_id64_from_userdata_id`
    - `_preferred_steam_id_candidates`
    - `discover_userdata_dir`
    - `discover_steam_id`
    - `build_context`
    - `is_steam_running`
    - `close_steam_best_effort`
    - `wait_for_steam_exit`
    - `_spawn_detached`
    - `_wait_for_steam_start`
    - `reopen_steam`
  - `steam_shortcuts.py`:
    - `_normalize_shortcuts_tags`
    - `_tags_to_vdf_map`
    - `_extract_tag_value`
    - `_normalize_launch_options`
    - `_emulator_family`
    - `_legacy_shortcut_matches`
    - `_extract_path_basenames`
    - `_pop_legacy_match`
    - `_is_managed_shortcut`
    - `_parse_shortcuts_table`
    - `_encode_shortcuts`
    - `_compute_shortcut_app_id`
    - `_canonical_unsigned_app_id`
    - `_canonical_signed_app_id_from_unsigned`
    - `_extract_persisted_app_id`
    - `_build_shortcut_entry`
    - `upsert_shortcuts`
  - `steam_collections.py`:
    - `_find_key_path`
    - `_resolve_path`
    - `_set_path`
    - `_decode_user_collections`
    - `_load_localconfig`
    - `_dump_localconfig`
    - `_collection_id_for_system`
    - `_to_int_if_numeric`
    - `_load_cloudstorage_entries`
    - `_write_cloudstorage_entries`
    - `_next_cloudstorage_version`
    - `update_cloud_collections`
    - `update_collections`
  - `steam_artwork.py`:
    - `_unlink_best_effort`
    - `copy_grid_art`
    - `prune_grid_noncanonical_variants`
    - `backup_steam_configs`
    - `_atomic_write_bytes`
    - `_atomic_write_text` (if kept shared, move to small `steam_io.py` instead)
- Acceptance criteria:
  - Existing CLI behavior and tests remain unchanged.
  - `steam.py` only exports dataclasses/constants and re-exported public functions.

## `cli-config`

### FB-CFG-001 (from GH-AUD-004, `P2`)
- Goal: unify rel-path conversion helper.
- Files:
  - `apps/cli/gamehub_cli/paths.py` (new)
  - `apps/cli/gamehub_cli/planner.py`
  - `apps/cli/gamehub_cli/sync.py`
  - tests touching `_from_rel_path` logic
- Implementation:
  1. Add shared `from_rel_path(base: Path, rel_path: str) -> Path`.
  2. Replace local helper copies in planner/sync.
- Acceptance criteria:
  - No duplicated relative-path conversion helper remains in CLI modules.

### FB-CFG-002 (from GH-AUD-011, `P3`)
- Goal: split `sync.py`, `emulators.py`, and `firmware_deploy.py` into smaller units.
- Target module boundaries:
  - `sync.py` split:
    - `sync_index.py`: `_is_retryable_index_status`, `_is_retryable_index_fetch_error`, `_fetch_index_with_retries`
    - `sync_steam_stage.py`: `_resolve_steam_context`, `_build_shortcut_specs`, `_apply_steam_updates`
    - `sync_artwork_stage.py`: `_build_artwork_assignments`, `kinds_to_download`
    - `sync_transfer_stage.py`: `_print_plan`, `_apply_downloads`, `_bootstrap_firmware_dirs`
    - `sync.py`: `run_sync` orchestration only
  - `emulators.py` split:
    - `emulator_resolution.py`: resolution/detection functions
    - `emulator_install.py`: install backend implementations and orchestration
  - `firmware_deploy.py` split:
    - `firmware_targets.py`: target-dir resolution
    - `pcsx2_ini.py`: INI read/update/controller bootstrap
    - `firmware_deploy.py`: deployment orchestration
- Acceptance criteria:
  - Per-module LOC substantially reduced.
  - No behavior change and no public CLI/API changes.

## `tests`

### FB-TST-001 (from GH-AUD-009, `P3`)
- Goal: remove duplicated `_workspace_tempdir` definitions.
- Files:
  - `tests/conftest.py`
  - all `tests/test_*.py` using local `_workspace_tempdir`
- Implementation:
  1. Add shared fixture/helper in `tests/conftest.py`.
  2. Migrate tests to use shared helper.
  3. Keep cleanup behavior identical.
- Acceptance criteria:
  - One canonical tempdir helper used across tests.
  - Test runtime and pass-rate remain stable.

### FB-TST-002 (cross-cutting)
- Goal: add audit coverage gates.
- Implementation:
  - Add CI job slices for:
    - Linux portability behavior tests
    - config precedence tests
    - server refresh/caching tests once implemented
  - Add lightweight grep check ensuring runtime code contains no `bazzite` literals (tests may keep fixtures).
- Acceptance criteria:
  - Audit regressions are caught in CI before release cut.
