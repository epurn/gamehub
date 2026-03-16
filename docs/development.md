# Development

## Environment
- Python: 3.12+
- Required local virtual environment: `venv/`

## First-time setup (macOS/Linux)
```bash
python3 -m venv venv
./venv/bin/python -m pip install -e .[dev]
```

## First-time setup (Windows PowerShell)
```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -e .[dev]
```

## Run server
macOS/Linux:
```bash
./venv/bin/gamehub-server
```

Windows PowerShell:
```powershell
.\venv\Scripts\gamehub-server.exe
```

Development-only broad bind examples:

```bash
./venv/bin/python -m uvicorn gamehub_server.main:app --host 0.0.0.0 --port 8000
```

```powershell
.\venv\Scripts\python.exe -m uvicorn gamehub_server.main:app --host 0.0.0.0 --port 8000
```

Use `0.0.0.0` only when you intentionally want a development server reachable beyond the local host. Do not treat this direct-run shape as production; move to the hardened Compose deployment with [dev-to-prod-server-migration.md](./dev-to-prod-server-migration.md).

## Run CLI
macOS/Linux:
```bash
./venv/bin/python -m gamehub_cli.main init --dry-run
./venv/bin/python -m gamehub_cli.main sync --dry-run
```

Windows PowerShell:
```powershell
.\venv\Scripts\python.exe -m gamehub_cli.main init --dry-run
.\venv\Scripts\python.exe -m gamehub_cli.main sync --dry-run
```

## CLI module boundaries
- `src/gamehub_cli/common/config.py`: config schema + TOML/env resolution.
- `src/gamehub_cli/common/config_edit.py`: shared key-value config editing primitives (simple cfg + QSettings).
- `src/gamehub_cli/sync/orchestrator.py`: orchestration and dependency wiring only.
- `src/gamehub_cli/sync/index.py`: index fetch/retry policy.
- `src/gamehub_cli/sync/planner.py`: index/state diff and action planning.
- `src/gamehub_cli/sync/diagnostics.py`: doctor/audit helpers built on sync planning.
- `src/gamehub_cli/sync/state.py`: persisted sync-state load/save/mark helpers.
- `src/gamehub_cli/sync/downloads.py`: streamed atomic download primitive.
- `src/gamehub_cli/sync/artwork.py`: SteamGridDB client/pipeline/cache primitives.
- `src/gamehub_cli/sync/transfer_stage.py`: download/bootstrap plan application.
- `src/gamehub_cli/sync/artwork_stage.py`: SGDB artwork assignment/download logic.
- `src/gamehub_cli/sync/steam_stage.py`: Steam lifecycle + shortcuts/collections apply stage.
- `src/gamehub_cli/emulators/__init__.py`: public emulator exports.
- `src/gamehub_cli/emulators/resolution.py`: emulator executable discovery/resolution.
- `src/gamehub_cli/emulators/installer.py`: install orchestration only.
- `src/gamehub_cli/emulators/install_common.py`: shared install command/version/path helpers.
- `src/gamehub_cli/emulators/install_windows.py`: Windows installer backends (winget + bundled installer flows).
- `src/gamehub_cli/emulators/install_linux.py`: Linux package/backend install flows.
- `src/gamehub_cli/emulators/install_flatpak.py`: Flatpak backend helpers + install flow.
- `src/gamehub_cli/emulators/install_macos.py`: macOS official-asset and configured-command install flows.
- `src/gamehub_cli/firmware/deploy.py`: firmware deployment orchestration.
- `src/gamehub_cli/firmware/runtime_retroarch.py`: RetroArch runtime config/bootstrap.
- `src/gamehub_cli/firmware/runtime_pcsx2.py`: PCSX2 runtime config/bootstrap.
- `src/gamehub_cli/firmware/runtime_dolphin.py`: Dolphin runtime config/bootstrap.
- `src/gamehub_cli/firmware/runtime_azahar.py`: Azahar runtime config/bootstrap.
- `src/gamehub_cli/firmware/deploy_copy.py`: checksum/copy helpers for firmware deployment.
- `src/gamehub_cli/firmware/targets.py`: emulator-specific firmware target discovery.
- `src/gamehub_cli/firmware/pcsx2_ini.py`: PCSX2 INI read/update/controller bootstrap logic.
- `src/gamehub_cli/controllers/profiles.py`: bundled/user-overridden controller profile defaults and seeding.
- `src/gamehub_cli/controllers/detection.py`: launch-time controller detection and profile selection across Windows, Linux, and macOS.
- `src/gamehub_cli/controllers/apply.py`: controller profile orchestration entrypoints only.
- `src/gamehub_cli/controllers/apply_pcsx2.py`: PCSX2 profile application logic.
- `src/gamehub_cli/controllers/apply_dolphin.py`: Dolphin profile and device/hotkey application logic.
- `src/gamehub_cli/controllers/apply_azahar.py`: Azahar profile and SDL identity application logic.
- `src/gamehub_cli/controllers/sdl_guid.py`: SDL GUID discovery and normalization helpers.
- `src/gamehub_cli/controllers/apply_ini.py`: INI section parse/apply helpers used by controller apply modules.
- `src/gamehub_cli/common/shortcut_payload.py`: shared managed-shortcut payload codec and config-path resolution helpers.
- `src/gamehub_cli/shortcuts/shortcut_launch.py`: thin hidden wrapper entrypoint used by wrapped Steam shortcuts.
- `src/gamehub_cli/shortcuts/runtime.py`: launch-time controller/runtime and exit-hook behavior for managed shortcuts.
- `src/gamehub_cli/shortcuts/save_session.py`: launch-session save sync, metadata fetch, and managed memory-card handling.
- `src/gamehub_cli/steam/types.py`: Steam dataclasses/constants.
- `src/gamehub_cli/steam/lifecycle.py`, `src/gamehub_cli/steam/shortcuts.py`, `src/gamehub_cli/steam/collections.py`, `src/gamehub_cli/steam/artwork.py`, `src/gamehub_cli/steam/io.py`: focused Steam responsibilities.

Canonical internal patch/import targets:
- Steam lifecycle discovery hooks: `gamehub_cli.steam.lifecycle`.
- Firmware runtime hooks: `gamehub_cli.firmware.runtime_*` and `gamehub_cli.firmware.targets`.
- Controller runtime hooks: `gamehub_cli.controllers.apply_*` and `gamehub_cli.controllers.sdl_guid`.

## Run tests
macOS/Linux:
```bash
./venv/bin/python -m pytest . -p no:cacheprovider
```

Windows PowerShell:
```powershell
.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider
```

## Static checks
macOS/Linux:
```bash
./venv/bin/python -m ruff format --check .
./venv/bin/python -m ruff check .
./venv/bin/python -m mypy src
```

Windows PowerShell:
```powershell
.\venv\Scripts\python.exe -m ruff format --check .
.\venv\Scripts\python.exe -m ruff check .
.\venv\Scripts\python.exe -m mypy src
```

Typing note:
- `mypy` targets `src/` and enforces strict function annotation rules (`disallow_untyped_defs`, `disallow_incomplete_defs`, `check_untyped_defs`).
- `ignore_missing_imports = true` is enabled to avoid third-party stub churn.

## Run audit regression slices (local)
Use this before opening a PR that touches CLI portability, Steam integration, architecture boundaries, or config/env precedence logic.
CI is split into:
- `Audit Regression Gates` (quality/static + architecture + config/server slices + readiness audit, Linux).
- `Targeted Regression Matrix` (emulator/firmware + controllers + steam + sync slices, Linux/Windows/macOS).
To mirror CI exactly, run the emulator/controller/steam/sync slices on Windows, Linux, and macOS hosts.

macOS/Linux shell: replace each `.\venv\Scripts\python.exe` below with `./venv/bin/python`.

```powershell
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_cli_config_state.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_server_api.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_architecture.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_paths.py tests/test_emulators.py tests/test_firmware_deploy.py tests/test_retroarch_cores.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_controller_detection.py tests/test_controller_profiles.py tests/test_controller_apply.py tests/test_shortcut_runtime.py tests/test_shortcut_save_session.py tests/test_shortcut_orchestrator.py tests/test_shortcut_payload.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_steam.py tests/test_steam_integration.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_downloads.py tests/test_planner.py tests/test_sync.py
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

macOS/Linux:
```bash
GAMEHUB_DATA_DIR="$(pwd)/tests/fixtures/indexer_case" ./venv/bin/python -m uvicorn gamehub_server.main:app --host 127.0.0.1 --port 8011
```

Windows PowerShell:
```powershell
$env:GAMEHUB_DATA_DIR = (Resolve-Path 'tests/fixtures/indexer_case').Path
.\venv\Scripts\python.exe -m uvicorn gamehub_server.main:app --host 127.0.0.1 --port 8011
```

In another shell:

macOS/Linux:
```bash
./venv/bin/python -c "import httpx; r=httpx.get('http://127.0.0.1:8011/v1/index', timeout=5.0); print(r.status_code); print(r.json()['index_version']); print(len(r.json()['titles']))"
```

Windows PowerShell:
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
- `saves/<system>/<title_stem>/<kind>/<file...>`
