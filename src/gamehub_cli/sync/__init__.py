from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .orchestrator import configure_dependencies, run_init, run_sync

__all__ = [
    "configure_dependencies",
    "run_init",
    "run_sync",
]


def __getattr__(name: str) -> Any:
    if name == "configure_dependencies":
        from .orchestrator import configure_dependencies as exported_configure_dependencies

        return exported_configure_dependencies
    if name == "run_init":
        from .orchestrator import run_init as exported_run_init

        return exported_run_init
    if name == "run_sync":
        from .orchestrator import run_sync as exported_run_sync

        return exported_run_sync
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
