# Release v1.6.0

## Highlights
- Trusted-LAN home-server deployment is now ready for a real `amd64` server rollout.
- Server direct-run and Compose defaults now bind to loopback first, so operators must opt in explicitly before exposing the service to the wider LAN.
- Indexing and file-serving now reject symlinked ROM, firmware, and save content, and cached file reads are revalidated before bytes are served.
- The server deploy bundle is now release-pinned and ships a portable Python verifier, while CI and release flows now smoke-test the real container image against fixture data before publish.

## Server
- Docker image: `ghcr.io/epurn/gamehub-server:v1.6.0`
- Deploy bundle zip: `gamehub-server-deploy-v1.6.0.zip`
- Deployment notes:
  - Pull: `docker pull ghcr.io/epurn/gamehub-server:v1.6.0`
  - Run with compose: set `GAMEHUB_SERVER_IMAGE=ghcr.io/epurn/gamehub-server`, `GAMEHUB_IMAGE_TAG=v1.6.0`, and choose `GAMEHUB_SERVER_BIND_ADDRESS` intentionally in `docker/.env`, then run `docker compose -f docker/compose.yaml --env-file docker/.env up -d`
  - Verify: run `python3 scripts/verify_server_deploy.py --base-url "http://<SERVER_IP>:8000" --wait-seconds 30`

## Client
- Client wheel (macOS/Linux):
  - `gamehub-1.6.0-py3-none-any.whl`
- Windows EXE:
  - `gamehub-windows-amd64.exe`

## Compatibility / Migration Notes
- There are no new `gamehub_common` schema changes and no `/v1` API contract changes in this release.
- Existing server operators should review `docker/.env` after upgrading: the deploy template now defaults `GAMEHUB_SERVER_BIND_ADDRESS=127.0.0.1` and release bundles pin `GAMEHUB_IMAGE_TAG` to the tagged release instead of `latest`.
- If other LAN devices need to reach the server directly, set `GAMEHUB_SERVER_BIND_ADDRESS` to the host's explicit LAN address before starting the container.
- If you are converting a direct-run or broad-bind dev server into the production Compose deployment, use [dev-to-prod-server-migration.md](./dev-to-prod-server-migration.md) during the cutover.
- Ensure the server data root contains no symlinks anywhere under `roms/`, `firmware/`, or `saves/`; indexed symlinked content is now rejected and cached symlink escapes are blocked at read time.
- If save uploads are enabled, confirm `saves/` is writable and set `GAMEHUB_MAX_SAVE_UPLOAD_BYTES` explicitly if you need a server-side upload cap.
- Managed shortcut commands remain `shortcut-launch`; there is no new shortcut-command migration in this release.

## Known Limitations
- Deployment scope remains trusted-LAN only; there is still no built-in auth or TLS layer in this release.
- Server image architecture remains `amd64` only.
- Automatic save upload is launch-session scoped for GAMEHUB-managed shortcuts only; there is no background watcher service in this release.

## Checksums
- See `checksums.txt` in release assets.
