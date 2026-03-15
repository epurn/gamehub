# Release v1.3.0

## Highlights
- SteamOS (Steam Deck) support is verified for built-in controller flows.
- GAMEHUB now auto-syncs Steam Input templates for managed `Wii` and `N3DS` titles on Steam Deck.
- Controller launch autoconfig is hardened across Dolphin/Azahar/Deck detection paths.
- Config/path migration cleanup is now strict, with explicit ROM root override support.
- Save sync now supports stable save IDs, atomic server uploads, and managed launch-session bidirectional upload for wrapped shortcuts.

## Server
- Docker image: `ghcr.io/<org>/gamehub-server:v1.3.0`
- Deploy bundle zip: `gamehub-server-deploy-v1.3.0.zip`
- Deployment notes:
  - Pull: `docker pull ghcr.io/<org>/gamehub-server:v1.3.0`
  - Run with compose: set `GAMEHUB_SERVER_IMAGE=ghcr.io/<org>/gamehub-server` and `GAMEHUB_IMAGE_TAG=v1.3.0` in `docker/.env`, then run `docker compose -f docker/compose.yaml --env-file docker/.env up -d`

## Client
- Linux wheel:
  - `gamehub-1.3.0-py3-none-any.whl`
- Windows EXE:
  - `gamehub-windows-amd64.exe`

## Compatibility / Migration Notes
- New optional ROM destination config/env:
  - `paths.roms_dir`
  - `GAMEHUB_ROMS_DIR`
- Removed legacy config keys/env aliases:
  - `paths.library_dir`
  - `paths.firmware_dir`
  - `paths.state_path`
  - `paths.output_dir`
  - `GAMEHUB_OUTPUT_DIR`
- Legacy unmanaged shortcut adoption is no longer performed.
- Legacy localconfig collection-path migration is no longer performed.
- If upgrading from older branch builds, run one sync with `--reseed-profiles`.
- Managed shortcut wrapper commands are now emitted as `shortcut-launch` instead of `controller-launch`.
- After upgrading, run one non-dry `gamehub sync` before launching managed shortcuts so existing Steam entries are rewritten to `shortcut-launch`.

## Steam / Controller Behavior Changes
- Deck-managed shortcuts default to native-first `AllowDesktopConfig` behavior.
  - Override with `GAMEHUB_STEAM_ALLOW_DESKTOP_CONFIG=true|false`.
- Managed app overrides are repaired for Steam Input consistency.

## Packaging
- Steam Deck template seed files are now packaged with client artifacts.
- Standard assets remain:
  - Linux wheel
  - Windows EXE
  - Server deploy zip
  - `checksums.txt`
  - GHCR server image

## Known Limitations
- Steam Deck external Xbox controller support remains planned for a later release.
- Automatic save upload is launch-session scoped for GAMEHUB-managed shortcuts only; there is no background watcher service in this release.

## Checksums
- See `checksums.txt` in release assets.
