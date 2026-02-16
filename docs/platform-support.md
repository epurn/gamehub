# Platform Support (v1)

## Validation Status
- Windows: verified
- Bazzite: tested
- SteamOS (Deck): untested
- Fedora: untested
- Ubuntu: untested

## Recommended Config Templates
- Windows:
  - [docs/templates/config.windows.template.toml](templates/config.windows.template.toml)
- Bazzite:
  - [docs/templates/config.bazzite.template.toml](templates/config.bazzite.template.toml)
- SteamOS (Deck, untested):
  - [docs/templates/config.steamdeck.template.toml](templates/config.steamdeck.template.toml)

Legacy/general templates are still available:
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

### SteamOS (Deck), Fedora, Ubuntu (untested)
- These are not validated release targets for v1.
- SteamOS (Deck): start from:
  - [docs/templates/config.steamdeck.template.toml](templates/config.steamdeck.template.toml)
- Fedora/Ubuntu: start from:
  - [docs/templates/config.linux.template.toml](templates/config.linux.template.toml)
- Then review:
  - [config-and-state.md](config-and-state.md)
  - [cli-sync.md](cli-sync.md)
  - [steam-integration.md](steam-integration.md)
