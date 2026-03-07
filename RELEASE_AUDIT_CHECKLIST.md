# Release Audit Checklist

Use this checklist from the repo root while validating the release candidate.

## Environment readiness

- [ ] Install or refresh dev dependencies:
  - `./venv/bin/python -m pip install -e .[dev]`
- [ ] Confirm tooling is available in `./venv`:
  - `./venv/bin/python -m pytest --version`
  - `./venv/bin/python -m ruff --version`
  - `./venv/bin/python -m mypy --version`

## Required quality gates

- [ ] `./venv/bin/python -m ruff format --check .`
- [ ] `./venv/bin/python -m ruff check .`
- [ ] `./venv/bin/python -m mypy src`
- [ ] `./venv/bin/python -m pytest . -p no:cacheprovider`

## Audit-critical test slices

- [ ] `./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_architecture.py`
- [ ] `./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_save_contracts.py`
- [ ] `./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_server_api.py`
- [ ] `./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_cli_config_state.py`
- [ ] `./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_planner.py`
- [ ] `./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_shortcut_launch.py`
- [ ] `./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_sync.py`
- [ ] `./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_indexer.py`
- [ ] `./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_paths.py`
- [ ] `./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_emulators.py`
- [ ] `./venv/bin/python -m pytest -q -p no:cacheprovider tests/test_downloads.py`

## Manual save-sync validation

Prepare one representative title for each save shape you intend to ship:

- [ ] RetroArch battery save
- [ ] Managed `PSX` or `PS2` memory-card save
- [ ] Learned-tree `GC`, `Wii`, or `N3DS` save

Run the following on each required target host:

- [ ] `save_sync.enabled = false`: dry-run shows deterministic `skip` reasons and non-dry sync leaves saves unchanged
- [ ] `save_sync.enabled = true`, `mode = "download"`: remote save downloads locally and second pass is a no-op
- [ ] `save_sync.enabled = true`, `mode = "bidirectional"`: changed existing local save uploads and converges
- [ ] First-time local exact-file save is created remotely (`battery` or managed `memory_card`)
- [ ] Conflict policies behave correctly for one deliberate both-side drift:
  - `manual`
  - `prefer_server`
  - `prefer_local`
- [ ] Managed `shortcut-launch` uploads a changed save on emulator exit
- [ ] Offline post-exit upload miss is recorded, then recovered correctly after reconnect
- [ ] Non-dry `gamehub sync` rewrites Steam shortcuts to `shortcut-launch` before managed launch validation

## Evidence capture

Record one row per scenario:

| Platform | Title/System | Local save path | Checksum before | Checksum after | Server route | Steam/launch result | Pass/Fail | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |  |  |

## Release gate

- [ ] Structure matches repo boundaries and ownership
- [ ] Code reuse is acceptable; no duplicate save-sync logic remains
- [ ] No `gamehub_cli` -> `gamehub_server` or `gamehub_server` -> `gamehub_cli` runtime imports
- [ ] Docs match shipped behavior
- [ ] Automated gates passed
- [ ] Manual save-sync validation passed
- [ ] Final release decision: `PASS`
