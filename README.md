# GAMEHUB 🎮

[![Latest Tag](https://img.shields.io/github/v/tag/epurn/gamehub?sort=semver&label=latest%20tag)](https://github.com/epurn/gamehub/tags)
[![Audit Regression Gates](https://github.com/epurn/gamehub/actions/workflows/audit-regression-gates.yml/badge.svg)](https://github.com/epurn/gamehub/actions/workflows/audit-regression-gates.yml)
[![Targeted Regression Matrix](https://github.com/epurn/gamehub/actions/workflows/targeted-regression-matrix.yml/badge.svg)](https://github.com/epurn/gamehub/actions/workflows/targeted-regression-matrix.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License](https://img.shields.io/github/license/epurn/gamehub?branch=main&label=license)](LICENSE)

Docker-first home server + client CLI that syncs emulator libraries into Steam non-Steam shortcuts, system collections, and artwork.

## ✅ v1 Compatibility Matrix

### Platform support
| Platform | Status |
| --- | --- |
| Windows | ✅ |
| Bazzite | ✅ |
| SteamOS (Deck) | ✅ |
| Other Linux distros (Fedora/Ubuntu/etc.) | ⚠️ |
| macOS | ❌ |

### Controller support (external Xbox)
| Platform | Xbox controllers |
| --- | --- |
| Bazzite | ✅ |
| Windows | ✅ |
| SteamOS (Deck) | ❌ |
| Other Linux distros (Fedora/Ubuntu/etc.) | ❌ |
| macOS | ❌ |

SteamOS (Deck) is fully supported with the built-in controller. External Xbox controller support on Deck is planned for a later update.

Details: [Platform Support (v1)](docs/platform-support.md)

## 🚀 v1 Capabilities
- Server hosts canonical ROM/firmware library and serves strict `/v1/index`.
- Client sync is deterministic and safe (atomic writes, strict schema validation, state tracking).
- Steam integration updates:
  - managed non-Steam shortcuts
  - per-system collections (exact names like `NES`, `PS2`, `Wii`)
  - grid/hero/logo/icon artwork
- SGDB artwork cache with cache-first lookups and portrait+landscape grid support.
- Steam lifecycle safety: close -> backup -> write -> reopen.
- Launch-time controller autoconfig for `PCSX2`, `Dolphin`, and `Azahar` with user-overridable profile files (including Steam Deck built-in controller defaults).
- Controller state convergence for managed profile templates and assisted emulator controller keys, with metadata markers and `doctor controllers` repair flow.
- On Steam Deck, managed `Wii`/`N3DS` shortcuts auto-sync Steam Input template seeds and repair app override flags for native-first controller behavior.

Supported systems in current release:
- `GB`, `GBA`, `GBC`, `GEN_MD`, `N64`, `NDS`, `N3DS`, `NES`, `PSX`, `SNES`, `GC`, `Wii`, `PS2`

## 👤 User Install (Latest Release)
Create `config.toml` in one of the default locations:
1. `./config.toml` (current working directory where you run `gamehub`)
2. `~/.gamehub/config.toml`
   - Windows path equivalent: `%USERPROFILE%\.gamehub\config.toml`

Start from a template:
- Windows: [`docs/templates/config.windows.template.toml`](docs/templates/config.windows.template.toml)
- Linux: [`docs/templates/config.linux.template.toml`](docs/templates/config.linux.template.toml)
- Bazzite: [`docs/templates/config.bazzite.template.toml`](docs/templates/config.bazzite.template.toml)
- Steam Deck: [`docs/templates/config.steamdeck.template.toml`](docs/templates/config.steamdeck.template.toml)

Linux install from latest release wheel:
```bash
LATEST_TAG="$(python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://api.github.com/repos/epurn/gamehub/releases/latest'))['tag_name'])")"
LATEST_VER="${LATEST_TAG#v}"
python3 -m pip install --user --upgrade "https://github.com/epurn/gamehub/releases/download/${LATEST_TAG}/gamehub-${LATEST_VER}-py3-none-any.whl"
```

Linux first run + sync:
```bash
gamehub init --dry-run
gamehub init
gamehub sync --dry-run --require-steam-closed
gamehub sync --require-steam-closed --skip-steam-relaunch
```

Windows install + first run:
```powershell
Invoke-WebRequest https://github.com/epurn/gamehub/releases/latest/download/gamehub-windows-amd64.exe -OutFile .\gamehub-windows-amd64.exe
.\gamehub-windows-amd64.exe init --dry-run
.\gamehub-windows-amd64.exe init
.\gamehub-windows-amd64.exe sync --dry-run --require-steam-closed
.\gamehub-windows-amd64.exe sync --require-steam-closed
```

More detail: [docs/client-install.md](docs/client-install.md), [docs/config-and-state.md](docs/config-and-state.md), [docs/cli-sync.md](docs/cli-sync.md)

### Controller Autoconfig Quick Start (PCSX2/Dolphin/Azahar)
- Ensure `[controllers].launch_autoconfig = true` (or `GAMEHUB_CONTROLLER_LAUNCH_AUTOCONFIG=true`).
- Run one `gamehub init` pass to seed default controller profiles.
- If you used older preview/branch builds before recent controller profile fixes, run one bootstrap refresh with:
  - `gamehub init --reseed-profiles`
- Launch emulator shortcuts from Steam (not directly from emulator executables) so launch-time profile apply runs.
- Profile selection is automatic by detected Xbox count:
  - `0` controllers -> `kbm`
  - `1` controller -> `xbox_1p`
  - `2+` controllers -> `xbox_2p`
- Inspect controller drift without launching games:
  - `gamehub doctor controllers`
  - `gamehub doctor controllers --apply` (safe ownership-tier repairs only)
  - `gamehub doctor controllers --apply --force` (archives and cleans unmanaged profile files too)
- On Linux Flatpak Azahar paths, GUID injection prefers Flatpak runtime detection; if runtime GUID discovery is unavailable, GAMEHUB preserves existing GUIDs and otherwise keeps port-only SDL mappings.

## 🖥️ Server Deployment (Latest Release)
Place `docker/.env` next to [`docker/compose.yaml`](docker/compose.yaml).

```powershell
Copy-Item docker/.env.template docker/.env
# Edit docker/.env:
# - GAMEHUB_DATA_HOST_PATH=<host path containing roms/ and firmware/>
# - GAMEHUB_SERVER_PORT=8000
# - GAMEHUB_IMAGE_TAG=latest
docker compose -f docker/compose.yaml --env-file docker/.env pull gamehub-server
docker compose -f docker/compose.yaml --env-file docker/.env up -d
.\scripts\verify_server_deploy.ps1 -BaseUrl "http://127.0.0.1:8000"
```
If you changed `GAMEHUB_SERVER_PORT`, update the verify URL to match.

More detail: [docs/deployment-server.md](docs/deployment-server.md), [docs/runbook.md](docs/runbook.md), [docs/server-api.md](docs/server-api.md)

## 📝 Notes
- Server ROM layout must be flat per system: `roms/<system>/<title.ext>`.
- Nested ROM directories under a system are rejected.
- ROM/firmware are server-first only (no internet ROM/BIOS fetching).
- `N3DS` uses Azahar (`azahar`) with no required firmware files enforced by GAMEHUB.
- GAMEHUB does not decrypt ROMs; N3DS content must already be in a compatible format.
- Server releases are published as GHCR images (`ghcr.io/epurn/gamehub-server:<tag>`).
- Prefer `GAMEHUB_SGDB_API_KEY` env var over storing SGDB keys in config files.

## 📚 Docs
- Install: [docs/client-install.md](docs/client-install.md)
- Server deploy: [docs/deployment-server.md](docs/deployment-server.md)
- Sync behavior: [docs/cli-sync.md](docs/cli-sync.md)
- Config + env overrides: [docs/config-and-state.md](docs/config-and-state.md)
- Platform support + templates: [docs/platform-support.md](docs/platform-support.md)
- Architecture: [docs/architecture.md](docs/architecture.md)
- Steam behavior: [docs/steam-integration.md](docs/steam-integration.md)
- Server API: [docs/server-api.md](docs/server-api.md)
- Operational runbook: [docs/runbook.md](docs/runbook.md)
- Release + pre-public audit flow: [docs/release-process.md](docs/release-process.md)

