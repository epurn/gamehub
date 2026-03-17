# Server Deployment (Production Compose)

This guide covers single-host LAN deployment for GAMEHUB server.

## Prerequisites
- Docker Engine + Docker Compose plugin
- Host data directory with:
  - `roms/<system>/<title.ext>`
  - `firmware/<system>/<filename>`
  - optional existing `saves/<system>/<title_stem>/<kind>/<file...>` data, or an empty writable `saves/` tree for server-side save creation
- No symlinks anywhere under `roms/`, `firmware/`, or `saves/`

Optional convenience:
- Download `gamehub-server-deploy-vX.Y.Z.zip` from the GitHub Release to get:
  - `docker/compose.yaml`
  - `docker/.env.template`
  - [docs/deployment-server.md](deployment-server.md)
  - [docs/dev-to-prod-server-migration.md](dev-to-prod-server-migration.md)
  - [docs/runbook.md](runbook.md)
  - `scripts/server_snapshot.py`
  - `scripts/verify_server_deploy.py`
  - `scripts/verify_server_deploy.ps1`
  - The bundled `docker/.env.template` is pinned to the release tag from that zip

If you are converting an existing development server into this production layout, run through [dev-to-prod-server-migration.md](./dev-to-prod-server-migration.md) before the first live cutover.

## 1) Create production env file
Copy the template and adjust paths/port:

```bash
cp docker/.env.template docker/.env
```

```powershell
Copy-Item docker/.env.template docker/.env
```

Required values in `docker/.env`:
- `GAMEHUB_DATA_HOST_PATH`: host path containing `roms/`, `firmware/`, and writable `saves/`
  - Windows example: `D:/GameHubData`
  - Linux example: `/srv/gamehub/data`
- `GAMEHUB_SERVER_BIND_ADDRESS`: host interface for published port access
  - `127.0.0.1` keeps the server loopback-only on the host
  - set a trusted LAN IP to expose it to other machines on your network
  - only use `0.0.0.0` if you explicitly want every host interface exposed
- `GAMEHUB_SERVER_PORT`: exposed host port
- `GAMEHUB_SERVER_IMAGE`: container image repository
  - Official release image: `ghcr.io/epurn/gamehub-server`
- `GAMEHUB_IMAGE_TAG`: image tag to run
  - prefer a pinned release tag for real servers
  - the GitHub Release deploy bundle already pins this value to its own release tag
- Optional: `GAMEHUB_INDEX_POLL_SECONDS` (defaults to `1`; set `0` to disable background polling)
- Optional: `GAMEHUB_INDEX_STABLE_SECONDS` (defaults to `2`; changed files must stop changing for this long before auto-reindex)
- Optional: `GAMEHUB_INDEX_REFRESH_SECONDS` (defaults to `0`; adds TTL-based rebuilds on top of change detection)
- Optional: `GAMEHUB_HASH_CACHE_PATH` (path for persistent SHA256 cache DB; default is `/app/.cache/gamehub/hash-cache.sqlite3`)
- Optional: `GAMEHUB_MAX_SAVE_UPLOAD_BYTES` (defaults to `134217728`; caps streamed save-upload size in bytes)
- Optional: `GAMEHUB_BACKUP_KEEP_LIMIT` (defaults to `3`; keeps the newest server-generated save backups per save file)

## 2) First-live checklist
- Take a backup snapshot of `docker/.env` and the host data root before the first real cutover.
- Keep `GAMEHUB_SERVER_BIND_ADDRESS=127.0.0.1` until you are ready to expose the service to a trusted LAN IP.
- Prefer a pinned release tag over `latest`.
- If bidirectional save sync is enabled, confirm the host `saves/` tree is writable by Docker.
- Remove or replace any symlinked files or directories under the server data root before startup.
- If this host previously ran a dev server, complete [dev-to-prod-server-migration.md](./dev-to-prod-server-migration.md) so old broad-bind or direct-run settings do not leak into production.

Canonical snapshot command:

```bash
python3 scripts/server_snapshot.py backup --env-file docker/.env --output-dir ./snapshots --apply
```

The snapshot directory contains `docker/.env`, the full data root, `image-tag.txt`, and `manifest.json`.

## 3) Pull released server image
```bash
docker compose -f docker/compose.yaml --env-file docker/.env pull gamehub-server
```

## 4) Deploy
```bash
docker compose -f docker/compose.yaml --env-file docker/.env up -d
```

## 5) Validate compose config
```bash
docker compose -f docker/compose.yaml --env-file docker/.env config
```

## 6) Verify runtime
Canonical cross-platform check:

```bash
python3 scripts/verify_server_deploy.py --base-url "http://127.0.0.1:8000" --wait-seconds 30
```

Windows convenience path:

```powershell
.\scripts\verify_server_deploy.ps1 -BaseUrl "http://127.0.0.1:8000"
```

If you changed the bind address or port, update the verification URL to match the deployed listener.

Higher-level configured-client smoke:

```bash
gamehub config verify --config ./config.toml
gamehub doctor server --config ./config.toml --server-url "http://127.0.0.1:8000"
gamehub doctor server --config ./config.toml --server-url "http://127.0.0.1:8000" --json
```

Run those from a configured client machine after the portable verifier passes. `--json` mode suppresses retry chatter on stdout so the output remains machine-readable.

## Notes
- Server distribution is GHCR image-based for releases (no separate server binary artifact on GitHub Releases).
- Data volume is mounted read-write in container. Bidirectional save sync, including first-time save creation, requires the server to be able to create and update files under `/data/saves`.
- Hash cache is stored in named Docker volume `gamehub-hash-cache-v2` and persists across container restarts/recreates.
- Container restart policy is `unless-stopped`.
- Healthcheck targets `GET /health`.
- Server performs index/hash warmup during startup; large libraries can increase startup time.
- Server runs a background index poller by default and waits for changed files to stay stable before rebuilding, which helps avoid hashing partially copied large files.
- Source-change rebuilds write explicit index-change lines to container logs for added, updated, and removed ROM, firmware, and save entries.
- Rebuilds reuse cached SHA256 values for unchanged files (metadata-keyed), which significantly reduces repeated hash work on large libraries.
- Startup logs include explicit warmup start/completion lines with elapsed time and indexed system/title counts.
- Scope is LAN-only in this phase (no TLS/auth in-container).
- Compose now defaults to loopback bind (`127.0.0.1`) until you opt into a trusted LAN address.
- Multi-homed hosts should set `GAMEHUB_SERVER_BIND_ADDRESS` explicitly instead of relying on broad interface exposure.
- Indexed server content must not contain symlinked files or directories under `roms/`, `firmware/`, or `saves/`.
- Compose defaults are architecture-portable for local deploys (no hard pin in `docker/compose.yaml`).
- If you need to pin image platform explicitly, use Docker runtime controls:
  - PowerShell: `$env:DOCKER_DEFAULT_PLATFORM = "linux/amd64"`
  - Bash: `export DOCKER_DEFAULT_PLATFORM=linux/amd64`
- If you are developing from source and want a local image build instead of GHCR, run:
  - `docker compose -f docker/compose.yaml --env-file docker/.env up -d --build`
