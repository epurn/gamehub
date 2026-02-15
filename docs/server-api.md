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
- `.7z` archives are not indexed/supported for `PSX`/`PS2`; use supported disc formats (for example `.chd`, `.cue` + `.bin`, `.iso`, `.pbp`).
- Nested title directories under `roms/<system>/` are rejected.
- Duplicate title stems in one system are rejected (for example `Title.iso` and `Title.chd`).
- Firmware metadata in `/v1/index` is scanned from `firmware/<system>/` and includes SHA256 per file.
- For systems with required firmware (for example PS2), index generation fails if required firmware is missing while titles are present.
- Asset serving endpoint exists, but flat-ROM indexing currently emits no local assets.
- Initial canonical systems: `GB`, `GBA`, `GBC`, `GEN_MD`, `N64`, `NDS`, `NES`, `PSX`, `SNES`, `GC`, `Wii`, `PS2`.

## Index refresh policy
- The server keeps the latest index snapshot in memory and serves `/v1/index`, `/v1/files/{file_id}`, and `/v1/assets/{asset_id}` from that cached snapshot.
- `GAMEHUB_INDEX_REFRESH_SECONDS` controls automatic refresh:
  - `0` (default): no TTL refresh; rebuild only on first load after startup and on explicit refresh requests
  - `>0`: rebuild on the next request after the cached snapshot age reaches this TTL
- Operators can force a manual rebuild at any time with:
  - `GET /v1/index?refresh=1`
