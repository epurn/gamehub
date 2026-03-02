# Web Codex Guide (WEB.md) – PR-centric workflow

# GameHub — Web Codex Guide

This file provides quick orientation for using Codex to contribute via the web-based PR interface.

---

## Quick orientation

The repository contains:

- A FastAPI server
- A Typer-based CLI
- Shared models under the `src/` tree

The server hosts the canonical ROM library, firmware and artwork while exposing an index and file endpoints.

The CLI synchronises your local library into Steam.

Planning artifacts live in the `PLANS/` directory.

Story IDs referenced there should be used when asking for specific work.

---

## Key commands exposed by the CLI

### `init`

Bootstraps a fresh client.

- Loads `config.toml`
- Fetches `/v1/index`
- Ensures emulators and RetroArch cores are installed
- Deploys firmware into emulator runtime directories
- Seeds controller profiles
- Writes `bootstrap_version` to `state.json`

`init` does not download ROMs or modify Steam.

---

### `sync`

Performs the full synchronisation pipeline.

- Loads config and state
- Verifies bootstrap marker
- Fetches and validates the index (with retries)
- Ensures required emulators and cores
- Builds a plan (firmware actions first)
- Streams downloads for missing ROMs and assets (`*.part → rename after verifying checksums`)
- Deploys firmware to emulator BIOS directories
- Converges controller profiles
- Updates Steam shortcuts, collections and artwork
- Closes and relaunches Steam as needed
- Writes updated `state.json`

Sync is idempotent across repeated runs.

---

### Doctor subcommands

Additional maintenance commands:

- `doctor controllers [--apply]`
- `doctor roms`
- `doctor firmware`
- `doctor all`

The client performs strict schema validation against the server’s index and fails fast on mismatches.

Do not “fudge” values to make tests pass; fix the underlying contract instead.

---

## PR workflow

- Use story IDs from `PLANS/*.md` or conversational guidance.
- Tasks should be small and focused.

At the start of a PR:

- Briefly orient (1-3 short bullets).
- List modules/files to modify.
- Outline approach (1–2 sentences).

Then continue autonomously through implementation, validation, commit, and PR creation without waiting for additional human confirmation.
Implement immediately — there is no separate approval step.

Keep changes within the declared scope.

---

### Always run Ruff

```
ruff format .
ruff check . --fix
```

---

### Always provide test command

```
.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider
```

---

## Guardrails

- Keep PRs self-contained.
- Avoid dependency bumps.
- Avoid reformatting unrelated files.
- Preserve domain separation.
- When touching sync or Steam integration code, respect Steam safety rules from AGENTS.md.

---

## Output expectations

A Web-mode Codex PR should include:

- Clear title
- Short summary
- Concise list of changed files
- Confirmation that diff is Ruff-clean
- Test command for verification

This structure allows reviewers to quickly understand scope and trust that GameHub guardrails were respected.