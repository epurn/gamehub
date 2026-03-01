# AGENTS.md – shared guardrails and core objectives

# GAMEHUB — AGENTS.md

GAMEHUB is a Docker-first home-server and CLI that synchronises emulator libraries into Steam as non-Steam games with deterministic behaviour and safety-first file handling. This file defines the shared guardrails and high-level architecture for both web and IDE workflows.

---

## What you need to know

### Server

Hosts the canonical ROM, firmware and artwork library and exposes a deterministic index via `/v1/index`.

The index returns stable IDs (both `title_id` and `file_id`) so that clients never rely on fuzzy matching.

The server also serves files:

- `/v1/files/{file_id}`
- `/v1/assets/{asset_id}`
- `/v1/firmware/{system}/{filename}`

---

### Client

The `gamehub` CLI provides a safe and repeatable way to bootstrap and sync your library.

#### `init`

Bootstrap a fresh installation.

- Loads the index  
- Creates local firmware directories  
- Installs required emulators and RetroArch cores  
- Seeds controller profiles  
- Writes a bootstrap marker into `state.json`  

It does not download ROMs or touch Steam.

#### `sync`

- Builds a diff plan against the server index  
- Streams downloads of firmware/ROMs/artwork  
- Deploys firmware  
- Converges controller profiles  
- Safely updates Steam  

Flags allow:

- dry-run  
- verification  
- skipping Steam  
- requiring Steam to close  
- reseeding controller/Steam profiles  

#### `doctor`

Diagnose and optionally repair managed content.

Subcommands include:

- `doctor controllers`
- `doctor roms`
- `doctor firmware`
- `doctor all`

---

### Supported systems (v1)

GB, GBA, GBC, GEN_MD, N64, NDS, NES, PSX, SNES, GC, Wii and PS2.

There is no fuzzy matching and there are no ROM/BIOS downloads.

---

### Safety & determinism

- All downloads stream to temporary `.part` files then rename  
- Every write is atomic and backed up  
- Updates can be dry-run  
- Steam files are never modified unless Steam is closed  

---

## Repo layout

Runtime code lives under `src/` and is organised by domain:

```
src/gamehub_server/      # FastAPI server (main.py, indexer.py, firmware endpoints)
src/gamehub_cli/         # Typer CLI subdivided into common, sync, steam, controllers, firmware, emulators
src/gamehub_common/      # Shared models and ID helpers
tests/                   # Unit and integration tests for Windows and Linux
docs/                    # Schemas, templates and integration notes
PLANS/                   # AI-first planning (plan files + story contracts)
kanban/                  # Legacy planning (read-only)
```

Never introduce new runtime code outside `src/`; the legacy `kanban/` folder is maintained for history and should not be used for new work.

---

## Planning & execution model

All new features are planned in `PLANS/` using a:

**Plan → Milestones → Story Contracts → PR**

flow.

A Story Contract describes a self-contained change in one domain (server, client, common or docs).

CROSS-BOUNDARY stories must freeze the contract in `gamehub_common` first and implement each side in separate PRs.

Story Contracts should be small, explicit and independently mergeable.

Before you start coding:

1. Briefly outline what you plan to change and where.
2. Then proceed with the implementation.

There is no approval gate between orientation and edits.

When implementing:

- Touch only the files described in the story.
- Avoid unrelated refactors or dependency updates.

---

## Boundaries & guardrails

### Domain separation

`gamehub_server` must never import `gamehub_cli` and vice versa.

Shared models live in `gamehub_common`.

Extract cross-runtime helpers instead of duplicating them.

---

### Index contract

The server’s `/v1/index` must:

- Return deterministic IDs
- Include metadata for systems:
  - firmware requirements
  - ROM extensions
  - default emulator
- Include metadata for titles:
  - relative path
  - SHA-256
  - emulator launch template
  - collection name

The client must validate this schema strictly using Pydantic and fail fast.

---

### Steam safety

Steam shortcuts reside in:

```
userdata/<steamid>/config/shortcuts.vdf
```

Collections reside in:

- `localconfig.vdf`
- cloud JSON

Always:

1. Detect and close Steam before writing  
2. Back up these files  
3. Write updates atomically  
4. Reopen Steam afterwards  

Use a proven VDF library for parsing — never hand-roll binary VDF parsing.

---

### Sync pipeline

```
load config and state
→ (fail fast if bootstrap marker missing)
→ fetch index
→ ensure emulators/cores/firmware
→ plan downloads
→ fetch SGDB artwork
→ download firmware/ROMs/assets
→ deploy firmware
→ converge controller profiles
→ close Steam and update shortcuts/collections/artwork
→ reopen Steam
→ save state.json
```

---

### Emulators

- RetroArch for cartridge-era systems  
- PCSX2 for PS2  
- Dolphin standalone for GC/Wii  

Launch strings are always:

```
emulator-exe + rom path
```

The `init` command installs emulators and cores if missing and seeds controller profiles:

- `kbm`
- `xbox_1p`
- `xbox_2p`

---

### Controller profiles

Managed profiles are stored under:

```
<paths.gamehub_dir>/controller_profiles
```

Use `--reseed-profiles` to overwrite defaults.

Profiles apply to:

- PCSX2
- Dolphin
- Azahar

They support Xbox controllers and keyboard/mouse combinations.

---

## Tooling & quality

### Formatting & linting

Run before completing a PR:

```
ruff format .
ruff check . --fix
```

Ruff is the single source of truth for code style.

---

### CI

All PRs must pass:

- ruff
- pytest
- any configured CI checks

Windows and Linux are both supported; tests must pass on both platforms.

---

### Environment

Develop in the local virtual environment (`venv/`).

On Windows use:

```
.\u200bvenv\Scripts\python.exe -m pytest . -p no:cacheprovider
```

---

### Documentation

Update `docs/` whenever behaviour or schema changes.

Keep docs concise and copy-paste runnable.

---

### Release

Server images are published to GHCR:

```
ghcr.io/<org>/gamehub-server:vX.Y.Z
```

Client artifacts include:

- Linux wheel
- Windows executable

A deploy bundle zip contains compose/env templates and verify scripts.

---

## Definition of done

A story is complete when:

- Its acceptance criteria are met.
- Tests are added or updated accordingly.
- Documentation is updated if the change affects behaviour, schemas or Steam integration.
- The codebase is ruff-clean and CI passes.
- The PR is focused, reviewable and only touches the intended scope.

---

This file provides shared guardrails for all environments.

See:

- `docs/agents/WEB.md`
- `docs/agents/IDE.md`