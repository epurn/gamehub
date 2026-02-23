# Steam Integration (v1 Implemented)

## Implemented now
- Steam userdata discovery (explicit path or common defaults)
- SteamID discovery:
  - auto-select most recently active numeric profile by default
  - optional explicit profile via `steam.steam_id`
- Steam running detection + close/wait lifecycle
- Backup before mutation:
  - `userdata/<steamid>/config/shortcuts.vdf`
  - `userdata/<steamid>/config/localconfig.vdf`
  - `userdata/<steamid>/config/cloudstorage/cloud-storage-namespace-1.json` (when present)
- Real shortcut upsert in binary `shortcuts.vdf` using `vdf` library
- Real `user-collections` merge in `localconfig.vdf` (canonical path: `UserLocalConfigStore/WebStorage/user-collections`)
- Real `user-collections.*` upsert in Steam cloud storage file (`config/cloudstorage/cloud-storage-namespace-1.json`) for clients that read categories from cloud namespace
- Artwork copy into `userdata/<steamid>/config/grid` using real appids derived from persisted shortcuts

## Shortcut ownership model
- Managed shortcuts are tagged with:
  - `GAMEHUB`
  - `GAMEHUB_TITLE:<title_id>`
  - `GAMEHUB_SYSTEM:<system>`
  - `<system>` (plain system tag for Steam tag/category compatibility)
- Non-GAMEHUB shortcuts are preserved unchanged.
- Repeated syncs are idempotent (no duplicate GAMEHUB shortcuts).
- Legacy matching entries (same title + launch options but missing GAMEHUB tags) are adopted/migrated in place so stale targets get corrected on sync.

## Collections model
- Collections are named exactly by system (`NES`, `PS2`, `Wii`, etc.).
- Managed collections include `gamehub_managed: true` marker in the JSON payload.
- Only managed collections are updated/removed by sync; unmanaged collections are preserved.
- Collection `added` appids are normalized to unsigned 32-bit decimal values for Steam compatibility.
- GAMEHUB writes both:
  - local `localconfig.vdf` collections payload
  - cloud `user-collections.gamehub-*` entries
- Stale GAMEHUB cloud collection entries are marked `is_deleted: true` instead of deleting unrelated keys.
- No-op local collection updates skip `localconfig.vdf` writes to reduce backup/file churn.

## Artwork filenames
- GAMEHUB writes Steam grid assets for both portrait and landscape grid variants:
  - `<appid>p.<ext>` (portrait)
  - `<appid>.<ext>` (landscape)
  - When SGDB provides dedicated landscape grid artwork, GAMEHUB uses that file for `<appid>.<ext>`; otherwise it falls back to the portrait grid file.
- Hero/logo/icon are written as:
  - `<appid>_hero.<ext>`
  - `<appid>_logo.<ext>`
  - `<appid>_icon.<ext>`
- GAMEHUB writes grid filenames using unsigned appid values only.
- During Steam update, GAMEHUB prunes duplicate signed-variant grid files when matching unsigned files exist.

## Steam Input Templates (Steam Deck)
- On Linux Steam Deck, GAMEHUB syncs seeded Steam Input templates for managed `Wii`, `GC`, and `N3DS` shortcuts.
- Files are written by normalized title path, not appid path:
  - `Steam Controller Configs/<steamid>/config/<normalized_title>/wii_0.vdf` (`Wii`, `GC`)
  - `Steam Controller Configs/<steamid>/config/<normalized_title>/3ds_0.vdf` (`N3DS`)
- Selection metadata is updated in:
  - `Steam Controller Configs/<steamid>/config/configset_controller_neptune.vdf`
  - active `Steam Controller Configs/<steamid>/config/configset_*.vdf` files (except other `configset_controller_*.vdf` variants)
  - `controller_config` entries are set to `template=wii_0` (`Wii`/`GC`) or `template=3ds_0` (`N3DS`) with `autosave=1`
- Root resolution precedence:
  - `~/.local/share/Steam/steamapps/common/Steam Controller Configs/<steamid>/config`
  - `~/.steam/steam/steamapps/common/Steam Controller Configs/<steamid>/config`
  - `~/.steam/root/steamapps/common/Steam Controller Configs/<steamid>/config`
- GAMEHUB deduplicates equivalent roots by resolved identity.
- Seed source files are committed in:
  - `src/gamehub_cli/steam/template_seeds/steamdeck/wii_gc/wii_0.vdf`
  - `src/gamehub_cli/steam/template_seeds/steamdeck/n3ds/3ds_0.vdf`
- Seed refresh helper:
  - `./venv/bin/python scripts/capture_deck_template_seed.py --system wii_gc --title "<TITLE>"`
  - `./venv/bin/python scripts/capture_deck_template_seed.py --system n3ds --title "<TITLE>"`
- Behavior toggles:
  - `GAMEHUB_DECK_TEMPLATE_SYNC=true|false` (default `true`)
  - `GAMEHUB_DECK_TEMPLATE_STRICT=true|false` (default `true`)

## Safety behavior
- If Steam is running, sync attempts close + wait.
- If Steam remains running:
  - with `--require-steam-closed`: sync fails
  - without it: Steam update stage is skipped for safety
- If Steam update stage runs:
  - backup first
  - atomic write of mutated files
  - copy artwork
  - reopen Steam if it was running at start
