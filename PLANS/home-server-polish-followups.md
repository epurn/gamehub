# PLAN: home-server-polish-followups

## Context
- Background:
  - `v1.6.0` finishes trusted-LAN deploy hardening, adds `/v1/status`, and introduces `doctor server` with exact client/server version checks.
  - The product is now viable as a real home server, but the remaining operator experience still depends on manual wrapper scripts, handwritten config bootstrap, and ad hoc backup steps.
- Current behavior:
  - `gamehub sync` is scriptable by exit code, but it only emits human-readable output and does not provide a stable machine-readable summary for schedulers or wrappers.
  - Operators can verify a server deploy and take manual pre-cutover snapshots, but there is no first-party snapshot helper for repeatable backup and restore.
  - Config bootstrap still depends on copying a template from `docs/templates/` and editing it manually before first use.
- Trigger/problem statement:
  - Home-server follow-up work now needs an implementation-ready plan that improves day-2 operator UX without adding a resident daemon, weakening deterministic behavior, or reopening server/CLI boundary questions.

## Goals
- Make recurring sync automation first-party and scheduler-friendly on Windows, macOS, and Linux without introducing a background service.
- Add a dry-run-first server snapshot helper that supports repeatable backup and explicit restore planning.
- Add a guided `gamehub config` workflow that writes safe starter configs and validates them before first use.

## Non-Goals
- No additional follow-on stories beyond the three implementation stories in this plan.
- No changes to `/v1/index`, deterministic IDs, or current save-binding contracts unless a later plan freezes a new shared contract first.
- No built-in auth, TLS, reverse-proxy orchestration, or remote-access workflow changes.
- No fuzzy matching, heuristic save reconciliation, or best-effort config repair.

## Constraints
- Keep Docker-first server deployment intact.
- Keep `gamehub_server` and `gamehub_cli` boundaries strict.
- Any config or restore write path must follow the repo backup + temp-file + flush/fsync where appropriate + atomic-replace + explicit-log pattern.
- Interactive flows must still support non-interactive/scripted use through flags.
- Windows, macOS, and Linux operator examples must stay runnable and aligned with the supported command surface.

## Contract Surface
- Existing contracts touched:
  - CLI entrypoints in `src/gamehub_cli/main.py`
  - sync orchestration and summaries in `src/gamehub_cli/sync/orchestrator.py`, `src/gamehub_cli/sync/transfer_stage.py`, and `src/gamehub_cli/sync/save_stage.py`
  - config defaults and resolution in `src/gamehub_cli/common/config.py`
  - deploy/operator scripts in `scripts/`
  - operator docs in `docs/cli-sync.md`, `docs/config-and-state.md`, `docs/deployment-server.md`, `docs/runbook.md`, and `docs/dev-to-prod-server-migration.md`
- New/updated contract artifacts:
  - `gamehub sync --json-summary`
  - `gamehub config init`
  - `gamehub config verify`
  - `scripts/server_snapshot.py`
  - stable sync-summary documentation in `docs/cli-sync.md`
- Cross-boundary implications:
  - No `gamehub_common` schema changes are expected.
  - No new server API endpoints are required for this phase.
  - Snapshot tooling may touch deploy-bundle contents and operator docs, but it must not move server-write policy into CLI runtime code.

## Milestones
1. M1: Add machine-readable sync summaries and first-party scheduler examples.
2. M2: Add a safe, dry-run-first server snapshot backup/restore helper.
3. M3: Add guided config init/verify flows and document the supported bootstrap path.

## Story Contracts

### STORY GH-POLISH-201
- Type: CLI
- Goal:
  - Make `gamehub sync` safe to automate from Windows Task Scheduler, macOS LaunchAgent, and Linux systemd user timers without changing the current default human-readable operator flow.
- Acceptance Criteria (deterministic):
  - [ ] Add `--json-summary` to `gamehub sync`.
  - [ ] When `--json-summary` is set, stdout is reserved for a single final JSON object with stable top-level keys: `ok`, `dry_run`, `server_url`, `plan`, `downloads`, `save_sync`, `steam`, `warnings`, and `errors`.
  - [ ] The `plan` summary includes `total_actions`, `blocked_systems`, `skipped_titles`, and per-kind counts derived from the final `SyncPlan`.
  - [ ] The `save_sync` summary reports `planned`, `downloaded`, `uploaded`, `conflicts`, and `skipped`, using zeros when save sync is disabled.
  - [ ] Failure outcomes still return a non-zero exit code and populate the same JSON structure with actionable `errors`.
  - [ ] Existing default sync output stays human-readable and behaviorally unchanged when `--json-summary` is not set.
  - [ ] `docs/cli-sync.md` ships first-party Windows Task Scheduler, macOS LaunchAgent, and Linux systemd user examples that call the supported non-interactive sync path and explain exit-code handling.
- Non-Goals:
  - No resident daemon, always-on client agent, or background scheduler installer.
  - No change to existing sync planning semantics, save-policy defaults, or default stdout format when the new flag is absent.
- Tests Required (exact locations / names):
  - `tests/test_cli_commands.py::test_typer_sync_command_dispatches_json_summary`
  - `tests/test_sync.py::test_run_sync_json_summary_dry_run_success`
  - `tests/test_sync.py::test_run_sync_json_summary_failure_preserves_nonzero_exit`
  - `tests/test_sync.py::test_run_sync_without_json_summary_keeps_human_output`
- PR Title Template:
  - `[GH-POLISH-201] Add scheduler-friendly sync JSON summaries`
- Rollback Risk: Medium

### STORY GH-POLISH-202
- Type: CROSS-BOUNDARY
- Goal:
  - Give home-server operators a first-party snapshot helper for repeatable backup and explicit restore planning of a deployed server.
- Acceptance Criteria (deterministic):
  - [ ] Add a stdlib-only `scripts/server_snapshot.py` with `backup` and `restore` subcommands.
  - [ ] `backup` is dry-run-first: without `--apply`, it reports the resolved inputs, output location, pinned image tag, and manifest entries it would write.
  - [ ] `backup --apply` stages snapshot output in a temp directory and finalizes it atomically; snapshot contents include `docker/.env`, the resolved server data root, the pinned image tag, and a manifest with SHA-256 checksums.
  - [ ] `restore` is also dry-run-first and reports the exact files and directories that would be replaced before any mutation occurs.
  - [ ] `restore --apply` backs up replaced non-ephemeral files, performs temp-file staging plus atomic replace for each restore target where applicable, and emits explicit log lines for every mutation.
  - [ ] If the snapshot helper becomes part of the release-facing operator workflow, `scripts/build_server_deploy_bundle.py` includes it in the server deploy bundle.
  - [ ] `docs/deployment-server.md`, `docs/runbook.md`, and `docs/dev-to-prod-server-migration.md` document the supported backup/restore flow and when operators should take a pre-cutover snapshot.
- Non-Goals:
  - No incremental backups, remote backup backends, snapshot scheduling, or retention policy automation in this story.
  - No direct mutation of server data by the running API process.
- Tests Required (exact locations / names):
  - `tests/test_server_snapshot.py::test_backup_dry_run_reports_manifest_and_inputs`
  - `tests/test_server_snapshot.py::test_backup_apply_writes_snapshot_manifest_and_checksums`
  - `tests/test_server_snapshot.py::test_restore_dry_run_reports_replacements`
  - `tests/test_server_snapshot.py::test_restore_apply_uses_backup_and_atomic_replace`
  - `tests/test_server_deploy_artifacts.py::test_build_server_deploy_bundle_includes_server_snapshot_helper_when_shipped`
- PR Title Template:
  - `[GH-POLISH-202] Add server snapshot backup and restore helper`
- Rollback Risk: Medium

### STORY GH-POLISH-203
- Type: CLI
- Goal:
  - Add a guided `gamehub config` surface that creates safe starter configs and validates them before first sync.
- Acceptance Criteria (deterministic):
  - [ ] Add a `config` Typer sub-app with `gamehub config init` and `gamehub config verify`.
  - [ ] `config init` is interactive by default when stdin/stdout is a TTY, but every prompt has a non-interactive flag equivalent.
  - [ ] `config init` defaults to the current config lookup target when one already exists; otherwise it defaults to `./config.toml`.
  - [ ] The wizard prompts for output path, server URL, local `paths.gamehub_dir`, detected Steam userdata path, detected Steam ID, controller autoconfig default `Y`, and save sync default `N`.
  - [ ] If save sync is enabled during `config init`, the default mode is `download`.
  - [ ] Conflict policy is only prompted when save sync mode is switched to `bidirectional`, and its default is `manual`.
  - [ ] The wizard does not ask users to store SGDB secrets in config by default; it points users to `GAMEHUB_SGDB_API_KEY` instead.
  - [ ] Writing a new config uses normal file creation; overwriting an existing config requires backup + temp-file + atomic replace + explicit console output.
  - [ ] `config verify` uses the same config resolution rules as other CLI commands, returns `0` for a valid config, and prints actionable validation errors for missing or invalid config state.
  - [ ] `docs/config-and-state.md` documents the new guided bootstrap and verification flow as the preferred starter path.
- Non-Goals:
  - No GUI config editor, secret vault integration, or automatic network probing beyond local Steam path detection and current config validation rules.
  - No silent repair of malformed config files.
- Tests Required (exact locations / names):
  - `tests/test_cli_commands.py::test_typer_config_init_dispatches`
  - `tests/test_cli_commands.py::test_typer_config_verify_dispatches`
  - `tests/test_cli_config_state.py::test_config_init_defaults_to_existing_resolution_target`
  - `tests/test_cli_config_state.py::test_config_init_overwrite_creates_backup_and_atomic_replace`
  - `tests/test_cli_config_state.py::test_config_verify_reports_actionable_errors`
- PR Title Template:
  - `[GH-POLISH-203] Add guided config init and verify commands`
- Rollback Risk: Medium

## Parallelization Notes
- Lane assignment:
  - CLI sync lane stories:
    - `GH-POLISH-201`
  - Operator tooling lane stories:
    - `GH-POLISH-202`
  - CLI config lane stories:
    - `GH-POLISH-203`
  - Docs lane stories:
    - doc updates land with their owning story; do not split them into a standalone story for this plan
- Conflict-avoidance notes:
  - `GH-POLISH-201` owns `sync` flag plumbing, sync-summary dataclasses/helpers, and scheduler examples in `docs/cli-sync.md`.
  - `GH-POLISH-202` owns `scripts/server_snapshot.py`, any deploy-bundle wiring in `scripts/build_server_deploy_bundle.py`, and server-operator doc updates.
  - `GH-POLISH-203` owns the new `config` CLI surface, config rendering/verification helpers, and `docs/config-and-state.md`.
  - `GH-POLISH-201` and `GH-POLISH-203` both touch `src/gamehub_cli/main.py`; if they run in parallel, one branch must be rebased cleanly before merge.
- Merge order constraints:
  - `GH-POLISH-202` is independent and may land at any time.
  - `GH-POLISH-201` before any external automation examples or wrappers rely on the JSON contract.
  - `GH-POLISH-203` before docs or runbooks point new operators at `gamehub config` as the preferred bootstrap path.

## Completion Criteria
- All milestone acceptance criteria are complete.
- Story contracts are implemented in scoped PRs.
- Scheduled sync is documented as a supported automation path on Windows, macOS, and Linux.
- Server snapshot backup/restore is dry-run-first, safe on mutation, and documented for operator use.
- Guided config bootstrap and validation are available and implementation-accurate in docs.
- Required tests are added or updated, and the repo quality gates pass.
