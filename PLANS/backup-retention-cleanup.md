# PLAN: backup-retention-cleanup

## Context
- GAMEHUB creates timestamped `*.bak` files across client and server mutation paths.
- Backup creation is already in place, but there is no retention limit and no operator cleanup utility for legacy buildup.
- Repo boundaries must stay strict: `gamehub_server` and `gamehub_cli` keep separate runtime helpers, and `gamehub_common` remains contracts-only.

## Goals
- Add a global backup keep limit with default `3`.
- Apply the keep limit to both CLI and server backup creation paths without weakening existing atomic/backup/logging guarantees.
- Add a dry-run-first cleanup script that prunes legacy GAMEHUB backups to policy.
- Cover the behavior with targeted tests and operator docs.

## Non-Goals
- No backup naming format change.
- No new cross-package runtime helper shared between CLI and server.
- No broad refactor of unrelated file-mutation code.

## Milestones
1. M1: Add config/env backup retention surfaces and low-level CLI/server pruning helpers.
2. M2: Wire retention into every existing GAMEHUB backup writer and add the cleanup script.
3. M3: Update docs/templates and land targeted regression tests.
4. M4: Run full repo quality gates and fix regressions.

## Story Contracts

### STORY BRC-1
- Type: CLI
- Goal: make CLI-created backups self-pruning and configurable.
- Acceptance Criteria:
  - [x] `[backups].keep_limit` defaults to `3` and `GAMEHUB_BACKUP_KEEP_LIMIT` overrides it.
  - [x] CLI backup families prune to the newest configured count immediately after creating a new backup.
  - [x] Steam config backups and unmanaged controller archive backups follow the same retention rule.
  - [x] Backup pruning is explicitly logged by the mutation owner.

### STORY BRC-2
- Type: Server
- Goal: make server save-upload backups self-pruning.
- Acceptance Criteria:
  - [x] `GAMEHUB_BACKUP_KEEP_LIMIT` defaults to `3` on the server.
  - [x] Repeated save uploads keep only the newest configured save backups per canonical save file.
  - [x] Server backup pruning stays local to `gamehub_server`.

### STORY BRC-3
- Type: Operator Utility
- Goal: give operators a safe way to prune legacy backup buildup.
- Acceptance Criteria:
  - [x] `scripts/cleanup_backups.py` supports `--config`, repeated `--root`, `--server-data-root`, `--keep`, and `--apply`.
  - [x] Dry-run is the default and prints exact deletions without mutating files.
  - [x] Apply mode deletes only GAMEHUB timestamped backups and preserves non-GAMEHUB `.bak` files.

### STORY BRC-4
- Type: Docs + Tests
- Goal: document and verify the retention contract.
- Acceptance Criteria:
  - [x] Config docs/templates describe `[backups].keep_limit`.
  - [x] Server deployment docs describe `GAMEHUB_BACKUP_KEEP_LIMIT`.
  - [x] CLI docs describe automatic retention and the cleanup script.
  - [x] Regression tests cover config parsing, helper pruning, Steam/controller outliers, server save retention, and script dry-run/apply flows.
