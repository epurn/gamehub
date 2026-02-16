# GAMEHUB 🎮

[![Latest Release](https://img.shields.io/github/v/release/epurn/gamehub?display_name=tag)](https://github.com/epurn/gamehub/releases)
[![Audit Regression Gates](https://github.com/epurn/gamehub/actions/workflows/audit-regression-gates.yml/badge.svg)](https://github.com/epurn/gamehub/actions/workflows/audit-regression-gates.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License](https://img.shields.io/github/license/epurn/gamehub)](LICENSE)

Docker-first home server + client CLI that syncs emulator libraries into Steam non-Steam shortcuts, system collections, and artwork.

## ✅ v1 Platform Status
- Windows: verified
- Bazzite: tested
- SteamOS (Deck): untested
- Fedora/Ubuntu: untested

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

Supported systems in v1:
- `GB`, `GBA`, `GBC`, `GEN_MD`, `N64`, `NDS`, `NES`, `PSX`, `SNES`, `GC`, `Wii`, `PS2`

## ⚡ Quick Start
1. Deploy server ([`docker/compose.yaml`](docker/compose.yaml)) and confirm `GET /v1/index` works.
2. Install client (Windows EXE or Linux wheel).
3. Create `config.toml` from a template:
   - Windows: [`docs/templates/config.windows.template.toml`](docs/templates/config.windows.template.toml)
   - Bazzite: [`docs/templates/config.bazzite.template.toml`](docs/templates/config.bazzite.template.toml)
   - Steam Deck (untested): [`docs/templates/config.steamdeck.template.toml`](docs/templates/config.steamdeck.template.toml)
4. Run dry-run:
```powershell
gamehub sync --config .\config.toml --dry-run --verbose --require-steam-closed
# Windows standalone EXE:
# .\gamehub-windows-amd64.exe sync --config .\config.toml --dry-run --verbose --require-steam-closed
```
5. Run real sync:
```powershell
gamehub sync --config .\config.toml --verbose --require-steam-closed
# Windows standalone EXE:
# .\gamehub-windows-amd64.exe sync --config .\config.toml --verbose --require-steam-closed
```

## 📝 Notes
- Server ROM layout must be flat per system: `roms/<system>/<title.ext>`.
- Nested ROM directories under a system are rejected.
- ROM/firmware are server-first only (no internet ROM/BIOS fetching).
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
