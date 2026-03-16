# Server API

Base URL: `http://<host>:8000`

Direct-run note:
- `gamehub-server` now defaults to `127.0.0.1:8000`
- set `GAMEHUB_SERVER_LISTEN_HOST` explicitly if you want broader host exposure outside Docker

## Endpoints
- `GET /health`
  - Returns `{ "status": "ok" }`
- `GET /v1/index`
  - Returns strict `LibraryIndex` JSON (`index_version=1`)
  - Returns gzip-encoded JSON when the client advertises `Accept-Encoding: gzip`
  - Query param `refresh=1` forces an immediate index rebuild before responding
- `GET /v1/files/{file_id}`
  - Streams ROM file content for IDs present in `/v1/index`
  - `404` for unknown `file_id`
  - `404` if the cached path is now missing, symlinked, or resolved outside the allowed content root
- `GET /v1/assets/{asset_id}`
  - Streams asset file content for IDs present in `/v1/index`
  - `404` for unknown `asset_id`
  - `404` if the cached path is now missing, symlinked, or resolved outside the allowed content root
- `GET /v1/saves/{save_id}`
  - Streams save file content for `save_id` values present in the active in-memory `/v1/index` snapshot
  - `404` for unknown `save_id` (including traversal-like target strings, because lookup is ID-based only)
  - `404` if the cached path is now missing, symlinked, or resolved outside the allowed content root
- `GET /v1/save-bindings`
  - Returns a strict `{ "bindings": [...] }` catalog of deterministic save-creation bindings for managed titles
  - Bindings exist even when a title has no current remote save files
- `PUT /v1/saves/{save_id}`
  - This is the only save write route and it now handles both create and update
  - Requires `multipart/form-data` with `binding_id`, `canonical_suffix`, and `file`
  - Upload parsing is streamed; the server does not read the entire multipart payload into memory before write
  - Upload size is capped by `GAMEHUB_MAX_SAVE_UPLOAD_BYTES` (default `134217728` bytes / `128 MiB`); oversized uploads return `413`
  - Existing-save updates also require `expected_remote_sha256`; the server returns `409` if the remote checksum changed
  - Missing remote saves are created when `binding_id + canonical_suffix` deterministically maps to `save_id`
  - Concurrent writes for the same `save_id` are serialized inside the server process so stale create/update requests re-check fresh remote state before write
  - Save writes force-refresh index state before conflict checks so stale cache snapshots cannot silently bypass overwrite safety
  - Writes use temp-file + fsync + atomic replace, create a backup before replacing existing user data, prune that save's backup family to `GAMEHUB_BACKUP_KEEP_LIMIT` (default `3`), force-refresh after write, then return refreshed `SaveSpec` JSON
  - `409` responses return structured payloads in `detail`: `reason` plus `current` `SaveSpec` when available (for example `remote-sha-mismatch`, `target-exists`, `indexed-save-missing-file`, `target-exists-unindexed`)
- `GET /v1/firmware/{system}/{filename}`
  - Streams raw firmware file from `firmware/<system>/<filename>`
  - `404` when file is missing
  - `404` when `system` or `filename` contains traversal-like segments (`..`, `/`, `\`)

## Data root
- Configured by env var `GAMEHUB_DATA_DIR` (default `/data`)
- Existing-save backup retention is configured by env var `GAMEHUB_BACKUP_KEEP_LIMIT` (default `3`)
- Expected layout:
  - `roms/<system>/<title.ext>`
  - `firmware/<system>/<filename>`
  - `saves/<system>/<title_stem>/<kind>/<file...>`
- Symlinked files or directories anywhere under `roms/`, `firmware/`, or `saves/` are invalid operator input and are rejected by indexing and file-serving paths.

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
- GAMEHUB-generated save backups (`<name>.<YYYYmmddHHMMSS>[.<n>].bak`) are never indexed as canonical saves and are never advertised to clients through `/v1/index`.
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
- Source-change detection covers:
  - `roms/<system>/`
  - `firmware/<system>/`
  - `saves/<system>/`
- Automatic rebuilds wait until a detected change remains unchanged for `GAMEHUB_INDEX_STABLE_SECONDS` seconds (default `2`) before replacing the cached snapshot.
- `GET /v1/index` also checks for pending changes, but it keeps serving the last good cached snapshot until the changed files have stayed stable long enough to rebuild safely.
- If an automatic rebuild fails after a previous snapshot already exists, the server keeps serving the last good cached snapshot and retries later.
- When a rebuild changes the indexed contents, the server logs a summary plus per-file lines for added, updated, and removed ROM, firmware, and save entries.
- `GAMEHUB_INDEX_REFRESH_SECONDS` is optional TTL-based refresh on top of change detection:
  - `0` (default): no TTL-based rebuilds
  - `>0`: also rebuild after the cached snapshot age reaches this TTL when no source change is still settling
- Operators can force a manual rebuild at any time with:
  - `GET /v1/index?refresh=1`
  - forced refresh bypasses the stability wait and returns an error immediately if the library is invalid

## Save endpoint behavior by rollout mode
- Download mode clients call `GET /v1/saves/{save_id}` only for saves selected by planner policy and checksum lineage.
- Bidirectional mode uses `GET /v1/save-bindings` plus `PUT /v1/saves/{save_id}` for both first-create and update actions.
- Unknown IDs always return `404`; clients must not attempt path-like probing or filename-based fallback lookups.
- Save writes require the server data root (`GAMEHUB_DATA_DIR`, default `/data`) to be mounted read-write.
