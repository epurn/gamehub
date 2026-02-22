# Steam Deck Support Plan (Research + Execution)

## External research references used
- Flatpak sandbox path conventions (`XDG_CONFIG_HOME` and `XDG_DATA_HOME` map into `~/.var/app/<app-id>/config|data`).
  - https://docs.flatpak.org/en/latest/conventions.html
- Steam Deck Linux profile path behavior and SteamOS desktop/game mode context (Steam Deck community/Arch references).
  - https://wiki.archlinux.org/title/Steam_Deck

## Goals
1. Make Steam Deck a first-class Linux target for GAMEHUB sync operations.
2. Keep Flatpak-based emulator/runtime paths deterministic.
3. Improve Steam userdata discovery for SteamOS path variants.
4. Default controller autoconfig to the built-in Steam Deck controller (while preserving Xbox support).
5. Document Game Mode/Desktop caveats and operator workflow.

## Implementation plan

### Phase 1 — SteamOS path and runtime alignment
- Set Steam Deck template defaults to Flatpak backend (`emulator_install_backend = "flatpak"`, `flatpak_remote = "flathub"`).
- Keep mutable state in `/home/deck/GameHub` (ROM cache, firmware staging, SGDB cache).
- Expand Steam userdata candidate discovery to include `~/.steam/root/userdata` and Flatpak-local Steam userdata variants.

### Phase 2 — Controller default policy for Steam Deck
- Detect Steam Deck platform via `/etc/os-release` markers (`steamos`, `steamdeck`, `holo`) with DMI vendor fallback (`Valve`).
- Extend Linux controller discovery for Steam Deck mode to include built-in controller names:
  - `Steam Deck Controller`
  - `Steam Virtual Gamepad`
  - `Steam Controller` / `Valve Software` / `Neptune` variants
- Preserve Xbox detection paths and profile mapping behavior.

### Phase 3 — Validation and test coverage
- Add detection tests for Steam Deck controller-name handling (enabled/disabled path).
- Add Steam userdata candidate test for Steam Deck path variants.
- Re-run focused test subset for controller and Steam integration modules.

### Phase 4 — Operational guidance
- Update template and docs to clarify:
  - Steam Deck path variants
  - Flatpak-first expectation
  - controller autoconfig defaults
  - Game Mode caveat: Steam lifecycle handling can differ from desktop sessions

## Execution status
- ✅ Phase 1 implemented
- ✅ Phase 2 implemented
- ✅ Phase 3 implemented
- ✅ Phase 4 implemented
