from __future__ import annotations

import tempfile
import time
import traceback
from pathlib import Path

_WINDOWS_ENTRYPOINT_LOG_NAME = "gamehub-windows-entrypoint.log"


def _append_entrypoint_log(message: str) -> None:
    try:
        log_path = Path(tempfile.gettempdir()) / _WINDOWS_ENTRYPOINT_LOG_NAME
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")
    except OSError:
        return


if __name__ == "__main__":
    _append_entrypoint_log("startup")
    try:
        from gamehub_cli.main import main

        main()
        _append_entrypoint_log("exit_ok")
    except Exception as exc:  # noqa: BLE001
        _append_entrypoint_log(f"fatal_exception={type(exc).__name__}: {exc}")
        for line in traceback.format_exc().splitlines():
            _append_entrypoint_log(line)
        raise
