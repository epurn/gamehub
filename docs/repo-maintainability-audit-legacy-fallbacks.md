# Repo maintainability audit: legacy migration + fallback paths

## Scope

This audit targets legacy migration code paths and fallback branches that were introduced to preserve compatibility with older layouts/configs, plus paths created only by tests/experimentation.

Reviewed areas:
- Runtime packages under `src/gamehub_cli/` and `src/gamehub_server/`
- Test fixtures/assertions under `tests/`
- Utility scripts under `scripts/`

## Findings

### 1) Config path and key compatibility branches are still active but legacy-heavy

**Code paths**
- `default_config_path()` checks three locations and keeps a legacy fallback at `platformdirs.user_config_dir("gamehub")/config.toml`.  
- `_resolve_paths()` supports both canonical `paths.gamehub_dir` and legacy keys (`paths.library_dir`, `paths.firmware_dir`, `paths.state_path`).  
- `load_config()` supports alias keys/env vars for ROM output (`paths.output_dir`, `GAMEHUB_OUTPUT_DIR`) in addition to `paths.roms_dir` and `GAMEHUB_ROMS_DIR`.

**Why it exists**
- These paths are migration shims for older branch/state layouts and older config templates.

**Evidence in tests**
- `tests/test_cli_config_state.py` explicitly validates legacy config path fallback and legacy key/alias support.

**Maintainability risk**
- Medium: these branches increase config-resolution complexity and code paths to test.

**Recommendation**
- Keep for now, but mark with a deprecation window in docs and remove after one minor release that emits migration warnings.

---

### 2) ROM destination resolver has a compatibility exception path likely never triggered in normal runtime

**Code path**
- `resolve_rom_destination()` wraps `from_rel_path(..., preferred_root="roms")` in `try/except TypeError` and falls back to calling a 2-arg `from_rel_path(library_dir, rel_path)`.

**Why it exists**
- Inline comment says it is for patched resolvers in tests/extensions that still use the old signature.

**Maintainability risk**
- Medium-high: this is effectively a compatibility shim for monkeypatch/extension behavior, not normal in-repo runtime flow.

**Recommendation**
- Prefer explicit adapter hook for extensions (or remove if extension contract is not official).
- If extension contract is not supported, drop the `TypeError` fallback and keep a strict signature.

---

### 3) Steam collections path migration is a one-time compatibility move

**Code path**
- `update_collections()` migrates `UserLocalConfigStore.user-collections` to `UserLocalConfigStore.WebStorage.user-collections`.

**Why it exists**
- Supports older/local layouts where GAMEHUB or previous logic wrote collections under a non-canonical key path.

**Evidence in tests**
- `tests/test_steam.py` includes migration coverage for older key placement and stale cloud keys cleanup.

**Maintainability risk**
- Low-medium: one-time migration branch, but safe and bounded.

**Recommendation**
- Keep until there is confidence that pre-migration installations are no longer in supported upgrade paths.

---

### 4) Steam shortcut legacy matching migrates unmanaged/older entries

**Code path**
- `shortcuts.py` includes `_legacy_shortcut_matches()` and `_pop_legacy_match()` to find older entries by title + executable family and migrate them into managed GAMEHUB entries.

**Why it exists**
- Allows seamless upgrades from pre-managed naming/launch-option variants.

**Evidence in tests**
- `tests/test_steam.py` has dedicated migration tests for launch-options changes and emulator family changes.

**Maintainability risk**
- Medium: matching heuristics are hard to reason about and can age poorly as launch templates evolve.

**Recommendation**
- Keep short-term; add telemetry/log counters for legacy migrations and remove when counters show near-zero usage.

---

### 5) Test-only and experimentation artifacts that intentionally model stale state

These are not runtime dead code, but they are intentionally creating old/stale paths to validate migration behavior:
- `tests/test_cli_config_state.py`: `legacy-config/gamehub/config.toml`, legacy path keys, output-dir aliases.
- `tests/test_paths.py`: fallback from canonical `roms/...` to legacy flat path.
- `tests/test_steam.py`: stale collection key (`user-collections.gamehub-old`), legacy shortcut payloads, older collection placement.
- `tests/test_artwork.py`: old cached artwork file naming (`grid-old.png`, etc.) used for replacement checks.

**Maintainability risk**
- Low: valuable regression coverage.

**Recommendation**
- Keep these tests; they are the strongest signal for safely removing production migration branches later.

## Likely low-value/cleanup candidates (follow-up PR candidates)

1. Remove `resolve_rom_destination()` TypeError fallback once extension compatibility is clarified.
2. Remove `orchestrator.httpx` compatibility export once tests are switched to dependency injection only.
3. Add explicit deprecation plan (docs + warning) for legacy config keys and `output_dir` aliases.
4. After deprecation window, remove one-time Steam migration branches that no longer have supported upgrade paths.

## Suggested phased cleanup plan

- **Phase 1 (now):** add deprecation logging + usage counters for legacy config/Steam migration branches.
- **Phase 2 (next minor):** retain behavior but print actionable migration warnings.
- **Phase 3 (following minor):** remove lowest-value shims first (`TypeError` resolver fallback, test-only compatibility exports), then prune legacy key-path migrations with release-note callouts.
