# Config and State

## Config file
Config resolution order:
1. `--config <path>` CLI option (when provided)
2. `./config.toml` in current working directory (if present)
3. platform-specific config dir `gamehub/config.toml`

Example:
```toml
[server]
url = "http://127.0.0.1:8000"

[paths]
gamehub_dir = "C:/gamehub"

[steam]
userdata_dir = "C:/Program Files (x86)/Steam/userdata"
steam_id = "76561198000000001"
steam_exe = "C:/Program Files (x86)/Steam/steam.exe"

[sgdb]
api_key = "optional-sgdb-api-key"
cache_dir = "C:/gamehub/artwork-cache/sgdb"
enabled_kinds = ["grid", "hero", "logo", "icon"]
```

`sgdb.api_key` can also be supplied via environment variable `GAMEHUB_SGDB_API_KEY` (takes precedence over config file value).

`steam.steam_id` is optional. When set, sync targets that exact Steam profile and fails if it does not exist under the configured userdata directory.
It accepts either:
- userdata account id (short numeric folder name under `Steam/userdata`)
- SteamID64 (community profile numeric id)

When SteamID64 is supplied, GAMEHUB maps it to the matching userdata account id automatically.
When omitted, sync auto-detects a profile under `steam.userdata_dir` and prefers the most recently active profile (`localconfig.vdf`/`shortcuts.vdf` mtime).

`paths.gamehub_dir` is the local sync root. Derived paths:
- ROMs/assets root: `<gamehub_dir>/roms/...` (from server index relative paths)
- Firmware root: `<gamehub_dir>/firmware/...`
- State file: `<gamehub_dir>/state.json`

On non-dry sync, firmware system subdirectories are auto-created under `<gamehub_dir>/firmware` based on indexed systems.

Firmware deployment env overrides:
- `RETROARCH_SYSTEM_DIR`: explicit RetroArch `system` directory target.
- `PCSX2_BIOS_DIR`: explicit BIOS directory written into PCSX2 config (`PCSX2.ini`).
- `DOLPHIN_EMU_USERPATH`: explicit Dolphin user directory target (Wii firmware deploys into `<userpath>/Wii`).
- `GAMEHUB_RETROARCH_CORES_BASE_URL`: optional base URL override for RetroArch core downloads.
- `GAMEHUB_RETROARCH_CORES_DIR`: explicit RetroArch cores directory for core auto-provisioning.
- `GAMEHUB_RETROARCH_INFO_DIR`: explicit RetroArch info directory for `.info` metadata auto-provisioning.

Legacy keys `paths.library_dir`, `paths.firmware_dir`, and `paths.state_path` are still accepted for compatibility, but `paths.gamehub_dir` is the canonical setting.

## State file
- Format: JSON
- Tracks:
  - `downloaded_checksums` (`file_id`/`asset_id` -> checksum)
  - `firmware_checksums` (`system/filename` -> checksum)
  - `tombstones`
  - `last_sync` (UTC timestamp)

Writes are atomic (`.tmp` then rename).
