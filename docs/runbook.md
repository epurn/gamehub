# GAMEHUB Ops Runbook

## Backup
Back up deployment configuration and data root.

```powershell
# Example paths; adjust for your environment.
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path ".\backups\$stamp" | Out-Null
Copy-Item .env.production ".\backups\$stamp\.env.production" -Force
Copy-Item -Recurse -Force $env:GAMEHUB_DATA_HOST_PATH ".\backups\$stamp\data"
```

## Restore
```powershell
# Stop server first.
docker compose -f docker/compose.yaml --env-file .env.production down

# Restore data + env from backup location.
Copy-Item ".\backups\<stamp>\.env.production" ".\.env.production" -Force
Copy-Item -Recurse -Force ".\backups\<stamp>\data\*" $env:GAMEHUB_DATA_HOST_PATH

# Start again.
docker compose -f docker/compose.yaml --env-file .env.production up -d
```

## Upgrade
```powershell
# Pull latest tag used in .env.production.
docker compose -f docker/compose.yaml --env-file .env.production pull
docker compose -f docker/compose.yaml --env-file .env.production up -d
.\scripts\verify_server_deploy.ps1
```

Optional platform pin (only when needed for cross-arch hosts):
- PowerShell: `$env:DOCKER_DEFAULT_PLATFORM = "linux/amd64"`
- Bash: `export DOCKER_DEFAULT_PLATFORM=linux/amd64`

## Rollback
1. Set `GAMEHUB_IMAGE_TAG` in `.env.production` to previous known-good image tag.
2. Re-run:
```powershell
docker compose -f docker/compose.yaml --env-file .env.production up -d
.\scripts\verify_server_deploy.ps1
```

## Triage Checklist
1. Container health:
```powershell
docker compose -f docker/compose.yaml --env-file .env.production ps
```
2. Server logs:
```powershell
docker compose -f docker/compose.yaml --env-file .env.production logs gamehub-server --tail=200
```
3. Data root contents:
   - verify `roms/<system>/` exists and files are readable
   - verify required firmware for systems with titles
4. API checks:
   - `GET /health`
   - `GET /v1/index`
   - `GET /v1/index?refresh=1` (manual cache refresh check)
   - `GET /v1/files/{file_id}` for a known title
