# Repo maintainability audit: legacy migration + fallback paths

Historical note:
- This document records one cleanup checkpoint.
- Current behavior and ownership live in [architecture.md](architecture.md), [cli-sync.md](cli-sync.md), and [config-and-state.md](config-and-state.md).
- Module-path references below are historical examples and may have moved as the codebase was split into smaller modules.

## Scope

This audit tracks status for compatibility branches that previously carried legacy config, path, and Steam migration behavior.

Reviewed areas:
- Runtime packages under `src/gamehub_cli/` and `src/gamehub_server/`
- Test fixtures/assertions under `tests/`
- Utility/docs updates under `docs/`

## Status summary

### Removed now: config compatibility branches

**Runtime changes**
- `default_config_path()` no longer checks `platformdirs.user_config_dir("gamehub")/config.toml`.
- `_resolve_paths()` now accepts only canonical `paths.gamehub_dir`.
- `load_config()` no longer accepts `paths.output_dir` or `GAMEHUB_OUTPUT_DIR` aliases.
- Removed keys/env aliases now fail fast with actionable `ValueError` messages.

**Test/doc changes**
- Legacy path/alias support tests were replaced with strict rejection tests.
- Config docs now describe only canonical keys and config resolution paths.

---

### Removed now: ROM destination compatibility fallbacks

**Runtime changes**
- `from_rel_path(..., preferred_root="roms")` no longer falls back to legacy existing flat paths.
- `resolve_rom_destination()` no longer swallows `TypeError` for old patched signatures.

**Test/doc changes**
- Path tests now assert strict canonical ROM destination behavior.

---

### Removed now: Steam legacy migration/adoption branches

**Runtime changes**
- `shortcuts.py` no longer adopts unmanaged legacy shortcuts via heuristic matching.
- `collections.py` no longer migrates `UserLocalConfigStore.user-collections` into `.../WebStorage/user-collections`.
- Collections parsing/writing is now canonical-path oriented.

**Test/doc changes**
- Legacy shortcut migration tests were replaced with strict no-adoption assertions.
- Collections tests now verify canonical-only behavior and no legacy key-path migration.
- Steam integration docs no longer claim unmanaged legacy adoption.

---

### Removed now: test-only orchestrator httpx compatibility export

**Runtime changes**
- `sync/orchestrator.py` no longer exports `httpx = sync_index.httpx`.
- Index fetch now uses `sync_index.httpx` directly.

**Test/doc changes**
- Sync tests patch `gamehub_cli.sync.index.httpx` directly.

## Remaining optional cleanup candidates

- None currently tracked.
