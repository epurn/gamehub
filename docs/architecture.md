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
- `common` must not depend on other CLI feature packages.
- `emulators` must not depend on other CLI feature packages.
- `gamehub_common` must not depend on `gamehub_cli` or `gamehub_server`.
- `gamehub_server` must not depend on `gamehub_cli`.
- `gamehub_cli` must not depend on `gamehub_server`.

## Guardrails
- `tests/test_architecture.py` enforces an acyclic dependency graph across `sync`, `steam`, `emulators`, `firmware`, `controllers`, and `common`.
- `tests/test_architecture.py` enforces explicit allowed dependency directions for each core package.
- `tests/test_architecture.py` enforces disallowed inter-package imports across `gamehub_cli`, `gamehub_server`, and `gamehub_common`.
- `.github/workflows/audit-regression-gates.yml` runs the architecture guard test on PRs/pushes whenever `src/`, `tests/`, or architecture/release development docs change.
- `.github/workflows/targeted-regression-matrix.yml` runs the emulator/firmware, controller, Steam, and sync regression slices on both Linux and Windows.

## Public package surfaces
- `gamehub_cli.steam` only re-exports intentional public Steam APIs; internal patch points live in concrete modules (for example `gamehub_cli.steam.lifecycle`).
- `gamehub_cli.sync` package exports are limited to `run_sync` and `configure_dependencies`.
- Internal test patch targets should use concrete modules, not package-level compatibility aliases.

## Entry points
- Top-level CLI entrypoint remains `gamehub = gamehub_cli.main:main`.
- Top-level server entrypoint remains `gamehub-server = gamehub_server.main:run`.
- Internal module paths under legacy `apps/...` were removed as part of the `src/` migration.
