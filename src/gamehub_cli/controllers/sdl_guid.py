from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..common.platform_paths import AZAHAR_FLATPAK_APP_ID

_AZAHAR_GUID_RE = re.compile(r"guid(?::|\$0)(?P<guid>[0-9a-fA-F]+)")
_AZAHAR_PORT_RE = re.compile(r"port(?::|\$0)(?P<port>\d+)")
_AZAHAR_ANALOG_GUID_RE = re.compile(r"\$1guid\$0[0-9a-fA-F]+", flags=re.IGNORECASE)
_AZAHAR_ANALOG_PORT_RE = re.compile(r"\$1port\$0\d+")
_AZAHAR_ANALOG_ENGINE_RE = re.compile(r"engine\$0sdl", flags=re.IGNORECASE)
_AZAHAR_GUID_VALUE_RE = re.compile(r"[0-9a-fA-F]{32}")
_AZAHAR_FLATPAK_GUID_TIMEOUT_SEC = 3.0
_AZAHAR_WINDOWS_SDL_DIR_ENV = "GAMEHUB_AZAHAR_SDL_DIR"


class _SDLJoystickGUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_uint8 * 16)]


@dataclass(frozen=True)
class _SDLJoystickDevice:
    slot: int
    name: str
    guid: str | None


def _azahar_detect_sdl_identity(lines: list[str]) -> tuple[str | None, int]:
    guid: str | None = None
    port = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or "=" not in stripped:
            continue
        value = stripped.split("=", 1)[1]
        lowered = value.casefold()
        if "engine:sdl" not in lowered and "engine$0sdl" not in lowered:
            continue
        guid_match = _AZAHAR_GUID_RE.search(value)
        if guid_match:
            guid = guid_match.group("guid")
        port_match = _AZAHAR_PORT_RE.search(value)
        if port_match:
            try:
                port = int(port_match.group("port"))
            except ValueError:
                port = 0
        if guid is not None:
            break
    return guid, port


def _normalize_sdl_guid(raw: str) -> str | None:
    guid = raw.strip().lower()
    if len(guid) != 32 or set(guid) == {"0"}:
        return None
    return guid


def _candidate_dirs_from_emulators() -> list[Path]:
    try:
        from ..emulators import resolve_emulator_executable
    except Exception:
        return []
    dirs: list[Path] = []
    for emulator_name in ("azahar", "retroarch", "pcsx2", "dolphin"):
        raw = str(resolve_emulator_executable(emulator_name)).strip('"')
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.exists():
            dirs.append(candidate.parent)
    return dirs


def _windows_sdl_library_candidates() -> list[str]:
    library_candidates: list[str] = []
    env_dir = os.environ.get(_AZAHAR_WINDOWS_SDL_DIR_ENV)
    if env_dir:
        env_path = Path(env_dir.strip().strip('"'))
        if env_path.is_file():
            library_candidates.append(str(env_path))
        else:
            for dll_name in ("SDL2.dll", "libSDL2-2.0.dll", "libSDL2.dll"):
                candidate = env_path / dll_name
                if candidate.exists():
                    library_candidates.append(str(candidate))
    for candidate_dir in _candidate_dirs_from_emulators():
        for dll_name in ("SDL2.dll", "libSDL2-2.0.dll", "libSDL2.dll"):
            candidate = candidate_dir / dll_name
            if candidate.exists():
                library_candidates.append(str(candidate))
    detected = ctypes.util.find_library("SDL2")
    if detected:
        library_candidates.append(detected)
    library_candidates.extend(["SDL2.dll", "libSDL2-2.0.dll", "libSDL2.dll"])
    return library_candidates


def _linux_sdl_library_candidates() -> list[str]:
    library_candidates: list[str] = []
    detected = ctypes.util.find_library("SDL2")
    if detected:
        library_candidates.append(detected)
    library_candidates.extend(["libSDL2-2.0.so.0", "libSDL2.so"])
    return library_candidates


def _macos_sdl_library_candidates() -> list[str]:
    library_candidates: list[str] = []
    detected = ctypes.util.find_library("SDL2")
    if detected:
        library_candidates.append(detected)
    library_candidates.extend(
        [
            "/Library/Frameworks/SDL2.framework/Versions/A/SDL2",
            "/opt/homebrew/lib/libSDL2-2.0.0.dylib",
            "/usr/local/lib/libSDL2-2.0.0.dylib",
            "libSDL2-2.0.0.dylib",
            "libSDL2.dylib",
            "SDL2",
        ]
    )
    return library_candidates


def _load_sdl_library(library_candidates: list[str]) -> ctypes.CDLL | None:
    for library_candidate in library_candidates:
        try:
            return ctypes.CDLL(library_candidate)
        except OSError:
            continue
    return None


def _configure_sdl_joystick_api(sdl: ctypes.CDLL) -> bool:
    try:
        sdl.SDL_Init.argtypes = [ctypes.c_uint32]
        sdl.SDL_Init.restype = ctypes.c_int
        sdl.SDL_Quit.argtypes = []
        sdl.SDL_Quit.restype = None
        sdl.SDL_NumJoysticks.argtypes = []
        sdl.SDL_NumJoysticks.restype = ctypes.c_int
        sdl.SDL_JoystickNameForIndex.argtypes = [ctypes.c_int]
        sdl.SDL_JoystickNameForIndex.restype = ctypes.c_char_p
        sdl.SDL_JoystickGetDeviceGUID.argtypes = [ctypes.c_int]
        sdl.SDL_JoystickGetDeviceGUID.restype = _SDLJoystickGUID
        sdl.SDL_JoystickGetGUIDString.argtypes = [_SDLJoystickGUID, ctypes.c_char_p, ctypes.c_int]
        sdl.SDL_JoystickGetGUIDString.restype = None
    except AttributeError:
        return False
    return True


def _enumerate_sdl_joysticks(
    library_candidates: list[str],
    *,
    max_devices: int | None = None,
) -> list[_SDLJoystickDevice]:
    sdl = _load_sdl_library(library_candidates)
    if sdl is None or not _configure_sdl_joystick_api(sdl):
        return []
    if sdl.SDL_Init(0x00000200) != 0:
        return []

    try:
        count = int(sdl.SDL_NumJoysticks())
        if count <= 0:
            return []
        devices: list[_SDLJoystickDevice] = []
        for slot in range(count):
            if max_devices is not None and len(devices) >= max_devices:
                break
            name_raw = sdl.SDL_JoystickNameForIndex(slot)
            name = name_raw.decode("utf-8", errors="ignore").strip() if name_raw else ""
            guid_value = sdl.SDL_JoystickGetDeviceGUID(slot)
            text = ctypes.create_string_buffer(33)
            sdl.SDL_JoystickGetGUIDString(guid_value, text, len(text))
            guid = _normalize_sdl_guid(text.value.decode("ascii", errors="ignore"))
            devices.append(_SDLJoystickDevice(slot=slot, name=name, guid=guid))
        return devices
    finally:
        sdl.SDL_Quit()


def _discover_host_sdl_joysticks(*, max_devices: int | None = None) -> list[_SDLJoystickDevice]:
    if sys.platform.startswith("linux"):
        return _enumerate_sdl_joysticks(_linux_sdl_library_candidates(), max_devices=max_devices)
    if sys.platform.startswith("win"):
        return _enumerate_sdl_joysticks(_windows_sdl_library_candidates(), max_devices=max_devices)
    if sys.platform == "darwin":
        return _enumerate_sdl_joysticks(_macos_sdl_library_candidates(), max_devices=max_devices)
    return []


def _discover_sdl_guid(*, port: int) -> str | None:
    if port < 0:
        return None
    for device in _discover_host_sdl_joysticks(max_devices=port + 1):
        if device.slot == port:
            return device.guid
    return None


def _discover_linux_sdl_guid(*, port: int) -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    return _discover_sdl_guid(port=port)


def _discover_windows_sdl_guid(*, port: int) -> str | None:
    if not sys.platform.startswith("win"):
        return None
    return _discover_sdl_guid(port=port)


def _discover_macos_sdl_guid(*, port: int) -> str | None:
    if sys.platform != "darwin":
        return None
    return _discover_sdl_guid(port=port)


def _discover_host_sdl_guid(*, port: int) -> str | None:
    if sys.platform.startswith("linux"):
        return _discover_linux_sdl_guid(port=port)
    if sys.platform.startswith("win"):
        return _discover_windows_sdl_guid(port=port)
    if sys.platform == "darwin":
        return _discover_macos_sdl_guid(port=port)
    return None


def _azahar_flatpak_guid_probe_script(port: int) -> str:
    return "\n".join(
        [
            "import ctypes,ctypes.util,sys",
            "class SDLJoystickGUID(ctypes.Structure):",
            "    _fields_ = [('data', ctypes.c_uint8 * 16)]",
            "def _load_sdl():",
            "    candidates = []",
            "    detected = ctypes.util.find_library('SDL2')",
            "    if detected:",
            "        candidates.append(detected)",
            "    candidates += ['libSDL2-2.0.so.0', 'libSDL2.so']",
            "    for candidate in candidates:",
            "        try:",
            "            return ctypes.CDLL(candidate)",
            "        except OSError:",
            "            continue",
            "    return None",
            "sdl = _load_sdl()",
            "if sdl is None:",
            "    sys.exit(2)",
            "try:",
            "    sdl.SDL_Init.argtypes = [ctypes.c_uint32]",
            "    sdl.SDL_Init.restype = ctypes.c_int",
            "    sdl.SDL_Quit.argtypes = []",
            "    sdl.SDL_Quit.restype = None",
            "    sdl.SDL_NumJoysticks.argtypes = []",
            "    sdl.SDL_NumJoysticks.restype = ctypes.c_int",
            "    sdl.SDL_JoystickGetDeviceGUID.argtypes = [ctypes.c_int]",
            "    sdl.SDL_JoystickGetDeviceGUID.restype = SDLJoystickGUID",
            "    sdl.SDL_JoystickGetGUIDString.argtypes = [SDLJoystickGUID, ctypes.c_char_p, ctypes.c_int]",
            "    sdl.SDL_JoystickGetGUIDString.restype = None",
            "except AttributeError:",
            "    sys.exit(3)",
            "if sdl.SDL_Init(0x00000200) != 0:",
            "    sys.exit(4)",
            "try:",
            "    count = int(sdl.SDL_NumJoysticks())",
            f"    port = int({port})",
            "    if count <= 0 or port < 0 or port >= count:",
            "        sys.exit(5)",
            "    guid_value = sdl.SDL_JoystickGetDeviceGUID(port)",
            "    text = ctypes.create_string_buffer(33)",
            "    sdl.SDL_JoystickGetGUIDString(guid_value, text, len(text))",
            "    guid = text.value.decode('ascii', errors='ignore').strip().lower()",
            "    if len(guid) != 32 or set(guid) == {'0'}:",
            "        sys.exit(6)",
            "    print(guid)",
            "finally:",
            "    sdl.SDL_Quit()",
        ]
    )


def _parse_guid_output(text: str) -> str | None:
    for line in text.splitlines():
        match = _AZAHAR_GUID_VALUE_RE.search(line)
        if not match:
            continue
        value = match.group(0).lower()
        if set(value) == {"0"}:
            continue
        return value
    return None


def _probe_azahar_flatpak_guid(*, port: int, timeout_sec: float = _AZAHAR_FLATPAK_GUID_TIMEOUT_SEC) -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    if shutil.which("flatpak") is None:
        return None

    normalized_port = _azahar_normalize_sdl_port(port)
    script = _azahar_flatpak_guid_probe_script(normalized_port)
    for interpreter in ("python3", "python"):
        try:
            completed = subprocess.run(
                [
                    "flatpak",
                    "run",
                    "--device=all",
                    f"--command={interpreter}",
                    AZAHAR_FLATPAK_APP_ID,
                    "-c",
                    script,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode != 0:
            continue
        guid = _parse_guid_output(completed.stdout)
        if guid:
            return guid
    return None


def _azahar_normalize_sdl_port(value: int) -> int:
    if value < 0:
        return 0
    if value > 15:
        return 15
    return value


def _inject_azahar_sdl_identity(
    value: str,
    *,
    guid: str | None,
    port: int,
    strip_guid: bool = False,
) -> str:
    normalized_port = _azahar_normalize_sdl_port(port)
    raw = value.strip()
    lowered = raw.casefold()

    if "engine$0sdl" in lowered:
        updated = _AZAHAR_ANALOG_PORT_RE.sub(f"$1port$0{normalized_port}", raw)
        if strip_guid:
            updated = _AZAHAR_ANALOG_GUID_RE.sub("", updated)
        elif guid:
            if _AZAHAR_ANALOG_GUID_RE.search(updated):
                updated = _AZAHAR_ANALOG_GUID_RE.sub(f"$1guid$0{guid}", updated)
            else:
                updated = _AZAHAR_ANALOG_ENGINE_RE.sub(f"engine$0sdl$1guid$0{guid}", updated)
        return updated

    if "engine:sdl" not in lowered:
        return raw

    quote = '"' if len(raw) >= 2 and raw[0] == raw[-1] == '"' else ""
    body = raw[1:-1] if quote else raw
    parts = [part.strip() for part in body.split(",") if part.strip()]
    updated_parts: list[str] = []
    has_port = False
    has_guid = False
    inserted_guid_after_engine = False
    for part in parts:
        token = part.casefold()
        if token.startswith("port:"):
            updated_parts.append(f"port:{normalized_port}")
            has_port = True
            continue
        if token.startswith("guid:"):
            if guid and not strip_guid and not has_guid:
                updated_parts.append(f"guid:{guid}")
                has_guid = True
            continue
        updated_parts.append(part)
        if token == "engine:sdl" and guid and not strip_guid:
            updated_parts.append(f"guid:{guid}")
            has_guid = True
            inserted_guid_after_engine = True
    if guid and not strip_guid and not has_guid and not inserted_guid_after_engine:
        updated_parts.append(f"guid:{guid}")
    if not has_port:
        updated_parts.append(f"port:{normalized_port}")
    payload = ",".join(updated_parts)
    return f'"{payload}"' if quote else payload
