# Platform Support (v1)

Current operator workflows and config details live in:
- [client-install.md](client-install.md)
- [cli-sync.md](cli-sync.md)
- [config-and-state.md](config-and-state.md)

This page is the short validation matrix only.

## Validation Status
- Windows: verified
- macOS: release target (Apple Silicon full parity implemented)
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

### macOS (Apple Silicon release target)
- macOS support is in scope for v1.
- Start from:
  - [docs/templates/config.macos.template.toml](templates/config.macos.template.toml)
- Validated host contract targets the latest stable Apple Silicon macOS release with native Steam.
- Steam auto-discovery covers `~/Applications/Steam.app`, `/Applications/Steam.app`, and `~/Library/Application Support/Steam/userdata`.
- `steam.steam_exe` may point to either `Steam.app` or `Steam.app/Contents/MacOS/steam_osx`; GAMEHUB normalizes lifecycle actions to the app bundle.
- Prefer `~/Applications` for admin-free Steam/emulator app installs; `/Applications` remains a supported native install location.
- GAMEHUB still prefers native Apple Silicon or universal emulator builds.
- `PCSX2` may fall back to Intel-only macOS builds when Rosetta is already installed; set `[macos].disable_pcsx2_rosetta = true` to force strict native-only `PCSX2` behavior.
- `RetroArch`, `Dolphin`, `Azahar`, `Steam`, and Intel Mac hosts remain outside the Rosetta fallback path.
- Operator bootstrap and smoke commands live in [client-install.md](client-install.md).
- Final macOS release-validation lane lives in [release-final-validation-playbook.md](release-final-validation-playbook.md).

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
