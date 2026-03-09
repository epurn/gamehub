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
from ..common.shortcut_payload_registry import load_shortcut_payload_token
from ..sync.state import load_state as _load_shortcut_state
from ..sync.state import save_state_atomic as _save_shortcut_state
from .runtime import (
    ShortcutLaunchError,
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


def _resolve_launch_payload(
    *,
    payload_token: str | None,
    payload_ref: str | None,
    payload_registry_path: Path | None,
) -> ShortcutLaunchPayload:
    if payload_token:
        return parse_shortcut_payload(payload_token)
    if payload_ref:
        if payload_registry_path is None:
            raise ValueError("Shortcut payload registry path missing")
        token = load_shortcut_payload_token(payload_registry_path, payload_ref)
        return parse_shortcut_payload(token)
    raise ValueError("Shortcut launch requires --payload or --payload-ref")


def run_shortcut_launch(
    *,
    payload_token: str | None = None,
    payload_ref: str | None = None,
    payload_registry_path: Path | None = None,
    config_path: Path | None = None,
    audit: bool = False,
) -> int:
    try:
        try:
            payload = _resolve_launch_payload(
                payload_token=payload_token,
                payload_ref=payload_ref,
                payload_registry_path=payload_registry_path,
            )
        except (OSError, ValueError) as exc:
            _warn_shortcut_runtime(f"shortcut payload resolution failed ({exc})")
            return 1
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
        except ShortcutLaunchError as exc:
            _warn_shortcut_runtime(str(exc))
            exit_code = 1
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
    except Exception as exc:  # noqa: BLE001
        _warn_shortcut_runtime(f"unexpected shortcut launch error ({type(exc).__name__}: {exc})")
        return 1
