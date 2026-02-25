# Client Install and Upgrade

Platform status and recommended templates:
- [Platform Support (v1)](platform-support.md)

## Linux (distro-agnostic) via pip

### Install from GitHub Release wheel
```bash
python3 -m pip install --user --upgrade "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"
```

### Upgrade
```bash
python3 -m pip install --user --upgrade "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"
```

### Uninstall
```bash
python3 -m pip uninstall gamehub
```

### Smoke check
```bash
gamehub --help
gamehub sync --help
```

### Default config location
- If `--config` is not supplied, GAMEHUB resolves config in this order:
1. `./config.toml`
2. `~/.gamehub/config.toml`

### Linux first-run config checklist
1. Set `steam.userdata_dir` in your config (`~/.gamehub/config.toml` by default) for deterministic profile targeting (or export `GAMEHUB_STEAM_USERDATA_DIR`).
2. Choose Linux emulator install strategy in `[linux]`:
   - `emulator_install_backend = "auto"` (default)
     - auto order: immutable/Bazzite/SteamOS-style hosts `flatpak` first, then Fedora `dnf`, Debian/Ubuntu `apt-get`, `flatpak`, then configured command backend
   - `emulator_install_backend = "flatpak"` (good default for immutable Linux hosts)
   - `emulator_install_backend = "dnf"`, `"apt"`, or `"command"` as needed
3. Optional: set `[linux]` path overrides (`retroarch_*`, `pcsx2_*`, `dolphin_user_path`) when your emulator profile paths are non-standard.
4. Run:
```bash
gamehub sync --dry-run --skip-steam --verbose
```
5. Run first non-`--skip-steam` sync from a desktop session so Steam can relaunch after config mutation.
6. If you used older preview/branch builds before recent controller profile fixes, run one reseed sync to refresh defaults:
```bash
gamehub sync --reseed-profiles
```
7. If RetroArch games do not launch, set `[linux].retroarch_cfg_path` or `[linux].retroarch_cores_dir` explicitly and re-run sync.
8. For Flatpak PCSX2, sync writes `PCSX2.ini` and mirrors BIOS into `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios` by default (unless you set an explicit BIOS override). Verify with:
```bash
grep -n "Bios" ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini
ls ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios
```
9. PCSX2 controller bindings and hotkeys are applied at launch via controller profiles when `launch_autoconfig` is enabled. After launching a PS2 title once via Steam, verify with:
```bash
grep -nE "^\[Pad1\]|^\[Pad2\]|^Type =|^Cross =|^Start =" ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini
grep -n "^OpenPauseMenu =" ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini
```
   - Use `--reseed-profiles` to overwrite the default profile files if you need to reset them.
10. Dolphin runtime bootstrap (GC/Wii) writes display/confirm/background input flags in `Dolphin.ini`. Controller profiles apply input + hotkey config at launch. Flatpak example:
```bash
grep -nE "^\[Display\]|^Fullscreen =|^\[Interface\]|^(ConfirmStop|BackgroundInput) =" ~/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu/Config/Dolphin.ini
```
After launching a GC/Wii title once, verify input + hotkeys:
```bash
grep -nE "^\[Hotkeys1\]|^Keys/(Stop|Exit) =" ~/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu/Config/Hotkeys.ini
grep -n "^Device =" ~/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu/Config/GCPadNew.ini
```
   - Controller exit default is `Back+Start` (pad1/pad2) and is applied via controller profiles.
   - On Linux, controller profiles prefer evdev device roots (for example `evdev/0/Xbox Wireless Controller`) and fall back to `SDL/<n>/Gamepad` when evdev cannot be detected.
   - Dolphin Xbox profile defaults now include Wii quick actions `R1 -> A` and `R2 -> B`; GameCube keeps `R2` on the right trigger path.
   - Existing Dolphin input files are preserved once present; controller profile apply reconciles managed stop/exit hotkeys.
11. RetroArch menu combo bootstrap sets `Start+Select` when a writable RetroArch config file is discovered. Verify with:
```bash
grep -n "^input_menu_toggle_gamepad_combo =" ~/.var/app/org.libretro.RetroArch/config/retroarch/retroarch.cfg ~/.config/retroarch/retroarch.cfg 2>/dev/null
```
12. N3DS Azahar runtime bootstrap sets `fullscreen=true` and `confirmClose=false` in `qt-config.ini`. Flatpak example:
```bash
grep -nE "^(fullscreen|confirmClose)=" ~/.var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini
```
   - Linux Flatpak GUID handling:
     - runtime GUID probe is preferred
     - when runtime GUID is unavailable, GAMEHUB preserves existing GUIDs and otherwise keeps port-only SDL mappings
   - Optional quick probe:
```bash
python - <<'PY'
from pathlib import Path
from gamehub_cli import controller_apply as ca
qt = Path.home()/".var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini"
if not qt.exists():
    qt = Path.home()/".var/app/org.azahar_emu.Azahar/config/azahar/qt-config.ini"
lines = ca.read_ini_lines(qt)
_guid, port = ca._azahar_detect_sdl_identity(lines)
print("runtime_guid:", ca._probe_azahar_flatpak_guid(port=port))
print("host_guid:", ca._discover_linux_sdl_guid(port=port))
PY
```
13. N3DS Linux native controller mode uses an Azahar wrapper hook by default:
```bash
gamehub sync --config ./config.bazzite.toml --verbose --skip-steam
```
   - The wrapper closes Azahar on strict `Select+Start` using:
     - `/dev/input/js*` joystick events, and
     - `/dev/input/event*` fallback (`BTN_SELECT` + `BTN_START`) when needed.
   - Optional overrides:
```bash
export GAMEHUB_AZAHAR_LINUX_EXIT_HOOK=true
export GAMEHUB_AZAHAR_EXIT_BUTTON_SELECT=4
export GAMEHUB_AZAHAR_EXIT_BUTTON_START=6
# Optional explicit joystick device:
# export GAMEHUB_AZAHAR_EXIT_JS_DEVICE=/dev/input/js0
```
14. N3DS Steam Input templates on Steam Deck:
   - GAMEHUB auto-syncs managed per-title Steam Input templates for `N3DS` shortcuts during non-dry sync.
   - Use `gamehub sync --reseed-profiles` to refresh managed Deck template seeds when needed.

## Steam Deck notes
- Start from template [docs/templates/config.steamdeck.template.toml](templates/config.steamdeck.template.toml).
- Steam Deck installs may use `~/.steam/steam/userdata` or `~/.local/share/Steam/userdata`.
- Keep config explicit with `steam.userdata_dir` and optional `steam.steam_id` to avoid profile ambiguity on shared devices.
- If you keep ROMs on microSD, set `paths.roms_dir` to `/run/media/deck/<SD_CARD_LABEL>/...`.
- Steam Deck should use Flatpak emulator management by default:
```toml
[linux]
emulator_install_backend = "flatpak"
flatpak_remote = "flathub"
```
- Steam Deck support is fully validated for the built-in controller path. External Xbox controller support on Deck is planned for a later release.
- Game Mode note: Steam relaunch/foreground behavior can differ from Desktop Mode; if relaunch is flaky during validation, run with `--skip-steam-relaunch` and reopen Steam manually.
- Detailed implementation notes: [docs/steamdeck-support-plan.md](steamdeck-support-plan.md).

## Windows standalone EXE

1. Download `gamehub-windows-amd64.exe` from GitHub Releases.
2. Run from PowerShell:

```powershell
.\gamehub-windows-amd64.exe --help
.\gamehub-windows-amd64.exe sync --help
.\gamehub-windows-amd64.exe sync --config .\config.toml --dry-run --skip-steam
```

## Notes
- `--skip-steam` is recommended for first validation runs.
- `--skip-steam-relaunch` keeps Steam updates enabled but leaves Steam closed after sync.
- For strict Steam update safety, include `--require-steam-closed`.

## Controller profile overrides
- Non-RetroArch launches (`PCSX2`, `Dolphin`, `Azahar`) can apply controller profiles at launch time.
- Default profile root:
  - `<paths.gamehub_dir>/controller_profiles`
- Optional config/env overrides:
  - `[controllers].launch_autoconfig`
  - `[controllers].profiles_dir`
  - `GAMEHUB_CONTROLLER_LAUNCH_AUTOCONFIG`
  - `GAMEHUB_CONTROLLER_PROFILES_DIR`
- Profile layout:
  - `pcsx2/<profile>/PCSX2.ini`
  - `dolphin/<profile>/GCPadNew.ini`
  - `dolphin/<profile>/WiimoteNew.ini`
  - `dolphin/<profile>/Hotkeys.ini`
  - `azahar/<profile>/qt-config.ini`
- Profiles:
  - `kbm`
  - `xbox_1p`
  - `xbox_2p`

### Windows value-capture checkpoint
Before customizing Windows mappings, inspect your current emulator config values and keep them for rollback/diff:

```powershell
# PCSX2
Get-Content "$env:USERPROFILE\\Documents\\PCSX2\\inis\\PCSX2.ini"

# Dolphin
Get-Content "$env:APPDATA\\Dolphin Emulator\\Config\\GCPadNew.ini"
Get-Content "$env:APPDATA\\Dolphin Emulator\\Config\\WiimoteNew.ini"
Get-Content "$env:APPDATA\\Dolphin Emulator\\Config\\Hotkeys.ini"

# Azahar
Get-Content "$env:APPDATA\\Azahar\\config\\qt-config.ini"
```
