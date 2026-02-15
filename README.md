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

## Linux First-Run Notes

- Linux sync is config-first. Put Linux overrides in `config.toml` under `[linux]` and use env vars only when needed.
- For immutable or Flatpak-heavy hosts, set:
  - `[linux] emulator_install_backend = "flatpak"`
- Set `steam.userdata_dir` explicitly (or `GAMEHUB_STEAM_USERDATA_DIR`) for deterministic profile selection.
- Run Steam mutation syncs from an active desktop session (not SSH-only) so Steam can relaunch.
- Linux RetroArch shortcuts are normalized to `.so` core paths automatically; set `[linux].retroarch_cores_dir`/`retroarch_cfg_path` when using custom RetroArch layouts.
- Flatpak PCSX2 defaults to sandbox-local BIOS path `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios`; GAMEHUB updates `PCSX2.ini` and mirrors BIOS files there automatically.
- Linux PCSX2 controller bootstrap uses generic SDL mappings for two controller slots by default (`[linux].pcsx2_controller_autoconfig = true`), so Xbox/DS4/DS5-class controllers work without per-device hardcoding; keyboard/mouse pad defaults are rewritten to controller mappings.
- If `/v1/index` is occasionally slow, tune `[server].index_timeout_seconds`, `index_fetch_attempts`, and `index_retry_backoff_seconds`.
- Use `--skip-steam-relaunch` when you want Steam files updated but do not want Steam relaunched automatically.
- Start with:
  - `gamehub sync --dry-run --skip-steam --verbose`

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
