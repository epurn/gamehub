# v1.6.0 Manual Release Checklist

Use this after the automated gates pass.

Target time: about 2 to 3 hours.

This minor release focuses on trusted-LAN home-server deployment readiness, release-pinned deploy artifacts, and cross-platform operator verification. It reuses the broader behavioral validation from [release-manual-checklist-v1.5.0.md](./release-manual-checklist-v1.5.0.md). If anything outside the deploy/readiness scope behaves differently, fall back to that full checklist before releasing.

Full release flow still lives in [release-final-validation-playbook.md](./release-final-validation-playbook.md).

## Before manual testing

- [ ] Rebuild the wheel and Windows EXE after the version bump.
- [ ] Confirm rebuilt artifacts and server version metadata report `1.6.0`.
- [ ] Confirm release notes and deploy references use `v1.6.0`.
- [ ] Prepare a release-candidate server data root with representative ROM, firmware, and save data and confirm there are no symlinks under `roms/`, `firmware/`, or `saves/`.

## 1. Deploy Bundle And Pinned Tag

Budget: 15 to 25 minutes.

- [ ] Download or generate the release-candidate deploy bundle and confirm it includes:
  - `docker/compose.yaml`
  - `docker/.env.template`
  - [deployment-server.md](./deployment-server.md)
  - [runbook.md](./runbook.md)
  - `scripts/verify_server_deploy.py`
  - `scripts/verify_server_deploy.ps1`
- [ ] Confirm the bundled `docker/.env.template` pins `GAMEHUB_IMAGE_TAG=v1.6.0`.
- [ ] Confirm the bundled `docker/.env.template` exposes `GAMEHUB_SERVER_BIND_ADDRESS` and `GAMEHUB_MAX_SAVE_UPLOAD_BYTES`.
- [ ] Copy the env template to `docker/.env`, set the intended `GAMEHUB_SERVER_BIND_ADDRESS`, and set `GAMEHUB_MAX_SAVE_UPLOAD_BYTES` if your rollout policy needs an upload limit.
- [ ] Run `docker compose -f docker/compose.yaml --env-file docker/.env config` and confirm the published port uses the chosen bind address rather than `0.0.0.0`.

## 2. Live Server Smoke

Budget: 20 to 30 minutes.

- [ ] Start the release-candidate server from the pinned `v1.6.0` image.
- [ ] Run the portable verifier:
```bash
python3 scripts/verify_server_deploy.py --base-url "http://<SERVER_IP>:8000" --wait-seconds 30
```
- [ ] Confirm `GET /health` returns `{"status":"ok"}`.
- [ ] Confirm `GET /v1/index` succeeds and returns the expected representative titles.
- [ ] Confirm the verifier fetches a sample file successfully when titles exist.
- [ ] If save upload is enabled for this rollout, confirm `saves/` is writable inside the deployed data root.
- [ ] If this server will be reached by other LAN devices, confirm a second machine can reach the chosen bind address and that the service is not exposed on unintended interfaces.

Stop if any of the above fail.

## 3. Client Carry-Forward Smoke

Budget: 45 to 60 minutes.

- [ ] Windows packaged client:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --dry-run --verbose --require-steam-closed
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --verbose --require-steam-closed
.\venv\Scripts\python.exe scripts\validate_steam_shortcuts.py --config .\config.windows.toml
```
- [ ] Confirm one managed Windows title launches successfully after the non-dry sync.
- [ ] macOS smoke:
```bash
./venv/bin/python -m gamehub_cli.main sync --config ./config.macos.toml --dry-run --verbose --require-steam-closed
./venv/bin/python -m gamehub_cli.main sync --config ./config.macos.toml --verbose --require-steam-closed
./venv/bin/python scripts/validate_steam_shortcuts.py --config ./config.macos.toml
```
- [ ] Linux or Bazzite smoke:
```bash
gamehub sync --config ./config.bazzite.toml --dry-run --verbose --require-steam-closed
gamehub sync --config ./config.bazzite.toml --verbose --require-steam-closed
./venv/bin/python scripts/validate_steam_shortcuts.py --config ./config.bazzite.toml
```
- [ ] Confirm at least one managed title launches on the non-Windows platform you are using for the release pass.

## 4. First-Live Operator Checklist

Budget: 15 to 20 minutes.

- [ ] Record the final pinned image tag, chosen bind address, and server host for the rollout notes.
- [ ] Take a backup snapshot of the server data root before the live cutover.
- [ ] Confirm the release operator has [runbook.md](./runbook.md) available for upgrade, rollback, and outage triage.
- [ ] Confirm the release operator understands that symlinks under the server data root are unsupported for indexed content.
- [ ] If `save_sync.enabled = true` will be used, confirm the release operator knows the initial save mode and conflict policy for the first live sync.

## Pass Criteria

Call `v1.6.0` ready only if all of these are true:

- [ ] Rebuilt artifacts and metadata report `1.6.0`.
- [ ] Deploy bundle contents and env pinning are correct.
- [ ] Live server smoke passed with the portable verifier.
- [ ] The selected bind-address exposure matches the intended rollout.
- [ ] Windows, macOS, and Linux/Bazzite carry-forward smoke checks passed for the platforms available to test.
- [ ] The first-live operator checklist is complete.
