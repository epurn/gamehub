# PLAN: home server deploy readiness

## Context
- Background:
  - GAMEHUB is moving from local and release-validation deploys to a real trusted-LAN home server.
  - The current product scope remains LAN-only and `amd64`-only for the server image.
- Current behavior:
  - The server, Docker assets, release bundle, and release workflows already exist and pass the current quality gates.
  - The repo also has a narrower hardening plan in [home-server-lan-security-hardening.md](./home-server-lan-security-hardening.md).
- Trigger/problem statement:
  - Real home-server rollout still had gaps in trusted-LAN hardening, deploy artifact determinism, Linux-friendly operator verification, and automated container smoke coverage.
  - This plan supersedes the narrower LAN-hardening plan by carrying its unresolved work into `GH-HS-101` and adding deploy/release/operator readiness stories.

## Goals
- Finish trusted-LAN hardening without changing `/v1` contracts or deterministic IDs for valid non-symlink data.
- Make deploy artifacts deterministic, release-pinned, and Linux-friendly.
- Add automated container smoke gates before merge and before GHCR publish.
- Update operator docs and release validation docs for a first real home-server cutover.

## Non-Goals
- Remote-access auth, TLS, or reverse-proxy work.
- ARM server image support.
- `gamehub_common` schema changes.
- New metrics/alerting surfaces beyond the current health/log-based deploy checks.

## Constraints
- Keep scope LAN-only and `amd64`-only.
- Preserve Docker-first deploy flow.
- Keep CLI sync behavior unchanged.
- Keep diffs focused; no dependency or packaging churn beyond the new deploy scripts/workflow wiring.

## Contract Surface
- Existing contracts touched:
  - Server runtime bind defaults and file-serving safety in `src/gamehub_server/`
  - Deploy artifacts in `docker/`
  - Release workflows in `.github/workflows/`
  - Operator docs in `docs/` and top-level `README.md`
- New/updated contract artifacts:
  - `GAMEHUB_SERVER_LISTEN_HOST` for direct-run host binding
  - `GAMEHUB_SERVER_BIND_ADDRESS` for published Docker host binding
  - Portable verifier script: `scripts/verify_server_deploy.py`
  - Testable bundle builder: `scripts/build_server_deploy_bundle.py`
- Cross-boundary implications:
  - No server API schema changes
  - No CLI/server dependency boundary changes

## Milestones
1. M1: Finish trusted-LAN runtime and deploy hardening.
2. M2: Make deploy artifacts deterministic and cross-platform operator-friendly.
3. M3: Add automated container smoke gates and align release/cutover docs.

## Story Contracts

### STORY GH-HS-101
- Type: SERVER
- Goal:
  - Finish trusted-LAN server hardening without changing `/v1` contracts or deterministic IDs for valid data.
- Acceptance Criteria (deterministic):
  - [ ] `gamehub_server.main.run()` reads `GAMEHUB_SERVER_LISTEN_HOST` and defaults to `127.0.0.1`.
  - [ ] `docker/compose.yaml` publishes `${GAMEHUB_SERVER_BIND_ADDRESS:-127.0.0.1}:${GAMEHUB_SERVER_PORT:-8000}:8000`.
  - [ ] `docker/.env.template` exposes `GAMEHUB_SERVER_BIND_ADDRESS` and `GAMEHUB_MAX_SAVE_UPLOAD_BYTES`.
  - [ ] Indexing rejects symlinked files or directories anywhere under `roms/`, `firmware/`, or `saves/`.
  - [ ] File, asset, save, and firmware responses revalidate that the resolved target is a regular non-symlink file inside the allowed content root before serving it.
  - [ ] Valid non-symlink libraries keep current `title_id`, `file_id`, `asset_id`, and `save_id` behavior unchanged.
- Non-Goals:
  - No auth/TLS work.
  - No change to container-internal `uvicorn` bind behavior.
- Tests Required (exact locations / names):
  - `tests/test_indexer.py::test_build_index_rejects_symlinked_rom_file`
  - `tests/test_indexer.py::test_build_index_rejects_symlinked_firmware_file`
  - `tests/test_indexer.py::test_build_index_rejects_symlinked_save_file`
  - `tests/test_indexer.py::test_build_index_rejects_symlinked_save_directory`
  - `tests/test_server_api.py::test_file_endpoint_rejects_cached_symlink_escape`
  - `tests/test_server_api.py::test_asset_endpoint_rejects_cached_symlink_escape`
  - `tests/test_server_api.py::test_save_endpoint_rejects_cached_symlink_escape`
  - `tests/test_server_api.py::test_firmware_endpoint_rejects_symlink_escape`
  - `tests/test_server_api.py::test_run_defaults_to_loopback_host`
  - `tests/test_server_api.py::test_run_honors_gamehub_server_listen_host`
- PR Title Template:
  - `[GH-HS-101] Complete trusted-LAN server hardening`
- Rollback Risk: Medium

### STORY GH-HS-102
- Type: CROSS-BOUNDARY
- Goal:
  - Make deploy artifacts deterministic, release-pinned, and Linux-friendly.
- Acceptance Criteria (deterministic):
  - [ ] Add a stdlib-only `scripts/verify_server_deploy.py` that verifies `/health`, `/v1/index`, and one sample `/v1/files/{file_id}` when titles exist.
  - [ ] Keep `scripts/verify_server_deploy.ps1` as a Windows convenience path while docs switch to the portable verifier as the canonical path.
  - [ ] Move deploy-bundle assembly into `scripts/build_server_deploy_bundle.py`.
  - [ ] Tagged release bundles include `docker/compose.yaml`, a bundle-local `docker/.env.template`, `docs/deployment-server.md`, `docs/runbook.md`, `scripts/verify_server_deploy.py`, and `scripts/verify_server_deploy.ps1`.
  - [ ] The bundle-local env template pins `GAMEHUB_IMAGE_TAG` to the release tag instead of `latest`.
  - [ ] Deployment docs prefer pinned release tags for real servers and show Linux-friendly verifier commands.
- Non-Goals:
  - No standalone server binary packaging.
  - No release-bundle format changes beyond the documented zip contents.
- Tests Required (exact locations / names):
  - `tests/test_server_deploy_artifacts.py::test_compose_binds_to_configured_host_interface_and_wires_upload_limit`
  - `tests/test_server_deploy_artifacts.py::test_env_template_exposes_bind_address_and_upload_limit`
  - `tests/test_server_deploy_artifacts.py::test_build_server_deploy_bundle_includes_expected_files_and_pins_release_tag`
  - `tests/test_server_deploy_artifacts.py::test_release_client_workflow_uses_bundle_script`
  - `tests/test_verify_server_deploy.py::test_verify_server_deploy_succeeds_for_health_index_and_file`
  - `tests/test_verify_server_deploy.py::test_verify_server_deploy_fails_when_index_payload_is_invalid`
- PR Title Template:
  - `[GH-HS-102] Harden deploy bundle and portable verification`
- Rollback Risk: Low

### STORY GH-HS-103
- Type: CROSS-BOUNDARY
- Goal:
  - Add automated container smoke gates and align release/cutover docs with the real deploy path.
- Acceptance Criteria (deterministic):
  - [ ] `audit-regression-gates.yml` includes a Linux job that builds `docker/Dockerfile`, runs the container against `tests/fixtures/indexer_case`, and verifies it with `scripts/verify_server_deploy.py`.
  - [ ] `release-server.yml` gates GHCR publish on the same smoke flow.
  - [ ] `docs/release-final-validation-playbook.md` uses the portable verifier against a live local container instead of build-only server checks.
  - [ ] `docs/runbook.md`, `docs/deployment-server.md`, `docs/release-process.md`, and current manual checklists document pinned tag choice, bind-address choice, backup snapshot, writable `saves/` when enabled, and the no-symlink rule.
- Non-Goals:
  - No Docker Compose-based integration test harness.
  - No remote-access operator guide.
- Tests Required (exact locations / names):
  - `tests/test_server_deploy_artifacts.py::test_audit_workflow_runs_server_container_smoke`
  - `tests/test_server_deploy_artifacts.py::test_release_server_workflow_gates_publish_on_container_smoke`
  - `tests/test_server_deploy_artifacts.py::test_deployment_docs_reference_portable_verifier_and_first_live_rules`
- PR Title Template:
  - `[GH-HS-103] Add deploy smoke gates and cutover validation`
- Rollback Risk: Low

## Parallelization Notes
- Lane assignment:
  - Server lane stories:
    - `GH-HS-101`
  - Docs/workflow lane stories:
    - `GH-HS-102`
    - `GH-HS-103`
- Conflict-avoidance notes:
  - `GH-HS-101` owns runtime hardening and the new server-path tests.
  - `GH-HS-102` owns deploy scripts, bundle contents, and deploy-artifact tests.
  - `GH-HS-103` owns workflow smoke jobs and the release/cutover doc sweep.
- Merge order constraints:
  - `GH-HS-101` before `GH-HS-103`
  - `GH-HS-102` before `GH-HS-103`

## Completion Criteria
- Trusted-LAN hardening is complete for runtime and Docker deploy defaults.
- Release bundles are deterministic and pinned to the release tag.
- Linux-friendly verification exists and is documented.
- PR and release workflows both prove the real server image boots and serves fixture data.
- Required tests/docs are updated and the full repo gates pass.
