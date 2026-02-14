# GAMEHUB

Docker-first home server and CLI sync tool for emulator libraries and Steam injection.

## Quick Start

1. Create/activate venv (Windows PowerShell):
   - `python -m venv venv`
   - `.\venv\Scripts\Activate.ps1`
2. Install project:
   - `.\venv\Scripts\pip.exe install -e .[dev]`
3. Start server:
   - `.\venv\Scripts\python.exe -m uvicorn gamehub_server.main:app --host 0.0.0.0 --port 8000`
4. Run CLI dry-run:
   - `.\venv\Scripts\python.exe -m gamehub_cli.main sync --dry-run`

## Production Server (Docker Compose)

1. Copy template:
   - `Copy-Item .env.production.template .env.production`
2. Update `.env.production` values (`GAMEHUB_DATA_HOST_PATH`, `GAMEHUB_SERVER_PORT`, `GAMEHUB_IMAGE_TAG`)
3. Launch:
   - `docker compose -f docker/compose.yaml --env-file .env.production up -d --build`
4. Verify:
   - `.\scripts\verify_server_deploy.ps1`

## Layout

- `apps/server/` FastAPI server
- `apps/cli/` Typer CLI
- `shared/gamehub_common/` shared models/helpers
- `kanban/` epics/stories/notes
- `docs/` technical docs

## Docs

- `docs/development.md`
- `docs/server-api.md`
- `docs/cli-sync.md`
- `docs/config-and-state.md`
- `docs/steam-integration.md`
- `docs/index-schema.md`
- `docs/deployment-server.md`
- `docs/runbook.md`
- `docs/client-install.md`
- `docs/release-process.md`
