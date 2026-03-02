# Release vX.Y.Z

## Highlights
- 

## Server
- Docker image: `ghcr.io/<org>/gamehub-server:vX.Y.Z`
- Deploy bundle zip: `gamehub-server-deploy-vX.Y.Z.zip`
- Deployment notes:
  - Pull: `docker pull ghcr.io/<org>/gamehub-server:vX.Y.Z`
  - Run with compose: set `GAMEHUB_SERVER_IMAGE=ghcr.io/<org>/gamehub-server` and `GAMEHUB_IMAGE_TAG=vX.Y.Z` in `docker/.env`, then run `docker compose -f docker/compose.yaml --env-file docker/.env up -d`

## Client
- Linux wheel:
  - `gamehub-<version>-py3-none-any.whl`
- Windows EXE:
  - `gamehub-windows-amd64.exe`

## Compatibility / Migration Notes
- Save sync rollout default remains disabled (`[save_sync].enabled = false`).
- If enabling save sync for existing installs, run `gamehub sync --dry-run` first and review planned save actions/reasons before first non-dry execution.
- Call out any state migration behavior (for example newly added `state.json` save keys loading as empty defaults).

## Known Limitations
- Bidirectional save upload may be unavailable on servers that still return `501` for `PUT /v1/saves/{save_id}`.
- Save states are intentionally out of scope; only indexed save artifacts are covered.

## Checksums
- See `checksums.txt` in release assets.

