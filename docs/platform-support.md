# Platform Support (v1)

Current operator workflows and config details live in:
- [client-install.md](client-install.md)
- [cli-sync.md](cli-sync.md)
- [config-and-state.md](config-and-state.md)

This page is the short validation matrix only.

## Validation Status
- Windows: verified
- macOS: partial parity (`MACOS-CLI-01` through `MACOS-CLI-04`, `MACOS-CLI-07` complete; save/controller/docs lanes pending)
- Bazzite: tested
- SteamOS (Deck): verified
- Fedora: untested
- Ubuntu: untested

## Recommended Config Templates
- Windows:
  - [docs/templates/config.windows.template.toml](templates/config.windows.template.toml)
- macOS:
  - [docs/templates/config.macos.template.toml](templates/config.macos.template.toml)
- Bazzite:
  - [docs/templates/config.bazzite.template.toml](templates/config.bazzite.template.toml)
- SteamOS (Deck):
  - [docs/templates/config.steamdeck.template.toml](templates/config.steamdeck.template.toml)

Legacy/general templates are still available:
- Steam Deck implementation details and research-backed assumptions:
  - [docs/steamdeck-support-plan.md](steamdeck-support-plan.md)
- [docs/templates/config.windows.template.toml](templates/config.windows.template.toml)
- [docs/templates/config.linux.template.toml](templates/config.linux.template.toml)

## Notes by Platform

### Windows (verified)
- Use the Windows template as-is, then set:
  - `[server].url`
  - `[paths].gamehub_dir`
  - optional `[steam].steam_id` for deterministic profile selection

### Bazzite (tested)
- Use the Bazzite template defaults:
  - `steam.userdata_dir` under Flatpak Steam path
  - `[linux].emulator_install_backend = "flatpak"`
  - `[linux].flatpak_remote = "flathub"`
- Keep Bazzite sync runs in an active desktop session so Steam relaunch works.

### macOS (partial parity, validation in progress)
- macOS support is in scope for v1.
- Start from:
  - [docs/templates/config.macos.template.toml](templates/config.macos.template.toml)
- Current frozen host contract targets the latest stable Apple Silicon macOS release with native Steam.
- Prefer `~/Applications` for admin-free Steam/emulator app installs; `/Applications` remains an expected native install location.
- GAMEHUB still prefers native Apple Silicon or universal emulator builds.
- `PCSX2` may fall back to Intel-only macOS builds when Rosetta is already installed; set `[macos].disable_pcsx2_rosetta = true` to force strict native-only `PCSX2` behavior.
- `RetroArch`, `Dolphin`, `Azahar`, `Steam`, and Intel Mac hosts remain outside the Rosetta fallback path.
- Landed on this branch: config contract, native Steam lifecycle, managed shortcut bundle launching, runtime-root discovery, and native installer/core provisioning.
- Still open: save-sync/runtime mutation parity, controller autoconfig parity, and final release-validation docs.

### SteamOS (Deck) (verified)
- Start from:
  - [docs/templates/config.steamdeck.template.toml](templates/config.steamdeck.template.toml)
- Built-in Steam Deck controller support is validated.
- External Xbox controller support on Deck is planned for a later update.

### Fedora, Ubuntu (untested)
- These are not validated release targets for v1.
- Start from:
  - [docs/templates/config.linux.template.toml](templates/config.linux.template.toml)
- Then review:
  - [config-and-state.md](config-and-state.md)
  - [cli-sync.md](cli-sync.md)
  - [steam-integration.md](steam-integration.md)
