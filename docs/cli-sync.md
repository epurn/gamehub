# CLI Sync

Command:
```powershell
.\venv\Scripts\python.exe -m gamehub_cli.main sync [flags]
```

## Flags
- `--dry-run`: build and print plan only
- `--verbose`: longer network timeout and extra output context
- `--verify`: re-hash local files before diff decisions
- `--skip-steam`: run sync downloads/state updates but skip Steam lifecycle and Steam file updates
- `--skip-steam-relaunch`: apply Steam updates but do not relaunch Steam at end
- `--require-steam-closed`: fail if Steam cannot be closed before config writes
- `--config <path>`: TOML config path override

Steam close behavior:
- non-dry sync attempts to close Steam first
- if Steam cannot be closed:
  - with `--require-steam-closed`: sync fails
  - without it: Steam update stage is skipped for safety

## Pipeline order
1. Load config and local state
2. Fetch and validate `/v1/index`
   - transient index fetch failures are retried with exponential backoff (`[server].index_fetch_attempts`, `[server].index_retry_backoff_seconds`)
   - per-attempt index timeout can be set via `[server].index_timeout_seconds` (defaults to current transport timeout behavior)
3. Ensure required emulators are available:
   - detects missing emulator binaries from index metadata
   - Windows detection checks executable PATH, common install locations, and uninstall registry locations (not only winget package metadata)
   - on Windows non-dry-run, attempts auto-install via `winget` for known emulators (`retroarch`, `pcsx2`)
   - Azahar installs on Windows skip winget and use a pinned GitHub release installer URL (override with `GAMEHUB_AZAHAR_WINDOWS_INSTALLER_URL`)
   - Dolphin installs on Windows skip winget entirely and use the latest official Dolphin Windows x64 release archive (`dl.dolphin-emu.org`)
   - if required Dolphin resolves to a known legacy Windows winget path/version (`<=5.0`), sync fails fast with an actionable upgrade error instead of emitting legacy `/b` parser args
   - on Linux non-dry-run, uses config-first install backend (`[linux].emulator_install_backend`):
     - `auto` (default): Fedora + `dnf`, then Debian/Ubuntu + `apt-get`, then `flatpak`, then configured command backend
     - `dnf`: force Fedora package install behavior
     - `apt`: force Debian/Ubuntu package install behavior (`apt-get install -y`)
     - `flatpak`: install `org.libretro.RetroArch`, `net.pcsx2.PCSX2`, `org.DolphinEmu.dolphin-emu`, `org.azahar_emu.Azahar` (remote optional via `[linux].flatpak_remote` / `GAMEHUB_LINUX_FLATPAK_REMOTE`)
     - `command`: run `[linux].emulator_install_command` for each missing emulator (supports `{package}` and `{emulator}` tokens)
     - `none`: disable Linux auto-install (sync prints actionable missing emulator output)
   - when Linux backend is flatpak-preferred (`flatpak`, or immutable-host `auto`), Dolphin and Azahar are treated as Flatpak-required; native installs are not used as substitutes for `org.DolphinEmu.dolphin-emu` / `org.azahar_emu.Azahar`, and sync fails fast if those Flatpak apps are unavailable
   - Steam shortcuts resolve emulator executable paths to concrete binaries when available
4. Ensure required RetroArch cores are available:
   - detects required cores from index launch templates (`-L cores/<core>`)
   - auto-downloads missing cores from Libretro buildbot on Windows/Linux x86_64
   - auto-installs matching `.info` metadata from `assets/frontend/info.zip`
   - dry-run reports missing core/info files without writing
5. Build plan:
   - firmware actions first
   - missing required firmware blocks title sync for that system
   - size mismatch detection for local ROM/assets runs even when `--verify` is off
6. SGDB artwork phase (only when SGDB API key is configured):
   - `--dry-run`: prints planned SGDB lookups/downloads for titles missing required cached kinds only (no cache writes)
   - real sync: if all configured kinds already exist in local SGDB cache for a title, skip SGDB API calls for that title
   - for titles with missing required cached kinds, look up titles, fetch configured artwork kinds, and cache to local files with safe writes
   - when `grid` is enabled, sync fetches both SGDB portrait (`600x900`) and landscape (`920x430`) grid variants
   - SGDB lookup/download failures emit warnings and do not abort unaffected titles
   - if SGDB lookups are unavailable, cached artwork is reused when present (self-heals missing Steam artwork)
   - SGDB URL selection prefers Steam-friendly formats (`png`/`jpg`/`ico`) before `webp`
7. If not `--dry-run`:
   - download firmware then ROM/assets
   - write to `*.part`, verify SHA-256, atomic rename
   - download execution uses a shared HTTP connection pool and configurable parallel workers (`[server].max_parallel_downloads` / `GAMEHUB_MAX_PARALLEL_DOWNLOADS`, default `4`)
8. Deploy firmware files into emulator-native BIOS locations (copy/link from `<gamehub_dir>/firmware/...`)
9. Discover Steam userdata + SteamID
10. Close Steam (best effort), backup configs, upsert Steam shortcuts, update collections (localconfig + cloud namespace), copy cached artwork into Steam grid, reopen Steam
   - managed shortcuts persist stable `appid` values on write, so first-run artwork/category mapping does not depend on a later Steam rewrite pass
   - collection membership appids are canonicalized to unsigned numeric values in both localconfig and cloud payloads
   - with `--skip-steam-relaunch`, Steam relaunch is skipped but all Steam file updates still run
11. Save `state.json`

Steam reconciliation is run on every non-dry sync (unless `--skip-steam`), even when there are no ROM/firmware downloads. This is what repairs missing Steam artwork/collections for already-synced games.
Verbose sync output prints both `userdata_id` (short folder id) and derived `steamid64` so profile selection is easy to verify.

## Local layout bootstrap
- Sync auto-creates firmware directories under `<gamehub_dir>/firmware` for indexed systems (non-dry-run).
- Dry-run prints intended firmware directory creation in verbose mode, but does not mutate local directories.

## Firmware Deployment Targets
- `PSX` firmware is mirrored to RetroArch `system_directory` targets discovered from:
  - explicit overrides (`RETROARCH_SYSTEM_DIR`/`GAMEHUB_RETROARCH_SYSTEM_DIR` or `[linux].retroarch_system_dir`)
  - `retroarch.cfg` `system_directory`
  - Linux defaults (`~/.config/retroarch/system` and Flatpak `~/.var/app/org.libretro.RetroArch/config/retroarch/system`)
  - Windows portable executable directory (`<retroarch-dir>/system`) when applicable
  - when a RetroArch config file is found, GAMEHUB sets `input_menu_toggle_gamepad_combo = "4"` (`Start+Select`) for controller quick-menu access
  - GAMEHUB also sets `all_users_control_menu = "true"` so menu combo works from non-primary controllers
- `PS2` config is auto-updated and setup wizard completion is written into `PCSX2.ini`.
  - default BIOS target is `<gamehub_dir>/firmware/PS2` unless overridden by `PCSX2_BIOS_DIR`/`GAMEHUB_PCSX2_BIOS_DIR`/`[linux].pcsx2_bios_dir`
  - for Flatpak PCSX2 on Linux (no explicit BIOS override), GAMEHUB targets `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios` and mirrors BIOS files there so the sandbox can read them reliably
  - on Linux, GAMEHUB bootstraps generic SDL pad bindings for `Pad1` and `Pad2` (no controller-model hardcoding) unless disabled with `[linux].pcsx2_controller_autoconfig = false`
  - keyboard/mouse default pad bindings are replaced by SDL controller bindings during bootstrap
  - GAMEHUB bootstraps `Hotkeys/OpenPauseMenu = SDL-0/Back & SDL-0/Start` when the existing binding is missing or keyboard-only
- `GC` firmware is mirrored to Dolphin runtime user path `GC/` (native default: `~/.local/share/dolphin-emu/GC`, Flatpak: `~/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu/GC`).
- `N3DS` has no required firmware deployment targets in this pass.
- When `N3DS` is present in the index, GAMEHUB bootstraps Azahar runtime config with `fullscreen=true` in `qt-config.ini` (Windows default root: `%APPDATA%/Azahar`, Linux Flatpak root: `~/.var/app/org.azahar_emu.Azahar/data/azahar`).
- GAMEHUB does not decrypt ROM content; N3DS ROMs must already be in a format Azahar can load.
- When `GC`/`Wii` systems are present, GAMEHUB writes Dolphin runtime config `Config/Dolphin.ini` with `[Display] Fullscreen = True` under the same resolved runtime user path and mirrors to additional detected config roots when present.
- GAMEHUB also bootstraps Dolphin `Config/GCPadNew.ini` and enables GC controller ports in `Dolphin.ini` (`SIDevice0/1 = 6`).
- For Wii input, GAMEHUB bootstraps `Config/WiimoteNew.ini` with two emulated Wii remotes (`Wiimote1` + `Wiimote2`) with right-stick pointer bindings (`IR/* = Right Stick`) and Nunchuk extension defaults.
- Wii bootstrap is explicit Wiimote+Nunchuk emulation (`[Wiimote*] Source = 1`, `Extension = Nunchuk`) and is not treated as GameCube pad input.
- Dolphin writes `Interface/ConfirmStop = False` in `Dolphin.ini` so stop/exit flows do not block on confirmation prompts.
- GAMEHUB bootstraps `Config/Hotkeys.ini` with controller-friendly stop/exit bindings:
  - pad1/pad2 `Back+Start`
- Windows Dolphin controller bootstrap sets explicit `XInput/0` and `XInput/1` device roots for pad/wiimote slots 1 and 2.
- Linux Dolphin controller bootstrap auto-detects evdev gamepads from `/proc/bus/input/devices` (for example `evdev/0/Xbox Wireless Controller`, `evdev/1/Xbox Wireless Controller`) and falls back to `SDL/0` + `SDL/1` when evdev devices are not detected.
- Dolphin writes `Interface/BackgroundInput = True` to reduce focus-related controller input drops when launched through Steam.
- Existing Dolphin input files are preserved once present; sync reconciles managed stop/exit hotkeys each run.
- Legacy managed Linux configs written with `XInput/<n>/Gamepad` or `All Devices` are auto-migrated on sync.
- Wii does not require indexed firmware in v1.

Linux path notes:
- Linux/Flatpak command matching and path-candidate discovery is shared across sync/firmware/core modules to keep behavior consistent.
- RetroArch core provisioning no longer uses Linux executable-parent directories like `/usr/bin/cores`.
- PCSX2 runtime config defaults are Linux-aware and Flatpak-aware (`~/.config/PCSX2/...` or `~/.var/app/net.pcsx2.PCSX2/...`).
- Dolphin target selection prefers explicit overrides, then existing user data roots, then a deterministic native/Flatpak default.
- Linux RetroArch Steam launch options rewrite `-L cores/<core>.dll` templates to Linux core paths (`.so`) and prefer absolute core paths from resolved RetroArch config/overrides.
- Linux Flatpak PCSX2 Steam launch options use `flatpak run --file-forwarding ... @@ <rom> @@` so host ROM paths are forwarded reliably to the sandbox.
- Linux Flatpak Dolphin Steam launch options use `flatpak run --device=all --file-forwarding ... -e @@ <rom> @@` so controller devices and host ROM paths are consistently available in the sandbox.
- Linux Flatpak Azahar Steam launch options use `flatpak run --device=all --file-forwarding ... -f -- @@ <rom> @@` so fullscreen starts enabled and controller devices are visible in the sandbox.

Environment overrides:
- `RETROARCH_SYSTEM_DIR`
- `PCSX2_BIOS_DIR`
- `GAMEHUB_PCSX2_CONTROLLER_AUTOCONFIG`
- `DOLPHIN_EMU_USERPATH`
- `GAMEHUB_AZAHAR_WINDOWS_INSTALLER_URL`

## RetroArch Core Defaults
For systems that launch via RetroArch, GAMEHUB uses these general-purpose core defaults when a core cannot be parsed from the index launch template:
- `GB`: `gambatte_libretro`
- `GBA`: `mgba_libretro`
- `GBC`: `gambatte_libretro`
- `GEN_MD`: `genesis_plus_gx_libretro`
- `N64`: `mupen64plus_next_libretro`
- `NDS`: `melondsds_libretro`
- `NES`: `fceumm_libretro`
- `PSX`: `swanstation_libretro`
- `SNES`: `snes9x_libretro`

Steam shortcut build normalizes emulator launch options for fullscreen:
- RetroArch shortcuts include `-f` (injected if missing).
- PCSX2 shortcuts include `-fullscreen` (injected if missing; Flatpak path already includes it).
- Azahar native shortcuts include `-f` (injected if missing). Linux Flatpak Azahar continues to use `flatpak run --file-forwarding`.
- Dolphin shortcuts include `-u "<dolphin-user-dir>"` so launch always uses the same user profile path GAMEHUB configured.
- Dolphin shortcuts include `-C Dolphin.Display.Fullscreen=True` for non-Flatpak installs when supported by the installed Dolphin CLI parser (injected before `-e/--exec` when missing).

Core provisioning environment overrides:
- `GAMEHUB_RETROARCH_CORES_BASE_URL`: override Libretro buildbot base URL
- `GAMEHUB_RETROARCH_CORES_DIR`: explicit RetroArch `cores` directory
- `GAMEHUB_RETROARCH_INFO_DIR`: explicit RetroArch `info` directory
- `GAMEHUB_RETROARCH_CFG_PATH`: explicit RetroArch config path used for path resolution

Steam Linux notes:
- Auto userdata discovery includes:
  - `~/.steam/steam/userdata`
  - `~/.local/share/Steam/userdata`
  - Flatpak Steam paths under `~/.var/app/com.valvesoftware.Steam/...`
- `steam.userdata_dir` (or `GAMEHUB_STEAM_USERDATA_DIR`) remains the preferred explicit override.
- Linux Steam reopen fallback tries `steam`, then `xdg-open`, then `flatpak run com.valvesoftware.Steam`.

Archive note:
- `.7z` ROM archives are not supported. Convert to supported formats before sync.
