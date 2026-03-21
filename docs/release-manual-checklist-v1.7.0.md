# Draft Manual Release Checklist for v1.7.0

Use this after the automated gates pass and after the `v1.7.0` release scope is frozen.

Target time: about 2 to 3 hours.

Keep compatible feature work batched under the current unreleased `v1.7.0` target instead of bumping versions for each in-progress feature. Before tagging, refresh this checklist and [release-notes-v1.7.0.md](./release-notes-v1.7.0.md) if the planned release scope expands.

This draft assumes the current `v1.7.0` focus remains `Azahar` control finalization, controller/runtime cleanup, and `config init` validation hardening. It reuses the broader deployment and cross-platform behavioral validation from [release-manual-checklist-v1.6.0.md](./release-manual-checklist-v1.6.0.md). If anything outside that client/control scope behaves differently, fall back to the full `v1.6.0` checklist before releasing.

Full release flow still lives in [release-final-validation-playbook.md](./release-final-validation-playbook.md).

## Before manual testing

- [ ] Rebuild the wheel and Windows EXE from the final `v1.7.0` release-candidate commit.
- [ ] Confirm rebuilt artifacts and server version metadata report `1.7.0`.
- [ ] Confirm release notes and deploy references use `v1.7.0`.
- [ ] Prepare the explicit client config files you will use for smoke (`config.windows.toml`, `config.macos.toml`, `config.bazzite.toml`, or equivalent).
- [ ] Keep a known-good managed `Azahar` title available on each host used for the release pass.

## 1. Windows Packaged Client

Budget: 35 to 50 minutes.

- [ ] Rebuild the Windows EXE after the version bump:
```powershell
.\venv\Scripts\pyinstaller.exe --noconfirm --clean packaging\windows\gamehub.spec
```
- [ ] Generate or refresh a release-candidate config:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe config init --output .\config.windows.toml
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe config verify --config .\config.windows.toml
```
- [ ] Confirm `config init` rejects an empty server URL override cleanly:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe config init --output .\throwaway-config.toml --server-url ""
```
- [ ] Run a dry-run sync:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --dry-run --verbose --require-steam-closed
```
- [ ] Run the first real sync so managed shortcuts and controller profiles are rewritten from the packaged `v1.7.0` release:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --verbose --require-steam-closed
```
- [ ] Run shortcut structure validation:
```powershell
.\venv\Scripts\python.exe scripts\validate_steam_shortcuts.py --config .\config.windows.toml
```
- [ ] Launch one managed `Azahar` title from Steam.
- [ ] Confirm `Esc` quits the managed session.
- [ ] Confirm `Start+Select` still exits cleanly through the Windows `shortcut-launch` exit hook.
- [ ] Confirm there is no pointer or mouse-simulation behavior required for the shipped `Azahar` path.
- [ ] Run a second real sync and confirm it remains effectively idempotent:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --verbose --require-steam-closed
```

## 2. macOS Client Carry-Forward

Budget: 30 to 40 minutes.

- [ ] Generate or refresh a release-candidate config:
```bash
./venv/bin/python -m gamehub_cli.main config init --output ./config.macos.toml
./venv/bin/python -m gamehub_cli.main config verify --config ./config.macos.toml
```
- [ ] Run a dry-run sync:
```bash
./venv/bin/python -m gamehub_cli.main sync --config ./config.macos.toml --dry-run --verbose --require-steam-closed
```
- [ ] Run the first real sync:
```bash
./venv/bin/python -m gamehub_cli.main sync --config ./config.macos.toml --verbose --require-steam-closed
```
- [ ] Run shortcut structure validation:
```bash
./venv/bin/python scripts/validate_steam_shortcuts.py --config ./config.macos.toml
```
- [ ] Launch one managed `Azahar` title from Steam.
- [ ] Confirm `Esc` quits the managed session.
- [ ] If the macOS `Azahar` exit hook is enabled, confirm `Start+Select` quits the newly launched session cleanly and that normal bundle/document launch behavior still works.
- [ ] Confirm there is no shipped mouse-bridge dependency or controller-to-pointer requirement in the `Azahar` release path.

## 3. Linux Or Bazzite Carry-Forward

Budget: 25 to 35 minutes.

- [ ] Generate or refresh a release-candidate config:
```bash
./venv/bin/python -m gamehub_cli.main config init --output ./config.bazzite.toml
./venv/bin/python -m gamehub_cli.main config verify --config ./config.bazzite.toml
```
- [ ] Run a dry-run sync:
```bash
gamehub sync --config ./config.bazzite.toml --dry-run --verbose --require-steam-closed
```
- [ ] Run the first real sync:
```bash
gamehub sync --config ./config.bazzite.toml --verbose --require-steam-closed
```
- [ ] Run shortcut structure validation:
```bash
./venv/bin/python scripts/validate_steam_shortcuts.py --config ./config.bazzite.toml
```
- [ ] Launch one managed `Azahar` title from Steam.
- [ ] Confirm `Esc` quits the managed session.
- [ ] Confirm the Linux wrapper still exits only on strict `Select+Start`.
- [ ] On Steam Deck, verify the managed built-in-controller `Esc` plus `Start+Select` path only.

## 4. Server Carry-Forward Smoke

Budget: 15 to 25 minutes.

- [ ] Run the portable verifier against the release-candidate server:
```bash
python3 scripts/verify_server_deploy.py --base-url "http://<SERVER_IP>:8000" --wait-seconds 30
```
- [ ] Confirm `GET /health` returns `{"status":"ok"}`.
- [ ] Confirm `GET /v1/index` succeeds and returns representative titles.
- [ ] On one configured client, run:
```bash
gamehub config verify --config ./config.toml
gamehub doctor server --config ./config.toml --server-url "http://<SERVER_IP>:8000"
gamehub doctor server --config ./config.toml --server-url "http://<SERVER_IP>:8000" --json
```
- [ ] Confirm text and JSON `doctor server` output both report matching `1.7.0` client/server versions.

## Pass Criteria

Call `v1.7.0` ready only if all of these are true:

- [ ] Rebuilt artifacts and metadata report `1.7.0`.
- [ ] Release notes and deploy references use `v1.7.0`.
- [ ] Windows packaged `config init`, `config verify`, and sync flows passed.
- [ ] Managed `Azahar` launches on the tested hosts confirm shipped `Esc` quit behavior.
- [ ] `Start+Select` exit behavior still works on the tested hosts where the relevant exit hook is enabled.
- [ ] No release validation step depended on the removed `Azahar` mouse-bridge path.
- [ ] Server carry-forward smoke passed.
