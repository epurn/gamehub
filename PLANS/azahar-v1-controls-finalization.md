# PLAN: azahar-v1-controls-finalization

## Context
- Background: `v1.6.0` shipped Azahar runtime bootstrap, managed controller profiles, and platform-specific exit-hook support, but three Azahar control gaps still block a polished "final v1" experience.
- Current behavior: GAMEHUB-managed Azahar sessions still lean on Azahar's platform-native quit shortcut instead of the repo's `Esc` exit/menu convention, the wrapper only handles `Start+Select` exit behavior, and joystick sensitivity is high enough that some managed controller paths can show ghost input without extra deadzone tuning.
- Trigger/problem statement: finalize Azahar control behavior so quitting matches the rest of the emulator stack, Xbox controllers can drive Azahar touch input without upstream emulator changes, and managed stick deadzones are reasonable enough to stop ghost inputs by default.

## Goals
- Normalize the managed Azahar quit shortcut to `Esc`.
- Add Xbox-controller mouse simulation for Azahar sessions: right stick moves the pointer and `R2` emits left click.
- Normalize managed Azahar stick deadzones so ghost inputs stop without per-title operator tuning.
- Keep Azahar pointer/touch config preservation-first; GAMEHUB should bridge controller input into ordinary OS mouse events instead of trying to invent unsupported native Azahar bindings.
- Fail open when the mouse bridge cannot initialize so launches still work without destructive fallback behavior.

## Non-Goals
- Patching or forking Azahar upstream.
- Changing non-Azahar emulator bindings or hotkey policy.
- Broad Steam Input template redesign.
- Adding non-Xbox controller-family support in the first pass unless it falls out naturally from the chosen backend without extra policy.

## Constraints
- Windows and macOS local development support are required; Linux support must explicitly call out X11/Wayland/Steam Deck behavior before shipping defaults.
- Reuse existing atomic/backup/logged mutation paths for any `qt-config.ini` rewrite.
- Keep wrapper/runtime logic in the Azahar controller/runtime modules; do not move emulator-specific policy into `common/`.
- Avoid dependency/lockfile/packaging changes unless the mouse-bridge spike proves a clear cross-platform win and a packaging path for local CLI + packaged shortcuts.
- Do not regress the existing Azahar `Start+Select` exit hook behavior on Windows, macOS, or Linux.

## Contract Surface
- Existing contracts touched:
  - managed Azahar profile defaults in `src/gamehub_cli/controllers/profiles.py`
  - assisted Azahar QSettings convergence in `src/gamehub_cli/controllers/convergence.py`
  - Azahar controller apply path in `src/gamehub_cli/controllers/apply_azahar.py`
  - Azahar managed shortcut runtime flow in `src/gamehub_cli/shortcuts/runtime.py`
  - platform-specific Azahar controller helpers in `src/gamehub_cli/controllers/azahar_exit_hook.py`
  - Xbox controller discovery metadata in `src/gamehub_cli/controllers/detection.py`
- New/updated contract artifacts:
  - optional Azahar mouse-bridge env toggles and tuning knobs if the implementation needs them
  - optional Azahar deadzone defaults or managed tuning knobs if ghost-input testing proves they are required
  - operator docs covering Azahar `Esc` quit, mouse simulation behavior, and platform caveats
- Cross-boundary implications:
  - none; this is CLI-only work

## Research Notes
- Repo-grounded implementation note: Azahar pointer/touch keys are already preservation-first in the apply path, and existing tests prove that `touch_device`/pointer keys survive managed controller rewrites. That makes wrapper input -> OS mouse output the safest v1 design.
- Repo-grounded implementation note: existing Steam Deck template seeds already carry explicit stick deadzone values, which suggests the managed Azahar path should converge deterministic deadzone defaults instead of assuming zero-deadzone joystick behavior is stable across controllers.
- Library candidate for controller polling: [pygame._sdl2.controller](https://www.pygame.org/docs/ref/sdl2_controller.html) exposes normalized controller buttons/axes, including `RIGHTX`, `RIGHTY`, and trigger axes, across common Xbox-class pads.
- Library candidate for mouse output: [pynput.mouse.Controller](https://pynput.readthedocs.io/en/latest/mouse.html) can move the pointer and emit click events from Python on macOS, Windows, and Xorg Linux.
- Linux caveat: [pynput platform limitations](https://pynput.readthedocs.io/en/latest/limitations.html) document X11 dependence by default and only limited Xwayland behavior under Wayland, so Linux/Deck validation is a hard gate rather than an assumption.
- Linux-native fallback candidate: [python-evdev/uinput](https://python-evdev.readthedocs.io/en/latest/) can read and inject mouse events on Linux, but it is Linux-only and depends on `/dev/input` and `/dev/uinput` availability.
- Recommendation: land the `Esc` shortcut story independently. For mouse simulation, explicitly choose between a dependency-backed bridge (`pygame` + `pynput`) and native per-OS emitters; do not silently ship partial support as the default.

## Milestones
1. M1: Converge Azahar quit shortcut state to `Esc` through existing managed/default + assisted QSettings paths.
2. M2: Finalize the Azahar mouse-bridge backend strategy, including platform gating, failure mode, and packaging implications.
3. M3: Implement Xbox right-stick mouse + `R2` left-click behavior, wire docs/tests, and preserve fail-open wrapper behavior.
4. M4: Normalize managed Azahar stick deadzones so ghost inputs stop without manual deadzone tuning.

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
- Goal: add a fail-open Azahar mouse bridge for Xbox controllers at launch time.
- Acceptance Criteria (deterministic):
  - [ ] During managed Azahar launches, when an Xbox controller is detected and the host backend is supported, right-stick input drives OS mouse movement for the launch session only.
  - [ ] `R2` emits a left-click press/release sequence for the same session, with debounce/hold behavior defined and covered by tests.
  - [ ] The bridge is scoped to Azahar launches, shuts down cleanly on process exit, and does not interfere with the existing Azahar exit hook.
  - [ ] When the controller/backend is unavailable or unsupported, launch continues without synthetic mouse input and the wrapper fails open.
  - [ ] Linux support is either verified for the chosen default backend or explicitly gated off by host detection; there is no hidden partial Wayland/Deck support claim.
- Non-Goals:
  - non-Azahar mouse emulation
  - non-Xbox controller policy expansion
  - background daemons or resident services
- Tests Required (exact locations / names):
  - `tests/test_shortcut_runtime.py::test_run_target_with_optional_azahar_mouse_bridge_starts_for_supported_xbox_controller`
  - `tests/test_shortcut_runtime.py::test_run_target_with_optional_azahar_mouse_bridge_fails_open_when_backend_unavailable`
  - `tests/test_shortcut_runtime.py::test_run_target_with_optional_azahar_mouse_bridge_coexists_with_exit_hook`
  - `tests/test_azahar_exit_hook.py::test_azahar_mouse_bridge_translates_right_stick_and_r2`
  - `tests/test_controller_detection.py::test_detect_xbox_controllers_returns_stable_slot_order_for_azahar_mouse_bridge`
- PR Title Template: `[AZAHAR-V1-02] CLI: add Azahar Xbox mouse bridge`
- Rollback Risk: Medium

### STORY AZAHAR-V1-03
- Type: DOCS
- Goal: document the Azahar control changes and operator-visible platform caveats.
- Acceptance Criteria (deterministic):
  - [ ] `docs/config-and-state.md` documents Azahar `Esc` quit behavior, mouse-bridge env toggles, and any platform gating.
  - [ ] `docs/client-install.md` adds a concise verification flow for Azahar right-stick pointer movement, `R2` click, and `Esc` quit behavior.
  - [ ] The next release-facing checklist/notes entry mentions the new Azahar control expectations if the behavior ships in a release branch.
- Non-Goals:
  - broad doc rewrites outside Azahar/operator flows
- Tests Required (exact locations / names):
  - none
- PR Title Template: `[AZAHAR-V1-03] Docs: document Azahar quit and mouse bridge behavior`
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
  - keep `AZAHAR-V1-02` focused on wrapper/runtime detection and mouse-emission helpers
  - keep `AZAHAR-V1-04` focused on managed deadzone defaults + assisted convergence only
  - land docs after the backend decision in `AZAHAR-V1-02` is fixed
- Merge order constraints:
  - `AZAHAR-V1-01` can merge independently before mouse-bridge work
  - `AZAHAR-V1-04` should merge after whichever Azahar profile/convergence story most recently touched the same managed QSettings keys
  - `AZAHAR-V1-03` should merge after whichever stories change shipped behavior

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
