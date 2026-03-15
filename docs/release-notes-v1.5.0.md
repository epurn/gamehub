# Release v1.5.0

## Highlights
- Apple Silicon macOS is now a supported GAMEHUB client platform.
- The macOS client ships with the same managed `init`, `sync`, native Steam lifecycle, controller autoconfig, and indexed save-sync flows as the primary Windows and Bazzite targets.
- macOS emulator bootstrap stays native-first: official Apple Silicon or universal assets are preferred, with optional `PCSX2` Rosetta fallback kept behind `[macos].disable_pcsx2_rosetta = false`.
- Release prep docs now include a dedicated `v1.5.0` manual checklist and refreshed macOS operator guidance.

## Server
- Docker image: `ghcr.io/epurn/gamehub-server:v1.5.0`
- Deploy bundle zip: `gamehub-server-deploy-v1.5.0.zip`
- Deployment notes:
  - Pull: `docker pull ghcr.io/epurn/gamehub-server:v1.5.0`
  - Run with compose: set `GAMEHUB_SERVER_IMAGE=ghcr.io/epurn/gamehub-server` and `GAMEHUB_IMAGE_TAG=v1.5.0` in `docker/.env`, then run `docker compose -f docker/compose.yaml --env-file docker/.env up -d`

## Client
- Client wheel (macOS/Linux):
  - `gamehub-1.5.0-py3-none-any.whl`
- Windows EXE:
  - `gamehub-windows-amd64.exe`

## Compatibility / Migration Notes
- Apple Silicon is the supported macOS target for this release. Intel Mac hosts are still out of scope.
- Start new macOS installs from [docs/templates/config.macos.template.toml](templates/config.macos.template.toml).
- If you validated older macOS branch builds before this release, run one `gamehub init --reseed-profiles` and one non-dry `gamehub sync --require-steam-closed` after upgrading so managed profiles, runtime config, and Steam shortcuts are rewritten from the release build.
- Managed shortcut wrapper commands remain `shortcut-launch`; after upgrading, run one non-dry `gamehub sync` before launching managed Steam shortcuts so existing entries are rewritten from the installed release.
- There are no new server API contract changes in this release.

## macOS Notes
- Supported Steam discovery covers `~/Applications/Steam.app`, `/Applications/Steam.app`, and `~/Library/Application Support/Steam/userdata`.
- Managed macOS `N64` RetroArch launches converge the validated Apple Silicon fallback (`glcore` plus the managed `Mupen64Plus-Next` core-option baseline) before launch, and they fail closed with an actionable warning if that baseline cannot be converged safely.
- Managed macOS `Azahar` launches prefer `~/Applications/Azahar.app` when present and use the bundle-safe launch path that waits for emulator exit before post-exit save work.

## Known Limitations
- Automatic save upload is launch-session scoped for GAMEHUB-managed shortcuts only; there is no background watcher service in this release.
- Steam Deck external Xbox controller support remains planned for a later update.
- `PCSX2` is the only emulator that may use Rosetta on macOS, and only when the operator allows it.

## Checksums
- See `checksums.txt` in release assets.
