# Steam Deck Support Implementation Plan

## Goal
Ship a first-class Steam Deck target that is opinionated for SteamOS + Flatpak + Game Mode, while preserving existing Windows and Bazzite behavior.

## Current-state notes from repository
- Steam Deck has a template config, but it is marked untested.
- Linux controller profile selection currently pivots only on Xbox controller count (`0 -> kbm`, `1 -> xbox_1p`, `2+ -> xbox_2p`).
- Flatpak runtime/config roots are already modeled for RetroArch/PCSX2/Dolphin/Azahar under `~/.var/app/<app-id>/...`.
- Linux launch wrappers already include Flatpak `--file-forwarding`, device flags, and Select+Start exit hooks for Dolphin/Azahar.

## Internet research requirement and status
- Attempted to fetch SteamOS/Flatpak reference docs from public sources, but outbound web requests from this environment returned `403 CONNECT tunnel failed`.
- Because of that limitation, this plan uses SteamOS/Flatpak conventions already reflected in the codebase plus well-known Steam Deck defaults and explicitly calls out validation checkpoints that must be run on real hardware.

## Scope
### In scope
1. Steam Deck environment detection + path/runtime hardening.
2. Default input behavior for Steam Deck built-in controller.
3. Steam Deck Game Mode compatibility and UX.
4. Regression coverage and rollout guardrails.

### Out of scope (separate follow-up)
- Touchscreen/gyro/touchpad advanced profile authoring.
- Per-game Steam Input template automation for every emulator family.

## Target platform assumptions to verify on hardware
1. Primary user is `deck`, home is `/home/deck`.
2. Steam userdata commonly at `/home/deck/.local/share/Steam/userdata`.
3. Flatpak user data/config under `/home/deck/.var/app/<app-id>/{data,config}`.
4. Flatpak exported binaries at `/home/deck/.local/share/flatpak/exports/bin`.
5. Game Mode launches under gamescope/Steam runtime and may differ from Desktop Mode env vars and PATH.

## Workstream A — Platform detection and Steam Deck profile selection
### A1. Add explicit Steam Deck host detection signal
- Implement a `steamdeck` host flavor detector independent of generic Linux/Bazzite detection.
- Detection signals (ordered, defensive):
  - Existing config override (`platform = steamdeck`) if present.
  - Presence of SteamOS markers (to be finalized during hardware validation).
  - Fallback to current Linux behavior if uncertain.

**Deliverable:** Deterministic host flavor (`windows`, `linux`, `bazzite`, `steamdeck`) used by sync/controller decision code.

### A2. Add Steam Deck-specific controller defaulting rules
- Introduce a Steam Deck-first profile resolution branch:
  - Built-in Deck controller detected, no external Xbox: default to new `steamdeck_builtin` profile.
  - External Xbox present: choose `xbox_1p`/`xbox_2p` according to controller count rules.
  - If Deck built-in + one Xbox: prefer explicit priority policy (recommend `steamdeck_builtin` for P1, Xbox as P2).
- Keep existing Windows/Bazzite defaults untouched unless explicitly configured.

**Deliverable:** Platform-aware profile resolver with backward compatibility.

### A3. Add controller profile assets for Steam Deck
- Seed a new default profile set:
  - `steamdeck_builtin` (primary profile)
  - Optional `steamdeck_builtin_plus_xbox` (if mixed mode is needed)
- Ensure non-destructive seeding behavior is retained (`--reseed-profiles` still controls overwrite).

**Acceptance criteria:**
- Fresh Steam Deck sync with no external controller no longer lands on `kbm` by default.

## Workstream B — SteamOS/Flatpak filesystem and emulator config resolution
### B1. Audit and formalize Steam Deck path matrix
Create a single source-of-truth matrix in docs and code comments for:
- Steam roots and userdata lookup order.
- Flatpak export binary locations.
- Emulator config/data locations for RetroArch/PCSX2/Dolphin/Azahar.
- Optional SD-card/library alternate roots if detected.

### B2. Harden path probes for Game Mode environment
- Ensure resolvers do not rely on Desktop Mode-only env vars.
- Use explicit fallback order with existence checks and telemetry logs.
- Confirm launch wrappers pass host ROM paths via Flatpak file forwarding in Game Mode.

### B3. Validate read/write behavior in immutable-style SteamOS constraints
- Confirm all writes target user-writable locations (`/home/deck/...` and `~/.var/app/...`).
- Avoid assumptions requiring mutable system paths.

**Acceptance criteria:**
- Dry sync and full sync can discover emulator configs from Flatpak locations on Steam Deck without manual path overrides.

## Workstream C — Game Mode compatibility and lifecycle behavior
### C1. Launch behavior under Game Mode
- Verify shortcut generation works identically when triggered from Game Mode UI.
- Validate command lines for each emulator in Game Mode (especially Dolphin/Azahar wrappers).

### C2. Exit hook behavior with Steam Deck built-in input stack
- Test Select+Start hook behavior from built-in controls.
- Confirm hook does not conflict with Steam Input chords.
- Add config toggles/documented escape hatch when conflicts occur.

### C3. Steam reopen/focus return behavior
- Validate post-sync/reopen logic in Game Mode.
- If current reopen fallback is desktop-centric, add Steam Deck-specific reopen command order.

**Acceptance criteria:**
- Launch/exit/reopen loop works end-to-end in Game Mode for at least one title per emulator family.

## Workstream D — Test plan and rollout
### D1. Automated tests
Add/extend tests for:
- Steam Deck host detection.
- Platform-aware controller profile selection.
- Steam Deck path candidate ordering for Steam + Flatpak emulator roots.
- Backward-compat assertions proving Bazzite/Windows behavior unchanged.

### D2. Manual hardware validation matrix
Run on real Steam Deck in both Desktop Mode and Game Mode:
1. Fresh install + first sync.
2. Controller defaults (built-in only, built-in + 1 Xbox, 2 Xbox).
3. Emulator launch via Steam shortcuts.
4. Exit hook behavior and reopen behavior.
5. Regression sanity against a Bazzite box using same Flatpak app set.

### D3. Staged rollout strategy
- Phase 1: feature flag / opt-in (`steamdeck` platform override).
- Phase 2: auto-detect enabled with conservative fallback.
- Phase 3: default docs and template promoted to “validated”.

## Proposed execution order (2-week sample)
### Week 1
1. Implement host detection + profile resolver updates.
2. Add `steamdeck_builtin` profile assets + unit tests.
3. Path matrix audit and resolver hardening.

### Week 2
4. Game Mode lifecycle validation and bug fixes.
5. Full regression pass (Windows/Bazzite/Steam Deck).
6. Documentation updates + rollout toggle.

## Risk register
1. **Steam Input abstraction mismatch** can hide physical controller identity.
   - Mitigation: detection fallback chain + explicit user override.
2. **Game Mode env differences** can break command/path assumptions.
   - Mitigation: hardcoded candidate paths + robust fallbacks + integration test logs.
3. **Flatpak sandbox/device permission variances** across app versions.
   - Mitigation: keep wrapper arguments explicit and version-tested.
4. **Behavior drift between SteamOS releases.**
   - Mitigation: path probes are additive, not exclusive; avoid brittle single-path assumptions.

## Definition of done
- Steam Deck no-controller-external scenario defaults to built-in controller profile.
- Steam Deck + Xbox scenarios are deterministic and documented.
- Game Mode launch + exit + reopen flow validated on hardware.
- Steam Deck template and CLI docs updated from “untested” to validated with explicit known limitations.
