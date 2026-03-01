# Codex Runbook (Short)

Use this runbook for daily Codex execution in GAMEHUB.

## Prompt style (one-liner)
Use one-liner prompts tied to a story contract:
- `Implement STORY <ID> from PLANS/<feature>.md`

No per-task prompt template should be required beyond the one-liner.

## Required execution loop
1. **Orientation (no edits yet)**
   - restate requested STORY ID
   - list files/directories to modify or create
   - call out risks and conflict points
   - list planned checks/commands
2. **Implement only the requested story**
   - stay inside story scope
   - do not expand to unrelated cleanup/refactors
3. **Add or update tests in scope**
   - keep assertions deterministic
   - include negative paths when applicable
4. **Provide Windows local test command**
   - canonical command:
     - `.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider`
5. **Provide PR-ready output**
   - PR title
   - short PR description
   - file list changed
   - acceptance-criteria checklist status

## Scope and boundary rules
- Do not touch both server and CLI in one story unless Type is `CROSS-BOUNDARY`.
- Prefer domain isolation:
  - Server: `src/gamehub_server/`
  - CLI: `src/gamehub_cli/`
  - Common: `src/gamehub_common/`
  - Docs/process: `docs/`, `PLANS/`, root guidance docs
- For cross-boundary work, define contract surface first, then implement.

## Explicitly forbidden in normal story PRs
- Repo-wide formatting.
- Dependency/version/lockfile/packaging bumps.
- Broad refactors outside story scope.
- Opportunistic multi-domain rewrites.

## Parallel work lanes
Use story contracts to run tasks in parallel with minimal conflicts:
- Server lane
- CLI lane
- Common lane
- Docs lane

Conflict avoidance:
- Keep diffs minimal.
- Keep each PR scoped to one story.
- Avoid touching shared files unless required by the contract.

## Windows-first local development
- Use the local repo venv for Python commands.
- Preferred style:
  - `.\venv\Scripts\python.exe -m <module>`
  - `.\venv\Scripts\python.exe -m pytest . -p no:cacheprovider`

## Definition of success for a story PR
- Acceptance criteria are met exactly.
- Tests are added/updated in the declared locations.
- Docs are updated when behavior/contracts change.
- PR references the STORY ID and scope.
