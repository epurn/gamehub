# PLAN: home server LAN security hardening

## Context
- Background:
  - GAMEHUB server is intentionally LAN-only in this phase and does not provide in-app auth or TLS.
  - The home-server threat model is "trusted LAN, not internet-exposed", but the repo should still be secure-by-default against accidental overexposure and filesystem escape paths.
- Current behavior:
  - Docker deploys publish `8000` on all host interfaces by default via `docker/compose.yaml`.
  - Direct `python -m gamehub_server.main` / `gamehub_server.main.run()` listens on `0.0.0.0`.
  - Server indexing accepts scanned files from `roms/`, `firmware/`, and `saves/` without rejecting symlinked entries.
  - `GET /v1/files/{file_id}`, `GET /v1/assets/{asset_id}`, and `GET /v1/saves/{save_id}` serve cached paths without resolved-root containment checks at read time.
  - `GAMEHUB_MAX_SAVE_UPLOAD_BYTES` exists in server code and docs, but the default Docker deploy does not surface or pass it through from `docker/.env`.
- Trigger/problem statement:
  - The repo audit found three outstanding issues to fix for a secure trusted-LAN deployment:
    - insecure-by-default host exposure in deploy/direct-run defaults
    - symlink-based read/index escape paths under the server data root
    - missing deployment wiring for the documented save-upload cap

## Goals
- Make direct-run and Docker deployment surfaces secure-by-default for trusted-LAN operators.
- Prevent indexed content and read endpoints from hashing or serving files outside the configured data root through symlinks or path replacement.
- Surface and document explicit deployment hardening knobs for host binding and save upload cap.
- Add regression tests covering server runtime hardening and deploy artifacts.

## Non-Goals
- Add authentication, TLS, reverse-proxy features, or internet-facing deployment support.
- Change `/v1` wire schemas, deterministic IDs, or client sync semantics.
- Change trusted-LAN unauthenticated API behavior beyond hardening filesystem and bind defaults.
- Introduce dependency, lockfile, or packaging changes.

## Constraints
- Windows-first local development support is required.
- Keep diffs minimal and conflict-resistant for parallel work.
- No dependency/lockfile/packaging changes unless explicitly required.
- No repo-wide formatting.
- Preserve Docker-first LAN deployment and existing client compatibility.
- Any new defaults must still allow explicit trusted-LAN opt-in without source edits.

## Contract Surface
- Existing contracts touched:
  - Server deployment behavior in `docker/compose.yaml`, `docker/.env.template`, `docs/deployment-server.md`, and `docs/runbook.md`
  - Direct server entrypoint behavior in `src/gamehub_server/main.py`
  - Accepted server data-root layout rules for `roms/`, `firmware/`, and `saves/`
- New/updated contract artifacts:
  - New direct-run env override: `GAMEHUB_SERVER_LISTEN_HOST`
    - Default for `gamehub_server.main.run()`: `127.0.0.1`
    - Explicit override required for broader listen addresses outside Docker
  - New deploy env: `GAMEHUB_SERVER_BIND_ADDRESS`
    - Used by `docker/compose.yaml` to bind the published host port to a specific host interface
    - Template default: `127.0.0.1`
    - LAN operators must set an explicit trusted LAN IP or explicitly opt into `0.0.0.0`
  - Existing deploy env surfaced end-to-end: `GAMEHUB_MAX_SAVE_UPLOAD_BYTES`
  - New operator rule: symlinked files or directories under server-scanned content roots are invalid and must be rejected
- Cross-boundary implications:
  - No `gamehub_common` model or API route changes
  - No CLI code changes required
  - Existing valid non-symlink data roots continue to produce identical IDs and index payloads

## Milestones
1. M1: Harden server indexing and read-path resolution against symlink and out-of-root content.
2. M2: Make deploy and direct-run bind behavior explicit and secure-by-default; wire upload-cap env through Docker artifacts.
3. M3: Update operator docs and add deploy-artifact regressions so the hardened behavior stays documented and enforced.

## Story Contracts

### STORY GH-SEC-101
- Type: SERVER
- Goal:
  - Reject symlinked content-root entries and enforce resolved-path containment for all indexed content reads.
- Acceptance Criteria (deterministic):
  - [ ] `build_index` fails with a clear actionable error when a symlinked file or directory is encountered anywhere in scanned `roms/`, `firmware/`, or `saves/` trees.
  - [ ] Server read helpers for ROM, asset, and save responses resolve the target path and refuse to serve entries that are missing, non-files, symlinked, or resolved outside the allowed content root.
  - [ ] Replacing an already-indexed file on disk with a symlink cannot be used to read data outside the configured server content roots before the next refresh.
  - [ ] Valid non-symlink content keeps existing `title_id`, `file_id`, `asset_id`, and `save_id` behavior unchanged.
  - [ ] Save upload path-containment logic remains intact and is not weakened by the new read-side hardening.
- Non-Goals:
  - No best-effort symlink canonicalization or support for symlinked libraries.
  - No API schema changes for successful read/write responses.
- Tests Required (exact locations / names):
  - `tests/test_indexer.py::test_build_index_rejects_symlinked_rom_file`
  - `tests/test_indexer.py::test_build_index_rejects_symlinked_firmware_file`
  - `tests/test_indexer.py::test_build_index_rejects_symlinked_save_file`
  - `tests/test_indexer.py::test_build_index_rejects_symlinked_save_directory`
  - `tests/test_server_api.py::test_file_endpoint_rejects_cached_symlink_escape`
  - `tests/test_server_api.py::test_asset_endpoint_rejects_cached_symlink_escape`
  - `tests/test_server_api.py::test_save_endpoint_rejects_cached_symlink_escape`
- PR Title Template:
  - `[GH-SEC-101] Harden server content roots against symlink escapes`
- Rollback Risk: Medium

### STORY GH-SEC-102
- Type: SERVER
- Goal:
  - Make direct-run and Docker exposure defaults explicit, loopback-safe, and operator-configurable.
- Acceptance Criteria (deterministic):
  - [ ] `gamehub_server.main.run()` listens on `127.0.0.1` by default and only uses broader interfaces when `GAMEHUB_SERVER_LISTEN_HOST` is explicitly set.
  - [ ] `docker/compose.yaml` publishes the service on `GAMEHUB_SERVER_BIND_ADDRESS` instead of all host interfaces by default.
  - [ ] `docker/.env.template` includes `GAMEHUB_SERVER_BIND_ADDRESS=127.0.0.1` and `GAMEHUB_MAX_SAVE_UPLOAD_BYTES=` with comments that explain trusted-LAN usage and explicit override behavior.
  - [ ] `docker/compose.yaml` passes `GAMEHUB_MAX_SAVE_UPLOAD_BYTES` through to the container when configured, while preserving current default behavior when unset.
  - [ ] The release verification script remains usable for loopback-bound and explicitly LAN-bound deployments without changing API semantics.
- Non-Goals:
  - No auth or TLS support.
  - No change to container internal `uvicorn` bind behavior beyond what is needed for Docker to keep working.
  - No change to CLI config surface or client rollout steps.
- Tests Required (exact locations / names):
  - `tests/test_server_api.py::test_run_defaults_to_loopback_host`
  - `tests/test_server_api.py::test_run_honors_gamehub_server_listen_host`
  - `tests/test_server_deploy_artifacts.py::test_compose_binds_to_configured_host_interface`
  - `tests/test_server_deploy_artifacts.py::test_compose_wires_max_save_upload_bytes_env`
  - `tests/test_server_deploy_artifacts.py::test_env_template_defaults_bind_address_to_loopback`
- PR Title Template:
  - `[GH-SEC-102] Harden server bind defaults and deploy env wiring`
- Rollback Risk: Medium

### STORY GH-SEC-103
- Type: DOCS
- Goal:
  - Align operator documentation and validation guidance with the hardened trusted-LAN deployment model.
- Acceptance Criteria (deterministic):
  - [ ] `docs/deployment-server.md` documents explicit bind-address choices, trusted-LAN-only scope, multi-homed host caution, and the `GAMEHUB_MAX_SAVE_UPLOAD_BYTES` deploy knob.
  - [ ] `docs/runbook.md` includes bind-address verification, writable `saves/` validation, and a "no symlinks under server data root" checklist item.
  - [ ] `docs/server-api.md` states that symlinked server content roots are invalid operator input and that direct-run defaults are loopback-only unless explicitly overridden.
  - [ ] `docs/development.md` keeps any `0.0.0.0` examples explicitly labeled as development-only, not production-safe defaults.
  - [ ] Documentation examples and env names match the final implemented names exactly.
- Non-Goals:
  - No client-install workflow rewrite.
  - No internet deployment, reverse proxy, or certificate guidance.
- Tests Required (exact locations / names):
  - `tests/test_server_deploy_artifacts.py::test_deployment_docs_reference_bind_address_and_upload_cap`
  - `tests/test_server_deploy_artifacts.py::test_runbook_mentions_no_symlink_data_root_rule`
- PR Title Template:
  - `[GH-SEC-103] Document LAN security hardening for server deploys`
- Rollback Risk: Low

## Parallelization Notes
- Lane assignment:
  - Server lane stories:
    - `GH-SEC-101`
    - `GH-SEC-102`
  - CLI lane stories:
    - none
  - Common lane stories:
    - none
  - Docs lane stories:
    - `GH-SEC-103`
- Conflict-avoidance notes:
  - `GH-SEC-101` owns server filesystem/index/read-path hardening in `src/gamehub_server/` plus related API/indexer tests.
  - `GH-SEC-102` owns deploy artifacts and `main.run()` bind-default behavior; keep `main.py` changes isolated to listen-host parsing and `run()`.
  - `GH-SEC-103` should not start until env variable names and defaults from `GH-SEC-102` are settled.
  - New artifact-regression tests should live in a dedicated `tests/test_server_deploy_artifacts.py` file to avoid collisions with server API tests.
- Merge order constraints:
  - `GH-SEC-101` before `GH-SEC-103`
  - `GH-SEC-102` before `GH-SEC-103`
  - `GH-SEC-101` and `GH-SEC-102` may run in parallel only if `main.py` ownership is rebased cleanly; otherwise land `GH-SEC-101` first, then `GH-SEC-102`

## Completion Criteria
- All milestone acceptance criteria are complete.
- Story contracts are implemented in scoped PRs.
- Required tests are added/updated and documented.
- Documentation updates are complete and implementation-accurate.
