# PLAN: dev-to-prod-server-migration-checklist

## Context
- Background:
  - Trusted-LAN production hardening for the home-server deployment recently landed.
  - The deploy bundle already ships the production Compose files, runbook, and portable verifier.
- Current behavior:
  - Operator docs cover first-live setup, but they do not provide a dedicated checklist for migrating an existing development server into the hardened production shape.
- Trigger/problem statement:
  - Operators need an explicit, reviewable path for moving from direct-run or broad-bind development servers to the release-pinned production deployment without carrying forward unsafe defaults.

## Goals
- Add a dedicated dev-to-production server migration checklist to the docs set.
- Ship that checklist in the server deploy bundle so release operators get it with the production artifacts.
- Update existing deploy/runbook/release docs to point at the new checklist.

## Non-Goals
- No server API or `gamehub_common` contract changes.
- No new auth, TLS, or non-LAN deployment behavior.
- No new runtime orchestration beyond packaging the checklist with the deploy bundle.

## Constraints
- Windows and macOS local development support are required.
- Keep diffs minimal and conflict-resistant for parallel work.
- No dependency/lockfile/packaging changes unless explicitly required.
- No repo-wide formatting.

## Contract Surface
- Existing contracts touched:
  - Deployment docs and release-bundle contents for server operators
- New/updated contract artifacts:
  - `docs/dev-to-prod-server-migration.md`
  - `scripts/build_server_deploy_bundle.py`
  - `tests/test_server_deploy_artifacts.py`
- Cross-boundary implications:
  - None; work stays in docs/supporting artifact coverage.

## Milestones
1. M1: Define the migration checklist content and operator sequence.
2. M2: Include the checklist in the release bundle and cross-link it from deployment docs.
3. M3: Add or update tests that pin the bundle contents and checklist references.

## Story Contracts

### STORY GH-DOCS-201
- Type: DOCS
- Goal: Add a dedicated dev-to-production server migration checklist and keep it bundled with deploy artifacts.
- Acceptance Criteria (deterministic):
  - [ ] `docs/dev-to-prod-server-migration.md` documents a concrete migration sequence from a dev server to the hardened production Compose deployment.
  - [ ] The server deploy bundle includes the migration checklist.
  - [ ] Deployment-facing docs point operators at the migration checklist.
- Non-Goals:
  - Runtime behavior changes in `src/gamehub_server/`
  - Client/CLI workflow changes
- Tests Required (exact locations / names):
  - `tests/test_server_deploy_artifacts.py::test_build_server_deploy_bundle_includes_expected_files_and_pins_release_tag`
  - `tests/test_server_deploy_artifacts.py::test_deployment_docs_reference_portable_verifier_and_first_live_rules`
- PR Title Template:
  - `[GH-DOCS-201] Add dev-to-production server migration checklist`
- Rollback Risk: Low

## Parallelization Notes
- Lane assignment:
  - Docs lane stories:
    - `GH-DOCS-201`
- Conflict-avoidance notes:
  - Keep changes scoped to deployment docs, deploy-bundle packaging, and artifact tests.
- Merge order constraints:
  - None.

## Completion Criteria
- All milestone acceptance criteria are complete.
- Story contracts are implemented in scoped PRs.
- Required tests are added/updated and documented.
- Documentation updates are complete and implementation-accurate.
