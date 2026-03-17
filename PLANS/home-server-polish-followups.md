# PLAN: home-server-polish-followups

## Context
- Background:
  - `v1.6.0` finishes trusted-LAN deploy hardening, adds `/v1/status`, and introduces a client-side `doctor server` flow with exact client/server version checks.
- Current behavior:
  - Operators can deploy, verify, and triage a real home server, but scheduled sync, snapshot automation, and config bootstrap are still manual.
  - The remaining polish ideas also include a read-only dashboard, optional notifications, and an unmanaged-launch save reconciler, but those are better treated as later phases than as `v1.6.0` scope creep.
- Trigger/problem statement:
  - The product is deployable, but there is still follow-up work to make it feel like a smoother long-lived home server system.

## Goals
- Add first-party scheduled sync support without introducing a resident daemon.
- Add a dry-run-first snapshot backup/restore helper for server operators.
- Add a guided `gamehub config` wizard that writes safe starter configs with sensible defaults.
- Capture the next-wave dashboard, notification, and background save ideas in-repo so they stay visible but clearly deferred.

## Non-Goals
- No changes to `/v1/index`, deterministic IDs, or current save-binding contracts in this plan unless a later story explicitly freezes a new shared contract first.
- No built-in auth, TLS, or reverse-proxy orchestration in this follow-up plan.
- No fuzzy matching or heuristic save reconciliation.

## Constraints
- Keep Docker-first server deployment intact.
- Keep `gamehub_server` and `gamehub_cli` boundaries strict.
- Any config-wizard write path must follow the repo's backup + temp-file + atomic-replace rules.
- Interactive flows must still support non-interactive/scripted use through flags.

## Contract Surface
- Expected CLI additions:
  - `gamehub sync --json-summary`
  - `gamehub config init`
  - `gamehub config verify`
- Expected operator tooling additions:
  - `scripts/server_snapshot.py`
- Expected deferred surfaces:
  - read-only dashboard endpoints or pages
  - optional notification/webhook sink configuration
  - optional unmanaged-launch save reconciliation flow

## Milestones
1. M1: scheduled sync and machine-readable sync summaries
2. M2: snapshot backup/restore helper
3. M3: config wizard and verification
4. M4: deferred dashboard/notification/background-save stories kept decision-ready

## Story Contracts

### STORY GH-POLISH-201
- Type: CLI
- Goal:
  - Make recurring client sync easy to automate on Windows, macOS, and Linux without adding a background service.
- Acceptance Criteria (deterministic):
  - [ ] `gamehub sync --json-summary` emits a stable machine-readable summary for success, warning, and failure outcomes.
  - [ ] Repo docs ship first-party Windows Task Scheduler, macOS LaunchAgent, and Linux systemd user examples that call the supported noninteractive sync path.
  - [ ] The new summary surface does not change existing default human-readable sync output.
- Non-Goals:
  - No resident daemon or always-on client agent.
- Tests Required (exact locations / names):
  - `tests/test_sync.py`
  - `tests/test_cli_commands.py`

### STORY GH-POLISH-202
- Type: CROSS-BOUNDARY
- Goal:
  - Give operators a safe, repeatable snapshot helper for backup and restore of a deployed server.
- Acceptance Criteria (deterministic):
  - [ ] Add `scripts/server_snapshot.py` with `backup` and `restore` subcommands.
  - [ ] Backup mode is dry-run-first and records `docker/.env`, the data root, the pinned image tag, and a manifest/checksum file.
  - [ ] Restore mode clearly reports what will be restored before mutating anything.
  - [ ] The helper is documented for real operator use and added to the server deploy bundle if it becomes part of the release-facing workflow.
- Non-Goals:
  - No incremental or remote backup backend integration in this story.
- Tests Required (exact locations / names):
  - `tests/test_server_deploy_artifacts.py`
  - `tests/test_cleanup_backups_script.py`

### STORY GH-POLISH-203
- Type: CLI
- Goal:
  - Add a guided `gamehub config` surface that creates safe starter configs and validates them before first use.
- Acceptance Criteria (deterministic):
  - [ ] Add `gamehub config init` and `gamehub config verify`.
  - [ ] `config init` is interactive in TTY by default, but supports flags for non-interactive/scripted use.
  - [ ] `config init` defaults to the existing config lookup target when one exists, otherwise `./config.toml`.
  - [ ] The wizard prompts for output path, server URL, local `gamehub_dir`, detected Steam paths, controller autoconfig default `Y`, and save sync default `N`.
  - [ ] If save sync is enabled in the wizard, default mode is `download`.
  - [ ] Conflict policy is only prompted when the wizard switches to `bidirectional`, and defaults to `manual`.
  - [ ] The wizard does not ask users to store SGDB secrets in config by default; it points them to env-based setup instead.
  - [ ] Overwriting an existing config uses backup + temp file + atomic replace + explicit console output.
- Non-Goals:
  - No secret vault integration or GUI config editor.
- Tests Required (exact locations / names):
  - `tests/test_cli_commands.py`
  - `tests/test_cli_config_state.py`

## Deferred Stories

### STORY GH-POLISH-204
- Type: SERVER
- Goal:
  - Add a read-only admin dashboard that surfaces status, counts, and operator-relevant warnings.
- Acceptance Criteria (deterministic):
  - [ ] Dashboard is read-only and backed by existing safe status/index data.
  - [ ] No write actions, admin mutations, or auth scope changes are introduced by this story.

### STORY GH-POLISH-205
- Type: CROSS-BOUNDARY
- Goal:
  - Add optional notification hooks for index failures, unresolved save conflicts, and unhealthy server states.
- Acceptance Criteria (deterministic):
  - [ ] Notification sinks are opt-in.
  - [ ] Initial implementation targets a simple webhook or notification endpoint and does not change core sync semantics.

### STORY GH-POLISH-206
- Type: CLI
- Goal:
  - Add a background save reconciler for unmanaged launches without weakening deterministic save rules.
- Acceptance Criteria (deterministic):
  - [ ] Any unmanaged-launch reconciliation reuses current deterministic binding and conflict policies.
  - [ ] No fuzzy matching, filename guessing, or best-effort path heuristics are introduced.

## Completion Criteria
- The scheduled sync, snapshot helper, and config wizard stories are implemented with tests and docs.
- Deferred stories remain explicitly documented in this plan with enough detail to pick up later without re-deciding defaults.
