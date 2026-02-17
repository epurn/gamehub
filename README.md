# GAMEHUB 🎮

[![Latest Tag](https://img.shields.io/github/v/tag/epurn/gamehub?sort=semver&label=latest%20tag)](https://github.com/epurn/gamehub/tags)
[![Audit Regression Gates](https://github.com/epurn/gamehub/actions/workflows/audit-regression-gates.yml/badge.svg)](https://github.com/epurn/gamehub/actions/workflows/audit-regression-gates.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License](https://img.shields.io/github/license/epurn/gamehub?branch=main&label=license)](LICENSE)

Docker-first home server + client CLI that syncs emulator libraries into Steam non-Steam shortcuts, system collections, and artwork.

## ✅ v1 Compatibility Matrix

### Platform support
| Platform | Status |
| --- | --- |
| Windows | ✅ |
| Bazzite | ✅ |
| SteamOS (Deck) | ⚠️ |
| Other Linux distros (Fedora/Ubuntu/etc.) | ⚠️ |
| macOS | ❌ |

### Controller support
| Platform | Xbox controllers |
| --- | --- |
| Bazzite | ✅ |
| Windows | ❌ |
| SteamOS (Deck) | ❌ |
| Other Linux distros (Fedora/Ubuntu/etc.) | ❌ |
| macOS | ❌ |

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

Supported systems in v1.1:
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
- Steam Deck (untested): [`docs/templates/config.steamdeck.template.toml`](docs/templates/config.steamdeck.template.toml)

Linux install from latest release wheel:
```bash
LATEST_TAG="$(python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://api.github.com/repos/epurn/gamehub/releases/latest'))['tag_name'])")"
LATEST_VER="${LATEST_TAG#v}"
python3 -m pip install --user --upgrade "https://github.com/epurn/gamehub/releases/download/${LATEST_TAG}/gamehub-${LATEST_VER}-py3-none-any.whl"
```

Linux sync:
```bash
gamehub sync --dry-run --require-steam-closed
gamehub sync --require-steam-closed --skip-steam-relaunch
```

Windows install + sync:
```powershell
Invoke-WebRequest https://github.com/epurn/gamehub/releases/latest/download/gamehub-windows-amd64.exe -OutFile .\gamehub-windows-amd64.exe
.\gamehub-windows-amd64.exe sync --dry-run --require-steam-closed
.\gamehub-windows-amd64.exe sync --require-steam-closed
```

More detail: [docs/client-install.md](docs/client-install.md), [docs/config-and-state.md](docs/config-and-state.md), [docs/cli-sync.md](docs/cli-sync.md)

## 🖥️ Server Deployment (Latest Release)
Place `.env.production` in the repo root (next to [`docker/compose.yaml`](docker/compose.yaml)).

```powershell
Copy-Item .env.production.template .env.production
# Edit .env.production:
# - GAMEHUB_DATA_HOST_PATH=<host path containing roms/ and firmware/>
# - GAMEHUB_SERVER_PORT=8000
# - GAMEHUB_IMAGE_TAG=latest
docker compose -f docker/compose.yaml --env-file .env.production pull gamehub-server
docker compose -f docker/compose.yaml --env-file .env.production up -d
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
- Steam behavior: [docs/steam-integration.md](docs/steam-integration.md)
- Server API: [docs/server-api.md](docs/server-api.md)
- Operational runbook: [docs/runbook.md](docs/runbook.md)
- Release + pre-public audit flow: [docs/release-process.md](docs/release-process.md)
