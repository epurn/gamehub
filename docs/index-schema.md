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
- `firmware`: list of `FirmwareSpec`

## `TitleEntry`
- `title_id`: deterministic from `system + title_rel_dir`
- `system`
- `title_name`
- `title_rel_dir`
- `emulator`
- `launch_template`
- `rom`: one `RomSpec` (exactly one ROM per title directory)
- `assets`: optional `AssetSpec` entries for `grid`, `hero`, `logo`, `icon`

## Validation guarantees
- Unknown fields are rejected (`extra=forbid`)
- SHA-256 fields must be lowercase 64-char hex
- ROM extensions are normalized and deduplicated

## Deterministic IDs
- `title_id`: `make_title_id(system, title_rel_dir)`
- `file_id`: `make_file_id(server_relative_path, sha256)`
- `asset_id`: `make_asset_id(server_relative_path, sha256)`
