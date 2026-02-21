# Architecture

## Runtime layout
- Source root: `src/`
- Runtime package: `src/gamehub_cli`
- Runtime package: `src/gamehub_server`
- Runtime package: `src/gamehub_common`

## CLI feature packages
- `src/gamehub_cli/sync`: sync orchestration and stage modules.
- `src/gamehub_cli/steam`: Steam lifecycle, shortcuts, collections, artwork, and shared Steam types.
- `src/gamehub_cli/emulators`: emulator resolution + installation services.
- `src/gamehub_cli/firmware`: firmware deploy, targets, and RetroArch/PCSX2 helpers.
- `src/gamehub_cli/controllers`: controller detection/profile/apply/launch and Azahar hook runtime.
- `src/gamehub_cli/common`: shared file/path/platform helpers used across features.

## Dependency direction (target)
- `sync` may depend on `steam`, `controllers`, `firmware`, `emulators`, and `common`.
- `controllers` may depend on `firmware`, `emulators`, and `common`.
- `firmware` may depend on `emulators` and `common`.
- `steam` may depend on `common`.
- `common` may depend on `emulators` for emulator path-resolution helpers.
- `emulators` must not depend on other CLI feature packages.

## Guardrails
- `tests/test_architecture.py` enforces:
- an acyclic dependency graph across `sync`, `steam`, `emulators`, `firmware`, `controllers`, and `common`
- explicit allowed dependency directions for each core package

## Entry points
- Top-level CLI entrypoint remains `gamehub = gamehub_cli.main:main`.
- Top-level server entrypoint remains `gamehub-server = gamehub_server.main:run`.
- Internal module paths under legacy `apps/...` were removed as part of the `src/` migration.
