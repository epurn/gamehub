# Final Validation and Release Playbook

This is the single reference for the final pre-release test flow and publish flow.

Use this in order:
1. Windows validation
2. Linux validation
3. Real sync validation on Bazzite
4. GitHub release execution

## 0. Prerequisites

1. You are on the release candidate commit.
2. Server endpoint is reachable at `http://<SERVER_IP>:8000`.
3. Local venv exists at `venv/`.
4. Steam is installed on test hosts and you can launch it interactively.

## 1. Windows Final Validation

Run from repo root in PowerShell.
Use direct commands in the active shell (avoid nested `powershell -Command "..."` wrappers with complex quoting).

1. Optional cleanup for stale interrupted runs:
```powershell
Get-Process python,python3.13 -ErrorAction SilentlyContinue | Stop-Process -Force
```
2. Install/update dependencies:
```powershell
.\venv\Scripts\pip.exe install -e .[dev]
```
3. Full test suite:
```powershell
.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider
```
4. Audit-critical slices:
```powershell
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_cli_config_state.py tests/test_server_api.py tests/test_paths.py tests/test_emulators.py tests/test_firmware_deploy.py tests/test_retroarch_cores.py tests/test_steam.py tests/test_steam_integration.py tests/test_sync.py
```
5. Runtime literal and secret scan:
```powershell
.\venv\Scripts\python.exe scripts/audit_repo_readiness.py
```
6. Dependency checks:
```powershell
.\venv\Scripts\python.exe -m pip install pip-audit
.\venv\Scripts\python.exe -m pip_audit --progress-spinner off
.\venv\Scripts\python.exe -m pip list --outdated --format=columns
```
7. Build Windows executable:
```powershell
pyinstaller --noconfirm --clean packaging/windows/gamehub.spec
```
8. EXE smoke tests:
```powershell
.\dist\gamehub-windows-amd64/gamehub-windows-amd64.exe --help
.\dist\gamehub-windows-amd64/gamehub-windows-amd64.exe sync --help
.\dist\gamehub-windows-amd64/gamehub-windows-amd64.exe sync --dry-run --skip-steam
```
9. Create `config.windows.toml` for real sync:
Start from template [docs/templates/config.windows.template.toml](templates/config.windows.template.toml), then fill in your values.

```toml
[server]
url = "http://<SERVER_IP>:8000"

[paths]
gamehub_dir = "D:/GameHub"

[steam]
userdata_dir = "C:/Program Files (x86)/Steam/userdata"
# steam_id = "7656119..."  # optional but recommended
steam_exe = "C:/Program Files (x86)/Steam/steam.exe"
```
10. Optional SGDB key (env-first):
```powershell
$env:GAMEHUB_SGDB_API_KEY="<YOUR_KEY>"
```
11. Confirm server index reachable:
```powershell
.\venv\Scripts\python.exe -c "import httpx;print(httpx.get('http://<SERVER_IP>:8000/v1/index',timeout=15).status_code)"
```
12. Dry-run real profile sync:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --dry-run --verbose --require-steam-closed
```
13. Real sync:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --verbose --require-steam-closed
```
14. Real sync second pass (idempotency):
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --verbose --require-steam-closed
```
15. Manual Steam verification:
- Shortcuts exist.
- Collections exist by exact system name.
- Artwork appears.
- A sample title launches.
- If `N3DS` titles are in index, verify `%APPDATA%\\Azahar\\config\\qt-config.ini` contains `fullscreen=true`.

## 2. Linux Final Validation (Ubuntu/Fedora host)

1. Create/refresh venv and deps:
```bash
python3 -m venv venv
./venv/bin/python -m pip install -e .[dev]
```
2. Full test suite:
```bash
./venv/bin/python -m pytest . -p no:cacheprovider
```
3. Audit-critical slices:
```bash
./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_cli_config_state.py tests/test_server_api.py tests/test_paths.py tests/test_emulators.py tests/test_firmware_deploy.py tests/test_retroarch_cores.py tests/test_steam.py tests/test_steam_integration.py tests/test_sync.py
```
4. Build Linux wheel and smoke with pip:
```bash
./venv/bin/python -m pip install build
./venv/bin/python -m build --wheel
python3 -m pip install --user --force-reinstall dist/*.whl
gamehub --help
gamehub sync --help
gamehub sync --dry-run --skip-steam
```
5. Server deploy checks:
```bash
docker compose -f docker/compose.yaml --env-file .env.production config
docker build -f apps/server/Dockerfile .
```

## 3. Bazzite Real Sync Validation

Run on Bazzite in an interactive desktop session.

1. Install wheel candidate:
```bash
python3 -m pip install --user --force-reinstall dist/*.whl
```
2. Create `config.bazzite.toml`:
Start from template [docs/templates/config.bazzite.template.toml](templates/config.bazzite.template.toml), then adjust `paths.gamehub_dir`, `steam.userdata_dir`, and `[linux]` backend if needed.

```toml
[server]
url = "http://<SERVER_IP>:8000"

[paths]
gamehub_dir = "/var/home/<user>/GameHub"

[steam]
userdata_dir = "/var/home/<user>/.var/app/com.valvesoftware.Steam/.local/share/Steam/userdata"
# steam_id = "7656119..."  # optional but recommended

[linux]
emulator_install_backend = "flatpak"
flatpak_remote = "flathub"
```
3. Optional SGDB key:
```bash
export GAMEHUB_SGDB_API_KEY="<YOUR_KEY>"
```
4. Confirm server index reachable:
```bash
python3 -c "import httpx;print(httpx.get('http://<SERVER_IP>:8000/v1/index',timeout=15).status_code)"
```
5. Dry-run:
```bash
gamehub sync --config ./config.bazzite.toml --dry-run --verbose --require-steam-closed
```
6. Real sync:
```bash
gamehub sync --config ./config.bazzite.toml --verbose --require-steam-closed
```
7. Real sync second pass:
```bash
gamehub sync --config ./config.bazzite.toml --verbose --require-steam-closed
```
8. Manual Steam verification:
- Shortcuts exist.
- Collections exist by exact system name.
- Artwork appears.
- Sample titles launch through configured emulators.
- If `N3DS` titles are in index, verify `~/.var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini` contains `fullscreen=true`.

## 4. GitHub Release Execution

1. Commit release-ready changes:
```powershell
git add -A
git commit -m "v1 final hardening and release prep"
git push origin <branch>
```
2. Open PR to `main`.
3. Wait for required checks:
- `Audit Regression Gates`
4. Merge PR.
5. Ensure version in `pyproject.toml` is final; commit if needed and push `main`.
6. Create and push release tag:
```powershell
git checkout main
git pull
git tag vX.Y.Z
git push origin vX.Y.Z
```
7. In GitHub Actions, verify tag workflows complete:
- `Client Artifact Release`
- `Server Image Release`
8. In GitHub Releases, confirm artifacts:
- Linux wheel
- Windows executable
- `gamehub-server-deploy-vX.Y.Z.zip`
- `checksums.txt`
9. In GHCR, confirm image tags:
- `ghcr.io/<org>/gamehub-server:vX.Y.Z`
- `ghcr.io/<org>/gamehub-server:latest`
10. Publish release notes and record final gate decision.

## 5. Release Gate PASS Criteria

Release is `PASS` only when all of the following are true:
1. Windows and Linux full suites pass.
2. Audit slices pass.
3. Real sync succeeded on Windows and Bazzite (including second idempotency pass).
4. Manual Steam verification passed on both platforms.
5. GitHub release workflows and artifacts are complete.
