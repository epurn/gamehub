# v1.5.1 Manual Release Checklist

Use this after the automated gates pass.

Target time: about 1 to 2 hours.

This patch release reuses the broader `v1.5.0` validation flow, but the only intended behavior change is the Windows managed shortcut wrapper fix. If anything outside that scope looks different, fall back to the full checklist in [release-manual-checklist-v1.5.0.md](./release-manual-checklist-v1.5.0.md).

Full release flow still lives in [release-final-validation-playbook.md](./release-final-validation-playbook.md).

## Before manual testing

- [ ] Rebuild the wheel and Windows EXE after the version bump.
- [ ] Confirm rebuilt artifacts and server version metadata report `1.5.1`.
- [ ] Confirm release notes and deploy references use `v1.5.1`.

## 1. Windows Packaged Client

Budget: 35 to 50 minutes.

- [ ] Rebuild the Windows EXE after the version bump:
```powershell
.\venv\Scripts\pyinstaller.exe --noconfirm --clean packaging\windows\gamehub.spec
```
- [ ] Prepare `config.windows.toml` from [docs/templates/config.windows.template.toml](./templates/config.windows.template.toml).
- [ ] Run a dry-run sync:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --dry-run --verbose --require-steam-closed
```
- [ ] Run the first real sync so managed Steam shortcuts are rewritten from the packaged `v1.5.1` release:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --verbose --require-steam-closed
```
- [ ] Run shortcut structure validation:
```powershell
.\venv\Scripts\python.exe scripts\validate_steam_shortcuts.py --config .\config.windows.toml
```
- [ ] In Steam, launch at least two managed titles that previously failed with "missing game executable".
- [ ] Confirm each managed title launches through the wrapper, no Steam dialog reports a missing executable, and the emulator does not exit immediately after launch.
- [ ] Run a second real sync and confirm it remains effectively idempotent:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --verbose --require-steam-closed
```

## 2. Cross-Platform Smoke Carry-Forward

Budget: 20 to 30 minutes.

- [ ] Server smoke:
```powershell
.\scripts\verify_server_deploy.ps1 -BaseUrl "http://<SERVER_IP>:8000"
```
- [ ] macOS client smoke:
```bash
./venv/bin/python -m gamehub_cli.main --help
./venv/bin/python -m gamehub_cli.main sync --help
./venv/bin/python -m gamehub_cli.main sync --config ./config.macos.toml --dry-run --verbose --require-steam-closed
```
- [ ] Linux or Bazzite client smoke:
```bash
./venv/bin/python -m gamehub_cli.main --help
./venv/bin/python -m gamehub_cli.main sync --help
gamehub sync --config ./config.bazzite.toml --dry-run --verbose --require-steam-closed
```

## Pass Criteria

Call `v1.5.1` ready only if all of these are true:

- [ ] Rebuilt artifacts and metadata report `1.5.1`.
- [ ] Windows packaged sync rewrites managed shortcuts cleanly.
- [ ] Previously affected Windows managed titles launch without a "missing game executable" error.
- [ ] Previously affected Windows managed titles remain running instead of exiting immediately from the packaged wrapper path.
- [ ] Shortcut structure validation passes after the rewrite sync.
- [ ] Server smoke passed.
- [ ] macOS and Linux/Bazzite client smoke checks passed.
