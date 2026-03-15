# Release v1.5.1

## Highlights
- Fix Windows managed Steam shortcut wrapper resolution for installed release layouts.
- Managed shortcuts now correctly reuse adjacent or PATH-discovered `gamehub-windows-amd64.exe`, which prevents Steam's "missing game executable" error after sync rewrites wrapper launches.
- This is a patch release with no server API or schema changes.

## Server
- Docker image: `ghcr.io/epurn/gamehub-server:v1.5.1`
- Deploy bundle zip: `gamehub-server-deploy-v1.5.1.zip`
- Deployment notes:
  - Pull: `docker pull ghcr.io/epurn/gamehub-server:v1.5.1`
  - Run with compose: set `GAMEHUB_SERVER_IMAGE=ghcr.io/epurn/gamehub-server` and `GAMEHUB_IMAGE_TAG=v1.5.1` in `docker/.env`, then run `docker compose -f docker/compose.yaml --env-file docker/.env up -d`

## Client
- Client wheel (macOS/Linux):
  - `gamehub-1.5.1-py3-none-any.whl`
- Windows EXE:
  - `gamehub-windows-amd64.exe`

## Compatibility / Migration Notes
- On Windows, run one non-dry `gamehub sync --require-steam-closed` after upgrading so managed Steam shortcuts are rewritten from the `v1.5.1` release build before launch.
- Managed shortcut wrapper commands remain `shortcut-launch`.
- There are no new server API contract changes in this release.

## Known Limitations
- Automatic save upload is launch-session scoped for GAMEHUB-managed shortcuts only; there is no background watcher service in this release.
- Steam Deck external Xbox controller support remains planned for a later update.

## Checksums
- See `checksums.txt` in release assets.
