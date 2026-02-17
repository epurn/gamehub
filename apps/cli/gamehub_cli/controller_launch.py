from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading

from . import azahar_exit_hook
from .config import load_config
from .controller_apply import apply_controller_profile, apply_named_controller_profile
from .controller_detection import detect_xbox_controllers
from .controller_profiles import PROFILE_KBM, seed_default_profiles

_DOLPHIN_FLATPAK_APP_ID = "org.DolphinEmu.dolphin-emu"
_DOLPHIN_LINUX_EXIT_HOOK_ENV = "GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK"
_DOLPHIN_EXIT_BUTTON_SELECT_ENV = "GAMEHUB_DOLPHIN_EXIT_BUTTON_SELECT"
_DOLPHIN_EXIT_BUTTON_START_ENV = "GAMEHUB_DOLPHIN_EXIT_BUTTON_START"
_DOLPHIN_EXIT_JS_DEVICE_ENV = "GAMEHUB_DOLPHIN_EXIT_JS_DEVICE"


@dataclass(frozen=True)
class ControllerLaunchPayload:
    version: int
    emulator: str
    target_exe: str
    target_args: tuple[str, ...]
    start_dir: str = ""
    config_path: str | None = None


def encode_controller_payload(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii")
    return token.rstrip("=")


def _decode_payload_token(token: str) -> dict[str, object]:
    padded = token + ("=" * (-len(token) % 4))
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("Controller launch payload must decode to a JSON object")
    return decoded


def _parse_target_args(raw: object) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(str(item) for item in raw)
    if isinstance(raw, tuple):
        return tuple(str(item) for item in raw)
    if isinstance(raw, str):
        if not raw.strip():
            return ()
        return tuple(shlex.split(raw, posix=not sys.platform.startswith("win")))
    return ()


def parse_controller_payload(token: str) -> ControllerLaunchPayload:
    payload = _decode_payload_token(token)
    version = int(payload.get("v", 1))
    emulator = str(payload.get("emulator", "")).strip().casefold()
    target_exe = str(payload.get("target_exe", "")).strip()
    if not emulator:
        raise ValueError("Controller launch payload missing emulator")
    if not target_exe:
        raise ValueError("Controller launch payload missing target_exe")

    target_args = _parse_target_args(payload.get("target_args"))
    if not target_args and isinstance(payload.get("target_launch_options"), str):
        target_args = _parse_target_args(payload["target_launch_options"])
    start_dir = str(payload.get("start_dir", "")).strip()
    config_path = payload.get("config_path")
    config_path_str = str(config_path).strip() if isinstance(config_path, str) and config_path.strip() else None
    return ControllerLaunchPayload(
        version=version,
        emulator=emulator,
        target_exe=target_exe,
        target_args=target_args,
        start_dir=start_dir,
        config_path=config_path_str,
    )


def _unquote_executable(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return stripped


def _resolve_config_path(override_config_path: Path | None, payload: ControllerLaunchPayload) -> Path | None:
    if override_config_path is not None:
        return override_config_path.expanduser()
    if payload.config_path:
        return Path(payload.config_path).expanduser()
    return None


def _env_enabled(name: str, *, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return default


def _int_env_optional(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return None


def _discover_js_devices(env_name: str) -> list[str]:
    env_device = os.environ.get(env_name)
    if env_device:
        return [env_device]
    dev_input = Path("/dev/input")
    if not dev_input.exists():
        return []
    devices: list[str] = []
    for candidate in sorted(dev_input.glob("js*")):
        if candidate.is_char_device() or candidate.exists():
            devices.append(str(candidate))
    return devices


def _payload_targets_flatpak_app(payload: ControllerLaunchPayload, *, app_id: str) -> bool:
    target_exe = _unquote_executable(payload.target_exe).strip().casefold()
    if target_exe != "flatpak":
        return False
    args_folded = [arg.casefold() for arg in payload.target_args]
    return "run" in args_folded and app_id.casefold() in args_folded


def _should_use_linux_dolphin_exit_hook(payload: ControllerLaunchPayload) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    if "dolphin" not in payload.emulator:
        return False
    if not _env_enabled(_DOLPHIN_LINUX_EXIT_HOOK_ENV, default=True):
        return False
    return _payload_targets_flatpak_app(payload, app_id=_DOLPHIN_FLATPAK_APP_ID)


def _run_linux_dolphin_target_with_exit_hook(payload: ControllerLaunchPayload) -> int:
    executable = _unquote_executable(payload.target_exe)
    command = [executable, *payload.target_args]
    cwd = None
    if payload.start_dir:
        candidate = Path(payload.start_dir)
        if candidate.exists():
            cwd = str(candidate)
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL)
    select_button = _int_env_optional(_DOLPHIN_EXIT_BUTTON_SELECT_ENV)
    start_button = _int_env_optional(_DOLPHIN_EXIT_BUTTON_START_ENV)
    js_devices = _discover_js_devices(_DOLPHIN_EXIT_JS_DEVICE_ENV)
    watcher = threading.Thread(
        target=azahar_exit_hook._monitor_combo_and_terminate,
        args=(process,),
        kwargs={
            "select_button": select_button if select_button is not None else 6,
            "start_button": start_button if start_button is not None else 7,
            "js_devices": js_devices,
            "app_id": _DOLPHIN_FLATPAK_APP_ID,
        },
        daemon=True,
    )
    watcher.start()
    return int(azahar_exit_hook._wait_for_session_exit(process, _DOLPHIN_FLATPAK_APP_ID))


def _run_target(payload: ControllerLaunchPayload) -> int:
    executable = _unquote_executable(payload.target_exe)
    command = [executable, *payload.target_args]
    cwd = None
    if payload.start_dir:
        candidate = Path(payload.start_dir)
        if candidate.exists():
            cwd = str(candidate)
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL)
    return int(process.wait())


def _run_target_with_optional_exit_hook(payload: ControllerLaunchPayload) -> int:
    if _should_use_linux_dolphin_exit_hook(payload):
        try:
            return _run_linux_dolphin_target_with_exit_hook(payload)
        except Exception as exc:
            print(f"Warning: Dolphin exit hook failed (error={exc}); falling back to direct launch")
    return _run_target(payload)


def run_controller_launch(*, payload_token: str, config_path: Path | None = None) -> int:
    payload = parse_controller_payload(payload_token)
    resolved_config = _resolve_config_path(config_path, payload)
    config = load_config(resolved_config)

    if config.controllers.launch_autoconfig:
        try:
            seed_default_profiles(config)
        except Exception as exc:
            print(f"Warning: failed to seed controller profile defaults (error={exc})")
        controller_count = 0
        try:
            controller_count = len(detect_xbox_controllers(max_devices=2))
        except Exception as exc:
            print(
                "Warning: controller detection failed "
                f"(emulator={payload.emulator}, error={exc}); using keyboard/mouse fallback profile selection"
            )
        try:
            apply_controller_profile(
                config,
                emulator_name=payload.emulator,
                controller_count=controller_count,
            )
        except Exception as exc:
            print(
                "Warning: controller autoconfig failed "
                f"(emulator={payload.emulator}, profile={PROFILE_KBM}, error={exc}); using keyboard/mouse fallback"
            )
            try:
                apply_named_controller_profile(
                    config,
                    emulator_name=payload.emulator,
                    profile_name=PROFILE_KBM,
                )
            except Exception as fallback_exc:
                print(
                    "Warning: keyboard/mouse fallback profile application failed "
                    f"(emulator={payload.emulator}, error={fallback_exc})"
                )
    return _run_target_with_optional_exit_hook(payload)
