# Steam Deck Controller Compatibility Audit and Remediation Plan (Deep-Dive)

## Why this revision

This revision addresses additional constraints:

1. We should **avoid relying on Steam Input profiles** when a native emulator mapping can preserve Steam Deck functionality.
2. For Azahar specifically, we need a **hybrid** model that keeps controller buttons stable while preserving trackpad-as-mouse/touch workflows.
3. Steam profile automation is considered a **high-risk, large-scope change** and should be excluded unless there is no realistic alternative.
4. Steam Deck should still follow the **existing sync/profile policy model** in this change (no cross-platform default-policy redesign in-scope).

---

## Executive summary

The safest path is a **native-first, Steam-profile-last** strategy:

- Keep GAMEHUB's current profile application pipeline and wrapper model.
- Add **Deck-preserving merge behavior** inside existing profile application rather than introducing new global policy defaults.
- For Dolphin (Wii): prefer direct emulator-native pointer/IR mappings over Steam template indirection.
- For Azahar: implement a **button-managed + pointer-preserved hybrid** merge policy that does not clobber existing mouse/touch mappings.
- Treat Steam Input templates as a documented **break-glass fallback only**.

This preserves Deck-specific functionality while minimizing architecture churn and avoiding behavior fragmentation.

---

## Current-state audit in GAMEHUB

### 1) Controller profile pipeline is write-oriented at launch
- Launch flow can apply profile files (`kbm`, `xbox_1p`, `xbox_2p`) before emulator start.
- Dolphin and Azahar mappings are rewritten into emulator config files from managed profile templates.

### 2) Dolphin behavior today
- GAMEHUB writes managed sections for:
  - `Dolphin.ini` core control mode keys
  - `GCPadNew.ini`
  - `WiimoteNew.ini`
  - `Hotkeys.ini`
- Linux device assignment is dynamically overridden to `evdev/...`, `SDL/...`, or pointer fallbacks.

### 3) Azahar behavior today
- GAMEHUB applies managed `qt-config.ini` profile keys and normalizes SDL GUID/port identity.
- Existing SDL mappings are preserved in some cases, but profile-owned keys are still actively rewritten.

### 4) Steam Deck controller detection
- Linux detection explicitly includes Steam Deck controller aliases (`Steam Deck Controller`, `Steam Virtual Gamepad`, `Neptune`, etc.), so Deck commonly lands in controller profiles rather than `kbm`.

### 5) Existing docs already indicate Steam Input-template limitations for N3DS
- Current docs acknowledge manual Steam template copying paths when template mode is used.

**Implication:** current behavior is robust for consistency, but rewrite-heavy flows can still erase Deck-tuned pointer/mouse/trackpad workflows.

---

## External research (high-confidence sources)

## A) Steam Input can change what the game sees
Steamworks docs indicate opting controllers into Steam Input causes those controllers to use Steam Input behavior instead of their standard gamepad protocols. This is excellent for portability, but it can alter device identity and input semantics from the emulator's perspective.

Reference:
- Steamworks Steam Input docs (`getting_started_for_devs`):
  - https://partner.steamgames.com/doc/features/steam_controller/getting_started_for_devs

### Why this matters here
Your concern is correct: if we lean on Steam profiles heavily, emulator-visible device identity can shift from direct SDL/evdev paths to Steam-mediated behavior, complicating deterministic per-emulator config logic.

## B) EmuDeck precedent is useful but should be used narrowly
EmuDeck documents Steam Input profile models and radial/action-set workflows to standardize hotkeys where emulators lack native controller-hotkey support.

Reference:
- EmuDeck hotkeys/profile guidance:
  - https://raw.githubusercontent.com/EmuDeck/emudeck.github.io/main/docs/controls-and-hotkeys/steamos/hotkeys.md

### Why this matters here
This confirms Steam Input profiles are a practical fallback pattern, but not proof they should be the default for GAMEHUB. For your goals, it supports a **fallback-only** role.

## C) Dolphin supports native per-device/per-profile controller configuration
Dolphin's controller documentation emphasizes selecting devices, assigning controls directly, and using profiles for save/load.

Reference:
- Dolphin controller configuration guide:
  - https://dolphin-emu.org/docs/guides/configuring-controllers/

### Why this matters here
For Wii pointer use-cases, native Dolphin mappings are realistic and should be preferred over Steam template indirection whenever possible.

## D) Azahar input model supports touch-from-button and motion/touch channels, but pointer semantics remain nuanced
Azahar source (Citra lineage) includes:
- `configure_touch_from_button` (button -> fixed touch coordinates mappings)
- motion/touch config flows (`configure_motion_touch`)

References:
- Azahar source tree (touch-from-button and motion/touch config widgets):
  - https://github.com/azahar-emu/azahar

### Why this matters here
This supports your concern: there is no single clean "bottom screen pointer" abstraction equivalent to native mouse-like trackpad behavior across all setups; a hybrid policy is appropriate.

## E) Flatpak runtime identity and config location differences are real
Flatpak conventions explain why runtime/host config identity can diverge (`~/.var/app/<id>/...`), reinforcing that identity normalization should be conservative and minimally destructive.

Reference:
- Flatpak conventions:
  - https://docs.flatpak.org/en/latest/conventions.html

---

## Design principles for this remediation

1. **Native-first:** Prefer emulator-native mappings over Steam template profiles.
2. **Preserve Deck affordances:** Never clobber mappings that provide trackpad/mouse/pointer utility unless explicitly requested.
3. **Stay in existing policy model:** No broad cross-platform default policy redesign in this change.
4. **Minimize churn:** Reduce writes to only required keys; avoid whole-profile replacement where merge is possible.
5. **Fallback clarity:** Steam profile paths are explicit, opt-in, and wrapper-aware only when no realistic native alternative exists.

---

## Concern-by-concern resolution plan

## Concern 1: Steam shortcuts can change controller identity

### Plan
- Keep wrappers, but add a **device-identity guardrail**:
  - detect when launch path is Steam/Flatpak-wrapped and avoid unnecessary remaps of emulator device keys.
- For Dolphin on Deck:
  - preserve existing `WiimoteNew.ini` device roots when already valid.
  - avoid forcing device rebind if existing mapping is pointer-capable and functional.

### Concrete implementation tasks
- Add merge helper for Dolphin managed sections:
  - managed hotkeys stay managed;
  - device keys become conditional (only set when missing/invalid).
- Add telemetry line item in controller-launch output:
  - `device_identity_mode=preserve|rebind`

### Acceptance criteria
- Repeated sync + launch does not change a working Deck Wii pointer mapping.
- External controller attach/detach still recovers gracefully.

---

## Concern 2: Azahar needs hybrid button + pointer handling

### Plan
Implement **hybrid apply** for Azahar profile writes:
- GAMEHUB manages canonical gamepad buttons and sticks.
- GAMEHUB preserves existing pointer/touch/mouse-relevant entries whenever present.
- GUID/port normalization still applies to SDL tokens, but semantic pointer mappings are not overwritten.

### Concrete implementation tasks
- Add Azahar key classifier:
  - `managed_button_keys`: face/dpad/start/select/shoulders/sticks/circle_pad/c_stick
  - `preserve_pointer_keys`: touch/mouse/pointer/touch-from-button related and unknown profile keys
- During apply:
  - if key exists and class is `preserve_pointer_keys`, keep existing;
  - if key exists with non-SDL engine and class is pointer-related, keep existing;
  - still normalize GUID/port inside SDL-managed button keys.

### Acceptance criteria
- Existing trackpad-as-pointer behavior survives profile apply.
- Controller face/dpad buttons remain deterministic.
- No GUID duplication/churn regressions in Flatpak/non-Flatpak paths.

---

## Concern 3: Avoid Steam profiling changes if possible

### Plan
- Explicitly mark Steam profile integration as **out-of-scope for this implementation phase**.
- Add a fallback decision table only for documentation/operator guidance.

### Fallback decision table (documentation-only)
Use Steam profile fallback **only if all are true**:
1. Emulator-native mapping cannot express required behavior.
2. Wrapper can preserve expected exit/hotkey behavior.
3. Behavior is validated against Deck built-in + one external controller.
4. Fallback is scoped per emulator and opt-in.

If any condition fails: remain native-first.

---

## Concern 4: Keep existing sync/profile policy model for now

### Plan
- Do **not** introduce a global new default profile policy in this change.
- Implement changes as merge semantics inside current profile apply paths.
- Keep profile selection (`kbm`/`xbox_1p`/`xbox_2p`) and existing sync flow intact.

### Acceptance criteria
- No behavior contract change for non-Deck platforms.
- Deck improvements are additive/preservational, not policy-breaking.

---

## Implementation blueprint (phased, code-ready)

### Phase 0 — Instrumentation + baselines
- Add `controller-launch --audit` (or equivalent dry-run diagnostic) showing:
  - files touched
  - keys changed
  - keys preserved due to Deck guardrails
- Capture baseline fixtures:
  - Dolphin Wii pointer-heavy configs
  - Azahar configs with mixed SDL + mouse/touch behavior

### Phase 1 — Dolphin preserve-merge
- Replace unconditional device key overrides with conditional merge logic.
- Keep hotkeys managed; make device/pointer config preservation-first on Deck.

### Phase 2 — Azahar hybrid merge
- Implement managed vs preserved key classes.
- Keep GUID/port normalization only in managed SDL keys.
- Preserve pointer/touch mappings and unknown custom keys.

### Phase 3 — Validation + rollout
- Validate matrix:
  - Steam Deck built-in only
  - Steam Deck + external pad
  - Linux desktop + Xbox pad
  - Windows + XInput pad
- Emulators:
  - Dolphin (GC + Wii pointer workflows)
  - Azahar (button + bottom-screen interaction)
- Launch vectors:
  - direct
  - Steam shortcut
  - wrapper path

No Steam template automation in scope for this rollout.

---

## Test strategy (required before enabling by default)

1. **Idempotency tests**
   - two consecutive applies produce zero diff on preserved keys.
2. **Regression tests for existing behavior**
   - existing controller profile tests stay green.
3. **Deck-specific preservation tests**
   - fixture with pre-existing Dolphin pointer mapping remains unchanged.
   - fixture with Azahar pointer/touch mapping remains unchanged while buttons normalize.
4. **GUID/port normalization tests**
   - verify normalization still occurs for SDL button keys in both Flatpak and non-Flatpak cases.
5. **Wrapper compatibility tests**
   - verify exit-hook behavior still works after preservation logic.

---

## Risks and mitigations

- **Risk:** Over-preservation can leave broken legacy mappings untouched.
  - **Mitigation:** preserve only when mapping parses as valid; otherwise backfill managed defaults.

- **Risk:** Under-preservation regresses Deck pointer workflows.
  - **Mitigation:** explicit key classifiers + fixture-based tests for pointer-heavy configs.

- **Risk:** Steam launch path still alters perceived controller identity unexpectedly.
  - **Mitigation:** avoid Steam profile reliance; preserve emulator-native device mapping when already functional.

---

## Recommended decision

Approve implementation of:
- Phase 0 (instrumentation),
- Phase 1 (Dolphin preserve-merge),
- Phase 2 (Azahar hybrid merge),
- plus the defined test matrix.

Defer Steam Input template/profile automation entirely unless post-rollout evidence shows a hard native limitation with no realistic alternative.

This matches your priorities: preserve Deck-specific functionality, avoid Steam-profile dependence, and keep existing cross-platform sync/profile policy intact for this change.


## Additional implementation notes (touchpad-as-mouse hardening)

To improve the practical Deck experience without Steam template automation, the implementation now applies two Deck-aware native defaults when safe:

1. **Dolphin Wii (Deck + controller profile on Linux):**
   - If an existing `Wiimote1` pointer mapping already uses `Cursor X/Y` expressions, preserve it.
   - Otherwise, backfill Wii IR to mouse cursor axes (`Cursor X/Y`) and add `Click 0` to `Buttons/B` so a mapped click button can drive pointer interactions.
   - This keeps right-stick mappings out of the critical path for titles that expect Wii pointer behavior while still allowing user customization.

2. **Azahar (Deck + controller profile on Linux):**
   - Backfill `profiles\1\touch_device="engine:emu_window"` when absent so host mouse input remains accepted for touchscreen interaction.
   - Backfill `profiles\1\use_touch_from_button=false` when absent to avoid unintentionally replacing pointer-style workflows.

These defaults are grounded in Azahar config behavior from upstream source (`touch_device`, `use_touch_from_button`, and touch-from-button map handling in `citra_qt/configuration/config.cpp`) and Dolphin's documented native controller mapping model.
