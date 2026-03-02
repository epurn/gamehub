# Server API

Base URL: `http://<host>:8000`

## Endpoints
- `GET /health`
  - Returns `{ "status": "ok" }`
- `GET /v1/index`
  - Returns strict `LibraryIndex` JSON (`index_version=1`)
  - Query param `refresh=1` forces an immediate index rebuild before responding
- `GET /v1/files/{file_id}`
  - Streams ROM file content for IDs present in `/v1/index`
  - `404` for unknown `file_id`
- `GET /v1/assets/{asset_id}`
  - Streams asset file content for IDs present in `/v1/index`
  - `404` for unknown `asset_id`
- `GET /v1/saves/{save_id}`
  - Streams save file content for `save_id` values present in the active in-memory `/v1/index` snapshot
  - `404` for unknown `save_id` (including traversal-like target strings, because lookup is ID-based only)
- `PUT /v1/saves/{save_id}`
  - Accepts raw save bytes for the indexed `save_id`
  - Streams to a temporary `.part` file, atomically replaces the target save file, refreshes the in-memory index snapshot, then returns the refreshed `SaveSpec` JSON
  - `404` for unknown `save_id`
- `GET /v1/firmware/{system}/{filename}`
  - Streams raw firmware file from `firmware/<system>/<filename>`
  - `404` when file is missing
  - `404` when `system` or `filename` contains traversal-like segments (`..`, `/`, `\`)

## Data root
- Configured by env var `GAMEHUB_DATA_DIR` (default `/data`)
- Expected layout:
  - `roms/<system>/<title.ext>`
  - `firmware/<system>/<filename>`

## Index generation notes
- ROMs are discovered from files in `roms/<system>/` matching the system's allowed extensions.
- Dolphin systems (`GC`, `Wii`) accept `.ciso` in addition to existing disc formats.
- `N3DS` accepts `.3ds`, `.cci`, and `.cxi` ROM extensions.
- `.7z` archives are not indexed/supported for `PSX`/`PS2`; use supported disc formats (for example `.chd`, `.cue` + `.bin`, `.iso`, `.pbp`).
- Nested title directories under `roms/<system>/` are rejected.
- Duplicate title stems in one system are rejected (for example `Title.iso` and `Title.chd`).
- Firmware metadata in `/v1/index` is scanned from `firmware/<system>/` for systems with firmware scanning enabled, and includes SHA256 per file.
- SHA256 generation uses a persistent metadata-keyed cache (`size` + `mtime_ns`) so unchanged files skip re-hash on future rebuilds.
- Hash cache path is configurable with `GAMEHUB_HASH_CACHE_PATH` (default: OS temp dir).
- Wii firmware directory files are ignored for indexing in v1 (no required Wii firmware).
- N3DS firmware directory files are ignored for indexing in v1.1 (no required N3DS firmware).
- For systems with required firmware (for example `PS2`), index generation fails if required firmware is missing while titles are present.
- Asset serving endpoint exists, but flat-ROM indexing currently emits no local assets.
- Initial canonical systems: `GB`, `GBA`, `GBC`, `GEN_MD`, `N64`, `NDS`, `N3DS`, `NES`, `PSX`, `SNES`, `GC`, `Wii`, `PS2`.

## Index refresh policy
- The server keeps the latest index snapshot in memory and serves `/v1/index`, `/v1/files/{file_id}`, `/v1/assets/{asset_id}`, and `/v1/saves/{save_id}` from that cached snapshot.
- The server automatically detects files added/removed/updated under:
  - `roms/<system>/`
  - `firmware/<system>/`
- A background poller checks for changes by default:
  - `GAMEHUB_INDEX_POLL_SECONDS=1` by default
  - set `GAMEHUB_INDEX_POLL_SECONDS=0` to disable background polling
- Automatic rebuilds wait until a detected change remains unchanged for `GAMEHUB_INDEX_STABLE_SECONDS` seconds (default `2`) before replacing the cached snapshot.
- `GET /v1/index` also checks for pending changes, but it keeps serving the last good cached snapshot until the changed files have stayed stable long enough to rebuild safely.
- If an automatic rebuild fails after a previous snapshot already exists, the server keeps serving the last good cached snapshot and retries later.
- When a rebuild changes the indexed contents, the server logs a summary plus per-file lines for added, updated, and removed ROM/firmware entries.
- `GAMEHUB_INDEX_REFRESH_SECONDS` is optional TTL-based refresh on top of change detection:
  - `0` (default): no TTL-based rebuilds
  - `>0`: also rebuild after the cached snapshot age reaches this TTL when no source change is still settling
- Operators can force a manual rebuild at any time with:
  - `GET /v1/index?refresh=1`
  - forced refresh bypasses the stability wait and returns an error immediately if the library is invalid

## Save endpoint behavior by rollout mode
- Download mode clients call `GET /v1/saves/{save_id}` only for saves selected by planner policy and checksum lineage.
- Bidirectional mode uses `PUT /v1/saves/{save_id}` for upload actions selected by client policy.
- Unknown IDs always return `404`; clients must not attempt path-like probing or filename-based fallback lookups.
