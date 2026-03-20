# Config and State

## Config file
Config resolution order:
1. `--config <path>` CLI option (when provided)
2. `./config.toml` in current working directory (if present)
3. `~/.gamehub/config.toml`

Preferred bootstrap flow:

macOS/Linux:
```bash
./venv/bin/python -m gamehub_cli.main config init
./venv/bin/python -m gamehub_cli.main config verify
```

Windows PowerShell:
```powershell
.\venv\Scripts\python.exe -m gamehub_cli.main config init
.\venv\Scripts\python.exe -m gamehub_cli.main config verify
```

`config init` writes a starter config using the same resolution defaults documented above.
- whether creating or updating, `config init` writes through temp-file + fsync + atomic replace
- if a resolved config file already exists, `config init` also backs it up first and prunes older backups with `[backups].keep_limit`
- if no config file exists yet, `config init` writes `./config.toml` by default
- platform templates under `docs/templates/` remain available when you want to start from a hand-edited example instead

Sample templates:
- Windows (verified): [docs/templates/config.windows.template.toml](templates/config.windows.template.toml)
- macOS (Apple Silicon supported): [docs/templates/config.macos.template.toml](templates/config.macos.template.toml)
- Bazzite (tested): [docs/templates/config.bazzite.template.toml](templates/config.bazzite.template.toml)
- Steam Deck (verified): [docs/templates/config.steamdeck.template.toml](templates/config.steamdeck.template.toml)
- General Linux: [docs/templates/config.linux.template.toml](templates/config.linux.template.toml)

Fresh installs should run `gamehub config init` and `gamehub config verify` before `gamehub init`, `gamehub sync`, or `gamehub doctor`.

Recommended deployment smoke from a configured client:

```bash
gamehub config verify --config ./config.toml
gamehub doctor server --config ./config.toml --server-url "http://<SERVER_IP>:8000"
gamehub doctor server --config ./config.toml --server-url "http://<SERVER_IP>:8000" --json
```

Platform validation status is tracked in [platform-support.md](platform-support.md).

Example:
```toml
[server]
url = "http://127.0.0.1:8000"
# Optional index fetch hardening for slower/unreliable links:
# timeout for each /v1/index request attempt (seconds)
index_timeout_seconds = 45
# total attempts (initial request + retries)
index_fetch_attempts = 3
# exponential backoff base delay between retries (seconds)
index_retry_backoff_seconds = 1.5
# download worker count for firmware/ROM/assets (1-16)
max_parallel_downloads = 4

[paths]
gamehub_dir = "C:/gamehub"

[steam]
userdata_dir = "C:/Program Files (x86)/Steam/userdata"
steam_id = "76561198000000001"
steam_exe = "C:/Program Files (x86)/Steam/steam.exe"

[sgdb]
# Fallback only; prefer GAMEHUB_SGDB_API_KEY in environment.
api_key = "optional-sgdb-api-key"
cache_dir = "C:/gamehub/artwork-cache/sgdb"
enabled_kinds = ["grid", "hero", "logo", "icon"]

[linux]
# Optional Linux emulator auto-install strategy:
# auto | dnf | apt | flatpak | none | command
emulator_install_backend = "auto"
# Used when emulator_install_backend = "command"
emulator_install_command = "sudo apt install -y {package}"
# Optional remote name used when backend is flatpak (for example: flathub)
flatpak_remote = "flathub"

# Optional Linux path hints (all optional)
retroarch_cfg_path = "~/.config/retroarch/retroarch.cfg"
retroarch_system_dir = "~/.config/retroarch/system"
retroarch_cores_dir = "~/.config/retroarch/cores"
retroarch_info_dir = "~/.config/retroarch/info"
retroarch_cores_base_url = "https://buildbot.libretro.com/nightly/linux/x86_64/latest/"
pcsx2_ini_path = "~/.config/PCSX2/inis/PCSX2.ini"
pcsx2_bios_dir = "~/.config/PCSX2/bios"
dolphin_user_path = "~/.local/share/dolphin-emu"

[macos]
# Optional macOS emulator auto-install strategy:
# auto | official | command | none
emulator_install_backend = "auto"
# Used when emulator_install_backend = "command"
emulator_install_command = "brew install --cask {package}"
# Force strict native-only PCSX2 behavior on Apple Silicon macOS.
disable_pcsx2_rosetta = false

# Optional macOS path hints (all optional)
retroarch_cfg_path = "~/Documents/RetroArch/retroarch.cfg"
retroarch_system_dir = "~/Documents/RetroArch/system"
retroarch_cores_dir = "~/Library/Application Support/RetroArch/cores"
retroarch_info_dir = "~/Library/Application Support/RetroArch/info"
retroarch_cores_base_url = "https://buildbot.libretro.com/nightly/apple/osx/arm64/latest/"
pcsx2_ini_path = "~/Library/Application Support/PCSX2/inis/PCSX2.ini"
pcsx2_bios_dir = "~/Library/Application Support/PCSX2/bios"
dolphin_user_path = "~/.local/share/dolphin-emu"

[controllers]
# Launch-time controller profile application for non-RetroArch emulators.
launch_autoconfig = true
# Optional explicit profile root.
# Default when omitted: <paths.gamehub_dir>/controller_profiles
profiles_dir = "~/.gamehub/controller_profiles"

[backups]
# Keep the newest GAMEHUB backup files per target path/family.
keep_limit = 3

[save_sync]
# Rollout default is disabled.
enabled = false
# download | bidirectional
mode = "download"
# manual | prefer_server | prefer_local
conflict_policy = "manual"
# Optional allow-list of systems; empty means all supported systems.
systems = ["PS2", "Wii"]

```

Secret policy:
- Preferred: set `GAMEHUB_SGDB_API_KEY` in the environment.
- Fallback only: `sgdb.api_key` in config file.
- Never commit real API keys in tracked files.

`steam.steam_id` is optional. When set, sync targets that exact Steam profile and fails if it does not exist under the configured userdata directory.
It accepts either:
- userdata account id (short numeric folder name under `Steam/userdata`)
- SteamID64 (community profile numeric id)

When SteamID64 is supplied, GAMEHUB maps it to the matching userdata account id automatically.
When omitted, sync auto-detects a profile under `steam.userdata_dir` and prefers the most recently active profile (`localconfig.vdf`/`shortcuts.vdf` mtime).

`steam.userdata_dir` is strict when set: if the configured path is missing, GAMEHUB does not fall back to auto-detection.

`GAMEHUB_STEAM_USERDATA_DIR` can override `steam.userdata_dir` from config.

On macOS, `steam.steam_exe` may point to either `Steam.app` or its inner `Contents/MacOS/steam_osx` path. GAMEHUB normalizes lifecycle actions back to the app bundle.

Steam mutation behavior notes:
- GAMEHUB writes managed shortcuts with stable `appid` values so artwork and category membership can be bound on first sync pass.
- On Linux Steam Deck, GAMEHUB writes managed shortcuts with `AllowDesktopConfig = 0` by default (native-first controller path).
  - override globally with `GAMEHUB_STEAM_ALLOW_DESKTOP_CONFIG=true|false`.
- On Linux Steam Deck, GAMEHUB syncs seeded Steam Input templates for managed `Wii` and `N3DS` shortcuts (`GC` is intentionally excluded).
  - per-title destinations:
    - `Steam Controller Configs/<steamid>/config/<normalized_title>/gamehub_wii.vdf` (`Wii`)
    - `Steam Controller Configs/<steamid>/config/<normalized_title>/gamehub_3ds.vdf` (`N3DS`)
    - local override destinations under detected Steam roots `controller_config/` directories (for example `~/.local/share/Steam/controller_config/app_<unsigned_appid>.vdf`)
  - existing managed per-title template files are preserved unless `--reseed-profiles` is used
  - with `--reseed-profiles`, managed per-title template files and override payloads are force-rewritten even when seed bytes already match
  - sync also updates `Steam Controller Configs/<steamid>/config/configset_controller_neptune.vdf` and active `configset_*.vdf` files (`controller_config`) so normalized title keys and companion aliases (`appid`/signed/title variants) select `template=CLOUD_<normalized_title>/gamehub_wii|gamehub_3ds`
  - when present, those per-title/configset writes are mirrored to `userdata/<steamid>/241100/remote/*/config/` to keep Deck startup Steam Input cloud/local roots aligned
  - seed source: `src/gamehub_cli/steam/template_seeds/steamdeck/`
  - GAMEHUB writes raw seed bytes without runtime metadata rewriting.
  - template sync is deterministic fail-fast when required Deck roots/seeds are unavailable.
- GAMEHUB canonicalizes collection membership appids to unsigned numeric values in both `localconfig.vdf` (`user-collections`) and cloud storage collection entries.
- On Linux Steam Deck, GAMEHUB always repairs managed app overrides so `UseSteamControllerConfig = 1` for managed app entries.
- Managed `Wii`/`N3DS` app entries are written with `DisableCloud = 1`.
- Steam reopen requires an active desktop/GUI session; SSH-only sessions may apply file updates successfully but fail to relaunch Steam.

`paths.gamehub_dir` is the local sync root. Derived paths:
- ROMs root: `<gamehub_dir>/roms/...` by default
  - Optional override: `paths.roms_dir`
  - Env override: `GAMEHUB_ROMS_DIR`
  - Removed aliases now rejected: `paths.output_dir`, `GAMEHUB_OUTPUT_DIR`
  - This ROM root is used consistently for both sync download destinations and Steam shortcut ROM launch targets.
- Asset root: `<gamehub_dir>/...` (from server asset relative paths)
- Firmware root: `<gamehub_dir>/firmware/...`
- State file: `<gamehub_dir>/state.json`

Removed compatibility keys are rejected at load time: `paths.library_dir`, `paths.firmware_dir`, and `paths.state_path`.

On non-dry sync, firmware system subdirectories are auto-created under `<gamehub_dir>/firmware` based on indexed systems.

Environment overrides are resolved centrally in `load_config` (precedence: CLI flag > env > config file > default).

Host install policy env overrides:
- `GAMEHUB_LINUX_EMULATOR_INSTALL_BACKEND`: overrides `[linux].emulator_install_backend`.
- `GAMEHUB_LINUX_EMULATOR_INSTALL_COMMAND`: overrides `[linux].emulator_install_command`.
- `GAMEHUB_LINUX_FLATPAK_REMOTE`: overrides `[linux].flatpak_remote`.
- `GAMEHUB_MACOS_EMULATOR_INSTALL_BACKEND`: overrides `[macos].emulator_install_backend`.
- `GAMEHUB_MACOS_EMULATOR_INSTALL_COMMAND`: overrides `[macos].emulator_install_command`.
- `GAMEHUB_MACOS_DISABLE_PCSX2_ROSETTA`: overrides `[macos].disable_pcsx2_rosetta`.

Shared emulator path/runtime env overrides (Linux and macOS):
- `RETROARCH_SYSTEM_DIR` or `GAMEHUB_RETROARCH_SYSTEM_DIR`: explicit RetroArch `system` directory target.
- `PCSX2_BIOS_DIR` or `GAMEHUB_PCSX2_BIOS_DIR`: explicit BIOS directory written into PCSX2 config (`PCSX2.ini`).
- `DOLPHIN_EMU_USERPATH` or `GAMEHUB_DOLPHIN_EMU_USERPATH`: explicit Dolphin runtime user directory target.
  - GC/Wii firmware deploys into `<userpath>/GC` and `<userpath>/Wii`.
  - Steam launch templates are normalized to pass `-u "<userpath>"`.
  - Dolphin runtime config bootstraps `Dolphin.ini` under `<userpath>/Config` (display/fullscreen + background input flags).
  - Dolphin input profiles (`GCPadNew.ini`, `WiimoteNew.ini`, `Hotkeys.ini`) are applied at launch via controller profiles.
  - Default Dolphin Xbox mappings include Wii `R1 -> A` and `R2 -> B`; GameCube keeps `R2` on right trigger.
- `GAMEHUB_RETROARCH_CFG_PATH`: explicit RetroArch config file path.
- `GAMEHUB_PCSX2_INI_PATH`: explicit PCSX2 ini path.
- `GAMEHUB_RETROARCH_CORES_BASE_URL`: optional base URL override for RetroArch core downloads.
- `GAMEHUB_RETROARCH_CORES_DIR`: explicit RetroArch cores directory for core auto-provisioning.
- `GAMEHUB_RETROARCH_INFO_DIR`: explicit RetroArch info directory for `.info` metadata auto-provisioning.
- These emulator path overrides remain shared across Linux and macOS; there are no macOS-specific duplicates for them.
- `GAMEHUB_AZAHAR_WINDOWS_INSTALLER_URL`: overrides the default pinned Windows Azahar installer URL used by emulator auto-install.
- `GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK`: enables/disables the Windows Azahar `shortcut-launch` `Start+Select` exit hook (`true` by default).
- `GAMEHUB_AZAHAR_LINUX_EXIT_HOOK`: enables/disables the Linux Azahar Steam-launch wrapper emitted during sync (`true` by default).
- `GAMEHUB_AZAHAR_MACOS_EXIT_HOOK`: enables/disables the macOS Azahar `shortcut-launch` `Start+Select` exit hook (`true` by default).
- `GAMEHUB_AZAHAR_EXIT_BUTTON_SELECT`: joystick button index used as `Select` for the Linux Azahar wrapper (default `4`).
- `GAMEHUB_AZAHAR_EXIT_BUTTON_START`: joystick button index used as `Start` for the Linux Azahar wrapper (default `6`).
- `GAMEHUB_AZAHAR_EXIT_JS_DEVICE`: optional explicit joystick device path for the Linux Azahar wrapper (for example `/dev/input/js0`).
- `GAMEHUB_AZAHAR_SDL_DIR`: optional directory containing Azahar's `SDL2.dll` for Windows GUID discovery.
- `GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK`: enables/disables Linux Dolphin Flatpak `Select+Start` exit hook wrapper in `shortcut-launch` (`true` by default).
- `GAMEHUB_DOLPHIN_EXIT_BUTTON_SELECT`: joystick button index used as `Select` for Linux Dolphin exit hook (default `6`).
- `GAMEHUB_DOLPHIN_EXIT_BUTTON_START`: joystick button index used as `Start` for Linux Dolphin exit hook (default `7`).
- `GAMEHUB_DOLPHIN_EXIT_JS_DEVICE`: optional explicit joystick device path for Linux Dolphin exit hook (for example `/dev/input/js0`).
- `GAMEHUB_STEAM_ALLOW_DESKTOP_CONFIG`: force managed shortcut `AllowDesktopConfig` (`true`/`false`).
- Linux Azahar wrapper input sources:
  - always watches available `/dev/input/js*` joystick devices with configured button indices
  - also watches available `/dev/input/event*` devices and exits only on strict `BTN_SELECT` + `BTN_START`
- `GAMEHUB_CONTROLLER_LAUNCH_AUTOCONFIG`: overrides `[controllers].launch_autoconfig` (`true`/`false`).
- `GAMEHUB_CONTROLLER_PROFILES_DIR`: overrides `[controllers].profiles_dir`.
- `GAMEHUB_BACKUP_KEEP_LIMIT`: overrides `[backups].keep_limit` (minimum `1`, default `3`).
- `GAMEHUB_INDEX_TIMEOUT_SECONDS`: overrides `[server].index_timeout_seconds`.
- `GAMEHUB_INDEX_FETCH_ATTEMPTS`: overrides `[server].index_fetch_attempts`.
- `GAMEHUB_INDEX_RETRY_BACKOFF_SECONDS`: overrides `[server].index_retry_backoff_seconds`.
- `GAMEHUB_MAX_PARALLEL_DOWNLOADS`: overrides `[server].max_parallel_downloads` (clamped to `1..16`).

Backup config keys:
- `[backups].keep_limit`: default `3`; automatic GAMEHUB backup families keep only the newest `N` timestamped backups after each new backup is created.
- Legacy backup buildup can be pruned manually with `./venv/bin/python scripts/cleanup_backups.py --config ./config.toml [--server-data-root <path>] [--apply]`.

Save sync config keys (TOML only for now):
- `[save_sync].enabled`: default `false` (safe rollout).
- `[save_sync].mode`: `download` (default) or `bidirectional`.
- `[save_sync].conflict_policy`: `manual` (default), `prefer_server`, or `prefer_local`; missing or invalid values normalize to `manual`.
- `[save_sync].systems`: optional allow-list of system names (case-insensitive in config, normalized to uppercase). Managed launch-session save sync and managed `PSX`/`PS2` memory-card rewrites only run for included systems.
- Save planning decisions are deterministic and include explicit reasons for `download`, `upload_existing`, `upload_new`, `conflict`, and `skip` paths (for example: `local-missing`, `download-mode-local-drift`, `local-only-create`, `download-mode-local-new`, `both-changed-manual`, `lineage-ambiguous-manual`, `save-sync-disabled`, `missed-upload-local-newer`, `missed-upload-remote-newer`).

Mode behavior reference:
- `enabled=false`: planner emits deterministic `skip` reasons (for example `save-sync-disabled`) and performs no save transfers.
- `mode=download`: planner may emit `download` or `skip`; missing local saves still download, while existing local drift becomes `skip(download-mode-local-drift)` and local-only first-time exact-file saves become `skip(download-mode-local-new)`. Both `upload_existing` and `upload_new` actions are suppressed.
- `mode=bidirectional`: planner may emit `download`, `upload_existing`, `upload_new`, `conflict`, or `skip` based on checksum lineage, local-only discovery, and `conflict_policy`.
- `conflict_policy=manual`: planner emits `conflict` for both-side drift and lineage-ambiguous drift, and records unresolved entries in state until operator intervention.
- `conflict_policy=prefer_server`: both-side drift and lineage-ambiguous drift converge to the server copy (planned `download`).
- `conflict_policy=prefer_local`: both-side drift and lineage-ambiguous drift converge to the local copy (planned `upload_existing`).
- Overwrite/conflict matrix:
  - `download`: only missing local indexed saves auto-download; any existing local drift is preserved as `skip`.
  - `bidirectional + manual` (default): one-sided drift auto-converges, but both-side or lineage-ambiguous drift becomes `conflict`.
  - `bidirectional + prefer_server`: one-sided drift auto-converges, and both-side or lineage-ambiguous drift downloads the server copy.
  - `bidirectional + prefer_local`: one-sided drift auto-converges, and both-side or lineage-ambiguous drift uploads the local copy.
- In `mode=bidirectional`, if `unresolved_save_conflicts[save_id] = "postexit-upload-missed-server-unreachable"`, planner and managed `shortcut-launch` pre-launch resolution compare local file mtime vs remote `updated_at` after UTC normalization/truncation to seconds:
  - local newer -> `upload_existing` (`missed-upload-local-newer`)
  - remote newer -> `download` (`missed-upload-remote-newer`)
  - missing/unreadable/tied timestamps -> fall back to the existing checksum/lineage conflict-safe path
- `offline_shortcut_titles[title_id]` records managed titles that launched while server metadata was unavailable. On the next connected managed pre-launch, GAMEHUB uses that title marker to seed the same `postexit-upload-missed-server-unreachable` timestamp recovery for lineage-missing indexed saves before clearing the title marker.
- In `mode=bidirectional`, managed `shortcut-launch` sessions run pre-launch download/skip/conflict reconciliation, then attempt post-exit upload when the remote save did not change during play and either the save changed during that session or pre-launch already resolved it toward `upload_existing`.
- Managed `shortcut-launch` save sync is fail-open: it runs a one-shot `/health` precheck (`1.0s` timeout) before pre-launch and post-exit network save work, and skips launch-session save network steps when the server is unreachable.
- Managed `shortcut-launch` metadata fetches (`/v1/index`, `/v1/save-bindings`) use launch-only fast-fail settings (`<=5.0s` timeout cap, attempts=`1`, backoff=`0.0s`).
- First-time local `battery` and managed `memory_card` saves are discovered on the next non-dry `gamehub sync` through `GET /v1/save-bindings`.
- Managed `shortcut-launch` sessions also auto-create those deterministic `exact_files` saves at post-exit for wrapped titles, so first-time RetroArch battery saves and managed `PSX`/`PS2` memory cards do not need to wait for the next full sync.
  - `PSX` Swanstation exact-file detection accepts managed `GH_<title_id>_1/2.mcd`, deterministic per-title `<title_name>.srm`, and deterministic per-title `<title_name>_1/2.mcd` output.
  - On macOS, native `~/Library/Application Support/RetroArch/config/retroarch.cfg` layouts materialize those deterministic `PSX` saves under sibling `~/Library/Application Support/RetroArch/saves`, while an already-materialized `~/Documents/RetroArch/saves` tree still wins for existing local saves.
- First-time `per_game` saves are learned and uploaded by managed `shortcut-launch` post-exit when one deterministic tree root can be proven (`GC` GCI folders, `Wii` title trees, and `N3DS` title data trees), including local-only saves that already existed before the connected bidirectional launch began.
- There is no background save watcher service in this release; unmanaged emulator launches reconcile on the next `gamehub sync` or next managed launch.

Dry-run expectations for save sync:
- Dry-run never writes local save files and never mutates remote save artifacts.
- Dry-run output should include explicit per-save decision reasons so operators can audit why each save is `download`, `upload_existing`, `upload_new`, `conflict`, or `skip`.

Linux PS2 note:
- When PCSX2 resolves to Flatpak and no BIOS override is set, GAMEHUB writes `Bios` in `PCSX2.ini` to `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios` and mirrors BIOS files there.
- PCSX2 controller bindings and hotkeys are managed at launch via controller profiles when `launch_autoconfig` is enabled.

RetroArch note:
- On macOS, save discovery checks `~/Documents/RetroArch` first and falls back to `~/Library/Application Support/RetroArch`.
- On macOS, config discovery prefers an existing native config file under `~/Library/Application Support/RetroArch/config/retroarch.cfg` before legacy root-level/document variants.
- On macOS, that native nested config layout uses sibling `~/Library/Application Support/RetroArch/saves` for deterministic save-sync materialization instead of `.../config/saves`.
- Deterministic RetroArch save downloads can materialize that root on first sync even before RetroArch has created the `saves/` directory tree itself.
- When RetroArch save sorting-by-core is enabled, GAMEHUB treats the core-specific subdirectory as the canonical destination instead of a legacy root-level filename match.
- That canonical sorted-core rule applies across RetroArch exact-file save systems that GAMEHUB manages (`GB`, `GBC`, `GBA`, `GEN_MD`, `NES`, `SNES`, `N64`, `NDS`, `PSX`) rather than only `N64`.
- If RetroArch config evidence for sorted-core mode is missing but the save root already contains known core subdirectories (for example `mGBA`, `Gambatte`, or `Mupen64Plus-Next`), GAMEHUB infers that sorted-core layout and keeps those core-specific paths canonical.
- When a RetroArch config file is discovered (`retroarch.cfg` candidates or explicit override), GAMEHUB sets `input_menu_toggle_gamepad_combo = "4"` (`Start+Select`) and `all_users_control_menu = "true"` for controller quick-menu access.
- For managed macOS `N64` launches, GAMEHUB also converges `video_driver = "glcore"` in `retroarch.cfg` and the current working Apple Silicon fallback `mupen64plus-rdp-plugin = "angrylion"` plus `mupen64plus-rsp-plugin = "hle"` in `retroarch-core-options.cfg`.
- If RetroArch already has `config/Mupen64Plus-Next/*.cfg` override files or existing `config/Mupen64Plus-Next/*.opt` core, folder, or per-game option overrides such as `Mupen64Plus-Next.opt`, GAMEHUB converges those files to the same macOS `N64` baseline before launch so they do not supersede the managed global files.
- That macOS `N64` remediation is applied through the same backup + temp write + atomic replace + explicit log path as other RetroArch runtime mutations and is idempotent on repeated sync/launch passes.
- If a managed macOS `N64` launch cannot resolve the RetroArch config or cannot find `mupen64plus_next_libretro.dylib` under the configured macOS cores directory, GAMEHUB blocks that launch with a warning instead of proceeding into the known audio-only black-screen path.
- On Windows, RetroArch config discovery includes portable installs (`<retroarch-install>/retroarch.cfg`) before `%APPDATA%/RetroArch/retroarch.cfg`.
- On Linux, when RetroArch resolves to Flatpak, config discovery prefers Flatpak `retroarch.cfg` before native `~/.config/retroarch/retroarch.cfg`.
- RetroArch `system_directory = ":/system"` (portable-relative) is normalized to `<retroarch.cfg dir>/system` on Windows.
- RetroArch `libretro_directory = ":/cores"` and `libretro_info_path = ":/info"` (portable-relative) are normalized to `<retroarch.cfg dir>/cores` / `<retroarch.cfg dir>/info` on Windows.
- GAMEHUB also writes a Swanstation core remap file to `<config remap dir>/SwanStation/SwanStation.rmp` (default `<retroarch.cfg dir>/config/remaps/...`) with the tested DualShock + analog/turbo defaults.
- GAMEHUB also sets:
  - `input_player1_analog_dpad_mode .. input_player8_analog_dpad_mode = "0"`
  - `input_libretro_device_p1 = "261"` (DualShock) and `input_libretro_device_p2..p8 = "1"`
  - `input_remap_port_p1..p8 = "0".."7"`
  - input turbo defaults (`input_turbo_*`) matching the tested PSX baseline
- GAMEHUB also ensures `swanstation_Controller1.Type = "AnalogController"` and `swanstation_Controller2.Type = "AnalogController"` in `retroarch-core-options.cfg` so PSX games default to DualShock-style pads.
- On Windows, GAMEHUB keeps PSX controller overrides out of `retroarch.cfg` and applies them only via the Swanstation core remap file.

Managed shortcut launch autoconfig:
- Applies to Steam shortcut launches for `PCSX2`, `Dolphin`, and `Azahar`.
- Wraps `RetroArch` launches when controller autoconfig or save sync is enabled.
- Runtime flow: detect Xbox controller count (`0`, `1`, `2+`) -> choose profile (`kbm`, `xbox_1p`, `xbox_2p`) -> apply managed keys -> launch emulator.
- The hidden wrapper command is `shortcut-launch`; older `controller-launch` shortcuts must be rewritten by a non-dry `gamehub sync` after upgrade.
- Linux Steam Deck `shortcut-launch` uses a single detect pass and applies `xbox_1p` when detection returns zero.
- Steam Deck validation scope is built-in controller mode; external Xbox controller support on Deck is planned for a later update.
- Non-Deck platforms keep standard behavior (`0 -> kbm`).
- On macOS, controller-count detection promotes only Xbox-like controllers into `xbox_*` profiles, using Xbox-branded names first and falling back to Microsoft vendor/GUID evidence when names are generic.
- On macOS, controller detection still prefers host SDL probing first, then falls back to `system_profiler` game-controller inventory, then `hidutil list` gamepad-class HID devices when no loadable SDL2 dylib is available; failure still falls through to `kbm`.
- Azahar controller-mode apply keeps pointer/touch keys preservation-first, while managed button keys are always normalized from profile mappings.
- Dolphin Linux controller-mode preserves existing controller-class device identities on non-Deck, while Deck controller-mode uses deterministic `evdev` rebinding.
- On macOS, Dolphin keyboard/mouse device identifiers use `Quartz/0/Keyboard & Mouse`.
- On macOS, Dolphin keyboard profile apply also normalizes native Quartz key tokens such as `Escape`, `Return`, and arrow/control/shift names at launch time so existing managed configs do not need manual reseeding.
- On macOS, Dolphin controller-mode apply rebinds to the current detected SDL device name when one is available; on guidless fallback inventory it prefers the emulator's embedded SDL mapping name for the exact detected vendor/product identity, and only falls back to generic `SDL/<slot>/Gamepad` when no meaningful SDL device name can be resolved.
- On macOS, Dolphin controller-mode apply also normalizes managed controller token names to the native SDL labels Dolphin expects there (for example `Button S/E/W/N` and trigger analog bindings), binds controller hotkeys to the resolved SDL pad device instead of `All Devices`, flips Wii IR vertical stick direction to the native mapping expected there, and writes every existing native/XDG Dolphin config root it finds so native `~/Library/Application Support/Dolphin` installs are not missed.
- On macOS, Azahar controller-mode apply also rewrites managed SDL button, trigger, D-pad, and analog bindings from the emulator's embedded SDL controller mapping database when a matching controller identity is found; otherwise it keeps the seeded profile layout and only normalizes GUID/port identity.
- On macOS, when repairing older Azahar configs that already contain saved SDL bindings or multiple profiles, GAMEHUB preserves the existing Azahar-written runtime GUID for the managed profile when one is present, uses the emulator's embedded SDL mapping only for button-layout normalization, and restores managed `profiles\\1\\*\\default` keys to boolean defaults instead of leaving old binding payloads there.
- Default profile root is `<gamehub_dir>/controller_profiles` and includes seeded defaults:
  - `<root>/pcsx2/<profile>/PCSX2.ini`
  - `<root>/dolphin/<profile>/GCPadNew.ini`
  - `<root>/dolphin/<profile>/WiimoteNew.ini`
  - `<root>/dolphin/<profile>/Hotkeys.ini`
  - `<root>/azahar/<profile>/qt-config.ini`
- Non-dry `gamehub init` and non-dry `gamehub sync` seed missing default profiles when `launch_autoconfig` is enabled.
- `shortcut-launch` does not seed controller profiles at launch time; run non-dry `gamehub init` or `gamehub sync` first when profile files may be missing.
- Use `--reseed-profiles` to force-overwrite managed defaults (controller profiles + Deck per-title Steam templates) on demand.
- Forced controller profile reseeds create a timestamped `*.bak` file beside each overwritten managed profile.
- If you used older branch builds before these controller profile changes, run one `gamehub init --reseed-profiles` before retesting.
- To supply custom profiles, set `[controllers].profiles_dir` (or `GAMEHUB_CONTROLLER_PROFILES_DIR`):
  - non-dry `gamehub init` and non-dry `gamehub sync` seed any missing profile files into that directory when `launch_autoconfig` is enabled
  - existing files are left unchanged unless `--reseed-profiles` is used
  - with `--reseed-profiles`, managed controller profile files are rewritten even when bytes already match, after a timestamped `*.bak` backup is created beside the target file
- Managed profile directories include `.gamehub-managed.json` markers for drift-safe ownership tracking:
  - schema version
  - source profile/template
  - timestamp
  - fingerprint/hash
  - ownership tier (`managed`)
  - when an existing marker file is rewritten, GAMEHUB writes a timestamped `.bak` beside it and logs the save
- Sync convergence applies assisted controller safety keys before Steam mutation and never fixes controller count to a single profile.
- Doctor mode for controller convergence:
  - inspect only: `gamehub doctor controllers`
  - safe repair: `gamehub doctor controllers --apply`
  - unmanaged drift is report-only by default
  - force cleanup: `gamehub doctor controllers --apply --force`
  - force cleanup archives unmanaged profile files under `.gamehub-unmanaged-backups/` before removing them from active profile directories
- If controller detection or profile application fails, GAMEHUB continues launch and attempts `kbm` fallback.

Windows Dolphin defaults:
- If Dolphin is installed by GAMEHUB (default `LOCALAPPDATA/Programs/Dolphin`), the runtime user dir is pinned to `<dolphin-install>/User`.
- Otherwise, Dolphin user dir detection prefers:
  - Portable `<dolphin-install>/User`
  - `%USERPROFILE%/Documents/Dolphin Emulator`
  - `%APPDATA%/Dolphin Emulator` (fallback)
- Override with `DOLPHIN_EMU_USERPATH` / `GAMEHUB_DOLPHIN_EMU_USERPATH` (or `dolphin_user_path` in `config.toml`).

Linux Dolphin defaults:
- Native runtime user dir: `~/.local/share/dolphin-emu`
- Flatpak runtime user dir: `~/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu`

macOS Dolphin defaults:
- Runtime/save discovery prefers an existing native-style `~/.local/share/dolphin-emu` root first.
- If no existing XDG-style Dolphin root is present, GAMEHUB falls back to `~/Library/Application Support/Dolphin`.

N3DS Azahar defaults:
- No required firmware files are enforced for N3DS.
- GAMEHUB bootstraps Azahar runtime config in:
  - Windows: `%APPDATA%/Azahar/config/qt-config.ini`
  - macOS preferred native-style config: `~/.config/azahar-emu/qt-config.ini`
  - Linux Flatpak: `~/.var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini`
- On macOS, GAMEHUB prefers an existing native-style Azahar save root `~/.local/share/azahar-emu/sdmc` before falling back to `~/Library/Application Support/Azahar/sdmc`.
- GAMEHUB sets `fullscreen=true` and `confirmClose=false` so fullscreen launch and controller-driven exit flows do not block on confirmation.
- Managed Azahar profiles and assisted `qt-config.ini` convergence also set `Shortcuts\Main%20Window\Exit%20Citra\KeySeq=Esc` with `Shortcuts\Main%20Window\Exit%20Citra\KeySeq\default=false` so managed sessions use the repo-wide `Esc` quit/menu convention instead of the inherited `Ctrl+Q` shortcut.
- Managed Azahar controller profiles and assisted `qt-config.ini` convergence also normalize `profiles\1\circle_pad` and `profiles\1\c_stick` to deterministic SDL bindings with `deadzone:0.100000`, so managed sessions stop common stick ghost-input without per-title tuning.
- Azahar controller bindings are applied at launch via controller profiles. GUID normalization is always detect-based.
- On macOS, controller-mode apply derives Azahar's managed SDL button map from the bundled SDL controller database when a matching controller identity is available, including hat-based D-pad bindings and trigger axis correction for Bluetooth Xbox pads.
- GUID discovery order (Linux Flatpak config paths): probe Azahar Flatpak runtime first; if unavailable, preserve existing GUID and otherwise keep port-only mappings (host GUID is not injected into Flatpak configs).
- GUID discovery order (Linux non-Flatpak config paths): fall back to host SDL, then keep existing GUID when discovery is unavailable.
- GUID discovery order (Windows): attempt host SDL via Azahar's bundled SDL2 or other installed SDL2 bundles (RetroArch/PCSX2/Dolphin) when available; otherwise keep existing GUIDs and fall back to port-only mappings.
- If a stored GUID matches host SDL but the Flatpak runtime probe returns a different GUID, GAMEHUB prefers the runtime GUID to keep Steam/Flatpak launches consistent.
- On Linux Flatpak Azahar, GAMEHUB emits `python -m gamehub_cli.controllers.azahar_exit_hook` in the Steam shortcut by default so `Select+Start` can close Azahar before any optional `shortcut-launch` wrapping runs.
- On Windows, GAMEHUB uses a `shortcut-launch` XInput `Start+Select` exit hook for Azahar by default; set `GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK=false` to disable it.
- On macOS, GAMEHUB uses a `shortcut-launch` native `Start+Select` exit hook for Azahar by default; it preserves the normal bundle/document launch path so native shortcuts such as `Cmd+Q` still work, prefers mapping-aware `GameController` polling for the configured controller port / combo when that mapping can be resolved, otherwise falls back to Xbox HID consumer-usage tracking via `hidutil dump services -f xml`, requests the Azahar app to quit on combo press, and only falls back to process termination for newly launched Azahar processes when one can be identified. Set `GAMEHUB_AZAHAR_MACOS_EXIT_HOOK=false` to disable it.
- On Linux Flatpak Dolphin launches wrapped by `shortcut-launch`, GAMEHUB also applies a fail-open `Select+Start` exit hook by default; set `GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK=false` to disable it.

## State file
- Format: JSON
- Tracks:
  - `downloaded_checksums` (`file_id`/`asset_id` -> checksum)
  - `firmware_checksums` (`system/filename` -> checksum)
  - `save_checksums` (`save_id` -> checksum)
  - `save_lineage` (`save_id` -> last synced local/remote checksum and timestamps)
  - `save_binding_roots` (`binding_id` -> learned `canonical_root` + client-local `materialized_root`)
  - `offline_shortcut_titles` (`title_id` -> UTC timestamp marker for managed launches that lost metadata/server reachability)
  - `unresolved_save_conflicts` (`save_id` -> last unresolved deterministic conflict reason)
  - `last_sync` (UTC timestamp)
  - `bootstrap_version` (local bootstrap marker written by `gamehub init`; current value `1`)

Save sync state semantics:
- Missing save keys in older `state.json` files load as empty defaults for backward compatibility.
- Older `state.json` files may still contain the legacy `tombstones` key; GAMEHUB ignores it on load and omits it on the next write.
- `save_checksums` tracks last-known local checksum by `save_id` for deterministic planner comparisons.
- `save_lineage` captures last-synced local/remote checksum snapshots and timestamps.
- `save_binding_roots` persists learned deterministic tree roots for `per_game` save materialization across clients and later runs.
- `offline_shortcut_titles` persists reconnect-recovery markers for managed launches that skipped metadata/save work while the server was unreachable.
- `unresolved_save_conflicts` persists manual-resolution-required conflicts between runs.
- `unresolved_save_conflicts[save_id] = "postexit-upload-missed-server-unreachable"` marks a managed launch-session upload miss caused by unreachable server; on reconnect in bidirectional mode, this enables deterministic timestamp comparison before fallback conflict logic.
- Use `gamehub doctor saves` for a read-only view of actionable persisted save conflicts, actionable binding-root ambiguity, and current save drift without opening `state.json` manually.
- Read-only doctor output suppresses stale launch-session markers when the current live save plan proves they are already synced or no longer live.
- Use `gamehub doctor saves --keep-local <save_id>` or `--keep-server <save_id>` for explicit single-save resolution; successful resolution updates lineage/checksum state and removes that save's unresolved marker.
- Non-dry `gamehub sync` prunes resolved or orphaned launch-session markers from `unresolved_save_conflicts`, refreshes lineage/checksum state for already-synced saves it clears, and leaves unresolved manual conflicts in place.
- Binding-root ambiguity markers (`savebind_*`) remain manual in this phase and are not cleared by the save-resolution flags.

Bootstrap notes:
- Fresh installs must run `gamehub init` before the first `gamehub sync`.
- `gamehub sync` requires `bootstrap_version`; if it is missing, run `gamehub init` again before syncing.

State writes back up existing `state.json`, write via `.tmp` + fsync + atomic replace, and emit explicit sync-state log records.
