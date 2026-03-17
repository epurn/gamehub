# GAMEHUB Ops Runbook

## First Live Cutover
- If this host previously ran a development server, complete [dev-to-prod-server-migration.md](./dev-to-prod-server-migration.md) before the live cutover.
- Prefer a pinned release tag in `docker/.env` before the first real server rollout.
- Keep `GAMEHUB_SERVER_BIND_ADDRESS=127.0.0.1` until you are ready to expose the service to a trusted LAN IP.
- Confirm there are no symlinks anywhere under the server data root.
- Take a backup snapshot of `docker/.env` and the host data root before the first cutover.
- If bidirectional save sync will be used, confirm the host `saves/` tree is writable by Docker.
- After `docker compose up -d`, run `python3 scripts/verify_server_deploy.py --base-url "http://127.0.0.1:8000" --wait-seconds 30`.
- From a configured client machine, run `gamehub doctor server --server-url "http://127.0.0.1:8000"` for the higher-level client/server compatibility check.

## Backup
Back up deployment configuration and data root with the snapshot helper.

```bash
python3 scripts/server_snapshot.py backup --env-file docker/.env --output-dir ./snapshots --apply
```

## Restore
```powershell
# Stop server first.
docker compose -f docker/compose.yaml --env-file docker/.env down

# Preview the restore plan first.
python scripts/server_snapshot.py restore .\snapshots\<snapshot-name>

# Restore data + env from snapshot.
python scripts/server_snapshot.py restore .\snapshots\<snapshot-name> --apply

# Start again.
docker compose -f docker/compose.yaml --env-file docker/.env up -d
```

## Upgrade
```powershell
# Pull the pinned tag already configured in docker/.env.
docker compose -f docker/compose.yaml --env-file docker/.env pull
docker compose -f docker/compose.yaml --env-file docker/.env up -d
```

```bash
python3 scripts/verify_server_deploy.py --base-url "http://127.0.0.1:8000" --wait-seconds 30
```

Optional platform pin (only when needed for cross-arch hosts):
- PowerShell: `$env:DOCKER_DEFAULT_PLATFORM = "linux/amd64"`
- Bash: `export DOCKER_DEFAULT_PLATFORM=linux/amd64`

## Rollback
1. Set `GAMEHUB_IMAGE_TAG` in `docker/.env` to previous known-good image tag.
2. Re-run:
```powershell
docker compose -f docker/compose.yaml --env-file docker/.env up -d
```

```bash
python3 scripts/verify_server_deploy.py --base-url "http://127.0.0.1:8000" --wait-seconds 30
```

## Triage Checklist
1. Container health:
```powershell
docker compose -f docker/compose.yaml --env-file docker/.env ps
```
2. Server logs:
```powershell
docker compose -f docker/compose.yaml --env-file docker/.env logs gamehub-server --tail=200
```
3. Data root contents:
   - verify `roms/<system>/` exists and files are readable
   - verify required firmware for systems with titles
   - verify `saves/` exists and is writable when bidirectional save sync is enabled
   - verify there are no symlinks anywhere under the server data root
4. Deployment bind and smoke checks:
   - verify `GAMEHUB_SERVER_BIND_ADDRESS` matches the intended host exposure
   - rerun `python3 scripts/verify_server_deploy.py --base-url "http://127.0.0.1:8000" --wait-seconds 30`
   - rerun `gamehub doctor server --server-url "http://127.0.0.1:8000"` from a managed client when validating exact client/server version pairing
5. API checks:
   - `GET /health`
   - `GET /v1/status`
   - `GET /v1/index`
   - `GET /v1/index?refresh=1` (manual cache refresh check)
   - `GET /v1/save-bindings` when validating save-sync issues
   - `GET /v1/files/{file_id}` for a known title
