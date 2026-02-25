# Linux Support Audit (Bazzite + Steam Deck + General Linux)

## Scope
This audit reviews Linux-specific client behavior with three runtime paths in mind:

1. **Bazzite** (validated target)
2. **SteamOS / Steam Deck** (validated target)
3. **General Linux distros** (currently marked untested in release matrix)

The goal is to identify:
- what is already reusable/stable,
- what remains risky for Fedora/Ubuntu-like hosts,
- where code is duplicated across the three paths,
- and concrete best-practice actions to make Linux support functional and maintainable.

---

## Current Reusable Linux Foundation (Good news)

The codebase already has a strong shared Linux baseline that Bazzite/Steam Deck/general Linux all consume:

- **Shared Linux path helpers and Flatpak IDs** in `common/platform_paths.py`.
  - Central constants for RetroArch/PCSX2/Dolphin/Azahar Flatpak IDs.
  - Shared Flatpak/native path detection helpers.
- **Shared emulator install strategy** in `emulators/installer.py` + `emulators/install_linux.py` + `emulators/install_flatpak.py`.
  - One flow selects backend (`auto|dnf|apt|flatpak|command|none`) and distro-aware behavior.
  - Immutable distro hints (Bazzite/SteamOS/etc.) already force/prefer Flatpak in auto mode.
- **Shared runtime target resolution** in `firmware/targets.py`.
  - Linux runtime/user/config directory discovery is centralized per emulator.
- **Shared Steam lifecycle handling** in `steam/lifecycle.py`.
  - Linux Steam process detection, close/wait/reopen logic is already common.
- **Steam Deck-only features are isolated** under `steam/deck_templates/*` and gated in `sync/steam_stage.py`.
  - This is good separation: Deck-specific behavior does not fully fork Linux behavior.

**Assessment:** The project is not split into three independent Linux implementations; it is already mostly one Linux implementation with selective Steam Deck augmentation.

---

## Functional Gaps Blocking “Supported Linux” Confidence

### 1) Validation gap (largest blocker)
General Linux is mostly an **evidence/testing gap**, not a total implementation gap.

What is missing:
- Repeatable end-to-end validation runs for Fedora and Ubuntu with both native and Flatpak Steam layouts.
- Explicit CI (or scripted local matrix) proving shortcut creation, collections, artwork copy, firmware deploy, and Steam relaunch for non-Bazzite Linux.

### 2) Steam root/path variability risk
Linux Steam location handling spans multiple known roots, but distro packaging differences remain high-risk:
- native Steam vs Flatpak Steam,
- different legacy symlink layouts (`.steam/root`, `.steam/steam`, `.local/share/Steam`),
- possible desktop-session relaunch differences.

Action needed: convert path assumptions into a validation matrix and collect known-good host profiles.

### 3) Emulator install backend confidence for non-immutable distros
Current behavior supports `apt`, `dnf`, `flatpak`, and custom command, but release confidence needs:
- tested package names per distro release,
- clear fallback behavior when packages are unavailable,
- explicit docs for recommended backend by distro class.

### 4) Controller support mismatch across Linux flavors
Matrix currently says external Xbox is unsupported for “other Linux.”
Given existing Linux controller parsing and launch wrapper behavior, this likely needs:
- distro/session-level controller validation,
- documented limitations (if any) by runtime and transport (USB/Bluetooth/dongle).

---

## Duplication Audit (where to improve reuse)

Even with strong shared architecture, there are repeated patterns across Bazzite/Steam Deck/general Linux paths that should be unified further.

### A) Repeated “Linux + Flatpak emulator” branch blocks in shortcut building
In `sync/steam_stage.py`, Dolphin/PCSX2/Azahar each have dedicated Flatpak branch blocks with very similar structure:
- detect Linux + emulator + Flatpak command,
- build a `SteamShortcutSpec` with `flatpak run --file-forwarding ...`,
- optionally wrap for controller launch,
- append and continue.

**Refactor target:** introduce a table-driven `FlatpakShortcutBuilder` helper keyed by emulator family.

Benefits:
- one place to define per-emulator flags (`--device=all`, `-u`, `-fullscreen`, etc.),
- fewer branch-specific bugs,
- easier to add future Linux emulators without copy/paste.

### B) Repeated Linux Flatpak preference checks across modules
Flatpak preference/identity logic appears in multiple places:
- install backend selection (`install_flatpak.py`, `installer.py`),
- runtime dir resolution (`firmware/targets.py`),
- launch template/shortcut selection (`sync/steam_stage.py`).

**Refactor target:** shared “Linux runtime profile” resolver object in `common/`.

Proposed shape:
- `LinuxRuntimeProfile` containing:
  - distro hints,
  - immutable/flatpak preference,
  - per-emulator resolved runtime mode (`flatpak|native`),
  - canonical paths for user/config/system roots.

Then all stages consume this same resolved profile.

### C) Repeated “detect Deck -> special behavior” checks
Deck checks are repeated in multiple stage points (`build_shortcut_specs`, template sync, override repair).

**Refactor target:** resolve platform capability flags once per sync run:
- `is_linux`, `is_steam_deck`, `apply_deck_templates`, `allow_desktop_config_default`, etc.

Then pass a typed context/capabilities object into stage functions.

### D) Config template duplication (linux vs bazzite vs steamdeck)
The three templates are mostly the same structure with small default differences.

**Refactor target:** generate templates from a shared base (scripted templating or documented inheritance model) to avoid divergence and stale comments.

---

## Best-Practice Plan to Make Linux “Supported”

## Phase 1 — Evidence first (no risky behavior changes)
1. Build a Linux validation matrix document with minimum scenarios:
   - Fedora Workstation + native Steam,
   - Ubuntu LTS + native Steam,
   - Fedora/Ubuntu + Flatpak Steam,
   - Bazzite (control baseline),
   - Steam Deck Desktop Mode (control baseline).
2. For each scenario, validate:
   - Steam close -> backup -> atomic write -> reopen,
   - shortcut/collection idempotency across repeated syncs,
   - firmware target placement per emulator,
   - artwork mapping/appid behavior,
   - controller launch wrapper behavior for PCSX2/Dolphin/Azahar.
3. Promote matrix results into release docs and compatibility table.

## Phase 2 — Reuse-focused refactors
1. Extract table-driven Flatpak shortcut builders from `steam_stage.py`.
2. Introduce shared Linux runtime profile resolver under `common/`.
3. Replace repeated Deck gates with one platform capabilities object created once in orchestration/stage entry.
4. Keep existing behavior identical; add unit tests for refactor parity.

## Phase 3 — Policy hardening
1. Add CI-targeted Linux smoke jobs (at least Ubuntu + Fedora containers/VM runners as available).
2. Require Linux regression checks before changing:
   - Steam lifecycle logic,
   - launch template normalization,
   - firmware target resolution,
   - controller detection/wrapping.
3. Keep “best effort” host-specific fallbacks, but always report actionable diagnostics in verbose mode.

---

## Suggested Story Breakdown

1. **STORY-A:** Linux validation matrix + scripted smoke checklist (docs + scripts only).
2. **STORY-B:** `steam_stage` Flatpak shortcut builder refactor (no behavior change).
3. **STORY-C:** Shared Linux runtime profile resolver and consumers (`installer`, `targets`, `steam_stage`).
4. **STORY-D:** Template deduplication pipeline (`config.linux`, `config.bazzite`, `config.steamdeck`).
5. **STORY-E:** Linux controller support validation and matrix policy update.

---

## Conclusion
The path to “functional Linux support” is primarily about **formal validation + targeted dedup refactors**, not rewriting Bazzite/Steam Deck logic.

The repo already contains substantial reusable Linux foundations; we should preserve those and converge remaining Linux branches onto shared helpers rather than adding new distro-specific forks.
