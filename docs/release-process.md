# Release Process

Detailed end-to-end validation and publishing steps are in:
- [release-final-validation-playbook.md](release-final-validation-playbook.md)

## Versioning
- Use semantic versioning (`MAJOR.MINOR.PATCH`).
- Tag format: `vX.Y.Z`.

## Release Checklist
1. Ensure tests pass:
```powershell
.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider
```
2. Run audit regression slices:
```powershell
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_cli_config_state.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_server_api.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_architecture.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_paths.py tests/test_emulators.py tests/test_firmware_deploy.py tests/test_retroarch_cores.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_controller_detection.py tests/test_controller_profiles.py tests/test_controller_apply.py tests/test_shortcut_launch.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_steam.py tests/test_steam_integration.py
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_downloads.py tests/test_planner.py tests/test_sync.py
```
3. Run dependency audit/update checks:
```powershell
.\venv\Scripts\python.exe -m pip install pip-audit
.\venv\Scripts\python.exe -m pip_audit --progress-spinner off
.\venv\Scripts\python.exe -m pip list --outdated --format=columns
```
4. Run local readiness audit (docs cohesion + secret leak scan + runtime literal guard):
```powershell
.\venv\Scripts\python.exe scripts/audit_repo_readiness.py
```
5. Bump version in `pyproject.toml`.
6. Update release notes/changelog.
7. Create and push tag:
```powershell
git tag vX.Y.Z
git push origin vX.Y.Z
```
8. Verify GitHub Actions:
   - audit regression gates workflow
   - targeted regression matrix workflow
   - server image release workflow
   - client artifact release workflow
9. Validate artifacts:
   - server image on GHCR
   - Linux wheel on GitHub Release
   - Windows EXE on GitHub Release
   - server deploy bundle zip on GitHub Release
   - checksums file
10. Run post-release smoke checks:
   - deploy server and run `scripts/verify_server_deploy.ps1`
   - run client `--help` and `sync --dry-run`

## Secret Rotation
- If a token is exposed in any tracked history, rotate it immediately at the provider and replace local config with a new value.
- For SGDB specifically, generate a new key and reconfigure `GAMEHUB_SGDB_API_KEY` in runtime environment.

## Artifact Naming
- Server image: `ghcr.io/<org>/gamehub-server:vX.Y.Z`
- Linux wheel: `gamehub-<version>-py3-none-any.whl`
- Windows executable: `gamehub-windows-amd64.exe`
- Server deploy bundle: `gamehub-server-deploy-vX.Y.Z.zip`
- Checksums: `checksums.txt`

## Server Release Channel
- Server is released via GHCR image tags (`ghcr.io/<org>/gamehub-server:<tag>`).
- GitHub Release assets include client artifacts, checksums, and an optional deploy bundle zip (compose/env template/docs/scripts).

## Known Scope Limits (Current Phase)
- Architecture: `amd64` only
- Deployment: LAN-only/no auth

