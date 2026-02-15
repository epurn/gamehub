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
   - on Windows non-dry-run, attempts auto-install via `winget` for known emulators (`retroarch`, `pcsx2`, `dolphin`)
   - on Linux non-dry-run, uses config-first install backend (`[linux].emulator_install_backend`):
     - `auto` (default): Fedora `dnf` when available, else `flatpak` when available, else configured command backend
     - `dnf`: force Fedora package install behavior
     - `flatpak`: install `org.libretro.RetroArch`, `net.pcsx2.PCSX2`, `org.DolphinEmu.dolphin-emu` (remote optional via `[linux].flatpak_remote` / `GAMEHUB_LINUX_FLATPAK_REMOTE`)
     - `command`: run `[linux].emulator_install_command` for each missing emulator (supports `{package}` and `{emulator}` tokens)
     - `none`: disable Linux auto-install (sync prints actionable missing emulator output)
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
   - `--dry-run`: prints planned SGDB lookups/downloads only (no cache writes)
   - real sync: look up titles, fetch configured artwork kinds, cache to local files with safe writes
   - SGDB lookup/download failures emit warnings and do not abort unaffected titles
   - if SGDB lookups are unavailable, cached artwork is reused when present (self-heals missing Steam artwork)
   - SGDB URL selection prefers Steam-friendly formats (`png`/`jpg`/`ico`) before `webp`
7. If not `--dry-run`:
   - download firmware then ROM/assets
   - write to `*.part`, verify SHA-256, atomic rename
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
- `PS2` config is auto-updated so PCSX2 reads BIOS directly from `<gamehub_dir>/firmware/PS2` (no BIOS copy mirror step), and setup wizard completion is written into `PCSX2.ini`.
  - for Flatpak PCSX2 on Linux, GAMEHUB writes BIOS paths using the canonical resolved host path (for example `/var/home/...` on Fedora-family hosts)
- `Wii` firmware is mirrored to Dolphin user path `Wii/`.
- `GC` firmware is mirrored to Dolphin user path `GC/`.

Linux path notes:
- RetroArch core provisioning no longer uses Linux executable-parent directories like `/usr/bin/cores`.
- PCSX2 runtime config defaults are Linux-aware and Flatpak-aware (`~/.config/PCSX2/...` or `~/.var/app/net.pcsx2.PCSX2/...`).
- Dolphin target selection prefers explicit overrides, then existing user data roots, then a deterministic native/Flatpak default.
- Linux RetroArch Steam launch options rewrite `-L cores/<core>.dll` templates to Linux core paths (`.so`) and prefer absolute core paths from resolved RetroArch config/overrides.
- Linux Flatpak PCSX2 Steam launch options use `flatpak run --file-forwarding ... @@ <rom> @@` so host ROM paths are forwarded reliably to the sandbox.

Environment overrides:
- `RETROARCH_SYSTEM_DIR`
- `PCSX2_BIOS_DIR`
- `DOLPHIN_EMU_USERPATH`

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

RetroArch launch templates are emitted with `-f` so synced Steam shortcuts request fullscreen on launch.

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
