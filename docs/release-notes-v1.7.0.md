# Draft Release Notes for v1.7.0

This file tracks the current unreleased `v1.7.0` target on `main`.

Keep compatible additional feature work batched into `v1.7.0` until you intentionally freeze or split the release. Before tagging, refresh this draft so it matches the final shipped scope.

## Highlights
- Managed `Azahar` sessions now converge the owned Qt quit shortcut to `Esc`, keep the legacy `Exit Citra` alias aligned for older configs, and clear the fullscreen-only `Esc` binding so managed quits match the rest of the emulator stack.
- Managed `Azahar` controller profiles and assisted `qt-config.ini` convergence now seed deterministic stick deadzones, which reduces common ghost-input reports without requiring per-title manual tuning.
- `Azahar` `Start+Select` exit hooks remain available on Windows, macOS, and Linux, with the macOS path now preferring native `GameController` combo polling before falling back to Xbox HID event tracking.
- The rejected `Azahar` controller-to-mouse bridge branch and its optional dependency path were removed before release, so the shipped `v1.7.0` runtime keeps the simpler `Esc` plus `Start+Select` control model only.
- `gamehub config init` now rejects an empty `--server-url` override instead of accepting a blank value in scripted or non-interactive flows.

## Planned Server Artifacts
- Expected Docker image: `ghcr.io/epurn/gamehub-server:v1.7.0`
- Expected deploy bundle zip: `gamehub-server-deploy-v1.7.0.zip`
- Planned deployment notes:
  - Pull: `docker pull ghcr.io/epurn/gamehub-server:v1.7.0`
  - Run with compose: set `GAMEHUB_SERVER_IMAGE=ghcr.io/epurn/gamehub-server`, `GAMEHUB_IMAGE_TAG=v1.7.0`, and choose `GAMEHUB_SERVER_BIND_ADDRESS` intentionally in `docker/.env`, then run `docker compose -f docker/compose.yaml --env-file docker/.env up -d`
  - Verify: run `python3 scripts/verify_server_deploy.py --base-url "http://<SERVER_IP>:8000" --wait-seconds 30`
  - Configured-client smoke: run `gamehub config verify --config <client-config>`, then `gamehub doctor server --config <client-config> --server-url "http://<SERVER_IP>:8000"` in text or `--json` mode

## Planned Client Artifacts
- Expected client wheel (macOS/Linux):
  - `gamehub-1.7.0-py3-none-any.whl`
- Expected Windows EXE:
  - `gamehub-windows-amd64.exe`

## Compatibility / Migration Notes
- There are no new server API contract changes in this release; existing server smoke should remain compatible with the `v1.6.0` deployment/readiness flow.
- Preferred client bootstrap remains `gamehub config init`, then `gamehub config verify`, then `gamehub init`. For automation, `gamehub config init --server-url ""` is now rejected explicitly instead of accepting an empty override.
- Run one non-dry `gamehub sync --require-steam-closed` after upgrading so managed shortcuts and controller-profile seeds are rewritten from the `v1.7.0` release build.
- After that sync, launch one managed `Azahar` title so existing managed `qt-config.ini` files can converge to the shipped `Esc` quit shortcut and deadzone defaults.
- `Azahar` exit hooks remain opt-out via `GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK`, `GAMEHUB_AZAHAR_MACOS_EXIT_HOOK`, and `GAMEHUB_AZAHAR_LINUX_EXIT_HOOK`.
- Managed shortcut commands remain `shortcut-launch`; there is no shortcut-command migration in this release.
- There is no shipped `Azahar` mouse-bridge dependency or controller-to-mouse runtime in this release.

## Known Limitations
- For the current planned scope, deployment remains trusted-LAN only; there is still no built-in auth or TLS layer in this release.
- Server image architecture remains `amd64` only.
- Automatic save upload is launch-session scoped for GAMEHUB-managed shortcuts only; there is no background watcher service in this release.
- Built-in Steam Deck controller support is verified, but external Xbox controller support on Deck remains planned for a later update.

## Checksums
- See `checksums.txt` in release assets.
