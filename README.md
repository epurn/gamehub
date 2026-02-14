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
