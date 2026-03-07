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
- Document any API contract changes (for example save-upload request/response changes such as `PUT /v1/saves/{save_id}` behavior).
- Document any save-sync rollout changes (for example first-time local save creation auto-upload in `bidirectional`, or any new read-only/write behavior).
- Document any managed shortcut command migrations only if this release changes them (for example `controller-launch` -> `shortcut-launch`).
- Document any required post-upgrade operator action (for example one non-dry `gamehub sync` to rewrite persisted Steam shortcut commands).
- Call out any state migration behavior (for example newly added `state.json` keys loading as empty defaults).

## Known Limitations
- Automatic save upload is launch-session scoped for GAMEHUB-managed shortcuts only; there is no background watcher service in this release.
- Save states are intentionally out of scope; only indexed save artifacts are covered.

## Checksums
- See `checksums.txt` in release assets.

