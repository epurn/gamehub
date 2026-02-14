# Server API

Base URL: `http://<host>:8000`

## Endpoints
- `GET /health`
  - Returns `{ "status": "ok" }`
- `GET /v1/index`
  - Returns strict `LibraryIndex` JSON (`index_version=1`)
- `GET /v1/files/{file_id}`
  - Streams ROM file content
  - `404` for unknown `file_id`
- `GET /v1/assets/{asset_id}`
  - Streams asset file content
  - `404` for unknown `asset_id`
- `GET /v1/firmware/{system}/{filename}`
  - Streams raw firmware file
  - `404` when file missing
  - `400` for invalid traversal-like paths

## Data root
- Configured by env var `GAMEHUB_DATA_DIR` (default `/data`)
- Expected layout:
  - `roms/<system>/<title-dir>/...`
  - `firmware/<system>/<filename>`
