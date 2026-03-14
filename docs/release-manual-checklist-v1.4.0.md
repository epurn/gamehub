# v1.4.0 Manual Release Checklist

Use this after the automated gates pass.

Target time: about 3 to 4 hours.

This is the short manual path for user-visible behavior. It intentionally skips static analysis, unit tests, and other checks already covered by automation.

Full release flow still lives in [release-final-validation-playbook.md](./release-final-validation-playbook.md).

## Already verified on this branch

These do not need to be repeated unless the branch changes again:

- `.\venv\Scripts\python.exe -m ruff format --check .`
- `.\venv\Scripts\python.exe -m ruff check .`
- `.\venv\Scripts\python.exe -m mypy src`
- `.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider`
- `.\venv\Scripts\python.exe scripts\audit_repo_readiness.py`
  - current result is `WARN` only because of a known revoked historical SGDB key in local `config.toml`
- `.\venv\Scripts\python.exe -m build --wheel`
- `.\venv\Scripts\pyinstaller.exe --noconfirm --clean packaging\windows\gamehub.spec`
- `.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe --help`
- `.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --help`

## Before manual testing

- [ ] Rebuild the wheel and Windows EXE after the version bump.
- [ ] Confirm rebuilt artifacts and server version metadata report `1.4.0`.

## Test data to prepare once

- [ ] One `RetroArch` title that writes a battery save.
- [ ] One managed `PSX` or `PS2` title that uses a memory card.
- [ ] One learned-tree save title: `GC`, `Wii`, or `N3DS`.
- [ ] One Windows machine with Steam.
- [ ] One Apple Silicon macOS machine with Steam.
- [ ] One Bazzite or Steam Deck machine with Steam and Flatpak emulators.
- [ ] A live release-candidate server with representative ROM, firmware, and save data.

## 1. Server Smoke

Budget: 10 to 15 minutes.

- [ ] Run `.\scripts\verify_server_deploy.ps1 -BaseUrl "http://<SERVER_IP>:8000"` against the release-candidate server.
- [ ] Confirm `GET /health` returns `{"status":"ok"}`.
- [ ] Confirm `GET /v1/index` succeeds.
- [ ] Confirm `GET /v1/save-bindings` succeeds and includes bindings for the save-validation titles.
- [ ] Confirm the server data root includes writable `saves/`.

Stop if any of the above fail.

## 2. Windows Packaged Client

Budget: 35 to 50 minutes.

- [ ] Rebuild the Windows EXE after the version bump:
```powershell
.\venv\Scripts\pyinstaller.exe --noconfirm --clean packaging\windows\gamehub.spec
```
- [ ] Confirm the EXE reports the expected version in artifact naming or release notes.
- [ ] Prepare `config.windows.toml` from [docs/templates/config.windows.template.toml](./templates/config.windows.template.toml).
- [ ] If this machine previously used older preview builds, run one reseed bootstrap first:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe init --config .\config.windows.toml --reseed-profiles
```
- [ ] Run a dry-run sync:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --dry-run --verbose --require-steam-closed
```
- [ ] Run the first real sync:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --verbose --require-steam-closed
```
- [ ] Run the second real sync immediately and confirm it is effectively idempotent:
```powershell
.\dist\gamehub-windows-amd64\gamehub-windows-amd64.exe sync --config .\config.windows.toml --verbose --require-steam-closed
```
- [ ] Run shortcut structure validation:
```powershell
.\venv\Scripts\python.exe scripts\validate_steam_shortcuts.py --config .\config.windows.toml
```
- [ ] In Steam, confirm:
  - managed shortcuts exist
  - collections exist by exact system name
  - artwork appears
  - one sample title launches

## 3. Windows Save-Sync User Flow

Budget: 35 to 45 minutes.

Use the prepared `RetroArch` and `PSX`/`PS2` titles here.

- [ ] `save_sync.enabled = false`
  - run dry-run and one real sync
  - confirm save work is `skip` only
  - confirm local and remote saves remain unchanged
- [ ] `save_sync.enabled = true`, `mode = "download"`
  - make one save missing locally or newer on the server
  - run dry-run, then real sync
  - confirm local bytes converge to the server copy
  - run sync again and confirm no-op behavior
- [ ] `save_sync.enabled = true`, `mode = "bidirectional"`
  - change one existing local save
  - run real sync
  - confirm the remote indexed save updates
- [ ] Managed exact-file creation:
  - start with no remote save for the battery-save or memory-card title
  - launch the managed Steam shortcut
  - create or modify the save
  - exit normally
  - confirm the server now has the indexed save without waiting for another full sync
- [ ] One conflict-safe scenario:
  - create deliberate both-side drift
  - set `conflict_policy = "manual"`
  - run dry-run or real sync
  - confirm GAMEHUB does not silently overwrite either side

## 4. macOS Apple Silicon Client

Budget: 40 to 55 minutes.

- [ ] Prepare `config.macos.toml` from [docs/templates/config.macos.template.toml](./templates/config.macos.template.toml).
- [ ] If this machine previously used older preview builds, run one reseed bootstrap first:
```bash
./venv/bin/python -m gamehub_cli.main init --config ./config.macos.toml --reseed-profiles
```
- [ ] Run dry-run init:
```bash
./venv/bin/python -m gamehub_cli.main init --config ./config.macos.toml --dry-run --verbose
```
- [ ] Run real init:
```bash
./venv/bin/python -m gamehub_cli.main init --config ./config.macos.toml
```
- [ ] Run dry-run sync:
```bash
./venv/bin/python -m gamehub_cli.main sync --config ./config.macos.toml --dry-run --verbose --require-steam-closed
```
- [ ] Run first real sync:
```bash
./venv/bin/python -m gamehub_cli.main sync --config ./config.macos.toml --verbose --require-steam-closed
```
- [ ] Run second real sync and confirm idempotent behavior.
- [ ] Run shortcut structure validation:
```bash
./venv/bin/python scripts/validate_steam_shortcuts.py --config ./config.macos.toml
```
- [ ] In Steam, confirm:
  - managed shortcuts exist
  - collections exist
  - artwork appears
- [ ] Launch one managed `RetroArch` title.
- [ ] Launch one managed macOS `N64` RetroArch title and confirm video output is present.
- [ ] Launch one managed `Dolphin` title.
- [ ] Launch one managed `Azahar` title and confirm the bundle-safe launch path works.
- [ ] If the macOS Azahar exit hook is enabled, confirm `Start+Select` quits the newly launched Azahar session cleanly.
- [ ] Save-sync spot checks:
  - one download-first convergence
  - one managed post-exit upload
  - one first-time exact-file save creation
- [ ] Controller autoconfig spot checks:
  - `0 -> kbm`
  - `1 -> xbox_1p`
  - `2+ -> xbox_2p`
  - `Dolphin` / `Azahar` bindings use macOS-native device tokens

## 5. Bazzite or Steam Deck User Flow

Budget: 45 to 60 minutes.

Use this pass for Flatpak, Deck-template, and Linux launch behavior.

- [ ] Install the rebuilt wheel candidate on Bazzite or Steam Deck.
- [ ] Prepare `config.bazzite.toml` or Steam Deck config from the template docs.
- [ ] If this machine previously used older preview builds, run one reseed bootstrap first:
```bash
gamehub init --config ./config.bazzite.toml --reseed-profiles
```
- [ ] Run dry-run sync:
```bash
gamehub sync --config ./config.bazzite.toml --dry-run --verbose --require-steam-closed
```
- [ ] Run first real sync:
```bash
gamehub sync --config ./config.bazzite.toml --verbose --require-steam-closed
```
- [ ] Run second real sync and confirm idempotent behavior.
- [ ] Run shortcut structure validation:
```bash
./venv/bin/python scripts/validate_steam_shortcuts.py --config ./config.bazzite.toml
```
- [ ] In Steam, confirm:
  - managed shortcuts exist
  - collections exist
  - artwork appears
  - one sample title launches
- [ ] If on Steam Deck and the library includes `Wii` or `N3DS`, confirm managed template files and override repair are present for one title.
- [ ] Launch one Linux Flatpak `Dolphin` title from Steam and verify the managed exit path works with `Select+Start`.
- [ ] If `N3DS` is available, launch one Linux Flatpak `Azahar` title from Steam and verify the sync-emitted Azahar wrapper exits on `Select+Start`.

## 6. Offline-Recovery Save Check

Budget: 20 to 30 minutes.

Do this once on the platform you trust most for managed-launch testing.

- [ ] Set `save_sync.enabled = true` and `mode = "bidirectional"`.
- [ ] Launch one managed shortcut with the server reachable and confirm pre-launch metadata succeeds.
- [ ] During play, make a local save change.
- [ ] Make the server unreachable before exit.
- [ ] Exit the title and confirm launch continues cleanly but upload is deferred.
- [ ] Restore server connectivity.
- [ ] Launch the same managed shortcut again without changing the save.
- [ ] Confirm the reconnect path uploads the preserved local save on the later connected launch.

## 7. Evidence To Record

Keep this lightweight for each scenario:

- [ ] platform
- [ ] title and system
- [ ] config mode used
- [ ] command run
- [ ] local save path or Steam shortcut checked
- [ ] pass/fail
- [ ] short note for anything surprising

## Pass Criteria

Call the branch manually validated only if all of these are true:

- [ ] Server smoke passed.
- [ ] Windows packaged client passed dry-run, real sync, and second-pass idempotency.
- [ ] Windows manual Steam verification passed.
- [ ] Windows save-sync scenarios passed.
- [ ] macOS client passed dry-run, real sync, and second-pass idempotency.
- [ ] macOS manual Steam verification passed.
- [ ] macOS save-sync and controller-autoconfig spot checks passed.
- [ ] Bazzite or Steam Deck manual Steam verification passed.
- [ ] Linux platform-specific launch behavior passed for the titles available to test.
- [ ] One offline-recovery managed-launch save scenario passed.
- [ ] Release artifacts were rebuilt after the version bump and show `1.4.0`.
