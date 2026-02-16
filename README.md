# GAMEHUB 🎮

Docker-first home server + client CLI for syncing emulator libraries and injecting them into Steam as non-Steam games with system collections and artwork.

## What GAMEHUB Does ✨
- Hosts canonical ROM/firmware data on a server.
- Generates a strict `/v1/index` used by clients for deterministic sync.
- Downloads only missing/outdated content to the client.
- Updates Steam shortcuts and collections (for example: `PS2`, `Wii`, `NES`).
- Copies artwork into Steam grid and reopens Steam after updates.

Supported systems in v1:
- `GB`, `GBA`, `GBC`, `GEN_MD`, `N64`, `NDS`, `NES`, `PSX`, `SNES`, `GC`, `Wii`, `PS2`

## New User Setup (Recommended Flow) 🚀

### 1. Prerequisites ✅
- Docker Engine + Docker Compose plugin (for server deployment).
- Steam installed on the client machine.
- Python 3.12+ (for source-based runs/tests).
- Server data in this exact layout:
  - `roms/<system>/<title.ext>`
  - `firmware/<system>/<filename>`

Important:
- Nested ROM directories under a system are invalid in current indexing behavior.
- ROM/firmware downloads are server-first only (no internet ROM/BIOS fetching).

### 2. Deploy the Server (Docker) 🐳
From repo root:

```powershell
Copy-Item .env.production.template .env.production
```

Edit `.env.production`:
- `GAMEHUB_DATA_HOST_PATH` (path containing `roms/` and `firmware/`)
- `GAMEHUB_SERVER_PORT` (for example `8000`)
- `GAMEHUB_IMAGE_TAG`
- Optional: `GAMEHUB_INDEX_REFRESH_SECONDS`

Start:
```powershell
docker compose -f docker/compose.yaml --env-file .env.production up -d --build
```

Validate:
```powershell
.\scripts\verify_server_deploy.ps1 -BaseUrl "http://127.0.0.1:$env:GAMEHUB_SERVER_PORT"
```

Note:
- Server warms the index/hash cache on startup; big libraries can make startup slower.
- Startup logs include warmup start/completion lines with elapsed time and counts.

### 3. Install the Client 🧰

Linux (wheel + pip):
```bash
python3 -m pip install --user --upgrade "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"
gamehub --help
```

Windows (standalone EXE):
```powershell
.\gamehub-windows-amd64.exe --help
.\gamehub-windows-amd64.exe sync --help
```

Windows/Linux from source (repo checkout):
```powershell
python -m venv venv
.\venv\Scripts\pip.exe install -e .[dev]
.\venv\Scripts\python.exe -m gamehub_cli.main sync --help
```

### 4. Create Client Config 🧩
Start from:
- Windows template: `docs/templates/config.windows.template.toml`
- Linux template: `docs/templates/config.linux.template.toml`

Default config lookup when `--config` is omitted:
- `./config.toml`
- `~/.gamehub/config.toml` (default home location)
- legacy fallback: platform config dir `gamehub/config.toml`

Minimum fields to set:
- `[server].url`
- `[paths].gamehub_dir`
- `[steam].userdata_dir`
- Optional but recommended: `[steam].steam_id`

Security note:
- Prefer `GAMEHUB_SGDB_API_KEY` environment variable over storing `sgdb.api_key` in files.

### 5. First Sync Safely (Dry Run) 🧪

Windows EXE:
```powershell
.\gamehub-windows-amd64.exe sync --config .\config.windows.toml --dry-run --verbose --require-steam-closed
```

Linux:
```bash
gamehub sync --config ./config.linux.toml --dry-run --verbose --require-steam-closed
```

### 6. Real Sync ▶️

Windows EXE:
```powershell
.\gamehub-windows-amd64.exe sync --config .\config.windows.toml --verbose --require-steam-closed
```

Linux:
```bash
gamehub sync --config ./config.linux.toml --verbose --require-steam-closed
```

What happens:
1. Fetch and validate server index.
2. Plan firmware/content updates.
3. Download to `*.part` then atomic rename.
4. Deploy firmware.
5. Close Steam, backup config files, update shortcuts + collections, copy artwork, reopen Steam.
6. Write `state.json`.

### 7. Validate in Steam 🕹️
- GAMEHUB shortcuts exist.
- Collections exist by exact system names.
- Artwork appears in grid.
- Sample titles launch through expected emulator.

## Linux-Specific Tips 🐧
- Set `[linux].emulator_install_backend = "flatpak"` on immutable or Flatpak-first systems.
- `auto` now prefers Flatpak first on immutable/Bazzite/SteamOS-style hosts, then falls back to distro package managers.
- On Flatpak-preferred Linux runs, Dolphin is forced to `org.DolphinEmu.dolphin-emu` (native `/usr/bin/dolphin` is not used as a substitute).
- Dolphin sync bootstrap writes runtime config (`Dolphin.ini`, `GCPadNew.ini`, `WiimoteNew.ini`, `Hotkeys.ini`) under the resolved Dolphin user dir and shortcuts pass `-u` to use that same profile.
- Dolphin controller exit default: `Back+Start` (pad1/pad2).
- Existing Dolphin input files are preserved once they exist; sync reconciles managed stop/exit hotkeys each run.
- Legacy Linux managed input files that used `XInput/<n>/Gamepad`/`All Devices` are auto-migrated by sync.
- Dolphin runtime bootstrap sets `BackgroundInput = True` to reduce Steam-launch focus/input issues.
- RetroArch bootstrap sets `input_menu_toggle_gamepad_combo = "4"` (`Start+Select`) when a RetroArch config file is detected.
- PCSX2 bootstrap sets `Hotkeys/OpenPauseMenu = SDL-0/Back & SDL-0/Start` when the existing binding is missing or keyboard-only.
- Run non-dry Steam updates from an active desktop session (not SSH-only), so Steam relaunch works.
- If RetroArch paths are custom, set `[linux].retroarch_cfg_path` and/or `[linux].retroarch_cores_dir`.
- Flatpak PCSX2 BIOS default target:
  - `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios`

## Common Issues and Fixes 🛠️
- Everything wants to redownload:
  - Usually wrong config file or wrong `paths.gamehub_dir` / `state_path`.
  - Confirm you are passing the intended `--config`.
- Steam updates skipped:
  - Steam may still be running and could not be closed.
  - Retry with `--require-steam-closed` and close Steam manually first.
- Slow index fetch:
  - Increase `[server].index_timeout_seconds`.
  - Increase `[server].index_fetch_attempts`.
  - Increase `[server].index_retry_backoff_seconds`.
- No profile found:
  - Set `[steam].userdata_dir` explicitly.
  - Set `[steam].steam_id` for deterministic targeting.

## Repo Layout 🗂️
- `apps/server/` FastAPI server
- `apps/cli/` Typer CLI
- `shared/gamehub_common/` shared models/helpers
- `kanban/` planning artifacts
- `docs/` technical docs

## Docs Index 📚
- `docs/client-install.md`
- `docs/deployment-server.md`
- `docs/cli-sync.md`
- `docs/config-and-state.md`
- `docs/server-api.md`
- `docs/steam-integration.md`
- `docs/index-schema.md`
- `docs/runbook.md`
- `docs/release-process.md`
- `docs/development.md`
