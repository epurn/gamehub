# PLAN: cli-missing-config-failfast

## Context
- `gamehub init` already rejects a missing config file at the CLI boundary.
- `gamehub sync` and `gamehub doctor ...` still call `load_config()` directly and can silently fall back to localhost/default-state assumptions when no config file exists.
- The docs already tell operators to create a real config file from `docs/templates/`, so the current CLI behavior is inconsistent with the documented contract.

## Goals
- Require a real config file for user-facing `init`, `sync`, and `doctor` commands.
- Standardize missing-config CLI errors so they are actionable and consistent.
- Add regression coverage and doc updates for the stricter contract.

## Non-Goals
- Adding a config scaffolding command.
- Changing low-level `load_config()` defaults used by internal helpers and tests.
- Changing hidden `shortcut-launch` behavior in this pass.

## Scope
- `src/gamehub_cli/main.py`
- `tests/test_cli_commands.py`
- `README.md`
- `docs/config-and-state.md`
- `docs/cli-sync.md`

## Acceptance Criteria
- `init`, `sync`, and `doctor` fail fast with the same missing-config error path.
- Missing-config CLI tests cover at least one `sync` and one `doctor` invocation.
- Operator docs state that the resolved config path must exist before running those commands.
