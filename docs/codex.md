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

If this file and `AGENTS.md` ever disagree, `AGENTS.md` wins.
