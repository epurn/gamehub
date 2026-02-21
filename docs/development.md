# Development

## Environment
- Python: 3.12+
- Required local virtual environment: `venv/`

## First-time setup (Windows PowerShell)
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
.\venv\Scripts\pip.exe install -e .[dev]
```

## Run server
```powershell
.\venv\Scripts\python.exe -m uvicorn gamehub_server.main:app --host 0.0.0.0 --port 8000
```

## Run CLI
```powershell
.\venv\Scripts\python.exe -m gamehub_cli.main sync --dry-run
```

## CLI module boundaries
- `src/gamehub_cli/common/config.py`: config schema + TOML/env resolution.
- `src/gamehub_cli/sync/orchestrator.py`: orchestration and dependency wiring only.
- `src/gamehub_cli/sync/index.py`: index fetch/retry policy.
- `src/gamehub_cli/sync/planner.py`: index/state diff and action planning.
- `src/gamehub_cli/sync/state.py`: persisted sync-state load/save/mark helpers.
- `src/gamehub_cli/sync/downloads.py`: streamed atomic download primitive.
- `src/gamehub_cli/sync/artwork.py`: SteamGridDB client/pipeline/cache primitives.
- `src/gamehub_cli/sync/transfer_stage.py`: download/bootstrap plan application.
- `src/gamehub_cli/sync/artwork_stage.py`: SGDB artwork assignment/download logic.
- `src/gamehub_cli/sync/steam_stage.py`: Steam lifecycle + shortcuts/collections apply stage.
- `src/gamehub_cli/emulators/__init__.py`: public emulator exports.
- `src/gamehub_cli/emulators/resolution.py`: emulator executable discovery/resolution.
- `src/gamehub_cli/emulators/installer.py`: install backend selection/execution.
- `src/gamehub_cli/firmware/deploy.py`: firmware deployment orchestration.
- `src/gamehub_cli/firmware/targets.py`: emulator-specific firmware target discovery.
- `src/gamehub_cli/firmware/pcsx2_ini.py`: PCSX2 INI read/update/controller bootstrap logic.
- `src/gamehub_cli/controllers/profiles.py`: bundled/user-overridden controller profile defaults and seeding.
- `src/gamehub_cli/controllers/detection.py`: Xbox controller detection (Linux `/proc` + Windows XInput).
- `src/gamehub_cli/controllers/apply.py`: managed-key profile application for PCSX2/Dolphin/Azahar.
- `src/gamehub_cli/controllers/launch.py`: hidden wrapper entrypoint used by wrapped Steam shortcuts.
- `src/gamehub_cli/steam/types.py`: Steam dataclasses/constants.
- `src/gamehub_cli/steam/lifecycle.py`, `src/gamehub_cli/steam/shortcuts.py`, `src/gamehub_cli/steam/collections.py`, `src/gamehub_cli/steam/artwork.py`, `src/gamehub_cli/steam/io.py`: focused Steam responsibilities.

## Run tests
```powershell
.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider
```

## Static checks
```powershell
.\venv\Scripts\python.exe -m ruff format --check src tests
.\venv\Scripts\python.exe -m ruff check src tests
.\venv\Scripts\python.exe -m mypy src
```

Typing note:
- `mypy` is configured with incremental strictness via `[[tool.mypy.overrides]]` in `pyproject.toml`.
- The old wildcard `ignore_errors` override was removed; strictness and temporary suppressions are now explicit per module pattern.

## Run audit regression slices (local)
Use this before opening a PR that touches CLI portability, Steam integration, or config/env precedence logic.

```powershell
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_cli_config_state.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_server_api.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_paths.py tests/test_emulators.py tests/test_firmware_deploy.py tests/test_retroarch_cores.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_steam.py tests/test_steam_integration.py tests/test_sync.py
```

Pre-public/local readiness audit:

```powershell
.\venv\Scripts\python.exe scripts/audit_repo_readiness.py
```

Dependency checks:

```powershell
.\venv\Scripts\python.exe -m pip install pip-audit
.\venv\Scripts\python.exe -m pip_audit --progress-spinner off
.\venv\Scripts\python.exe -m pip list --outdated --format=columns
```

## EPIC-001 smoke test (server index + file serving)
Use the fixture library to validate end-to-end API behavior quickly.

```powershell
$env:GAMEHUB_DATA_DIR = (Resolve-Path 'tests/fixtures/indexer_case').Path
.\venv\Scripts\python.exe -m uvicorn gamehub_server.main:app --host 127.0.0.1 --port 8011
```

In another PowerShell:

```powershell
.\venv\Scripts\python.exe -c "import httpx; r=httpx.get('http://127.0.0.1:8011/v1/index', timeout=5.0); print(r.status_code); print(r.json()['index_version']); print(len(r.json()['titles']))"
```

Expected output:
- `200`
- `1` (index version)
- `1` (fixture title count)

Fixture layout reminder:
- `roms/<system>/<title.ext>`
- `firmware/<system>/<filename>`
