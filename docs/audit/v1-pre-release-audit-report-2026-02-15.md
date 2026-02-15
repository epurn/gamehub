# V1 Pre-Release Audit Report (2026-02-15)

## Scope
- Audit focus: code reuse, repo structure, configurability/defaults, Linux portability, plus security/dependency/performance/reliability/release-process checks.
- Severity gate for v1 release: block on `P0` and `P1` only.
- Linux acceptance target: Fedora, Ubuntu, SteamOS-like environments.

## Evidence Baseline
- Full regression: `.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` -> `122 passed`.
- Linux/Steam/path-focused suite:
  - `.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_emulators.py tests/test_steam.py tests/test_sync.py tests/test_firmware_deploy.py tests/test_retroarch_cores.py` -> `81 passed`.
  - `.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_cli_config_state.py` -> `10 passed`.
- Runtime Bazzite literal check: `rg -n "bazzite|Bazzite" apps shared docs README.md` -> no runtime/docs matches.
- Synthetic index benchmark (240 ROM files, ~240 MiB fixture payload):
  - `build_index()` avg: `0.584s`
  - `IndexRepository.load(force_refresh=True)` avg: `0.557s`

## Findings
| Finding ID | Severity | Impact | Evidence | Fix Recommendation | Effort | Required Tests | Required Docs |
|---|---|---|---|---|---|---|---|
| GH-AUD-001 | P1 | Server re-hashes full library on each index/file request, creating avoidable latency and load under larger ROM sets. | `apps/server/gamehub_server/main.py:43`, `apps/server/gamehub_server/main.py:48`, `apps/server/gamehub_server/main.py:57` | Add refresh policy: cache index in-memory and refresh only on TTL/manual endpoint/startup background task; use cached lookup for `/v1/files` and `/v1/assets`. | M | Add API tests proving repeated reads do not force refresh; add explicit refresh-path test. | Update `docs/server-api.md`, `docs/deployment-server.md`. |
| GH-AUD-002 | P1 | Deployment defaults are not portable across host platforms and architectures. | `.env.production.template:3`, `docker/compose.yaml:7` | Replace path-like default with placeholder value; make compose platform configurable or remove hard pin for default local deploys. | S | Add compose config render check in CI (env-file variants). | Update `docs/deployment-server.md`, `docs/runbook.md`. |
| GH-AUD-003 | P2 | Linux path and Flatpak detection logic is duplicated in multiple modules, increasing drift risk. | `apps/cli/gamehub_cli/firmware_deploy.py:29`, `apps/cli/gamehub_cli/retroarch_cores.py:118`, `apps/cli/gamehub_cli/sync.py:246` | Introduce shared `PathResolver` utility module; centralize flatpak app-id path and command matching. | M | Add unit tests for shared resolver reused by all call sites. | Update `docs/cli-sync.md`, `docs/config-and-state.md`. |
| GH-AUD-004 | P2 | Duplicate relative-path conversion helper exists in planner and sync modules. | `apps/cli/gamehub_cli/planner.py:37`, `apps/cli/gamehub_cli/sync.py:182` | Move rel-path conversion to a shared `paths.py` helper in CLI package and import from both modules. | S | Add unit tests for separator normalization and relative path handling. | None required. |
| GH-AUD-005 | P2 | Linux auto-install `auto` mode does not natively handle apt-based hosts; Ubuntu requires explicit command backend configuration. | `apps/cli/gamehub_cli/emulators.py:546` | Add apt backend (`apt`/`apt-get`) and autodetection branch in `auto`; keep `command` backend for custom distros. | M | Add tests for Ubuntu dist-id path with apt present/absent. | Update `docs/cli-sync.md`, `docs/client-install.md`. |
| GH-AUD-006 | P2 | `localconfig.vdf` is always rewritten during collection update path, even when no logical change, increasing file churn/backups. | `apps/cli/gamehub_cli/steam.py:730`, `apps/cli/gamehub_cli/steam.py:811` | Skip atomic write when serialized payload is unchanged or when `updates == 0`. | S | Add no-op collection update test asserting write is skipped. | Update `docs/steam-integration.md` (no-op behavior note). |
| GH-AUD-007 | P2 | Env override handling is fragmented across modules, making precedence hard to reason about globally. | `apps/cli/gamehub_cli/config.py:174`, `apps/cli/gamehub_cli/firmware_deploy.py:19`, `apps/cli/gamehub_cli/emulators.py:546`, `apps/cli/gamehub_cli/steam.py:125`, `apps/cli/gamehub_cli/retroarch_cores.py:56` | Consolidate env parsing into config load path and pass resolved settings through typed config. | M | Add precedence matrix tests for CLI flag/config/env/default behavior. | Update `docs/config-and-state.md`. |
| GH-AUD-008 | P2 | Secret-handling hygiene risk: local developer config can still carry plaintext SGDB tokens even though ignored by git. | `config.toml:14` (local, untracked), `.gitignore:43`, `docs/config-and-state.md:30` | Document env-first secret policy; add optional secret-scanning step in release checklist; rotate any exposed local SGDB keys. | S | Add CI check/script for common secret patterns on tracked files. | Update `docs/release-process.md`, `docs/config-and-state.md`. |
| GH-AUD-009 | P3 | Test temp-dir helper duplication across many test files increases maintenance overhead and inconsistency risk. | `tests/test_sync.py:23`, `tests/test_steam.py:35`, `tests/test_emulators.py:13`, plus related files | Consolidate `_workspace_tempdir` into shared fixture/helper in `tests/conftest.py`. | S | Keep existing tests green; add one fixture unit smoke test. | Update `docs/development.md` (test helper conventions). |
| GH-AUD-010 | P3 | Dependency governance is minimal (no lock/constraints policy, no documented audit step). | `pyproject.toml:1`, `docs/release-process.md:1` | Add dependency update policy (`uv lock` or constraints), include security audit command in release checklist. | M | Add CI job for dependency audit command. | Update `docs/release-process.md`. |
| GH-AUD-011 | P3 | Large module size creates high cognitive load and mixed responsibilities. | `apps/cli/gamehub_cli/steam.py` (~930 LOC), `apps/cli/gamehub_cli/emulators.py` (~593 LOC), `apps/cli/gamehub_cli/sync.py` (~547 LOC), `apps/cli/gamehub_cli/firmware_deploy.py` (~543 LOC) | Execute staged module split (defined in fix backlog) without changing CLI/API behavior. | M | Preserve existing suite; add targeted module-level tests after split. | Update `docs/development.md` architecture section. |

## Linux Portability Conclusion
- Runtime code does not hardcode Bazzite-specific behavior.
- Current Linux behavior is capability-based/config-based (dnf/flatpak/command), but Ubuntu ergonomics are weaker in `auto` mode until apt backend is added.
- Steam path discovery and reopen fallback cover native and Flatpak layouts (`apps/cli/gamehub_cli/steam.py:78`, `apps/cli/gamehub_cli/steam.py:901`).

## Configurability and Defaults Conclusion
- Major user-facing paths are configurable (`paths.gamehub_dir`, steam path/id, Linux overrides, env overrides).
- Key gaps are portability defaults in deployment templates and centralization of override precedence logic.

## Recommended Gate Decision
- Do not block v1 on `P2`/`P3`.
- Block v1 until `GH-AUD-001` and `GH-AUD-002` are closed (or explicitly waived with risk sign-off).
