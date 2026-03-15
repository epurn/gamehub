# Codex Runbook

`AGENTS.md` is the authoritative rule file for AI contributors in this repo.

Use this page as a quick index only:
- repo rules, boundaries, and required quality gates: `AGENTS.md`
- architecture overview: [architecture.md](architecture.md)
- release validation commands: [release-process.md](release-process.md)
- non-trivial implementation planning: `PLANS/`

Short working defaults:
- start with the request, expected files/modules, and planned checks
- keep scope tight and respect package boundaries
- use the repo-local virtual environment for Python commands
- update docs whenever behavior, contracts, or operator flows change

## Worktree Setup

Codex local environments can run a setup script automatically for each new worktree. This repo wires that through `.codex/environments/environment.toml`, which calls `scripts/codex_worktree_setup.py`.

The bootstrap script:
- creates a repo-local `venv/` when the worktree does not have one yet
- installs the editable project plus `dev` extras into that worktree's venv

If a worktree setup fails or you need to rerun it manually:
- macOS/Linux: `python3 scripts/codex_worktree_setup.py`
- Windows: `py -3 scripts\codex_worktree_setup.py`

If this file and `AGENTS.md` ever disagree, `AGENTS.md` wins.
