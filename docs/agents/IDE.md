# IDE Codex Guide (IDE.md) – iterative local development

# GameHub — IDE Codex Guide

This guide explains how to use Codex for interactive development in a local IDE.

It strikes a balance between quick execution and conversational flexibility.

---

## Quick orientation

The GameHub repository has three primary code packages under `src/`:

### `gamehub_server`

A FastAPI service that:

- Hosts canonical ROM library, firmware and artwork
- Exposes:
  - `/v1/index`
  - `/v1/files/{file_id}`
  - `/v1/assets/{asset_id}`
  - `/v1/firmware/{system}/{filename}`

Responsible for deterministic identifiers (`title_id`, `file_id`).

---

### `gamehub_cli`

Typer-based CLI.

Main entry points:

- `init`
- `sync`

Also includes doctor subcommands for controllers, ROMs and firmware.

---

### `gamehub_common`

Shared models and helpers used by both server and client.

Cross-boundary changes should be defined here.

---

## Key workflows exposed by the CLI

### `init`

- Loads configuration
- Fetches server index
- Ensures required emulators and RetroArch cores
- Deploys firmware into emulator runtime directories
- Seeds managed controller profiles
- Writes `bootstrap_version` to `state.json`

Use `--dry-run` to inspect without mutating.

---

### `sync`

Executes the full sync pipeline:

- Loads config and state
- Validates bootstrap marker
- Fetches and validates server index (with retries)
- Ensures emulators and cores
- Builds plan (firmware first)
- Streams downloads and verifies checksums
- Deploys firmware
- Applies controller convergence
- Updates Steam safely (close → backup → atomic write → relaunch)
- Writes updated state

Flags include:

- `--dry-run`
- `--skip-steam`
- `--skip-steam-relaunch`
- `--verify`
- `--verbose`

Sync is idempotent.

---

### Doctor commands

Maintenance commands to check or repair:

- controllers
- ROMs
- firmware

---

## Iterative development guidelines

Use Codex conversationally:

- Ask architecture questions.
- Clarify requirements before implementation.

When ready:

1. Provide brief orientation (modules + approach).
2. Implement immediately.

There is no approval gate.

---

### Development guardrails

- Keep changes focused.
- Respect domain boundaries.
- Server code must not import CLI code.
- Use `gamehub_common` for shared logic.

---

## Local validation

Run frequently:

```
ruff format .
ruff check . --fix
.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider
```

Unit tests cover:

- index generation
- diff planning
- Steam file writer round-trip logic

Integration tests use a fake Steam userdata directory.

Add or update tests when behaviour changes.

---

## Configuration tips

Use configuration and environment variables documented in `docs/client-install.md`.

Examples:

- Set `steam.userdata_dir`
- Choose Linux emulator install backend:
  - `flatpak`
  - `dnf`
  - `apt`

---

## Helpful tips

- Run `gamehub init` before first `gamehub sync`.
- Use `--dry-run` to preview actions.
- Use `--skip-steam` to validate without mutating Steam.
- Use `--verbose` for debugging.
- Run `gamehub doctor controllers --apply` for controller issues.

---

## Completion

A development task is complete when:

- The requested change or feature is implemented.
- Necessary tests are added or updated.
- All tests pass.
- The codebase is Ruff-clean.
- CI would succeed.
- The changes are reviewable and focused.

This flexible approach allows fast iteration while respecting GameHub’s architecture and quality expectations.

These files are ready to be added to your repo and will help Codex understand the project quickly while keeping development lightweight and high-quality.