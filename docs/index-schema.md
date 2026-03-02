# Index Schema (v1)

`/v1/index` returns a strict `LibraryIndex` payload (`index_version=1`) from `gamehub_common.models`.

## Top-level fields
- `index_version`: fixed literal `1`
- `generated_at`: UTC timestamp
- `systems`: list of `SystemSpec`
- `titles`: list of `TitleEntry`
- `saves`: list of `SaveSpec` (may be empty during phased rollout)

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


## `SaveSpec`
- `save_id`: deterministic from canonical server-relative save path plus save checksum
- `title_id`: deterministic title binding (must reference a known title)
- `system`: canonical system name (for strict matching / filtering)
- `kind`: one of `battery`, `memory_card`, `per_game`
- `rel_path`: canonical server-relative save path
- `sha256`: lowercase 64-char hex digest for save content
- `size_bytes`: save file size in bytes
- `updated_at`: server UTC timestamp for save artifact freshness
- `portable`: whether the save format is expected to be portable across clients/emulator variants

Save sync matching rules:
- Clients must match saves by `save_id`/`title_id` only (never by fuzzy title names or filename heuristics).
- `system` is part of strict filtering behavior (`[save_sync].systems`) and must use canonical uppercase names.
- `portable=false` indicates the server indexed a known non-portable format; clients should still parse it but may choose conservative conflict behavior.

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
- `save_id`: `make_save_id(server_relative_path, sha256)`

## Index versioning expectation for save-sync contract freeze
- Save artifacts are additive contract surface in `index_version=1` for the current rollout phase.
- Existing clients that ignore unknown fields continue to parse legacy sections, while strict save-aware clients must validate `SaveSpec` when `saves` are present.
- Any future breaking save contract change must bump `index_version` in a dedicated contract story before implementation.

## Rollout interpretation
- `saves` may be an empty list during staged rollout even when save sync config is enabled client-side.
- Empty `saves` is a valid deterministic state and should produce no save transfer actions.
