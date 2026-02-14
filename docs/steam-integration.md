# Steam Integration (v1 Status)

Current implementation is a safe skeleton in `apps/cli/gamehub_cli/steam.py`.

## Implemented now
- Steam userdata discovery (explicit path or common defaults)
- SteamID discovery from numeric userdata directory
- Steam running detection
- Best-effort close + wait-for-exit
- Backups for:
  - `userdata/<steamid>/config/shortcuts.vdf`
  - `userdata/<steamid>/config/localconfig.vdf`
- Reopen Steam attempt after modifications

## Placeholders (next iteration)
- Upsert non-Steam shortcuts in binary `shortcuts.vdf`
- Update `user-collections` JSON in `localconfig.vdf` with system collections
- Copy artwork to `userdata/<steamid>/config/grid`

## Safety requirements
- Always close Steam before writes
- Always backup before writes
- Prefer atomic writes for any config mutation
