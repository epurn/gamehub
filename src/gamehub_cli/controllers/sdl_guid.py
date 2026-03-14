from __future__ import annotations

import ctypes
import ctypes.util
import json
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
_MACOS_SYSTEM_PROFILER_EXECUTABLE = "/usr/sbin/system_profiler"
_MACOS_SYSTEM_PROFILER_TIMEOUT_SEC = 2.0
_MACOS_SYSTEM_PROFILER_GENERIC_NAMES = {"controller", "controllers", "game controller", "game controllers"}
_MACOS_HIDUTIL_EXECUTABLE = "/usr/bin/hidutil"
_MACOS_HIDUTIL_TIMEOUT_SEC = 2.0
_MACOS_HIDUTIL_GAMEPAD_USAGES = {4, 5}
_MACOS_STRINGS_EXECUTABLE = "/usr/bin/strings"
_MACOS_STRINGS_TIMEOUT_SEC = 4.0
_SDL_MAPPING_LINE_RE = re.compile(r"^(?P<guid>[0-9a-fA-F]{32}),(?P<name>[^,]+),(?P<body>.+)$")
_MACOS_EMBEDDED_SDL_MAPPING_CACHE: dict[tuple[str, int, int], list["_SDLControllerMapping"]] = {}


class _SDLJoystickGUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_uint8 * 16)]


@dataclass(frozen=True)
class _SDLJoystickDevice:
    slot: int
    name: str
    guid: str | None
    is_game_controller: bool | None = None
    vendor_id: int | None = None
    product_id: int | None = None
    transport: str | None = None


@dataclass(frozen=True)
class _SDLControllerMapping:
    guid: str
    name: str
    vendor_id: int | None
    product_id: int | None
    version: int | None
    fields: dict[str, str]


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
    return [candidate.parent for candidate in _candidate_executables_from_emulators()]


def _candidate_executables_from_emulators() -> list[Path]:
    try:
        from ..emulators import resolve_emulator_executable
    except Exception:
        return []
    executables: list[Path] = []
    for emulator_name in ("azahar", "retroarch", "dolphin", "pcsx2"):
        raw = str(resolve_emulator_executable(emulator_name)).strip('"')
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.exists() and candidate.is_file():
            executables.append(candidate)
    return executables


def _append_library_candidate(candidates: list[str], value: str | Path) -> None:
    rendered = str(value)
    if rendered and rendered not in candidates:
        candidates.append(rendered)


def _append_library_candidates_from_dirs(
    candidates: list[str],
    directories: list[Path],
    filenames: tuple[str, ...],
) -> None:
    for candidate_dir in directories:
        for filename in filenames:
            candidate = candidate_dir / filename
            if candidate.exists():
                _append_library_candidate(candidates, candidate)


def _windows_sdl_library_candidates() -> list[str]:
    library_candidates: list[str] = []
    env_dir = os.environ.get(_AZAHAR_WINDOWS_SDL_DIR_ENV)
    if env_dir:
        env_path = Path(env_dir.strip().strip('"'))
        if env_path.is_file():
            _append_library_candidate(library_candidates, env_path)
        else:
            for dll_name in ("SDL2.dll", "libSDL2-2.0.dll", "libSDL2.dll"):
                candidate = env_path / dll_name
                if candidate.exists():
                    _append_library_candidate(library_candidates, candidate)
    _append_library_candidates_from_dirs(
        library_candidates,
        _candidate_dirs_from_emulators(),
        ("SDL2.dll", "libSDL2-2.0.dll", "libSDL2.dll"),
    )
    detected = ctypes.util.find_library("SDL2")
    if detected:
        _append_library_candidate(library_candidates, detected)
    for dll_name in ("SDL2.dll", "libSDL2-2.0.dll", "libSDL2.dll"):
        _append_library_candidate(library_candidates, dll_name)
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
    emulator_dirs = _candidate_dirs_from_emulators()
    bundle_framework_dirs = [candidate_dir.parent / "Frameworks" for candidate_dir in emulator_dirs]
    _append_library_candidates_from_dirs(
        library_candidates,
        bundle_framework_dirs,
        (
            "SDL2.framework/Versions/A/SDL2",
            "libSDL2-2.0.0.dylib",
            "libSDL2.dylib",
        ),
    )
    _append_library_candidates_from_dirs(
        library_candidates,
        emulator_dirs,
        ("libSDL2-2.0.0.dylib", "libSDL2.dylib"),
    )
    detected = ctypes.util.find_library("SDL2")
    if detected:
        _append_library_candidate(library_candidates, detected)
    for candidate in (
        "/Library/Frameworks/SDL2.framework/Versions/A/SDL2",
        "/opt/homebrew/lib/libSDL2-2.0.0.dylib",
        "/usr/local/lib/libSDL2-2.0.0.dylib",
        "libSDL2-2.0.0.dylib",
        "libSDL2.dylib",
        "SDL2",
    ):
        _append_library_candidate(library_candidates, candidate)
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
    is_game_controller = getattr(sdl, "SDL_IsGameController", None)
    if is_game_controller is not None:
        is_game_controller.argtypes = [ctypes.c_int]
        is_game_controller.restype = ctypes.c_int
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
        is_game_controller = getattr(sdl, "SDL_IsGameController", None)
        for slot in range(count):
            if max_devices is not None and len(devices) >= max_devices:
                break
            name_raw = sdl.SDL_JoystickNameForIndex(slot)
            name = name_raw.decode("utf-8", errors="ignore").strip() if name_raw else ""
            guid_value = sdl.SDL_JoystickGetDeviceGUID(slot)
            text = ctypes.create_string_buffer(33)
            sdl.SDL_JoystickGetGUIDString(guid_value, text, len(text))
            guid = _normalize_sdl_guid(text.value.decode("ascii", errors="ignore"))
            device_is_game_controller = bool(is_game_controller(slot)) if is_game_controller is not None else None
            devices.append(
                _SDLJoystickDevice(
                    slot=slot,
                    name=name,
                    guid=guid,
                    is_game_controller=device_is_game_controller,
                )
            )
        return devices
    finally:
        sdl.SDL_Quit()


def _macos_system_profiler_device_name(node: object) -> str | None:
    if not isinstance(node, dict):
        return None
    raw_name = node.get("_name")
    if not isinstance(raw_name, str):
        return None
    normalized = raw_name.strip()
    if not normalized:
        return None
    if normalized.casefold() in _MACOS_SYSTEM_PROFILER_GENERIC_NAMES:
        return None
    return normalized


def _collect_macos_system_profiler_devices(
    node: object,
    *,
    devices: list[_SDLJoystickDevice],
    max_devices: int | None = None,
) -> None:
    if max_devices is not None and len(devices) >= max_devices:
        return
    if isinstance(node, list):
        for item in node:
            _collect_macos_system_profiler_devices(item, devices=devices, max_devices=max_devices)
            if max_devices is not None and len(devices) >= max_devices:
                return
        return
    if not isinstance(node, dict):
        return

    children = node.get("_items")
    if isinstance(children, list) and children:
        _collect_macos_system_profiler_devices(children, devices=devices, max_devices=max_devices)
        if max_devices is not None and len(devices) >= max_devices:
            return

    name = _macos_system_profiler_device_name(node)
    if name is None:
        return
    if isinstance(children, list) and children:
        return
    devices.append(_SDLJoystickDevice(slot=len(devices), name=name, guid=None, is_game_controller=True))


def _parse_macos_system_profiler_game_controllers(
    text: str,
    *,
    max_devices: int | None = None,
) -> list[_SDLJoystickDevice]:
    payload_text = text.strip()
    if not payload_text:
        return []
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return []

    devices: list[_SDLJoystickDevice] = []
    root = payload.get("SPGameControllerDataType", payload) if isinstance(payload, dict) else payload
    _collect_macos_system_profiler_devices(root, devices=devices, max_devices=max_devices)
    return devices


def _discover_macos_system_profiler_joysticks(
    *,
    max_devices: int | None = None,
    timeout_sec: float = _MACOS_SYSTEM_PROFILER_TIMEOUT_SEC,
) -> list[_SDLJoystickDevice]:
    if sys.platform != "darwin":
        return []
    executable = Path(_MACOS_SYSTEM_PROFILER_EXECUTABLE)
    if not executable.exists():
        return []
    try:
        completed = subprocess.run(
            [str(executable), "SPGameControllerDataType", "-detailLevel", "mini", "-json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    return _parse_macos_system_profiler_game_controllers(completed.stdout, max_devices=max_devices)


def _parse_macos_hidutil_joysticks(text: str, *, max_devices: int | None = None) -> list[_SDLJoystickDevice]:
    lines = [line.rstrip("\n") for line in text.splitlines() if line.strip()]
    header_line = next((line for line in lines if line.lstrip().startswith("VendorID ")), None)
    if header_line is None:
        return []

    header_tokens = list(re.finditer(r"\S+", header_line))
    if len(header_tokens) < 11:
        return []
    column_names = [token.group(0) for token in header_tokens]
    column_starts = [token.start() for token in header_tokens]
    devices: list[_SDLJoystickDevice] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "Devices:" or line == header_line:
            continue
        if max_devices is not None and len(devices) >= max_devices:
            break
        values: dict[str, str] = {}
        for index, name in enumerate(column_names):
            start = column_starts[index]
            end = column_starts[index + 1] if index + 1 < len(column_starts) else None
            values[name] = line[start:end].strip()
        try:
            usage_page = int(values.get("UsagePage", "0"), 10)
            usage = int(values.get("Usage", "0"), 10)
        except ValueError:
            continue
        if usage_page != 1 or usage not in _MACOS_HIDUTIL_GAMEPAD_USAGES:
            continue
        if values.get("Built-In") == "1":
            continue
        product = values.get("Product", "").strip()
        if not product:
            continue
        try:
            vendor_id = int(values.get("VendorID", "0"), 16)
        except ValueError:
            vendor_id = None
        try:
            product_id = int(values.get("ProductID", "0"), 16)
        except ValueError:
            product_id = None
        transport = values.get("Transport", "").strip() or None
        devices.append(
            _SDLJoystickDevice(
                slot=len(devices),
                name=product,
                guid=None,
                is_game_controller=True,
                vendor_id=vendor_id,
                product_id=product_id,
                transport=transport,
            )
        )
    return devices


def _parse_sdl_controller_mapping_line(line: str) -> _SDLControllerMapping | None:
    match = _SDL_MAPPING_LINE_RE.match(line.strip())
    if match is None:
        return None
    guid = _normalize_sdl_guid(match.group("guid"))
    name = match.group("name").strip()
    if guid is None or not name:
        return None
    fields: dict[str, str] = {}
    for token in match.group("body").split(","):
        stripped = token.strip()
        if not stripped or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip().casefold()
        value = value.strip()
        if not key or key in fields:
            continue
        fields[key] = value
    try:
        raw_guid = bytes.fromhex(guid)
    except ValueError:
        return None
    vendor_id = int.from_bytes(raw_guid[4:6], "little") if len(raw_guid) >= 6 else None
    product_id = int.from_bytes(raw_guid[8:10], "little") if len(raw_guid) >= 10 else None
    version = int.from_bytes(raw_guid[12:14], "little") if len(raw_guid) >= 14 else None
    return _SDLControllerMapping(
        guid=guid,
        name=name,
        vendor_id=vendor_id,
        product_id=product_id,
        version=version,
        fields=fields,
    )


def _load_macos_embedded_sdl_mappings(
    executable_path: Path,
    *,
    timeout_sec: float = _MACOS_STRINGS_TIMEOUT_SEC,
) -> list[_SDLControllerMapping]:
    candidate = executable_path.expanduser()
    if sys.platform != "darwin" or not candidate.is_file():
        return []
    strings_executable = Path(_MACOS_STRINGS_EXECUTABLE)
    if not strings_executable.exists():
        return []
    try:
        stat = candidate.stat()
    except OSError:
        return []
    cache_key = (str(candidate), int(stat.st_mtime_ns), int(stat.st_size))
    cached = _MACOS_EMBEDDED_SDL_MAPPING_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        completed = subprocess.run(
            [str(strings_executable), str(candidate)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    mappings: list[_SDLControllerMapping] = []
    seen: set[tuple[str, str]] = set()
    for line in completed.stdout.splitlines():
        mapping = _parse_sdl_controller_mapping_line(line)
        if mapping is None:
            continue
        key = (mapping.guid, mapping.name.casefold())
        if key in seen:
            continue
        seen.add(key)
        mappings.append(mapping)
    _MACOS_EMBEDDED_SDL_MAPPING_CACHE[cache_key] = mappings
    return mappings


def _select_macos_embedded_sdl_mapping(
    mappings: list[_SDLControllerMapping],
    *,
    name: str,
    vendor_id: int | None = None,
    product_id: int | None = None,
) -> _SDLControllerMapping | None:
    normalized_name = name.strip().casefold()
    if not normalized_name and vendor_id is None and product_id is None:
        return None

    def _sort_key(mapping: _SDLControllerMapping) -> tuple[int, int]:
        if product_id is None or mapping.product_id is None:
            distance = 0
        else:
            distance = abs(mapping.product_id - product_id)
        return (distance, -(mapping.version or 0))

    def _select_best(candidates: list[_SDLControllerMapping]) -> _SDLControllerMapping | None:
        if not candidates:
            return None
        if product_id is not None:
            exact_product = [mapping for mapping in candidates if mapping.product_id == product_id]
            if exact_product:
                return max(exact_product, key=lambda mapping: mapping.version or 0)
        return min(candidates, key=_sort_key)

    if vendor_id is not None and product_id is not None:
        exact_identity = [
            mapping for mapping in mappings if mapping.vendor_id == vendor_id and mapping.product_id == product_id
        ]
        if exact_identity:
            exact_named_identity = [mapping for mapping in exact_identity if mapping.name.casefold() == normalized_name]
            return _select_best(exact_named_identity or exact_identity)

    named = [mapping for mapping in mappings if mapping.name.casefold() == normalized_name]
    if named:
        vendor_matched = named
        if vendor_id is not None:
            exact_vendor = [mapping for mapping in named if mapping.vendor_id == vendor_id]
            if exact_vendor:
                vendor_matched = exact_vendor
        return _select_best(vendor_matched)

    # Fail open when we cannot prove identity; guessing another controller DB
    # entry here silently rewrites the wrong GUID/button layout downstream.
    return None


def _lookup_macos_embedded_sdl_mapping_for_identity(
    *,
    name: str,
    vendor_id: int | None = None,
    product_id: int | None = None,
) -> _SDLControllerMapping | None:
    for executable_path in _candidate_executables_from_emulators():
        mappings = _load_macos_embedded_sdl_mappings(executable_path)
        selected = _select_macos_embedded_sdl_mapping(
            mappings,
            name=name,
            vendor_id=vendor_id,
            product_id=product_id,
        )
        if selected is not None:
            return selected
    return None


def _lookup_macos_embedded_sdl_guid_for_identity(
    *,
    name: str,
    vendor_id: int | None = None,
    product_id: int | None = None,
) -> str | None:
    mapping = _lookup_macos_embedded_sdl_mapping_for_identity(
        name=name,
        vendor_id=vendor_id,
        product_id=product_id,
    )
    if mapping is None:
        return None
    return mapping.guid


def _lookup_macos_embedded_sdl_mapping_for_port(*, port: int) -> _SDLControllerMapping | None:
    if sys.platform != "darwin" or port < 0:
        return None
    for device in _discover_host_sdl_joysticks(max_devices=port + 1):
        if device.slot != port:
            continue
        return _lookup_macos_embedded_sdl_mapping_for_identity(
            name=device.name,
            vendor_id=device.vendor_id,
            product_id=device.product_id,
        )
    return None


def _discover_macos_hidutil_joysticks(
    *,
    max_devices: int | None = None,
    timeout_sec: float = _MACOS_HIDUTIL_TIMEOUT_SEC,
) -> list[_SDLJoystickDevice]:
    if sys.platform != "darwin":
        return []
    executable = Path(_MACOS_HIDUTIL_EXECUTABLE)
    if not executable.exists():
        return []
    try:
        completed = subprocess.run(
            [str(executable), "list", "--matching", '{"DeviceUsagePage":1}'],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    return _parse_macos_hidutil_joysticks(completed.stdout, max_devices=max_devices)


def _discover_host_sdl_joysticks(*, max_devices: int | None = None) -> list[_SDLJoystickDevice]:
    if sys.platform.startswith("linux"):
        return _enumerate_sdl_joysticks(_linux_sdl_library_candidates(), max_devices=max_devices)
    if sys.platform.startswith("win"):
        return _enumerate_sdl_joysticks(_windows_sdl_library_candidates(), max_devices=max_devices)
    if sys.platform == "darwin":
        devices = _enumerate_sdl_joysticks(_macos_sdl_library_candidates(), max_devices=max_devices)
        if devices:
            return devices
        devices = _discover_macos_system_profiler_joysticks(max_devices=max_devices)
        if devices:
            return devices
        return _discover_macos_hidutil_joysticks(max_devices=max_devices)
    return []


def _discover_sdl_guid(*, port: int) -> str | None:
    if port < 0:
        return None
    for device in _discover_host_sdl_joysticks(max_devices=port + 1):
        if device.slot == port:
            if device.guid is not None:
                return device.guid
            if sys.platform == "darwin":
                return _lookup_macos_embedded_sdl_guid_for_identity(
                    name=device.name,
                    vendor_id=device.vendor_id,
                    product_id=device.product_id,
                )
            return None
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
