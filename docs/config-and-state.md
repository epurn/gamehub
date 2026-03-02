# Config and State

## Config file
Config resolution order:
1. `--config <path>` CLI option (when provided)
2. `./config.toml` in current working directory (if present)
3. `~/.gamehub/config.toml`

Sample templates:
- Windows (verified): [docs/templates/config.windows.template.toml](templates/config.windows.template.toml)
- Bazzite (tested): [docs/templates/config.bazzite.template.toml](templates/config.bazzite.template.toml)
- Steam Deck (verified): [docs/templates/config.steamdeck.template.toml](templates/config.steamdeck.template.toml)
- General Linux: [docs/templates/config.linux.template.toml](templates/config.linux.template.toml)

Fresh installs must have a real config file in place before running `gamehub init`.

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

[controllers]
# Launch-time controller profile application for non-RetroArch emulators.
launch_autoconfig = true
# Optional explicit profile root.
# Default when omitted: <paths.gamehub_dir>/controller_profiles
profiles_dir = "~/.gamehub/controller_profiles"

[save_sync]
# Rollout default is disabled.
enabled = false
# download | bidirectional
mode = "download"
# prefer_server | prefer_local | manual
conflict_policy = "prefer_server"
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

Firmware deployment and Linux runtime env overrides:
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
- `GAMEHUB_LINUX_EMULATOR_INSTALL_BACKEND`: overrides `[linux].emulator_install_backend`.
- `GAMEHUB_LINUX_EMULATOR_INSTALL_COMMAND`: overrides `[linux].emulator_install_command`.
- `GAMEHUB_LINUX_FLATPAK_REMOTE`: overrides `[linux].flatpak_remote`.
- `GAMEHUB_AZAHAR_WINDOWS_INSTALLER_URL`: overrides the default pinned Windows Azahar installer URL used by emulator auto-install.
- `GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK`: enables/disables Windows Azahar `Start+Select` exit hook (`true` by default).
- `GAMEHUB_AZAHAR_LINUX_EXIT_HOOK`: enables/disables Linux Azahar `Select+Start` exit hook wrapper (`true` by default).
- `GAMEHUB_AZAHAR_EXIT_BUTTON_SELECT`: joystick button index used as `Select` for Linux Azahar exit hook (default `4`).
- `GAMEHUB_AZAHAR_EXIT_BUTTON_START`: joystick button index used as `Start` for Linux Azahar exit hook (default `6`).
- `GAMEHUB_AZAHAR_EXIT_JS_DEVICE`: optional explicit joystick device path for Linux Azahar exit hook (for example `/dev/input/js0`).
- `GAMEHUB_AZAHAR_SDL_DIR`: optional directory containing Azahar's `SDL2.dll` for Windows GUID discovery.
- `GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK`: enables/disables Linux Dolphin Flatpak `Select+Start` exit hook wrapper in `shortcut-launch` (`true` by default).
- `GAMEHUB_DOLPHIN_EXIT_BUTTON_SELECT`: joystick button index used as `Select` for Linux Dolphin exit hook (default `6`).
- `GAMEHUB_DOLPHIN_EXIT_BUTTON_START`: joystick button index used as `Start` for Linux Dolphin exit hook (default `7`).
- `GAMEHUB_DOLPHIN_EXIT_JS_DEVICE`: optional explicit joystick device path for Linux Dolphin exit hook (for example `/dev/input/js0`).
- `GAMEHUB_STEAM_ALLOW_DESKTOP_CONFIG`: force managed shortcut `AllowDesktopConfig` (`true`/`false`).
- Linux Azahar exit hook input sources:
  - always watches available `/dev/input/js*` joystick devices with configured button indices
  - also watches available `/dev/input/event*` devices and exits only on strict `BTN_SELECT` + `BTN_START`
- `GAMEHUB_CONTROLLER_LAUNCH_AUTOCONFIG`: overrides `[controllers].launch_autoconfig` (`true`/`false`).
- `GAMEHUB_CONTROLLER_PROFILES_DIR`: overrides `[controllers].profiles_dir`.
- `GAMEHUB_INDEX_TIMEOUT_SECONDS`: overrides `[server].index_timeout_seconds`.
- `GAMEHUB_INDEX_FETCH_ATTEMPTS`: overrides `[server].index_fetch_attempts`.
- `GAMEHUB_INDEX_RETRY_BACKOFF_SECONDS`: overrides `[server].index_retry_backoff_seconds`.
- `GAMEHUB_MAX_PARALLEL_DOWNLOADS`: overrides `[server].max_parallel_downloads` (clamped to `1..16`).

Save sync config keys (TOML only for now):
- `[save_sync].enabled`: default `false` (safe rollout).
- `[save_sync].mode`: `download` (default) or `bidirectional`.
- `[save_sync].conflict_policy`: `prefer_server` (default), `prefer_local`, or `manual`.
- `[save_sync].systems`: optional allow-list of system names (case-insensitive in config, normalized to uppercase).
- Save planning decisions are deterministic per indexed save and include explicit reasons for `download`, `upload`, `conflict`, and `skip` paths (for example: `local-missing`, `both-changed-manual`, `save-sync-disabled`).

Mode behavior reference:
- `enabled=false`: planner emits deterministic `skip` reasons (for example `save-sync-disabled`) and performs no save transfers.
- `mode=download`: planner may emit `download` or `skip`; `upload` actions are suppressed.
- `mode=bidirectional`: planner may emit `download`, `upload`, `conflict`, or `skip` based on checksum lineage and `conflict_policy`.
- `conflict_policy=prefer_server`: conflict path converges to server copy (planned `download`).
- `conflict_policy=prefer_local`: conflict path converges to local copy (planned `upload`).
- `conflict_policy=manual`: planner emits `conflict` and records unresolved entries in state until operator intervention.
- In `mode=bidirectional`, managed `shortcut-launch` sessions run pre-launch download/skip/conflict reconciliation, then attempt post-exit upload only when the remote save did not change during play.
- There is no background save watcher service in this release; unmanaged emulator launches reconcile on the next `gamehub sync` or next managed launch.

Dry-run expectations for save sync:
- Dry-run never writes local save files and never mutates remote save artifacts.
- Dry-run output should include explicit per-save decision reasons so operators can audit why each save is `download`, `upload`, `conflict`, or `skip`.

Linux PS2 note:
- When PCSX2 resolves to Flatpak and no BIOS override is set, GAMEHUB writes `Bios` in `PCSX2.ini` to `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios` and mirrors BIOS files there.
- PCSX2 controller bindings and hotkeys are managed at launch via controller profiles when `launch_autoconfig` is enabled.

RetroArch note:
- When a RetroArch config file is discovered (`retroarch.cfg` candidates or explicit override), GAMEHUB sets `input_menu_toggle_gamepad_combo = "4"` (`Start+Select`) and `all_users_control_menu = "true"` for controller quick-menu access.
- On Windows, RetroArch config discovery includes portable installs (`<retroarch-install>/retroarch.cfg`) before `%APPDATA%/RetroArch/retroarch.cfg`.
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
- Does not wrap `RetroArch` launches.
- Runtime flow: detect Xbox controller count (`0`, `1`, `2+`) -> choose profile (`kbm`, `xbox_1p`, `xbox_2p`) -> apply managed keys -> launch emulator.
- The hidden wrapper command is `shortcut-launch`; older `controller-launch` shortcuts must be rewritten by a non-dry `gamehub sync` after upgrade.
- Linux Steam Deck `shortcut-launch` uses a single detect pass and applies `xbox_1p` when detection returns zero.
- Steam Deck validation scope is built-in controller mode; external Xbox controller support on Deck is planned for a later update.
- Non-Deck platforms keep standard behavior (`0 -> kbm`).
- Azahar controller-mode apply keeps pointer/touch keys preservation-first, while managed button keys are always normalized from profile mappings.
- Dolphin Linux controller-mode preserves existing controller-class device identities on non-Deck, while Deck controller-mode uses deterministic `evdev` rebinding.
- Default profile root is `<gamehub_dir>/controller_profiles` and includes seeded defaults:
  - `<root>/pcsx2/<profile>/PCSX2.ini`
  - `<root>/dolphin/<profile>/GCPadNew.ini`
  - `<root>/dolphin/<profile>/WiimoteNew.ini`
  - `<root>/dolphin/<profile>/Hotkeys.ini`
  - `<root>/azahar/<profile>/qt-config.ini`
- Non-dry `gamehub init` and non-dry `gamehub sync` seed missing default profiles when `launch_autoconfig` is enabled.
- Use `--reseed-profiles` to force-overwrite managed defaults (controller profiles + Deck per-title Steam templates) on demand.
- If you used older branch builds before these controller profile changes, run one `gamehub init --reseed-profiles` before retesting.
- To supply custom profiles, set `[controllers].profiles_dir` (or `GAMEHUB_CONTROLLER_PROFILES_DIR`):
  - non-dry `gamehub init` and non-dry `gamehub sync` seed any missing profile files into that directory when `launch_autoconfig` is enabled
  - existing files are left unchanged unless `--reseed-profiles` is used
  - with `--reseed-profiles`, managed files are rewritten even when bytes already match
- Managed profile directories include `.gamehub-managed.json` markers for drift-safe ownership tracking:
  - schema version
  - source profile/template
  - timestamp
  - fingerprint/hash
  - ownership tier (`managed`)
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

N3DS Azahar defaults:
- No required firmware files are enforced for N3DS.
- GAMEHUB bootstraps Azahar runtime config in:
  - Windows: `%APPDATA%/Azahar/config/qt-config.ini`
  - Linux Flatpak: `~/.var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini`
- GAMEHUB sets `fullscreen=true` and `confirmClose=false` so fullscreen launch and controller-driven exit flows do not block on confirmation.
- Azahar controller bindings are applied at launch via controller profiles. GUID normalization is always detect-based.
- GUID discovery order (Linux Flatpak config paths): probe Azahar Flatpak runtime first; if unavailable, preserve existing GUID and otherwise keep port-only mappings (host GUID is not injected into Flatpak configs).
- GUID discovery order (Linux non-Flatpak config paths): fall back to host SDL, then keep existing GUID when discovery is unavailable.
- GUID discovery order (Windows): attempt host SDL via Azahar's bundled SDL2 or other installed SDL2 bundles (RetroArch/PCSX2/Dolphin) when available; otherwise keep existing GUIDs and fall back to port-only mappings.
- If a stored GUID matches host SDL but the Flatpak runtime probe returns a different GUID, GAMEHUB prefers the runtime GUID to keep Steam/Flatpak launches consistent.
- On Linux, GAMEHUB uses a wrapper launch hook by default to close Azahar when `Select+Start` is pressed (native-controller mode).
- On Windows, GAMEHUB uses a `shortcut-launch` XInput `Start+Select` exit hook for Azahar by default; set `GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK=false` to disable it.
- On Linux Flatpak Dolphin launches wrapped by `shortcut-launch`, GAMEHUB also applies a fail-open `Select+Start` exit hook by default; set `GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK=false` to disable it.

## State file
- Format: JSON
- Tracks:
  - `downloaded_checksums` (`file_id`/`asset_id` -> checksum)
  - `firmware_checksums` (`system/filename` -> checksum)
  - `save_checksums` (`save_id` -> checksum)
  - `save_lineage` (`save_id` -> last synced local/remote checksum and timestamps)
  - `unresolved_save_conflicts` (`save_id` -> last unresolved deterministic conflict reason)
  - `tombstones`
  - `last_sync` (UTC timestamp)
  - `bootstrap_version` (local bootstrap marker written by `gamehub init`; current value `1`)

Save sync state semantics:
- Missing save keys in older `state.json` files load as empty defaults for backward compatibility.
- `save_checksums` tracks last-known local checksum by `save_id` for deterministic planner comparisons.
- `save_lineage` captures last-synced local/remote checksum snapshots and timestamps.
- `unresolved_save_conflicts` persists manual-resolution-required conflicts between runs.

Bootstrap notes:
- Fresh installs must run `gamehub init` before the first `gamehub sync`.
- `gamehub sync` fails fast on fresh installs when `bootstrap_version` is missing and no legacy sync evidence exists.
- Existing installs upgrade in place:
  - if older `state.json` files do not include `bootstrap_version` but do include prior sync evidence (`last_sync`, downloaded checksums, or firmware checksums), `gamehub sync` still runs and backfills `bootstrap_version` after a successful non-dry sync.

Writes are atomic (`.tmp` then rename).
