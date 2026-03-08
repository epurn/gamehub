from __future__ import annotations

from pathlib import Path
from typing import Any

from ..common.config import load_config
from ..common.shortcut_payload import (
    ShortcutLaunchPayload,
    encode_shortcut_payload,
    parse_shortcut_payload,
    resolve_shortcut_config_path,
)
from ..sync.state import load_state as _load_shortcut_state
from ..sync.state import save_state_atomic as _save_shortcut_state
from .runtime import (
    _run_target_with_optional_exit_hook,
    apply_shortcut_controller_configuration,
    prepare_shortcut_runtime_environment,
)
from .runtime import (
    warn_shortcut_runtime as _warn_shortcut_runtime,
)
from .save_session import (
    ShortcutSaveContext as _ShortcutSaveContext,
)
from .save_session import (
    build_shortcut_save_resolver as _shortcut_save_resolver,
)
from .save_session import (
    ensure_managed_memory_card_paths as _ensure_managed_memory_card_paths,
)
from .save_session import (
    run_shortcut_postexit_save_sync as _run_shortcut_postexit_save_sync,
)
from .save_session import (
    run_shortcut_prelaunch_save_sync as _run_shortcut_prelaunch_save_sync,
)
from .save_session import (
    should_sync_shortcut_saves as _should_sync_shortcut_saves,
)

__all__ = [
    "ShortcutLaunchPayload",
    "encode_shortcut_payload",
    "parse_shortcut_payload",
    "run_shortcut_launch",
]


def run_shortcut_launch(*, payload_token: str, config_path: Path | None = None, audit: bool = False) -> int:
    payload = parse_shortcut_payload(payload_token)
    resolved_config = resolve_shortcut_config_path(config_path, payload)
    config = load_config(resolved_config)
    save_resolver = _shortcut_save_resolver(payload)
    state: Any = None
    state_changed = False

    if _should_sync_shortcut_saves(payload, config):
        try:
            state = _load_shortcut_state(config.state_path)
        except Exception as exc:  # noqa: BLE001
            _warn_shortcut_runtime(f"save sync state helpers unavailable ({exc})")
            state = None

    prepare_shortcut_runtime_environment(payload)
    apply_shortcut_controller_configuration(payload=payload, config=config, audit=audit)

    if _should_sync_shortcut_saves(payload, config):
        try:
            _ensure_managed_memory_card_paths(payload, config)
        except Exception as exc:  # noqa: BLE001
            _warn_shortcut_runtime(f"managed memory-card setup failed ({exc})")

    save_context = _ShortcutSaveContext(save_snapshots={}, exact_binding_snapshots={}, tree_snapshots={})
    if state is not None:
        try:
            save_context, prelaunch_changed = _run_shortcut_prelaunch_save_sync(
                payload=payload,
                config=config,
                state=state,
                resolve_executable=save_resolver,
                verbose=False,
                audit=audit,
            )
            state_changed = state_changed or prelaunch_changed
        except Exception as exc:  # noqa: BLE001
            _warn_shortcut_runtime(f"pre-launch save sync failed; continuing launch ({exc})")

    exit_code = 0
    launch_completed = False
    try:
        exit_code = _run_target_with_optional_exit_hook(payload)
        launch_completed = True
    finally:
        if state is not None:
            if launch_completed:
                try:
                    postexit_changed = _run_shortcut_postexit_save_sync(
                        payload=payload,
                        config=config,
                        state=state,
                        context=save_context,
                        resolve_executable=save_resolver,
                        verbose=False,
                        audit=audit,
                    )
                    state_changed = state_changed or postexit_changed
                except Exception as exc:  # noqa: BLE001
                    _warn_shortcut_runtime(f"post-exit save sync failed ({exc})")
            if state_changed:
                _save_shortcut_state(config.state_path, state)
    return exit_code
