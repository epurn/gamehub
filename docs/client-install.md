# Client Install and Upgrade

Platform status and recommended templates:
- [Platform Support (v1)](platform-support.md)
- Apple Silicon macOS is a supported release platform and uses the same universal wheel as Linux; Windows ships a standalone EXE.

## macOS (Apple Silicon) via pip

### Install from GitHub Release wheel
```bash
# Outside a virtualenv:
python3 -m pip install --user --upgrade "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"

# Inside an active virtualenv:
python3 -m pip install --upgrade "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"
```

### Upgrade
```bash
# Outside a virtualenv:
python3 -m pip install --user --upgrade "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"

# Inside an active virtualenv:
python3 -m pip install --upgrade "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"
```

### Install latest release dynamically
```bash
LATEST_TAG="$(curl -fsSL https://api.github.com/repos/<org>/<repo>/releases/latest | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')"
LATEST_VER="${LATEST_TAG#v}"

# Outside a virtualenv:
python3 -m pip install --user --upgrade "https://github.com/<org>/<repo>/releases/download/${LATEST_TAG}/gamehub-${LATEST_VER}-py3-none-any.whl"

# Inside an active virtualenv:
python3 -m pip install --upgrade "https://github.com/<org>/<repo>/releases/download/${LATEST_TAG}/gamehub-${LATEST_VER}-py3-none-any.whl"
```

If your macOS Python.org install still reports certificate verification failures, run `/Applications/Python 3.14/Install Certificates.command` once for that Python installation and retry.

### Uninstall
```bash
python3 -m pip uninstall gamehub
```

### Smoke check
```bash
gamehub --help
gamehub config --help
gamehub init --help
gamehub sync --help
```

Start from template [docs/templates/config.macos.template.toml](templates/config.macos.template.toml) and save it as `./config.macos.toml`.
You can also generate a starter config with `gamehub config init`; either way, run `gamehub config verify` before `gamehub init`, `gamehub sync`, or `gamehub doctor`.

### macOS first-run install checklist
1. Install native Steam manually first. GAMEHUB integrates with an existing `Steam.app` and never auto-installs Steam.
   - `steam.steam_exe` may point to `~/Applications/Steam.app`, `/Applications/Steam.app`, or the inner `Contents/MacOS/steam_osx` path; lifecycle handling is normalized back to the app bundle.
2. Choose the macOS emulator install backend in `[macos]`:
   - `emulator_install_backend = "auto"` (default) maps to `official`
   - `emulator_install_backend = "official"` installs only official Apple Silicon or universal assets into `~/Applications`
     - the current macOS implementation uses pinned official asset URLs in code; no extra macOS-only asset config is required
   - `emulator_install_backend = "command"` runs your configured `emulator_install_command`
   - `emulator_install_backend = "none"` disables emulator auto-install
3. Supported official macOS auto-install targets are currently:
   - `RetroArch`
   - `Dolphin`
   - `Azahar`
   - `PCSX2`
4. GAMEHUB still prefers native Apple Silicon or universal macOS assets first.
   - For `PCSX2` only, GAMEHUB accepts an Intel-only bundle by default when Rosetta is already installed.
   - Set `[macos].disable_pcsx2_rosetta = true` or `GAMEHUB_MACOS_DISABLE_PCSX2_ROSETTA=true` to force strict native-only `PCSX2` behavior.
   - `RetroArch`, `Dolphin`, `Azahar`, and `Steam` remain native-only.
5. Optional command backend placeholders:
   - `{package}`: canonical install token (`retroarch`, `dolphin`, `azahar`, `pcsx2`)
   - `{emulator}`: emulator name from the index/config
6. Verify config:
```bash
gamehub config verify --config ./config.macos.toml
```
7. Run bootstrap dry-run:
```bash
gamehub init --config ./config.macos.toml --dry-run --verbose
```
8. Run bootstrap:
```bash
gamehub init --config ./config.macos.toml
```
9. RetroArch macOS core provisioning defaults to:
   - cores: `~/Library/Application Support/RetroArch/cores`
   - info: `~/Library/Application Support/RetroArch/info`
   - Apple Silicon buildbot base: `https://buildbot.libretro.com/nightly/apple/osx/arm64/latest/`
10. RetroArch macOS save discovery still checks `~/Documents/RetroArch` first and falls back to `~/Library/Application Support/RetroArch`, but config discovery prefers an existing native config file under `~/Library/Application Support/RetroArch/config/retroarch.cfg` before legacy root-level/document variants. GAMEHUB can materialize deterministic RetroArch save downloads there on first sync even before RetroArch has created the `saves/` tree. If your RetroArch config uses different locations, set `[macos].retroarch_cfg_path`, `[macos].retroarch_cores_dir`, `[macos].retroarch_info_dir`, or `[macos].retroarch_cores_base_url` explicitly and re-run sync.
11. Managed macOS `N64` RetroArch launches now force the tested Apple Silicon fallback `video_driver = "glcore"` plus `mupen64plus-rdp-plugin = "angrylion"` and `mupen64plus-rsp-plugin = "hle"` before launch. When RetroArch already has `config/Mupen64Plus-Next/*.cfg` or existing core, folder, or per-game `.opt` overrides such as `config/Mupen64Plus-Next/Mupen64Plus-Next.opt`, GAMEHUB converges those files too so they cannot supersede the managed baseline. If GAMEHUB cannot resolve `retroarch.cfg` or cannot find `mupen64plus_next_libretro.dylib` in the configured macOS cores directory, it blocks that launch and prints an actionable warning instead of continuing into the known black-screen failure.
12. Dolphin macOS runtime/save discovery prefers an existing `~/.local/share/dolphin-emu` root first and otherwise falls back to `~/Library/Application Support/Dolphin`. If your Dolphin user dir is elsewhere, set `[macos].dolphin_user_path` explicitly.
13. Azahar macOS save/runtime discovery prefers existing native-style paths first: `~/.local/share/azahar-emu/sdmc` for saves and `~/.config/azahar-emu/qt-config.ini` for runtime config. If those do not exist, GAMEHUB falls back to `~/Library/Application Support/Azahar`.
14. Managed macOS Azahar launches pin to `~/Applications/Azahar.app` when that bundle exists, and GAMEHUB opens the ROM as a document with that bundle before falling back to CLI-style launch. This matches the app's declared macOS document handling more closely than relying on app-name lookup or ROM `--args` alone.
15. Minimal macOS smoke after the template is filled:
```bash
gamehub config verify --config ./config.macos.toml
gamehub init --config ./config.macos.toml --dry-run --verbose
gamehub sync --config ./config.macos.toml --dry-run --verbose --require-steam-closed
gamehub sync --config ./config.macos.toml --verbose --require-steam-closed
```
16. Release-validation note: before cutting a release, revalidate the pinned macOS official asset URLs in code and run the macOS lane in [release-final-validation-playbook.md](release-final-validation-playbook.md).

## Linux (distro-agnostic) via pip

### Install from GitHub Release wheel
```bash
# Outside a virtualenv:
python3 -m pip install --user --upgrade "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"

# Inside an active virtualenv:
python3 -m pip install --upgrade "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"
```

### Upgrade
```bash
# Outside a virtualenv:
python3 -m pip install --user --upgrade "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"

# Inside an active virtualenv:
python3 -m pip install --upgrade "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"
```

### Install latest release dynamically
```bash
LATEST_TAG="$(curl -fsSL https://api.github.com/repos/<org>/<repo>/releases/latest | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')"
LATEST_VER="${LATEST_TAG#v}"

# Outside a virtualenv:
python3 -m pip install --user --upgrade "https://github.com/<org>/<repo>/releases/download/${LATEST_TAG}/gamehub-${LATEST_VER}-py3-none-any.whl"

# Inside an active virtualenv:
python3 -m pip install --upgrade "https://github.com/<org>/<repo>/releases/download/${LATEST_TAG}/gamehub-${LATEST_VER}-py3-none-any.whl"
```

### Uninstall
```bash
python3 -m pip uninstall gamehub
```

### Smoke check
```bash
gamehub --help
gamehub config --help
gamehub init --help
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
4. Verify config:
```bash
gamehub config verify --config ./config.toml
```
5. Run bootstrap dry-run:
```bash
gamehub init --dry-run --verbose
```
6. Run bootstrap:
```bash
gamehub init
```
7. Run first non-`--skip-steam` sync from a desktop session so Steam can relaunch after config mutation.
8. If you need to reset managed controller or Deck template defaults, run one reseed init:
```bash
gamehub init --reseed-profiles
```
9. If RetroArch games do not launch, set `[linux].retroarch_cfg_path` or `[linux].retroarch_cores_dir` explicitly and re-run sync.
10. For Flatpak PCSX2, sync writes `PCSX2.ini` and mirrors BIOS into `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios` by default (unless you set an explicit BIOS override). Verify with:
```bash
grep -n "Bios" ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini
ls ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios
```
11. PCSX2 controller bindings and hotkeys are applied at launch via controller profiles when `launch_autoconfig` is enabled. After launching a PS2 title once via Steam, verify with:
```bash
grep -nE "^\[Pad1\]|^\[Pad2\]|^Type =|^Cross =|^Start =" ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini
grep -n "^OpenPauseMenu =" ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini
```
   - Use `--reseed-profiles` to overwrite the default profile files if you need to reset them.
12. Dolphin runtime bootstrap (GC/Wii) writes display/confirm/background input flags in `Dolphin.ini`. Controller profiles apply input + hotkey config at launch. Flatpak example:
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
13. RetroArch menu combo bootstrap sets `Start+Select` when a writable RetroArch config file is discovered. Verify with:
```bash
grep -n "^input_menu_toggle_gamepad_combo =" ~/.var/app/org.libretro.RetroArch/config/retroarch/retroarch.cfg ~/.config/retroarch/retroarch.cfg 2>/dev/null
```
14. N3DS Azahar runtime bootstrap sets `fullscreen=true`, `confirmClose=false`, and the managed quit shortcut `Shortcuts\Main%20Window\Exit%20Citra\KeySeq=Esc` in `qt-config.ini`. Flatpak example:
```bash
grep -nE "^(fullscreen|confirmClose|Shortcuts\\\\Main%20Window\\\\Exit%20Citra\\\\KeySeq)=" ~/.var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini
```
   - Linux Flatpak GUID handling:
     - runtime GUID probe is preferred
     - when runtime GUID is unavailable, GAMEHUB preserves existing GUIDs and otherwise keeps port-only SDL mappings
   - Optional quick probe:
```bash
python - <<'PY'
from pathlib import Path
from gamehub_cli.controllers import sdl_guid
from gamehub_cli.firmware.pcsx2_ini import read_ini_lines
qt = Path.home()/".var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini"
if not qt.exists():
    qt = Path.home()/".var/app/org.azahar_emu.Azahar/config/azahar/qt-config.ini"
lines = read_ini_lines(qt)
_guid, port = sdl_guid._azahar_detect_sdl_identity(lines)
print("runtime_guid:", sdl_guid._probe_azahar_flatpak_guid(port=port))
print("host_guid:", sdl_guid._discover_linux_sdl_guid(port=port))
PY
```
14. N3DS Linux Flatpak Steam shortcuts default to a sync-emitted Azahar exit hook wrapper:
```bash
gamehub sync --config ./config.bazzite.toml --verbose
```
   - During the Steam stage, GAMEHUB emits `python -m gamehub_cli.controllers.azahar_exit_hook --app-id org.azahar_emu.Azahar --rom ...` by default.
   - The Linux Azahar wrapper closes Azahar on strict `Select+Start` using:
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
   - `GAMEHUB_AZAHAR_LINUX_EXIT_HOOK` changes the Steam launch command emitted by sync. The Windows-only `GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK` controls the `shortcut-launch` runtime hook instead.
   - Quick Bazzite verification:
     - connect an external Xbox controller
     - launch one Azahar title from Steam
     - verify `Start+Select` still exits cleanly
15. N3DS Steam Input templates on Steam Deck:
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
2. Create a real config file first with `gamehub config init` or a platform template, then verify it.
3. Run from PowerShell:

```powershell
.\gamehub-windows-amd64.exe --help
.\gamehub-windows-amd64.exe config verify --config .\config.toml
.\gamehub-windows-amd64.exe init --help
.\gamehub-windows-amd64.exe init --config .\config.toml --dry-run
.\gamehub-windows-amd64.exe sync --config .\config.toml --dry-run --skip-steam
```

## Notes
- `gamehub config init` or a platform template should create the real config file first, and `gamehub config verify` should succeed before `gamehub init`.
- `gamehub init` is the required runtime bootstrap command on fresh installs after config exists.
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
- Managed Azahar profiles own the Qt quit shortcut `Shortcuts\Main%20Window\Exit%20Citra\KeySeq=Esc`; existing managed `qt-config.ini` files are repaired to the same value during controller convergence, while the separate `Start+Select` exit-hook wrapper behavior remains unchanged.
- Managed Azahar controller profiles also seed stick deadzones in the owned `qt-config.ini` bindings, so the default managed path does not rely on zero-deadzone analog input.

### Azahar control verification
1. Run a non-dry `gamehub sync`, then launch one managed `Azahar` title from Steam.
2. Verify `Esc` quits the managed Azahar session, and verify `Start+Select` still exits cleanly on hosts where the Azahar exit hook is enabled.
3. On Steam Deck, verify the managed `Esc`/`Start+Select` path only.

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
