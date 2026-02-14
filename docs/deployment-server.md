# Server Deployment (Production Compose)

This guide covers single-host LAN deployment for GAMEHUB server.

## Prerequisites
- Docker Engine + Docker Compose plugin
- Host data directory with:
  - `roms/<system>/<title.ext>`
  - `firmware/<system>/<filename>`

## 1) Create production env file
Copy the template and adjust paths/port:

```powershell
Copy-Item .env.production.template .env.production
```

Required values in `.env.production`:
- `GAMEHUB_DATA_HOST_PATH`: host path containing `roms/` and `firmware/`
- `GAMEHUB_SERVER_PORT`: exposed host port
- `GAMEHUB_IMAGE_TAG`: image tag to run

## 2) Deploy
```powershell
docker compose -f docker/compose.yaml --env-file .env.production up -d --build
```

## 3) Validate compose config
```powershell
docker compose -f docker/compose.yaml --env-file .env.production config
```

## 4) Verify runtime
```powershell
.\scripts\verify_server_deploy.ps1 -BaseUrl "http://127.0.0.1:$env:GAMEHUB_SERVER_PORT"
```

## Notes
- Data volume is mounted read-only in container.
- Container restart policy is `unless-stopped`.
- Healthcheck targets `GET /health`.
- Scope is LAN-only in this phase (no TLS/auth in-container).
