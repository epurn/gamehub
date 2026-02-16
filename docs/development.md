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
- `apps/cli/gamehub_cli/sync.py`: orchestration only.
- `apps/cli/gamehub_cli/sync_index.py`: index fetch/retry policy.
- `apps/cli/gamehub_cli/sync_transfer_stage.py`: download/bootstrap plan application.
- `apps/cli/gamehub_cli/sync_artwork_stage.py`: SGDB artwork assignment/download logic.
- `apps/cli/gamehub_cli/sync_steam_stage.py`: Steam lifecycle + shortcuts/collections apply stage.
- `apps/cli/gamehub_cli/emulators.py`: compatibility facade and public entrypoint.
- `apps/cli/gamehub_cli/emulator_resolution.py`: emulator executable discovery/resolution.
- `apps/cli/gamehub_cli/emulator_install.py`: install backend selection/execution.
- `apps/cli/gamehub_cli/firmware_deploy.py`: firmware deployment orchestration.
- `apps/cli/gamehub_cli/firmware_targets.py`: emulator-specific firmware target discovery.
- `apps/cli/gamehub_cli/pcsx2_ini.py`: PCSX2 INI read/update/controller bootstrap logic.
- `apps/cli/gamehub_cli/steam.py`: compatibility facade + shared dataclasses/constants.
- `apps/cli/gamehub_cli/steam_lifecycle.py`, `apps/cli/gamehub_cli/steam_shortcuts.py`, `apps/cli/gamehub_cli/steam_collections.py`, `apps/cli/gamehub_cli/steam_artwork.py`, `apps/cli/gamehub_cli/steam_io.py`: focused Steam responsibilities.

## Run tests
```powershell
.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider
```

## Run audit regression slices (local)
Use this before opening a PR that touches CLI portability, Steam integration, or config/env precedence logic.

```powershell
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_cli_config_state.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_server_api.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_paths.py tests/test_emulators.py tests/test_firmware_deploy.py tests/test_retroarch_cores.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_steam.py tests/test_steam_integration.py tests/test_sync.py
```

Runtime literal guard (must produce no output):

```powershell
git grep -n -i "bazzite" -- apps shared
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
