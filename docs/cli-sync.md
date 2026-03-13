# CLI Flow

Init command:
```powershell
.\venv\Scripts\python.exe -m gamehub_cli.main init [flags]
```

Sync command:
```powershell
.\venv\Scripts\python.exe -m gamehub_cli.main sync [flags]
```

Controller doctor command:
```powershell
.\venv\Scripts\python.exe -m gamehub_cli.main doctor controllers [--apply] [--force]
```

Managed content doctor commands:
```powershell
.\venv\Scripts\python.exe -m gamehub_cli.main doctor roms [--verify] [--verbose]
.\venv\Scripts\python.exe -m gamehub_cli.main doctor firmware [--verify] [--verbose]
.\venv\Scripts\python.exe -m gamehub_cli.main doctor all [--verify] [--verbose]
```

Fresh installs must run `gamehub init` before the first `gamehub sync`.

## Init Flags
- `--dry-run`: inspect bootstrap actions only
- `--verbose`: longer network timeout and extra output context
- `--reseed-profiles`: force-overwrite managed profile/template files during init (even when bytes already match)
- `--config <path>`: TOML config path override (required to exist for `init`)

## Sync Flags
- `--dry-run`: build and print plan only
- `--verbose`: longer network timeout and extra output context
- `--verify`: re-hash local files before diff decisions
- `--skip-steam`: run sync downloads/state updates but skip Steam lifecycle and Steam file updates
- `--skip-steam-relaunch`: apply Steam updates but do not relaunch Steam at end
- `--require-steam-closed`: fail if Steam cannot be closed before config writes
- `--reseed-profiles`: force-overwrite managed profile/template files during sync (even when bytes already match)
- Save sync remains config-driven in this phase (`[save_sync]` in `config.toml`); no additional CLI flags are required.
- `--config <path>`: TOML config path override

Steam close behavior:
- non-dry sync attempts to close Steam first
- if Steam cannot be closed:
  - with `--require-steam-closed`: sync fails
  - without it: Steam update stage is skipped for safety

## Init Flow
1. Load config and local state
2. Fetch and validate `/v1/index`
3. Ensure required emulators are available
4. Ensure required RetroArch cores are available
5. Create local firmware layout for indexed systems
6. Deploy firmware into emulator-native runtime locations and apply runtime bootstrap config
7. Seed and converge managed controller profiles when controller autoconfig is enabled
8. Save `state.json` with `bootstrap_version`

`init` does not download ROMs/assets, touch Steam, or set `last_sync`.

## Sync Pipeline Order
1. Load config and local state
2. Fail fast on fresh installs when `bootstrap_version` is missing and no legacy sync evidence exists
3. Fetch and validate `/v1/index`
   - transient index fetch failures are retried with exponential backoff (`[server].index_fetch_attempts`, `[server].index_retry_backoff_seconds`)
   - per-attempt index timeout can be set via `[server].index_timeout_seconds` (defaults to current transport timeout behavior)
4. Ensure required emulators are available:
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
5. Ensure required RetroArch cores are available:
   - detects required cores from index launch templates (`-L cores/<core>`)
   - auto-downloads missing cores from Libretro buildbot on Windows/Linux x86_64
   - auto-installs matching `.info` metadata from `assets/frontend/info.zip`
   - dry-run reports missing core/info files without writing
6. Build plan:
   - firmware actions first
   - missing required firmware blocks title sync for that system
   - size mismatch detection for local ROM/assets runs even when `--verify` is off
7. SGDB artwork phase (only when SGDB API key is configured):
   - `--dry-run`: prints planned SGDB lookups/downloads for titles missing required cached kinds only (no cache writes)
   - real sync: if all configured kinds already exist in local SGDB cache for a title, skip SGDB API calls for that title
   - for titles with missing required cached kinds, look up titles, fetch configured artwork kinds, and cache to local files with safe writes
   - when `grid` is enabled, sync fetches both SGDB portrait (`600x900`) and landscape (`920x430`) grid variants
   - SGDB lookup/download failures emit warnings and do not abort unaffected titles
   - if SGDB lookups are unavailable, cached artwork is reused when present (self-heals missing Steam artwork)
   - SGDB URL selection prefers Steam-friendly formats (`png`/`jpg`/`ico`) before `webp`
8. If not `--dry-run`:
   - download firmware then ROM/assets
   - write to `*.part`, verify SHA-256, atomic rename
   - download execution uses a shared HTTP connection pool and configurable parallel workers (`[server].max_parallel_downloads` / `GAMEHUB_MAX_PARALLEL_DOWNLOADS`, default `4`)
9. Deploy firmware files into emulator-native BIOS locations (copy/link from `<gamehub_dir>/firmware/...`)
10. Controller convergence stage (after runtime/bootstrap setup, before Steam mutation):
   - validates managed controller profile templates under `<gamehub_dir>/controller_profiles`
   - records per-directory `.gamehub-managed.json` metadata markers (schema version, source profile/template, timestamp, fingerprint, ownership)
   - applies assisted emulator config key convergence for known-safe controller sections (`PCSX2.ini`, `Dolphin.ini`, Azahar `qt-config.ini`) using minimal key/section edits
   - does not choose a fixed profile; runtime selection remains launch-time autodetect (`0 -> kbm`, `1 -> xbox_1p`, `2+ -> xbox_2p`)
11. Discover Steam userdata + SteamID
12. Close Steam (best effort), backup configs, upsert Steam shortcuts, update collections (localconfig + cloud namespace), copy cached artwork into Steam grid, reopen Steam
   - managed shortcuts persist stable `appid` values on write, so first-run artwork/category mapping does not depend on a later Steam rewrite pass
   - collection membership appids are canonicalized to unsigned numeric values in both localconfig and cloud payloads
    - when `[controllers].launch_autoconfig = true` or `[save_sync].enabled = true`, GAMEHUB wraps `RetroArch`/`PCSX2`/`Dolphin`/`Azahar` shortcuts through an internal `shortcut-launch` command that:
      - decodes target emulator command payload
      - detects attached controllers (Xbox on non-Deck platforms; built-in controller on Steam Deck)
      - applies controller profile (`kbm`, `xbox_1p`, `xbox_2p`) with managed-key writes only
      - rewrites managed `PSX`/`PS2` memory-card targets to deterministic GAMEHUB filenames before launch when save sync is enabled
      - performs a one-shot `/health` reachability precheck (`1.0s` timeout) before launch-session save-sync network work
      - runs title-scoped pre-launch save reconciliation when save sync is enabled
      - skips launch-session save-sync network work when the precheck fails (fail-open; launch continues)
      - uses launch-only metadata fetch limits for `/v1/index` and `/v1/save-bindings` (`<=5.0s` timeout cap, attempts=`1`, backoff=`0.0s`)
      - launches the original emulator command
      - runs title-scoped post-exit save upload when `save_sync.mode = "bidirectional"`:
        - uploads changed indexed saves when the remote save did not change during play
        - creates remote-missing deterministic `exact_files` saves (`battery`, managed `memory_card`) automatically
        - learns first-time `per_game` save trees for supported `GC`/`Wii`/`N3DS` bindings and uploads newly created remote save files automatically when the learned root is deterministic
   - Linux Steam Deck default shortcut policy:
     - managed shortcuts default to `AllowDesktopConfig = 0` (native-first controller path)
     - override globally with `GAMEHUB_STEAM_ALLOW_DESKTOP_CONFIG=true|false`
    - Linux Steam Deck template sync for managed `Wii` and `N3DS` shortcuts (`GC` is intentionally excluded):
      - writes per-title Steam Input files under:
        - `Steam Controller Configs/<steamid>/config/<normalized_title>/gamehub_wii.vdf` (`Wii`)
        - `Steam Controller Configs/<steamid>/config/<normalized_title>/gamehub_3ds.vdf` (`N3DS`)
      - writes Steam local override payloads under each detected Steam root `controller_config/` directory (for example `~/.local/share/Steam/controller_config/app_<unsigned_appid>.vdf`)
      - updates `Steam Controller Configs/<steamid>/config/configset_controller_neptune.vdf` and active `configset_*.vdf` files so managed normalized title keys and companion aliases (`appid`/signed/title variants) all point to `template=CLOUD_<normalized_title>/gamehub_wii|gamehub_3ds`
      - when present, mirrors the same template/configset writes into `userdata/<steamid>/241100/remote/*/config/` to align Deck startup local+cloud Steam Input sources
      - uses committed seed files from `src/gamehub_cli/steam/template_seeds/steamdeck/` as authoritative payloads
      - writes raw seed bytes without runtime metadata rewriting
      - is deterministic fail-fast: missing required roots/seeds fail the Steam apply stage
      - without `--reseed-profiles`, existing managed per-title files and override payloads are preserved; `--reseed-profiles` force-rewrites them
      - managed app overrides are always repaired so `UseSteamControllerConfig = 1` for managed app entries
      - managed `Wii`/`N3DS` app entries are written with `DisableCloud = 1`
    - Linux Steam Deck zero-controller detection in `shortcut-launch` is deterministic: one detect pass, then `xbox_1p` fallback only when Deck detect count is zero
    - Steam Deck validation scope is built-in controller mode; external Xbox controller support on Deck is planned for a later release
- with `--skip-steam-relaunch`, Steam relaunch is skipped but all Steam file updates still run
13. Save `state.json`

Save sync stays disabled by default unless `[save_sync].enabled = true` is set in config.

### Save sync dry-run and conflict interpretation
- In `mode = "download"`, save planning is read-only: expected actions are `download` or `skip` only.
- In `mode = "bidirectional"`, planner decisions may include `upload_existing`, `upload_new`, and `conflict` in addition to `download`/`skip` according to checksum lineage, binding discovery, and `conflict_policy`.
- `conflict_policy = "prefer_server"` resolves conflict paths toward download decisions.
- `conflict_policy = "prefer_local"` resolves conflict paths toward `upload_existing` decisions.
- `conflict_policy = "manual"` preserves explicit `conflict` outcomes for operator review.
- In `mode = "bidirectional"`, if managed post-exit upload is missed because the server is unreachable, GAMEHUB records `unresolved_save_conflicts[save_id] = "postexit-upload-missed-server-unreachable"` and keeps local timestamp observation in `save_lineage`.
- On reconnect (planner and managed pre-launch), that marker enables deterministic UTC-second timestamp comparison (`local mtime` vs remote `updated_at`):
  - local newer -> `upload_existing` (`missed-upload-local-newer`)
  - remote newer -> `download` (`missed-upload-remote-newer`)
  - missing/unreadable/tied timestamps -> fallback to existing checksum/lineage conflict-safe behavior
- If a managed launch starts while the server is unreachable, GAMEHUB records that title for reconnect recovery. On the next connected managed pre-launch, lineage-missing indexed saves reuse the same timestamp comparison to seed `postexit-upload-missed-server-unreachable` recovery before the session starts.
- `[save_sync].systems` gates both launch-session save sync and managed `PSX`/`PS2` memory-card path rewrites.
- `--dry-run` performs no save writes and no remote mutations; it is the required safety preview for save plan auditing before enabling non-dry execution.
- Managed shortcut launches use launch-session save sync only; there is no resident background watcher in this release.
- Pre-launch shortcut sync never auto-uploads.
- Post-exit shortcut sync uploads only when the remote save is unchanged from the pre-launch snapshot and either the local save changed during the session or pre-launch already resolved that indexed save as `keep-local` / `upload_existing`.
- First-time local `battery` and managed `memory_card` saves are discovered on the next non-dry sync from the server-published save-binding catalog and become `upload_new` actions in `bidirectional`.
- Managed shortcut launches also auto-create those deterministic `exact_files` saves at post-exit, so wrapped RetroArch and managed `PSX`/`PS2` sessions do not need to wait for the next full `gamehub sync`.
  - For `PSX` Swanstation, GAMEHUB accepts managed `GH_<title_id>_1/2.mcd`, deterministic per-title `<title_name>.srm`, and deterministic per-title `<title_name>_1/2.mcd` output.
- Managed shortcut launches also auto-create first-time deterministic `learned_tree` saves at post-exit when one root can be proven, even if that local save already existed before the connected bidirectional session began (for example after an offline launch or after switching from `disabled`/`download` to `bidirectional`).
- `download` mode stays read-only: missing local saves may still download, existing local drift becomes `skip(download-mode-local-drift)`, local-only first-time saves become `skip(download-mode-local-new)`, and the server is never mutated.
- If learned-tree materialization is ambiguous (for example multiple valid Azahar profile prefixes), GAMEHUB records an explicit conflict and performs no save write.
- If the remote save changed during the play session, GAMEHUB records a conflict and does not auto-overwrite either side.
- After upgrading to the build that introduces `shortcut-launch`, run one non-dry `gamehub sync` before starting managed shortcuts so Steam commands are rewritten.

Steam reconciliation is run on every non-dry sync (unless `--skip-steam`), even when there are no ROM/firmware downloads. This is what repairs missing Steam artwork/collections for already-synced games.
Verbose sync output prints both `userdata_id` (short folder id) and derived `steamid64` so profile selection is easy to verify.

## Local layout bootstrap
- `gamehub init` and non-dry `gamehub sync` auto-create firmware directories under `<gamehub_dir>/firmware` for indexed systems.
- Dry-run prints intended firmware directory creation in verbose mode, but does not mutate local directories.

## Firmware Deployment Targets
- `PSX` firmware is mirrored to RetroArch `system_directory` targets discovered from:
  - explicit overrides (`RETROARCH_SYSTEM_DIR`/`GAMEHUB_RETROARCH_SYSTEM_DIR` or `[linux].retroarch_system_dir`)
  - `retroarch.cfg` `system_directory`
  - Linux defaults (`~/.config/retroarch/system` and Flatpak `~/.var/app/org.libretro.RetroArch/config/retroarch/system`)
  - Windows portable executable directory (`<retroarch-dir>/system`) when applicable
- when a RetroArch config file is found, GAMEHUB sets `input_menu_toggle_gamepad_combo = "4"` (`Start+Select`) for controller quick-menu access
  - on Windows, RetroArch config discovery includes portable installs (`<retroarch-install>/retroarch.cfg`) before `%APPDATA%/RetroArch/retroarch.cfg`
  - on macOS, config discovery prefers an existing native config file under `~/Library/Application Support/RetroArch/config/retroarch.cfg` before legacy root-level/document variants
  - on Linux, when RetroArch resolves to Flatpak, config discovery prefers the Flatpak config path before native `~/.config/retroarch/retroarch.cfg`
  - RetroArch `system_directory = ":/system"` (portable-relative) is normalized to `<retroarch.cfg dir>/system` on Windows
  - RetroArch `libretro_directory = ":/cores"` and `libretro_info_path = ":/info"` (portable-relative) are normalized to `<retroarch.cfg dir>/cores` / `<retroarch.cfg dir>/info` on Windows
  - GAMEHUB writes `config/remaps/SwanStation/SwanStation.rmp` (or the configured `input_remapping_directory`) with the tested DualShock + analog/turbo defaults
  - GAMEHUB also sets `input_player1_analog_dpad_mode .. input_player8_analog_dpad_mode = "0"`
  - GAMEHUB also sets `input_libretro_device_p1 = "261"` (DualShock) and `input_libretro_device_p2..p8 = "1"`
  - GAMEHUB also sets `input_remap_port_p1..p8 = "0".."7"` and the tested `input_turbo_*` defaults
  - GAMEHUB also ensures `swanstation_Controller1.Type` / `swanstation_Controller2.Type` are set to `"AnalogController"` in `retroarch-core-options.cfg` so PSX defaults to DualShock-style pads
  - On Windows, GAMEHUB keeps PSX controller overrides out of `retroarch.cfg` and applies them via the Swanstation core remap file only
  - GAMEHUB also sets `all_users_control_menu = "true"` so menu combo works from non-primary controllers
- `PS2` config is auto-updated and setup wizard completion is written into `PCSX2.ini`.
  - default BIOS target is `<gamehub_dir>/firmware/PS2` unless overridden by `PCSX2_BIOS_DIR`/`GAMEHUB_PCSX2_BIOS_DIR`/`[linux].pcsx2_bios_dir`
  - for Flatpak PCSX2 on Linux (no explicit BIOS override), GAMEHUB targets `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios` and mirrors BIOS files there so the sandbox can read them reliably
- `GC` firmware is mirrored to Dolphin runtime user path `GC/` (native default: `~/.local/share/dolphin-emu/GC`, Flatpak: `~/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu/GC`).
- `N3DS` has no required firmware deployment targets in this pass.
- When `N3DS` is present in the index, GAMEHUB bootstraps Azahar runtime config in `qt-config.ini` with:
  - `fullscreen=true`
  - `confirmClose=false` (disables quit confirmation while emulation is running)
  - Windows default path: `%APPDATA%/Azahar/config/qt-config.ini`
  - Linux Flatpak default path: `~/.var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini`
- GAMEHUB does not decrypt ROM content; N3DS ROMs must already be in a format Azahar can load.
- When `GC`/`Wii` systems are present, GAMEHUB writes Dolphin runtime config `Config/Dolphin.ini` with `[Display] Fullscreen = True` under the same resolved runtime user path and mirrors to additional detected config roots when present.
- Dolphin writes `Interface/ConfirmStop = False` in `Dolphin.ini` so stop/exit flows do not block on confirmation prompts.
- Dolphin writes `Interface/BackgroundInput = True` to reduce focus-related controller input drops when launched through Steam.
- Dolphin input profiles (`GCPadNew.ini`, `WiimoteNew.ini`, `Hotkeys.ini`) and input-source keys (`SIDevice0/1`, `WiimoteSource0/1`) are applied at launch by controller profiles, not during firmware deploy.
- Wii does not require indexed firmware in v1.

Linux path notes:
- Linux/Flatpak command matching and path-candidate discovery is shared across sync/firmware/core modules to keep behavior consistent.
- RetroArch core provisioning no longer uses Linux executable-parent directories like `/usr/bin/cores`.
- PCSX2 runtime config defaults are Linux-aware and Flatpak-aware (`~/.config/PCSX2/...` or `~/.var/app/net.pcsx2.PCSX2/...`).
- Dolphin target selection prefers explicit overrides, then existing user data roots, then a deterministic native/Flatpak default.
- Linux RetroArch Steam launch options rewrite `-L cores/<core>.dll` templates to Linux core paths (`.so`) and prefer absolute core paths from resolved RetroArch config/overrides.
- Linux Flatpak RetroArch Steam launch options use `flatpak run --file-forwarding ... @@ <rom> @@` so ROM paths (including SD-card paths) are forwarded reliably to the sandbox.
- Linux Flatpak PCSX2 Steam launch options use `flatpak run --file-forwarding ... @@ <rom> @@` so host ROM paths are forwarded reliably to the sandbox.
- Linux Flatpak Dolphin Steam launch options use `flatpak run --device=all --file-forwarding ... -e @@ <rom> @@` so controller devices and host ROM paths are consistently available in the sandbox.
- Linux Flatpak Azahar Steam launch options default to a sync-emitted Linux-only wrapper (`python -m gamehub_cli.controllers.azahar_exit_hook`) that:
  - launches `flatpak run --device=all --file-forwarding org.azahar_emu.Azahar -f -- @@ <rom> @@`
  - listens for strict `Select+Start` and terminates Azahar when pressed:
    - joystick path (`/dev/input/js*`) using configured Azahar button indices
    - evdev fallback (`/dev/input/event*`) using `BTN_SELECT` + `BTN_START`
  - can be disabled by setting `GAMEHUB_AZAHAR_LINUX_EXIT_HOOK=false` (falls back to direct flatpak launch)
- Linux Flatpak Dolphin launches wrapped by `shortcut-launch` include a fail-open `Select+Start` exit hook by default:
  - monitors `/dev/input/js*` (configurable button indices) and `/dev/input/event*` (`BTN_SELECT` + `BTN_START`)
  - on combo press, issues `flatpak kill org.DolphinEmu.dolphin-emu`
- Windows Azahar launches wrapped by `shortcut-launch` include a fail-open `Start+Select` XInput exit hook by default (disable with `GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK=false`).

Windows path notes:
- If Dolphin is installed by GAMEHUB (default `LOCALAPPDATA/Programs/Dolphin`), the runtime user dir is pinned to `<dolphin-install>/User`.
- Otherwise, Dolphin user dir detection prefers a portable `<dolphin-install>/User` folder when present, then `%USERPROFILE%/Documents/Dolphin Emulator`, then `%APPDATA%/Dolphin Emulator`.
- Override with `DOLPHIN_EMU_USERPATH` / `GAMEHUB_DOLPHIN_EMU_USERPATH` (or `dolphin_user_path` in `config.toml`).
  - can be disabled by setting `GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK=false`
Controller launch profile defaults:
- Profile root default: `<paths.gamehub_dir>/controller_profiles` (override with `[controllers].profiles_dir` or `GAMEHUB_CONTROLLER_PROFILES_DIR`).
- Non-dry `gamehub init` and non-dry `gamehub sync` seed missing default profiles when `launch_autoconfig` is enabled.
- `shortcut-launch` does not seed controller profiles at launch time; run non-dry `gamehub init` or `gamehub sync` first when managed profiles may not exist yet.
- Use `--reseed-profiles` to force-overwrite managed defaults (controller profiles + Deck per-title Steam templates) on demand.
- If you used older branch builds before these controller profile changes, run one `gamehub init --reseed-profiles` before retesting.
- To supply custom profiles, set `[controllers].profiles_dir` (or `GAMEHUB_CONTROLLER_PROFILES_DIR`):
  - non-dry sync seeds any missing profile files into that directory when `launch_autoconfig` is enabled
  - existing files are left unchanged unless `--reseed-profiles` is used
  - with `--reseed-profiles`, managed files are rewritten even when bytes already match
- Controller profiles apply input mappings for `PCSX2`, `Dolphin`, and `Azahar` at launch; firmware deploy does not write controller bindings.
- Profile selection:
  - `0` Xbox controllers -> `kbm`
  - `1` Xbox controller -> `xbox_1p`
  - `2+` Xbox controllers -> `xbox_2p`
- Dolphin device defaults within profiles:
  - `kbm`: P1 keyboard/mouse, P2 disabled
  - `xbox_1p`: P1 controller, P2 keyboard/mouse
  - `xbox_2p`: P1 + P2 controllers
- On macOS, controller-count detection accepts SDL game controllers even when the device name is not Xbox-branded.
- On macOS, controller detection still prefers host SDL probing first, then falls back to `system_profiler` game-controller inventory, then `hidutil list` gamepad-class HID devices when no loadable SDL2 dylib is available; failure remains fail-open to `kbm`.
- On macOS, Dolphin keyboard/mouse device identifiers use `Quartz/0/Keyboard & Mouse`.
- On macOS, Dolphin keyboard profile apply also normalizes native Quartz key tokens such as `Escape`, `Return`, and arrow/control/shift names at launch time so existing managed configs do not need manual reseeding.
- On macOS, Dolphin controller-mode apply rebinds to the current detected SDL device name when one is available; on guidless fallback inventory it prefers the emulator's embedded SDL mapping name for the exact detected vendor/product identity, and only falls back to generic `SDL/<slot>/Gamepad` when no meaningful SDL device name can be resolved.
- On macOS, Dolphin controller-mode apply also normalizes managed controller token names to the native SDL labels Dolphin expects there (for example `Button S/E/W/N` and trigger analog bindings), binds controller hotkeys to the resolved SDL pad device instead of `All Devices`, flips Wii IR vertical stick direction to the native mapping expected there, and writes every existing native/XDG Dolphin config root it finds so native `~/Library/Application Support/Dolphin` installs are not missed.
- Azahar GUID normalization is always detect-based.
- On macOS, Azahar controller-mode apply also rewrites managed SDL button, trigger, D-pad, and analog bindings from the emulator's embedded SDL controller mapping database when a matching controller identity is found; otherwise it keeps the seeded profile layout and only normalizes GUID/port identity.
- GUID discovery order (Linux Flatpak config paths): probe Azahar Flatpak runtime first; if unavailable, preserve existing GUID and otherwise keep port-only mappings (host GUID is not injected into Flatpak configs).
- GUID discovery order (Linux non-Flatpak config paths): fall back to host SDL, then keep existing GUID when discovery is unavailable.
- GUID discovery order (Windows): attempt host SDL via Azahar's bundled SDL2 or other installed SDL2 bundles (RetroArch/PCSX2/Dolphin) when available, otherwise keep existing GUIDs and fall back to port-only mappings.
- If a stored GUID matches host SDL but the Flatpak runtime probe returns a different GUID, GAMEHUB prefers the runtime GUID for Steam/Flatpak launches.
- `RetroArch` shortcuts are wrapped whenever controller autoconfig or save sync is enabled, so managed launch-time battery save sync can run at post-exit.

Environment overrides:
- `RETROARCH_SYSTEM_DIR`
- `PCSX2_BIOS_DIR`
- `DOLPHIN_EMU_USERPATH`
- `GAMEHUB_AZAHAR_WINDOWS_INSTALLER_URL`
- `GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK`
- `GAMEHUB_AZAHAR_LINUX_EXIT_HOOK`
- `GAMEHUB_AZAHAR_EXIT_BUTTON_SELECT`
- `GAMEHUB_AZAHAR_EXIT_BUTTON_START`
- `GAMEHUB_AZAHAR_EXIT_JS_DEVICE`
- `GAMEHUB_AZAHAR_SDL_DIR`
- `GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK`
- `GAMEHUB_DOLPHIN_EXIT_BUTTON_SELECT`
- `GAMEHUB_DOLPHIN_EXIT_BUTTON_START`
- `GAMEHUB_DOLPHIN_EXIT_JS_DEVICE`
- `GAMEHUB_STEAM_ALLOW_DESKTOP_CONFIG`
- `GAMEHUB_CONTROLLER_LAUNCH_AUTOCONFIG`
- `GAMEHUB_CONTROLLER_PROFILES_DIR`

## Deck Controller Triage
Use these commands on Steam Deck Desktop Mode to inspect managed shortcut flags, app overrides, and visible input devices.

```bash
./venv/bin/python - <<'PY'
from pathlib import Path
import json, vdf
from gamehub_cli.common.config import load_config
from gamehub_cli.steam.lifecycle import discover_userdata_dir, discover_steam_id, build_context
from gamehub_cli.steam.shortcuts import _canonical_unsigned_app_id
cfg = load_config(Path("config.toml"))
userdata = discover_userdata_dir(cfg.steam_userdata_dir)
steam_id = discover_steam_id(userdata, preferred_steam_id=cfg.steam_id)
ctx = build_context(userdata, steam_id, cfg.steam_exe)
table = vdf.binary_load(ctx.shortcuts_path.open("rb")).get("shortcuts", {})
rows = []
for e in table.values():
    tags = e.get("tags", {})
    vals = [tags[k] for k in sorted(tags, key=lambda k: int(str(k)) if str(k).isdigit() else str(k))]
    if "GAMEHUB" not in vals:
        continue
    appid = str(e.get("appid", "")).strip()
    rows.append({
        "AppName": e.get("AppName"),
        "appid": appid,
        "appid_unsigned": _canonical_unsigned_app_id(appid) if appid else "",
        "AllowDesktopConfig": e.get("AllowDesktopConfig"),
        "AllowOverlay": e.get("AllowOverlay"),
        "LaunchOptions": e.get("LaunchOptions"),
    })
print(json.dumps(rows, indent=2))
PY
```

```bash
./venv/bin/python - <<'PY'
from pathlib import Path
import vdf
from gamehub_cli.common.config import load_config
from gamehub_cli.steam.lifecycle import discover_userdata_dir, discover_steam_id, build_context
from gamehub_cli.steam.shortcuts import _canonical_unsigned_app_id
cfg = load_config(Path("config.toml"))
userdata = discover_userdata_dir(cfg.steam_userdata_dir)
steam_id = discover_steam_id(userdata, preferred_steam_id=cfg.steam_id)
ctx = build_context(userdata, steam_id, cfg.steam_exe)
shortcuts = vdf.binary_load(ctx.shortcuts_path.open("rb")).get("shortcuts", {})
apps = vdf.loads(ctx.localconfig_path.read_text(encoding="utf-8")).get("UserLocalConfigStore", {}).get("Software", {}).get("Valve", {}).get("Steam", {}).get("apps", {})
for e in shortcuts.values():
    tags = e.get("tags", {})
    vals = [tags[k] for k in sorted(tags, key=lambda k: int(str(k)) if str(k).isdigit() else str(k))]
    if "GAMEHUB" not in vals:
        continue
    appid = _canonical_unsigned_app_id(str(e.get("appid", "")))
    use = apps.get(appid, {}).get("UseSteamControllerConfig") if isinstance(apps, dict) else None
    print(f"{e.get('AppName')}\tappid={appid}\tUseSteamControllerConfig={use}")
PY
```

```bash
grep -E 'Name=|Handlers=' /proc/bus/input/devices | sed -n '/Steam Deck Controller/,+3p;/Steam Virtual Gamepad/,+3p;/Xbox/,+3p'
ls -l /dev/input/js*
```

```bash
STEAM_ID=95402412
find "$HOME/.local/share/Steam/steamapps/common/Steam Controller Configs/$STEAM_ID/config" -maxdepth 2 -name '*.vdf' | sort
```

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
- Azahar native shortcuts include `-f` (injected if missing). Linux Flatpak Azahar uses a sync-emitted GAMEHUB wrapper hook by default (or direct `flatpak run` when `GAMEHUB_AZAHAR_LINUX_EXIT_HOOK=false`).
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
