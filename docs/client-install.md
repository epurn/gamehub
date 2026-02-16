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
3. legacy fallback: platform config dir `gamehub/config.toml`

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
6. If RetroArch games do not launch, set `[linux].retroarch_cfg_path` or `[linux].retroarch_cores_dir` explicitly and re-run sync.
7. For Flatpak PCSX2, sync writes `PCSX2.ini` and mirrors BIOS into `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios` by default (unless you set an explicit BIOS override). Verify with:
```bash
grep -n "Bios" ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini
ls ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios
```
8. Linux PCSX2 controller autoconfig writes generic SDL mappings for Pad1+Pad2 by default. Verify with:
```bash
grep -nE "^\[Pad1\]|^\[Pad2\]|^Type =|^Cross =|^Start =" ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini
grep -n "^OpenPauseMenu =" ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini
```
   - If Pad1 was still keyboard-defaulted, re-run sync once on the updated client build; bootstrap now rewrites keyboard/mouse defaults to SDL controller bindings.
   - `OpenPauseMenu` is bootstrapped to `SDL-0/Back & SDL-0/Start` when missing or keyboard-only.
9. Dolphin runtime bootstrap (GC/Wii) writes fullscreen/controller/hotkey config under the resolved Dolphin user path. Flatpak example:
```bash
grep -nE "^\[Display\]|^Fullscreen =|^\[Interface\]|^(ConfirmStop|BackgroundInput) =" ~/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu/Config/Dolphin.ini
grep -nE "^\[Hotkeys1\]|^Keys/(Stop|Exit) =" ~/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu/Config/Hotkeys.ini
grep -n "^Device =" ~/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu/Config/GCPadNew.ini
```
   - Controller exit default is `Back+Start` (pad1/pad2).
   - On Linux, GAMEHUB prefers evdev device roots (for example `evdev/0/Xbox Wireless Controller`) and falls back to `SDL/<n>/Gamepad` when evdev cannot be detected.
   - Existing Dolphin input files are preserved once present; sync reconciles managed stop/exit hotkeys each run.
10. RetroArch menu combo bootstrap sets `Start+Select` when a writable RetroArch config file is discovered. Verify with:
```bash
grep -n "^input_menu_toggle_gamepad_combo =" ~/.var/app/org.libretro.RetroArch/config/retroarch/retroarch.cfg ~/.config/retroarch/retroarch.cfg 2>/dev/null
```

## Steam Deck notes
- Start from template [docs/templates/config.steamdeck.template.toml](templates/config.steamdeck.template.toml).
- Steam Deck installs may use `~/.steam/steam/userdata` or `~/.local/share/Steam/userdata`.
- Keep config explicit with `steam.userdata_dir` and optional `steam.steam_id` to avoid profile ambiguity on shared devices.
- If emulators are Flatpak-based, prefer:
```toml
[linux]
emulator_install_backend = "flatpak"
```

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
