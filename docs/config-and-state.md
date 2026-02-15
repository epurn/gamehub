# Config and State

## Config file
Config resolution order:
1. `--config <path>` CLI option (when provided)
2. `./config.toml` in current working directory (if present)
3. platform-specific config dir `gamehub/config.toml`

Sample templates:
- Windows: `docs/templates/config.windows.template.toml`
- Linux (Fedora/Ubuntu/SteamOS-like): `docs/templates/config.linux.template.toml`

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
- `DOLPHIN_EMU_USERPATH` or `GAMEHUB_DOLPHIN_EMU_USERPATH`: explicit Dolphin user directory target (Wii firmware deploys into `<userpath>/Wii`).
- `GAMEHUB_RETROARCH_CFG_PATH`: explicit RetroArch config file path.
- `GAMEHUB_PCSX2_INI_PATH`: explicit PCSX2 ini path.
- `GAMEHUB_PCSX2_CONTROLLER_AUTOCONFIG`: overrides `[linux].pcsx2_controller_autoconfig` (`true`/`false`).
- `GAMEHUB_RETROARCH_CORES_BASE_URL`: optional base URL override for RetroArch core downloads.
- `GAMEHUB_RETROARCH_CORES_DIR`: explicit RetroArch cores directory for core auto-provisioning.
- `GAMEHUB_RETROARCH_INFO_DIR`: explicit RetroArch info directory for `.info` metadata auto-provisioning.
- `GAMEHUB_LINUX_EMULATOR_INSTALL_BACKEND`: overrides `[linux].emulator_install_backend`.
- `GAMEHUB_LINUX_EMULATOR_INSTALL_COMMAND`: overrides `[linux].emulator_install_command`.
- `GAMEHUB_LINUX_FLATPAK_REMOTE`: overrides `[linux].flatpak_remote`.
- `GAMEHUB_INDEX_TIMEOUT_SECONDS`: overrides `[server].index_timeout_seconds`.
- `GAMEHUB_INDEX_FETCH_ATTEMPTS`: overrides `[server].index_fetch_attempts`.
- `GAMEHUB_INDEX_RETRY_BACKOFF_SECONDS`: overrides `[server].index_retry_backoff_seconds`.
- `GAMEHUB_MAX_PARALLEL_DOWNLOADS`: overrides `[server].max_parallel_downloads` (clamped to `1..16`).

Linux PS2 note:
- When PCSX2 resolves to Flatpak and no BIOS override is set, GAMEHUB writes `Bios` in `PCSX2.ini` to `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios` and mirrors BIOS files there.
- On Linux, GAMEHUB can also bootstrap generic SDL controller mappings for `Pad1` and `Pad2` so first-run PCSX2 controller setup works for Xbox/DS4/DS5/other SDL controllers without per-device hardcoding.
- During this bootstrap, keyboard/mouse default pad bindings are replaced with SDL bindings; set `[linux].pcsx2_controller_autoconfig = false` (or `GAMEHUB_PCSX2_CONTROLLER_AUTOCONFIG=false`) to opt out.

Legacy keys `paths.library_dir`, `paths.firmware_dir`, and `paths.state_path` are still accepted for compatibility, but `paths.gamehub_dir` is the canonical setting.

## State file
- Format: JSON
- Tracks:
  - `downloaded_checksums` (`file_id`/`asset_id` -> checksum)
  - `firmware_checksums` (`system/filename` -> checksum)
  - `tombstones`
  - `last_sync` (UTC timestamp)

Writes are atomic (`.tmp` then rename).
