# PLAN: 1.4.0 branch hardening

## Summary
- Preserve the current 1.4.0 runtime and wire contracts while reducing module sprawl, duplicated contract literals, and architecture guard bypasses.
- Scope includes all branch-touched runtime, contract, test, script, and release-doc modules in `gamehub_common`, `gamehub_cli`, and `gamehub_server`.

## Main modules
- `src/gamehub_common/models.py`
- `src/gamehub_common/__init__.py`
- `src/gamehub_cli/common/*`
- `src/gamehub_cli/emulators/save_resolution.py`
- `src/gamehub_cli/shortcuts/*`
- `src/gamehub_cli/sync/steam_stage.py`
- `src/gamehub_server/main.py`
- `src/gamehub_server/indexer.py`
- `src/gamehub_server/index_repository.py`
- touched tests under `tests/`

## Execution notes
- Add named shared save contract aliases in `gamehub_common` and update CLI/server to consume them.
- Consolidate low-level CLI helpers in `gamehub_cli.common`.
- Split shortcut runtime into payload, runtime, and save-session modules while keeping `shortcut-launch` behavior stable.
- Split server save indexing and save API logic out of `main.py` and `indexer.py`.
- Tighten architecture tests to cover `shortcuts` and forbid repo-local dynamic import bypasses.
- Run the required repository quality gates with the repo-local `venv`.
