# PLAN: azahar-v1-controls-finalization

## Context
- Background: `v1.6.0` shipped Azahar runtime bootstrap, managed controller profiles, and platform-specific exit-hook support, but two Azahar control gaps still block a polished "final v1" experience.
- Current behavior: GAMEHUB-managed Azahar sessions still lean on Azahar's platform-native quit shortcut instead of the repo's `Esc` exit/menu convention, the wrapper only handles `Start+Select` exit behavior, and joystick sensitivity is high enough that some managed controller paths can show ghost input without extra deadzone tuning.
- Trigger/problem statement: finalize Azahar control behavior so quitting matches the rest of the emulator stack and managed stick deadzones are reasonable enough to stop ghost inputs by default, while removing the rejected non-live controller-to-mouse bridge branch work.

## Goals
- Normalize the managed Azahar quit shortcut to `Esc`.
- Remove the non-live Azahar mouse bridge implementation, package hooks, and operator guidance.
- Normalize managed Azahar stick deadzones so ghost inputs stop without per-title operator tuning.

## Non-Goals
- Patching or forking Azahar upstream.
- Changing non-Azahar emulator bindings or hotkey policy.
- Broad Steam Input template redesign.
- Changing Steam Deck Steam Input template seed behavior.

## Constraints
- Windows and macOS local development support are required.
- Reuse existing atomic/backup/logged mutation paths for any `qt-config.ini` rewrite.
- Keep wrapper/runtime logic in the Azahar controller/runtime modules; do not move emulator-specific policy into `common/`.
- Do not regress the existing Azahar `Start+Select` exit hook behavior on Windows, macOS, or Linux.
- Do not change Steam Deck Steam Input seed payloads or configset sync as part of this work.

## Contract Surface
- Existing contracts touched:
  - managed Azahar profile defaults in `src/gamehub_cli/controllers/profiles.py`
  - assisted Azahar QSettings convergence in `src/gamehub_cli/controllers/convergence.py`
  - Azahar controller apply path in `src/gamehub_cli/controllers/apply_azahar.py`
  - Azahar managed shortcut runtime flow in `src/gamehub_cli/shortcuts/runtime.py`
  - platform-specific Azahar controller helpers in `src/gamehub_cli/controllers/azahar_exit_hook.py`
  - package metadata in `pyproject.toml`
- New/updated contract artifacts:
  - active Azahar finalization stories centered on `Esc` and deadzones only
  - operator docs covering Azahar `Esc` quit, deadzones, and existing exit-hook behavior
- Cross-boundary implications:
  - none; this is CLI-only work

## Research Notes
- Repo-grounded implementation note: Azahar pointer/touch keys are already preservation-first in the apply path, and existing tests prove that `touch_device`/pointer keys survive managed controller rewrites.
- Repo-grounded implementation note: existing Steam Deck template seeds already carry explicit stick deadzone values, which suggests the managed Azahar path should converge deterministic deadzone defaults instead of assuming zero-deadzone joystick behavior is stable across controllers.
- Repo-grounded implementation note: the Azahar mouse bridge was branch-only work and is not a live shipped feature, so it can be removed outright rather than retained behind flags.
- Recommendation: keep the plan focused on shipped Azahar controls only: `Esc` quit normalization, managed deadzones, and existing exit-hook behavior.

## Milestones
1. M1: Converge Azahar quit shortcut state to `Esc` through existing managed/default + assisted QSettings paths.
2. M2: Remove the rejected Azahar mouse-bridge runtime, packaging hooks, and docs without regressing existing exit hooks.
3. M3: Normalize managed Azahar stick deadzones so ghost inputs stop without manual deadzone tuning.

## Story Contracts

### STORY AZAHAR-V1-01
- Type: CLI
- Goal: make managed Azahar quit behavior consistent with GAMEHUB's `Esc` exit/menu convention.
- Acceptance Criteria (deterministic):
  - [x] Managed Azahar default profile/runtime state includes an `Esc` quit binding in the Azahar QSettings surface GAMEHUB owns.
  - [x] Assisted Azahar convergence repairs existing managed `qt-config.ini` files to the same `Esc` quit binding using backup + atomic replace + logging.
  - [x] Existing pointer/touch keys remain preservation-first and are not cleared or remapped while converging the quit shortcut.
  - [x] Existing `Start+Select` wrapper exit behavior is unchanged.
- Non-Goals:
  - mouse simulation
  - upstream Azahar shortcut refactors beyond the managed key GAMEHUB owns
- Tests Required (exact locations / names):
  - `tests/test_controller_profiles.py::test_seed_default_profiles_azahar_sets_quit_shortcut_to_escape`
  - `tests/test_controller_convergence.py::test_controller_convergence_apply_repairs_azahar_quit_shortcut_with_backup`
  - `tests/test_controller_apply.py::test_apply_controller_profile_azahar_preserves_pointer_keys_when_quit_shortcut_is_escape`
- PR Title Template: `[AZAHAR-V1-01] CLI: normalize Azahar quit shortcut to Esc`
- Rollback Risk: Low

### STORY AZAHAR-V1-02
- Type: CLI
- Goal: hard-remove the non-live Azahar mouse bridge implementation and all runtime/package hooks.
- Acceptance Criteria (deterministic):
  - [ ] `src/gamehub_cli/controllers/azahar_mouse_bridge.py` is deleted and no runtime code imports or references it.
  - [ ] Azahar launch paths no longer attempt controller detection, background mouse threads, or mouse-bridge warning paths on Windows, macOS, or Linux.
  - [ ] `pyproject.toml` no longer exposes `linux-input` / `evdev` for Azahar mouse-bridge support.
  - [ ] Existing Windows/macOS `Start+Select` exit hooks and the Linux Flatpak Azahar wrapper keep their current quit behavior.
  - [ ] Existing managed `Esc` quit convergence and managed deadzone behavior are unchanged.
  - [ ] Steam Deck Steam Input seed/template sync behavior is unchanged.
- Non-Goals:
  - changing Steam Deck Steam Input seeds or configset sync
  - changing Azahar exit-hook policy or button combos
  - changing deadzone values or `Esc` ownership keys
- Tests Required (exact locations / names):
  - `tests/test_shortcut_runtime.py::test_run_target_with_windows_azahar_exit_hook_does_not_start_removed_mouse_bridge`
  - `tests/test_shortcut_runtime.py::test_run_target_with_macos_azahar_exit_hook_does_not_start_removed_mouse_bridge`
  - `tests/test_shortcut_runtime.py::test_run_target_azahar_direct_launch_does_not_start_removed_mouse_bridge`
  - `tests/test_azahar_exit_hook.py::test_launch_azahar_flatpak_skips_removed_mouse_bridge_and_starts_combo_monitor`
  - `tests/test_architecture.py::test_gamehub_install_has_no_azahar_mouse_bridge_optional_dependency`
- PR Title Template: `[AZAHAR-V1-02] CLI: remove non-live Azahar mouse bridge`
- Rollback Risk: Low

### STORY AZAHAR-V1-03
- Type: DOCS
- Goal: remove mouse-bridge/operator guidance and rewrite the active Azahar finalization plan around `Esc` + deadzones only.
- Acceptance Criteria (deterministic):
  - [ ] `PLANS/azahar-v1-controls-finalization.md` no longer lists mouse-bridge goals, milestones, research, or tests; `AZAHAR-V1-01` and `AZAHAR-V1-04` remain the live work.
  - [ ] Operator docs remove `GAMEHUB_AZAHAR_MOUSE_BRIDGE`, `GAMEHUB_AZAHAR_MOUSE_BRIDGE_EVENT_DEVICE`, right-stick mouse, `R2` click, `evdev`, and `linux-input` guidance.
  - [ ] Release/manual validation text no longer asks for Azahar mouse verification and instead keeps `Esc` + exit-hook expectations only.
  - [ ] Steam Deck Steam Input docs remain intact except for removing any accidental coupling to the removed mouse bridge.
- Non-Goals:
  - broad Steam Input doc rewrites
  - changing non-Azahar controller documentation
- Tests Required (exact locations / names):
  - none
- PR Title Template: `[AZAHAR-V1-03] Docs: remove Azahar mouse bridge references`
- Rollback Risk: Low

### STORY AZAHAR-V1-04
- Type: CLI
- Goal: auto-set reasonable managed Azahar stick deadzones so ghost inputs stop by default.
- Acceptance Criteria (deterministic):
  - [ ] Managed Azahar default profile/runtime state includes deterministic left/right stick deadzone values in the Azahar QSettings surface GAMEHUB owns.
  - [ ] Assisted Azahar convergence repairs existing managed `qt-config.ini` files to the same deadzone defaults using backup + atomic replace + logging.
  - [ ] The chosen deadzone defaults are automatic for the managed path; operators do not need per-title manual deadzone tuning just to stop ghost inputs.
  - [ ] Existing pointer/touch preservation, `Esc` quit behavior, and `Start+Select` wrapper exit behavior remain unchanged.
- Non-Goals:
  - interactive stick-calibration UX
  - non-Azahar deadzone policy changes
  - broad Steam Input template redesign beyond what is required to stop managed Azahar ghost input
- Tests Required (exact locations / names):
  - `tests/test_controller_profiles.py::test_seed_default_profiles_azahar_sets_stick_deadzone_defaults`
  - `tests/test_controller_convergence.py::test_controller_convergence_apply_repairs_azahar_stick_deadzones_with_backup`
  - `tests/test_controller_apply.py::test_apply_controller_profile_azahar_preserves_pointer_keys_while_setting_stick_deadzones`
- PR Title Template: `[AZAHAR-V1-04] CLI: normalize Azahar stick deadzones`
- Rollback Risk: Medium

## Parallelization Notes
- Lane assignment:
  - CLI lane stories:
    - `AZAHAR-V1-01`
    - `AZAHAR-V1-02`
    - `AZAHAR-V1-04`
  - Docs lane stories:
    - `AZAHAR-V1-03`
- Conflict-avoidance notes:
  - keep `AZAHAR-V1-01` focused on managed defaults + assisted QSettings convergence only
  - keep `AZAHAR-V1-02` focused on wrapper/runtime cleanup, package metadata cleanup, and preservation of existing exit hooks
  - keep `AZAHAR-V1-04` focused on managed deadzone defaults + assisted convergence only
  - land docs after the `AZAHAR-V1-02` removal diff is fixed
- Merge order constraints:
  - `AZAHAR-V1-01` can merge independently before mouse-bridge work
  - `AZAHAR-V1-02` should merge before the docs cleanup if the work is split
  - `AZAHAR-V1-04` should merge after whichever Azahar profile/convergence story most recently touched the same managed QSettings keys

## Completion Criteria
- All milestone acceptance criteria are complete.
- Story contracts are implemented in scoped PRs.
- Required tests are added/updated and documented.
- Documentation updates are complete and implementation-accurate.
- Required quality gates pass with the repo-local virtual environment:
  - `./venv/bin/python -m ruff format --check .`
  - `./venv/bin/python -m ruff check .`
  - `./venv/bin/python -m mypy src`
  - `./venv/bin/python -m pytest . -p no:cacheprovider`
