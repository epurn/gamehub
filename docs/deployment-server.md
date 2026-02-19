# Server Deployment (Production Compose)

This guide covers single-host LAN deployment for GAMEHUB server.

## Prerequisites
- Docker Engine + Docker Compose plugin
- Host data directory with:
  - `roms/<system>/<title.ext>`
  - `firmware/<system>/<filename>`

Optional convenience:
- Download `gamehub-server-deploy-vX.Y.Z.zip` from the GitHub Release to get:
  - `docker/compose.yaml`
  - `docker/.env.template`
  - [docs/deployment-server.md](deployment-server.md)
  - `scripts/verify_server_deploy.ps1`

## 1) Create production env file
Copy the template and adjust paths/port:

```powershell
Copy-Item docker/.env.template docker/.env
```

Required values in `docker/.env`:
- `GAMEHUB_DATA_HOST_PATH`: host path containing `roms/` and `firmware/`
  - Windows example: `D:/GameHubData`
  - Linux example: `/srv/gamehub/data`
- `GAMEHUB_SERVER_PORT`: exposed host port
- `GAMEHUB_SERVER_IMAGE`: container image repository
  - Official release image: `ghcr.io/epurn/gamehub-server`
- `GAMEHUB_IMAGE_TAG`: image tag to run
  - `latest` for most recent release
  - `v1.0.3` (or any release tag) for pinned deploys
- Optional: `GAMEHUB_INDEX_REFRESH_SECONDS` (defaults to `0`, meaning startup/manual refresh only)
- Optional: `GAMEHUB_HASH_CACHE_PATH` (path for persistent SHA256 cache DB; default is `/app/.cache/gamehub/hash-cache.sqlite3`)

## 2) Pull released server image
```powershell
docker compose -f docker/compose.yaml --env-file docker/.env pull gamehub-server
```

## 3) Deploy
```powershell
docker compose -f docker/compose.yaml --env-file docker/.env up -d
```

## 4) Validate compose config
```powershell
docker compose -f docker/compose.yaml --env-file docker/.env config
```

## 5) Verify runtime
```powershell
.\scripts\verify_server_deploy.ps1 -BaseUrl "http://127.0.0.1:$env:GAMEHUB_SERVER_PORT"
```

## Notes
- Server distribution is GHCR image-based for releases (no separate server binary artifact on GitHub Releases).
- Data volume is mounted read-only in container.
- Hash cache is stored in named Docker volume `gamehub-hash-cache-v2` and persists across container restarts/recreates.
- Container restart policy is `unless-stopped`.
- Healthcheck targets `GET /health`.
- Server performs index/hash warmup during startup; large libraries can increase startup time.
- Rebuilds reuse cached SHA256 values for unchanged files (metadata-keyed), which significantly reduces repeated hash work on large libraries.
- Startup logs include explicit warmup start/completion lines with elapsed time and indexed system/title counts.
- Scope is LAN-only in this phase (no TLS/auth in-container).
- Compose defaults are architecture-portable for local deploys (no hard pin in `docker/compose.yaml`).
- If you need to pin image platform explicitly, use Docker runtime controls:
  - PowerShell: `$env:DOCKER_DEFAULT_PLATFORM = "linux/amd64"`
  - Bash: `export DOCKER_DEFAULT_PLATFORM=linux/amd64`
- If you are developing from source and want a local image build instead of GHCR, run:
  - `docker compose -f docker/compose.yaml --env-file docker/.env up -d --build`

