# PLANS Workflow (AI-First)

`PLANS/` is the authoritative planning location for new GAMEHUB work.

## Why this exists
- Codex should be runnable with one-liner prompts.
- Planning must be deterministic so multiple Codex tasks can run in parallel safely.
- Every implementation PR should map to a scoped STORY contract.

## Workflow
1. Copy `PLANS/_template.md` to a new plan file (example: `PLANS/steamdeck-controller-hardening.md`).
2. Fill in Context, Goals, Constraints, Contract Surface, Milestones, and Story Contracts.
3. Break work into independently mergeable STORY contracts with strict scope boundaries.
4. Prompt Codex with a one-liner:
   - `Implement STORY <ID> from PLANS/<feature>.md`
5. Ensure PR title/body references the STORY ID and acceptance criteria.

## Story contract writing rules
- Keep acceptance criteria deterministic and testable.
- Keep non-goals explicit to prevent scope creep.
- Include required tests and expected command(s).
- Use `CROSS-BOUNDARY` only when the story must touch both server and CLI domains.

## Parallel lanes
Use separate lanes to reduce merge conflicts:
- **Server lane**: `src/gamehub_server/` + server docs/tests.
- **CLI lane**: `src/gamehub_cli/` + CLI docs/tests.
- **Docs lane**: `docs/`, `PLANS/`, top-level process docs.

Rules for parallel safety:
- Keep diffs minimal and scoped.
- Avoid dependency/lockfile/packaging changes in feature stories.
- Avoid repo-wide formatting.
- If boundary contracts change, land contract-first story before implementation stories.

## PR linkage
- PR title should include STORY ID.
- PR description should reference:
  - STORY ID
  - acceptance criteria status
  - tests run (or exact command for local execution)

## Example STORY block
```md
### STORY GH-142
- Type: CLI
- Goal: Make Steam close-wait logging explicit during sync.
- Acceptance Criteria:
  - `--verbose` logs close/wait transitions.
  - Existing behavior is unchanged for non-verbose mode.
- Tests Required: `tests/test_steam_lifecycle.py::test_verbose_close_wait_logging`
- PR Title Template: `[GH-142] Improve Steam lifecycle verbose logging`
- Rollback Risk: Low
```

## Deprecation notice
`kanban/` is deprecated for new planning work. Do not add new stories there.
Use `PLANS/` for all new plans and STORY contracts.
