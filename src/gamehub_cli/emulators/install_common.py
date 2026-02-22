from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_HOST_PATH_TYPE = type(Path.cwd())
_OS_NAME = os.name
_SYS_PLATFORM = sys.platform
_WINERROR_ELEVATION_REQUIRED = 740


def _safe_path(value: str) -> Path:
    normalized = value.replace("\\", "/")
    return _HOST_PATH_TYPE(normalized)


def _run_install_command(command: list[str], *, verbose: bool) -> int:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=not verbose,
            text=True,
        )
    except OSError as exc:
        if _OS_NAME == "nt" and getattr(exc, "winerror", None) == _WINERROR_ELEVATION_REQUIRED:
            return _WINERROR_ELEVATION_REQUIRED
        raise
    return int(completed.returncode)


def _run_windows_elevated_command(executable: Path, args: tuple[str, ...], *, verbose: bool) -> int:
    if _OS_NAME != "nt":
        return 1
    powershell_cmd = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell_cmd:
        return 1

    def _ps_single_quoted(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    exe_literal = _ps_single_quoted(str(executable))
    arg_tokens = [_ps_single_quoted(value) for value in args]
    arg_list_literal = ", ".join(arg_tokens)
    script = (
        f"$argList = @({arg_list_literal}); "
        f"$proc = Start-Process -FilePath {exe_literal} -ArgumentList $argList -Verb RunAs -Wait -PassThru; "
        "exit [int]$proc.ExitCode"
    )
    completed = subprocess.run(
        [powershell_cmd, "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=not verbose,
        text=True,
    )
    return int(completed.returncode)


def _version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in re.split(r"[^0-9]+", value):
        if token:
            parts.append(int(token))
    return tuple(parts) if parts else (0,)


def _is_version_at_or_below_5_0(value: str) -> bool | None:
    parts = _version_key(value)
    if not parts or parts == (0,):
        return None
    major = parts[0]
    minor = parts[1] if len(parts) > 1 else 0
    if major < 5:
        return True
    if major > 5:
        return False
    if minor < 0:
        return True
    if minor > 0:
        return False
    # 5.0.x: treat non-zero patch/build as newer than plain 5.0.
    return all(part == 0 for part in parts[2:])
