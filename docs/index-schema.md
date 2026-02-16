# Index Schema (v1)

`/v1/index` returns a strict `LibraryIndex` payload (`index_version=1`) from `gamehub_common.models`.

## Top-level fields
- `index_version`: fixed literal `1`
- `generated_at`: UTC timestamp
- `systems`: list of `SystemSpec`
- `titles`: list of `TitleEntry`

## `SystemSpec`
- `name`: canonical system name (for Steam collections)
- `rom_extensions`: normalized lowercase extensions with `.` prefix
- `default_emulator`
- `launch_template`
- `firmware`: list of `FirmwareSpec` scanned from `firmware/<system>/` when firmware scanning is enabled for that system
  - `required=true` for known required firmware filenames (per system catalog)
  - `required=false` for additional optional firmware files present on disk

## Initial canonical systems (v1)
- `GB`, `GBA`, `GBC`, `GEN_MD`, `N64`, `NDS`, `N3DS`, `NES`, `PSX`, `SNES`, `GC`, `Wii`, `PS2`

## `TitleEntry`
- `title_id`: deterministic from `system + title_rel_dir`
- `system`
- `title_name`
- `title_rel_dir` (system-relative ROM path, for example `NES/SuperMarioBros.nes`)
- `emulator`
- `launch_template`
- `rom`: one `RomSpec` for each file in `roms/<system>/` matching allowed extensions
- `assets`: currently empty in flat-ROM layout; reserved for artwork ingestion workflow

## Validation guarantees
- Unknown fields are rejected (`extra=forbid`)
- SHA-256 fields must be lowercase 64-char hex
- ROM extensions are normalized and deduplicated
- Nested title directories under `roms/<system>/` are rejected (layout is flat files only)
- Duplicate title stems within a system (for example `Title.iso` + `Title.chd`) are rejected
- If a system has indexed titles and required firmware is missing on the server, index generation fails (for example: `PS2` `scph10000.bin`)

## Deterministic IDs
- `title_id`: `make_title_id(system, title_rel_dir)`
- `file_id`: `make_file_id(server_relative_path, sha256)`
- `asset_id`: `make_asset_id(server_relative_path, sha256)`
