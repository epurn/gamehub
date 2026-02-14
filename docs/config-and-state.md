# Config and State

## Config file
Default path: platform-specific config dir `gamehub/config.toml`.

Example:
```toml
[server]
url = "http://127.0.0.1:8000"

[paths]
library_dir = "C:/gamehub/library"
firmware_dir = "C:/gamehub/firmware"
state_path = "C:/gamehub/state.json"

[steam]
userdata_dir = "C:/Program Files (x86)/Steam/userdata"
steam_exe = "C:/Program Files (x86)/Steam/steam.exe"
```

## State file
- Format: JSON
- Tracks:
  - `downloaded_checksums` (`file_id`/`asset_id` -> checksum)
  - `firmware_checksums` (`system/filename` -> checksum)
  - `tombstones`
  - `last_sync` (UTC timestamp)

Writes are atomic (`.tmp` then rename).
