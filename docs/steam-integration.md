# Steam Integration (v1 Implemented)

## Implemented now
- Steam userdata discovery (explicit path or common defaults)
  - macOS auto-discovery includes `~/Library/Application Support/Steam/userdata`
- SteamID discovery:
  - auto-select most recently active numeric profile by default
  - optional explicit profile via `steam.steam_id`
- Steam running detection + close/wait lifecycle
  - macOS checks native Steam process names first (`Steam`, `steam_osx`, `steamwebhelper`)
  - macOS close uses a best-effort app quit before falling back to exact-name `pkill`
  - macOS reopen uses `open -a <Steam.app>` against either configured or auto-discovered app bundles
- On macOS, `steam.steam_exe` may point to either `Steam.app` or its inner `Contents/MacOS/...` executable; GAMEHUB normalizes it to the app bundle for lifecycle actions
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

## Collections model
- Collections are named exactly by system (`NES`, `PS2`, `Wii`, etc.).
- Managed collections include `gamehub_managed: true` marker in the JSON payload.
- Only managed collections are updated/removed by sync; unmanaged collections are preserved.
- Collection `added` appids are normalized to unsigned 32-bit decimal values for Steam compatibility.
- Local collections are read/written at the canonical `UserLocalConfigStore/WebStorage/user-collections` path.
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

## Managed launch wrappers
- When `[controllers].launch_autoconfig = true` or `[save_sync].enabled = true`, supported managed shortcuts (`RetroArch`, `PCSX2`, `Dolphin`, `Azahar`) are emitted through the hidden `shortcut-launch` wrapper so launch-time controller and save-session policy stays deterministic.
- On macOS, when a managed shortcut target resolves to an app bundle executable (`*.app/Contents/MacOS/...`), GAMEHUB persists bundle-aware launch metadata and `shortcut-launch` runs `open -W -a <App> --args ...` so Apple Silicon apps launch natively and post-exit save sync waits for the app session to close.
- Linux Flatpak Azahar is a special case: sync first emits `python -m gamehub_cli.controllers.azahar_exit_hook --app-id org.azahar_emu.Azahar --rom ...` by default, and `shortcut-launch` treats that wrapper as the target command payload.
- Linux Dolphin and Windows Azahar exit hooks live in `shortcut-launch` runtime behavior; the Linux Azahar hook lives in the sync-emitted Steam launch command instead.
- After upgrading from older builds that still emitted `controller-launch`, run one non-dry `gamehub sync` so persisted Steam shortcut commands are rewritten.

## Steam Input Templates (Steam Deck)
- On Linux Steam Deck, GAMEHUB syncs seeded Steam Input templates for managed `Wii` and `N3DS` shortcuts (`GC` is intentionally excluded).
- Files are written by normalized title path, not appid path:
  - `Steam Controller Configs/<steamid>/config/<normalized_title>/gamehub_wii.vdf` (`Wii`)
  - `Steam Controller Configs/<steamid>/config/<normalized_title>/gamehub_3ds.vdf` (`N3DS`)
- GAMEHUB also writes Steam local override payloads for managed Deck-template titles:
  - for example: `~/.local/share/Steam/controller_config/app_<unsigned_appid>.vdf`
  - writes only when missing by default; with `--reseed-profiles`, force rewrites even when files already exist
- Selection metadata is updated in:
  - `Steam Controller Configs/<steamid>/config/configset_controller_neptune.vdf`
  - active `Steam Controller Configs/<steamid>/config/configset_*.vdf` files (including `configset_controller_*.vdf` variants)
  - when present, mirrored app-remote roots under `userdata/<steamid>/241100/remote/*/config/` receive the same `configset_*.vdf` updates
  - `controller_config` entries set both normalized title keys and companion alias keys (`appid`/signed/title variants) to `template=CLOUD_<normalized_title>/gamehub_wii|gamehub_3ds`
- Managed template sync force-overwrites per-title selection aliases (appid/title variants) for `Wii` and `N3DS`.
- Managed per-title template payload files (`gamehub_wii.vdf`/`gamehub_3ds.vdf`) are preserved by default and only overwritten when sync runs with `--reseed-profiles` (force rewrite even when bytes already match).
- Managed template sync does not delete legacy per-title template variant files; only managed `gamehub_wii.vdf`/`gamehub_3ds.vdf` payloads and selection configsets are updated.
- Managed per-title template files are also mirrored to present app-remote roots under `userdata/<steamid>/241100/remote/*/config/<normalized_title>/`.
- Deck app override repair sets `UseSteamControllerConfig=1` and `DisableCloud=1` for managed `Wii`/`N3DS` app entries.
- Root resolution precedence:
  - `~/.local/share/Steam/steamapps/common/Steam Controller Configs/<steamid>/config` and `.../<steamid>/`
  - `~/.steam/steam/steamapps/common/Steam Controller Configs/<steamid>/config` and `.../<steamid>/`
  - `~/.steam/root/steamapps/common/Steam Controller Configs/<steamid>/config` and `.../<steamid>/`
- GAMEHUB deduplicates equivalent roots by resolved identity.
- Seed source files are committed in:
  - `src/gamehub_cli/steam/template_seeds/steamdeck/wii_gc/wii_0.vdf`
  - `src/gamehub_cli/steam/template_seeds/steamdeck/n3ds/3ds_0.vdf`
- GAMEHUB writes raw seed bytes as-is (no runtime metadata rewriting).
- Seed refresh helper:
  - `./venv/bin/python scripts/capture_deck_template_seed.py --system wii_gc --title "<TITLE>"`
  - `./venv/bin/python scripts/capture_deck_template_seed.py --system n3ds --title "<TITLE>"`
- Deck template sync behavior is deterministic fail-fast when required roots/seeds are missing.

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
