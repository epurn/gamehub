# Draft Release Notes for v1.6.0

This file tracks the current unreleased `v1.6.0` target on `main`.

Keep compatible additional feature work batched into `v1.6.0` until you intentionally freeze or split the release. Before tagging, refresh this draft so it matches the final shipped scope.

## Highlights
- Trusted-LAN home-server deployment is now ready for a real `amd64` server rollout.
- Server direct-run and Compose defaults now bind to loopback first, so operators must opt in explicitly before exposing the service to the wider LAN.
- Indexing and file-serving now reject symlinked ROM, firmware, and save content, and cached file reads are revalidated before bytes are served.
- The server deploy bundle is now release-pinned and ships a portable Python verifier, while CI and release flows now smoke-test the real container image against fixture data before publish.
- `gamehub config init` and `gamehub config verify` now provide a supported config bootstrap path, and user-facing `init`, `sync`, and `doctor ...` commands fail fast when the resolved config file is missing.
- `gamehub doctor server` now validates live deployments from a configured client, with both human-readable output and stdout-clean `--json` output for automation.
- Save-sync hardening in this release adds `/v1/save-bindings`, save conflict review/resolution commands, stricter learned-tree root handling, stale conflict cleanup, backup-family retention, and `sync --json-summary`.

## Planned Server Artifacts
- Expected Docker image: `ghcr.io/epurn/gamehub-server:v1.6.0`
- Expected deploy bundle zip: `gamehub-server-deploy-v1.6.0.zip`
- Planned deployment notes:
  - Pull: `docker pull ghcr.io/epurn/gamehub-server:v1.6.0`
  - Run with compose: set `GAMEHUB_SERVER_IMAGE=ghcr.io/epurn/gamehub-server`, `GAMEHUB_IMAGE_TAG=v1.6.0`, and choose `GAMEHUB_SERVER_BIND_ADDRESS` intentionally in `docker/.env`, then run `docker compose -f docker/compose.yaml --env-file docker/.env up -d`
  - Verify: run `python3 scripts/verify_server_deploy.py --base-url "http://<SERVER_IP>:8000" --wait-seconds 30`
  - Configured-client smoke: run `gamehub config verify --config <client-config>`, then `gamehub doctor server --config <client-config> --server-url "http://<SERVER_IP>:8000"` in text or `--json` mode

## Planned Client Artifacts
- Expected client wheel (macOS/Linux):
  - `gamehub-1.6.0-py3-none-any.whl`
- Expected Windows EXE:
  - `gamehub-windows-amd64.exe`

## Compatibility / Migration Notes
- `/v1/index` remains `index_version=1`, but this release adds additive server-side contracts for `GET /v1/status` (`status_version=1`) and `GET /v1/save-bindings`.
- Existing server operators should review `docker/.env` after upgrading: the deploy template now defaults `GAMEHUB_SERVER_BIND_ADDRESS=127.0.0.1` and release bundles pin `GAMEHUB_IMAGE_TAG` to the tagged release instead of `latest`.
- If other LAN devices need to reach the server directly, set `GAMEHUB_SERVER_BIND_ADDRESS` to the host's explicit LAN address before starting the container.
- If you are converting a direct-run or broad-bind dev server into the production Compose deployment, use [dev-to-prod-server-migration.md](./dev-to-prod-server-migration.md) during the cutover.
- Ensure the server data root contains no symlinks anywhere under `roms/`, `firmware/`, or `saves/`; indexed symlinked content is now rejected and cached symlink escapes are blocked at read time.
- If save uploads are enabled, confirm `saves/` is writable and set `GAMEHUB_MAX_SAVE_UPLOAD_BYTES` explicitly if you need a server-side upload cap. `GAMEHUB_BACKUP_KEEP_LIMIT` now controls retained server-generated save backups per save family.
- Preferred client bootstrap is now `gamehub config init`, then `gamehub config verify`, then `gamehub init`. User-facing `init`, `sync`, and `doctor ...` commands no longer fall back silently when the resolved config file is missing.
- For automation, `gamehub doctor server --json` and `gamehub sync --json-summary` now reserve stdout for one final JSON object.
- Older `state.json` files may still contain the legacy `tombstones` key; GAMEHUB ignores it on load and omits it on the next write.
- Save conflict handling is stricter by default in this release: new or unspecified bidirectional configs default to `conflict_policy = "manual"`, and `gamehub doctor saves --keep-local/--keep-server` is the supported single-save resolution path.
- Managed shortcut commands remain `shortcut-launch`; there is no new shortcut-command migration in this release.

## Known Limitations
- For the current planned scope, deployment remains trusted-LAN only; there is still no built-in auth or TLS layer in this release.
- Server image architecture remains `amd64` only.
- Automatic save upload is launch-session scoped for GAMEHUB-managed shortcuts only; there is no background watcher service in this release.

## Checksums
- See `checksums.txt` in release assets.
