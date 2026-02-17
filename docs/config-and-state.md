# Config and State

## Config file
Config resolution order:
1. `--config <path>` CLI option (when provided)
2. `./config.toml` in current working directory (if present)
3. `~/.gamehub/config.toml`
4. legacy fallback: platform-specific config dir `gamehub/config.toml`

Sample templates:
- Windows (verified): [docs/templates/config.windows.template.toml](templates/config.windows.template.toml)
- Bazzite (tested): [docs/templates/config.bazzite.template.toml](templates/config.bazzite.template.toml)
- Steam Deck (untested): [docs/templates/config.steamdeck.template.toml](templates/config.steamdeck.template.toml)
- General Linux: [docs/templates/config.linux.template.toml](templates/config.linux.template.toml)

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
# Linux PCSX2 controller bootstrap (generic SDL mapping for Pad1 + Pad2)
pcsx2_controller_autoconfig = true
dolphin_user_path = "~/.local/share/dolphin-emu"

[controllers]
# Launch-time controller profile application for non-RetroArch emulators.
launch_autoconfig = true
# Optional explicit profile root.
# Default when omitted: <paths.gamehub_dir>/controller_profiles
profiles_dir = "~/.gamehub/controller_profiles"
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
- GAMEHUB canonicalizes collection membership appids to unsigned numeric values in both `localconfig.vdf` (`user-collections`) and cloud storage collection entries.
- Steam reopen requires an active desktop/GUI session; SSH-only sessions may apply file updates successfully but fail to relaunch Steam.

`paths.gamehub_dir` is the local sync root. Derived paths:
- ROMs/assets root: `<gamehub_dir>/roms/...` (from server index relative paths)
- Firmware root: `<gamehub_dir>/firmware/...`
- State file: `<gamehub_dir>/state.json`

On non-dry sync, firmware system subdirectories are auto-created under `<gamehub_dir>/firmware` based on indexed systems.

Environment overrides are resolved centrally in `load_config` (precedence: CLI flag > env > config file > default).

Firmware deployment and Linux runtime env overrides:
- `RETROARCH_SYSTEM_DIR` or `GAMEHUB_RETROARCH_SYSTEM_DIR`: explicit RetroArch `system` directory target.
- `PCSX2_BIOS_DIR` or `GAMEHUB_PCSX2_BIOS_DIR`: explicit BIOS directory written into PCSX2 config (`PCSX2.ini`).
- `DOLPHIN_EMU_USERPATH` or `GAMEHUB_DOLPHIN_EMU_USERPATH`: explicit Dolphin runtime user directory target.
  - GC/Wii firmware deploys into `<userpath>/GC` and `<userpath>/Wii`.
  - Steam launch templates are normalized to pass `-u "<userpath>"`.
  - Dolphin runtime config files (`Dolphin.ini`, `GCPadNew.ini`, `WiimoteNew.ini`, `Hotkeys.ini`) are bootstrapped under `<userpath>/Config`.
- `GAMEHUB_RETROARCH_CFG_PATH`: explicit RetroArch config file path.
- `GAMEHUB_PCSX2_INI_PATH`: explicit PCSX2 ini path.
- `GAMEHUB_PCSX2_CONTROLLER_AUTOCONFIG`: overrides `[linux].pcsx2_controller_autoconfig` (`true`/`false`).
- `GAMEHUB_RETROARCH_CORES_BASE_URL`: optional base URL override for RetroArch core downloads.
- `GAMEHUB_RETROARCH_CORES_DIR`: explicit RetroArch cores directory for core auto-provisioning.
- `GAMEHUB_RETROARCH_INFO_DIR`: explicit RetroArch info directory for `.info` metadata auto-provisioning.
- `GAMEHUB_LINUX_EMULATOR_INSTALL_BACKEND`: overrides `[linux].emulator_install_backend`.
- `GAMEHUB_LINUX_EMULATOR_INSTALL_COMMAND`: overrides `[linux].emulator_install_command`.
- `GAMEHUB_LINUX_FLATPAK_REMOTE`: overrides `[linux].flatpak_remote`.
- `GAMEHUB_AZAHAR_WINDOWS_INSTALLER_URL`: overrides the default pinned Windows Azahar installer URL used by emulator auto-install.
- `GAMEHUB_AZAHAR_LINUX_EXIT_HOOK`: enables/disables Linux Azahar `Select+Start` exit hook wrapper (`true` by default).
- `GAMEHUB_AZAHAR_EXIT_BUTTON_SELECT`: joystick button index used as `Select` for Linux Azahar exit hook (default `4`).
- `GAMEHUB_AZAHAR_EXIT_BUTTON_START`: joystick button index used as `Start` for Linux Azahar exit hook (default `6`).
- `GAMEHUB_AZAHAR_EXIT_JS_DEVICE`: optional explicit joystick device path for Linux Azahar exit hook (for example `/dev/input/js0`).
- `GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK`: enables/disables Linux Dolphin Flatpak `Select+Start` exit hook wrapper in `controller-launch` (`true` by default).
- `GAMEHUB_DOLPHIN_EXIT_BUTTON_SELECT`: joystick button index used as `Select` for Linux Dolphin exit hook (default `6`).
- `GAMEHUB_DOLPHIN_EXIT_BUTTON_START`: joystick button index used as `Start` for Linux Dolphin exit hook (default `7`).
- `GAMEHUB_DOLPHIN_EXIT_JS_DEVICE`: optional explicit joystick device path for Linux Dolphin exit hook (for example `/dev/input/js0`).
- `GAMEHUB_AZAHAR_FORCE_DISCOVERED_GUID`: when `true`, Linux Azahar controller apply replaces existing GUID-bound SDL mappings with discovered GUIDs (Flatpak runtime first, host SDL fallback) (default `false`).
- `GAMEHUB_AZAHAR_GUID_MODE`: Linux Azahar GUID policy for controller apply (`preserve` default, `detect`, `fixed`, `off`).
- `GAMEHUB_AZAHAR_FIXED_GUID`: 32-hex SDL GUID used when `GAMEHUB_AZAHAR_GUID_MODE=fixed`.
- Linux Azahar exit hook input sources:
  - always watches available `/dev/input/js*` joystick devices with configured button indices
  - also watches available `/dev/input/event*` devices and exits only on strict `BTN_SELECT` + `BTN_START`
- `GAMEHUB_CONTROLLER_LAUNCH_AUTOCONFIG`: overrides `[controllers].launch_autoconfig` (`true`/`false`).
- `GAMEHUB_CONTROLLER_PROFILES_DIR`: overrides `[controllers].profiles_dir`.
- `GAMEHUB_INDEX_TIMEOUT_SECONDS`: overrides `[server].index_timeout_seconds`.
- `GAMEHUB_INDEX_FETCH_ATTEMPTS`: overrides `[server].index_fetch_attempts`.
- `GAMEHUB_INDEX_RETRY_BACKOFF_SECONDS`: overrides `[server].index_retry_backoff_seconds`.
- `GAMEHUB_MAX_PARALLEL_DOWNLOADS`: overrides `[server].max_parallel_downloads` (clamped to `1..16`).

Linux PS2 note:
- When PCSX2 resolves to Flatpak and no BIOS override is set, GAMEHUB writes `Bios` in `PCSX2.ini` to `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios` and mirrors BIOS files there.
- On Linux, GAMEHUB can also bootstrap generic SDL controller mappings for `Pad1` and `Pad2` so first-run PCSX2 controller setup works for Xbox/DS4/DS5/other SDL controllers without per-device hardcoding.
- During this bootstrap, keyboard/mouse default pad bindings are replaced with SDL bindings; set `[linux].pcsx2_controller_autoconfig = false` (or `GAMEHUB_PCSX2_CONTROLLER_AUTOCONFIG=false`) to opt out.
- GAMEHUB also bootstraps `Hotkeys/OpenPauseMenu = SDL-0/Back & SDL-0/Start` when the existing binding is missing or keyboard-only.

RetroArch note:
- When a RetroArch config file is discovered (`retroarch.cfg` candidates or explicit override), GAMEHUB sets `input_menu_toggle_gamepad_combo = "4"` (`Start+Select`) and `all_users_control_menu = "true"` for controller quick-menu access.

Controller launch autoconfig:
- Applies to Steam shortcut launches for `PCSX2`, `Dolphin`, and `Azahar`.
- Does not wrap `RetroArch` launches.
- Runtime flow: detect Xbox controller count (`0`, `1`, `2+`) -> choose profile (`kbm`, `xbox_1p`, `xbox_2p`) -> apply managed keys -> launch emulator.
- Default profile root is `<gamehub_dir>/controller_profiles` and includes seeded defaults:
  - `<root>/pcsx2/<profile>/PCSX2.ini`
  - `<root>/dolphin/<profile>/GCPadNew.ini`
  - `<root>/dolphin/<profile>/WiimoteNew.ini`
  - `<root>/dolphin/<profile>/Hotkeys.ini`
  - `<root>/azahar/<profile>/qt-config.ini`
- Override any seeded file to customize mappings; GAMEHUB loads user file first and falls back to bundled defaults when missing.
- If controller detection or profile application fails, GAMEHUB continues launch and attempts `kbm` fallback.

Legacy keys `paths.library_dir`, `paths.firmware_dir`, and `paths.state_path` are still accepted for compatibility, but `paths.gamehub_dir` is the canonical setting.

Linux Dolphin defaults:
- Native runtime user dir: `~/.local/share/dolphin-emu`
- Flatpak runtime user dir: `~/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu`

N3DS Azahar defaults:
- No required firmware files are enforced for N3DS.
- GAMEHUB bootstraps Azahar runtime config in:
  - Windows: `%APPDATA%/Azahar/config/qt-config.ini`
  - Linux Flatpak: `~/.var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini`
- GAMEHUB sets `fullscreen=true` and `confirmClose=false` so fullscreen launch and controller-driven exit flows do not block on confirmation.
- On Linux, GAMEHUB bootstraps SDL controller bindings for Azahar profile 1 when keyboard defaults are detected.
- On Linux controller-profile apply, Azahar GUID behavior is policy-driven:
  - `preserve` (default): keep existing GUID if present, otherwise use discovered GUID
  - `detect`: always prefer discovered GUID when available
  - `fixed`: force `GAMEHUB_AZAHAR_FIXED_GUID`
  - `off`: strip/avoid GUID tokens and rely on SDL `port` only
  - Legacy override `GAMEHUB_AZAHAR_FORCE_DISCOVERED_GUID=true` maps to `detect`
- GUID discovery order (Linux): probe Azahar Flatpak runtime first (if available), then fall back to host SDL.
- If a stored GUID matches host SDL but the Flatpak runtime probe returns a different GUID, GAMEHUB prefers the runtime GUID to keep Steam/Flatpak launches consistent.
- On Linux, GAMEHUB uses a wrapper launch hook by default to close Azahar when `Select+Start` is pressed (native-controller mode).
- On Linux Flatpak Dolphin launches wrapped by `controller-launch`, GAMEHUB also applies a fail-open `Select+Start` exit hook by default; set `GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK=false` to disable it.
- Steam Input layout/template copy for N3DS remains manual in this pass.

## State file
- Format: JSON
- Tracks:
  - `downloaded_checksums` (`file_id`/`asset_id` -> checksum)
  - `firmware_checksums` (`system/filename` -> checksum)
  - `tombstones`
  - `last_sync` (UTC timestamp)

Writes are atomic (`.tmp` then rename).
