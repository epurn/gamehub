from __future__ import annotations

import base64
import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ShortcutLaunchPayload:
    version: int
    emulator: str
    target_exe: str
    target_args: tuple[str, ...]
    start_dir: str = ""
    config_path: str | None = None
    title_id: str | None = None
    system: str | None = None
    rom_rel_path: str | None = None
    macos_open_app: str | None = None
    macos_open_args: tuple[str, ...] = ()


def strip_wrapping_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return stripped


def unquote_executable(value: str) -> str:
    return strip_wrapping_quotes(value)


def encode_shortcut_payload(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii")
    return token.rstrip("=")


def resolve_shortcut_config_path(
    override_config_path: Path | None,
    payload: ShortcutLaunchPayload,
) -> Path | None:
    if override_config_path is not None:
        return override_config_path.expanduser()
    if payload.config_path:
        return Path(payload.config_path).expanduser()
    return None


def parse_shortcut_payload(token: str) -> ShortcutLaunchPayload:
    payload = _decode_payload_token(token)
    version = _parse_payload_version(payload.get("v", 1))
    emulator = str(payload.get("emulator", "")).strip().casefold()
    target_exe = str(payload.get("target_exe", "")).strip()
    if not emulator:
        raise ValueError("Shortcut launch payload missing emulator")
    if not target_exe:
        raise ValueError("Shortcut launch payload missing target_exe")

    target_args = _parse_target_args(payload.get("target_args"))
    if not target_args and isinstance(payload.get("target_launch_options"), str):
        target_args = _parse_target_args(payload["target_launch_options"])
    start_dir = strip_wrapping_quotes(str(payload.get("start_dir", "")).strip())
    config_path = payload.get("config_path")
    config_path_str = str(config_path).strip() if isinstance(config_path, str) and config_path.strip() else None
    title_id_raw = payload.get("title_id")
    system_raw = payload.get("system")
    rom_rel_path_raw = payload.get("rom_rel_path")
    title_id = str(title_id_raw).strip() if isinstance(title_id_raw, str) and title_id_raw.strip() else None
    system = str(system_raw).strip() if isinstance(system_raw, str) and system_raw.strip() else None
    rom_rel_path = (
        str(rom_rel_path_raw).strip() if isinstance(rom_rel_path_raw, str) and rom_rel_path_raw.strip() else None
    )
    macos_open_app_raw = payload.get("macos_open_app")
    macos_open_app = (
        str(macos_open_app_raw).strip() if isinstance(macos_open_app_raw, str) and macos_open_app_raw.strip() else None
    )
    macos_open_args = _parse_target_args(payload.get("macos_open_args"))
    if not macos_open_args and isinstance(payload.get("macos_open_launch_options"), str):
        macos_open_args = _parse_target_args(payload["macos_open_launch_options"])
    return ShortcutLaunchPayload(
        version=version,
        emulator=emulator,
        target_exe=target_exe,
        target_args=target_args,
        start_dir=start_dir,
        config_path=config_path_str,
        title_id=title_id,
        system=system,
        rom_rel_path=rom_rel_path,
        macos_open_app=macos_open_app,
        macos_open_args=macos_open_args,
    )


def _decode_payload_token(token: str) -> dict[str, object]:
    padded = token + ("=" * (-len(token) % 4))
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("Shortcut launch payload must decode to a JSON object")
    return decoded


def _parse_target_args(raw: object) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(strip_wrapping_quotes(str(item)) for item in raw)
    if isinstance(raw, tuple):
        return tuple(strip_wrapping_quotes(str(item)) for item in raw)
    if isinstance(raw, str):
        if not raw.strip():
            return ()
        return tuple(
            strip_wrapping_quotes(token) for token in shlex.split(raw, posix=not sys.platform.startswith("win"))
        )
    return ()


def _parse_payload_version(raw: object) -> int:
    if isinstance(raw, bool):
        return 1
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text and text.isdigit():
            return int(text)
    return 1
