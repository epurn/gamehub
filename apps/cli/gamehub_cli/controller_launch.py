from __future__ import annotations

from dataclasses import dataclass
import base64
import json
from pathlib import Path
import shlex
import subprocess
import sys

from .config import load_config
from .controller_apply import apply_controller_profile, apply_named_controller_profile
from .controller_detection import detect_xbox_controllers
from .controller_profiles import PROFILE_KBM, seed_default_profiles


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
    return _run_target(payload)
