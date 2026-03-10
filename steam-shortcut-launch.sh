#!/bin/sh
set -eu
[ "$#" -ge 1 ]
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export HOME=/Users/epurn
unset PYTHONHOME PYTHONPATH PYTHONEXECUTABLE __PYVENV_LAUNCHER__
exec /usr/bin/arch -arm64 /Users/epurn/.codex/worktrees/1e94/gamehub/venv/bin/python -m gamehub_cli.main shortcut-launch --payload-registry shortcut_payloads.json --payload-ref "$1"
