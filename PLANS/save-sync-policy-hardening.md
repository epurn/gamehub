# PLAN: save-sync-policy-hardening

## Context
- Current save sync behavior allows `bidirectional + prefer_server` to auto-download over divergent local saves when lineage is missing or ambiguous.
- That behavior is deterministic, but it does not match the expected operator model for a default configuration where both-side drift should surface as a conflict instead of silently converging to server.
- The server write path is already conflict-safe; this work is client policy hardening only.

## Goals
- Make new or unspecified save-sync configs default to explicit manual conflict handling.
- Keep offline reconnect recovery unchanged so newer offline local saves still upload on reconnect.
- Ensure every bidirectional `local != remote` classification path is policy-driven instead of silently defaulting to download.
- Preserve `prefer_server` and `prefer_local` as explicit opt-in operator choices.

## Non-Goals
- Removing `prefer_server`.
- Changing server save APIs or save-state schema.
- Redesigning the manual conflict-resolution UX beyond the existing `doctor saves` phase-2 flow.

## Scope
- `src/gamehub_cli/common/config.py`
- `src/gamehub_cli/common/save_sync.py`
- `tests/test_cli_config_state.py`
- `tests/test_planner.py`
- `tests/test_shortcut_save_session.py`
- `README.md`
- `docs/config-and-state.md`
- `docs/cli-sync.md`

## Acceptance Criteria
- Missing or invalid `[save_sync].conflict_policy` normalizes to `manual`.
- `bidirectional` save classification returns policy-specific results for lineage-missing and lineage-ambiguous drift instead of falling back to unconditional download.
- Managed pre-launch save sync preserves the new manual-default behavior because it reuses the shared classifier.
- Offline reconnect timestamp recovery remains unchanged.
- Docs clearly describe the new default and the overwrite/conflict matrix for `download`, `bidirectional/manual`, `bidirectional/prefer_server`, and `bidirectional/prefer_local`.
