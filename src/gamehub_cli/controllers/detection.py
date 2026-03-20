from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from . import linux_input_devices, xinput
from .sdl_guid import _discover_host_sdl_joysticks

_STEAMOS_RELEASE_PATH = Path("/etc/os-release")
_DMI_BOARD_VENDOR_PATH = Path("/sys/devices/virtual/dmi/id/board_vendor")
_LINUX_NON_GAMEPAD_NAME_MARKERS = (
    "motion sensor",
    "motion sensors",
    "accelerometer",
    "gyroscope",
    "gyro",
    "imu",
)

_MICROSOFT_VENDOR_ID = 0x045E


@dataclass(frozen=True)
class XboxController:
    slot: int
    name: str
    subtype: int | None = None
    guid: str | None = None
    vendor_id: int | None = None
    product_id: int | None = None


def _is_steam_deck_linux() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        os_release = _STEAMOS_RELEASE_PATH.read_text(encoding="utf-8", errors="ignore").casefold()
    except OSError:
        os_release = ""
    if "id=steamos" in os_release or "steamdeck" in os_release or "holo" in os_release:
        return True
    try:
        vendor = _DMI_BOARD_VENDOR_PATH.read_text(encoding="utf-8", errors="ignore").strip().casefold()
    except OSError:
        vendor = ""
    return "valve" in vendor


def _is_supported_linux_controller_name(name: str, *, include_steam_deck: bool) -> bool:
    normalized = name.casefold()
    if any(marker in normalized for marker in _LINUX_NON_GAMEPAD_NAME_MARKERS):
        return False
    if any(marker in normalized for marker in ("xbox", "x-box", "xinput")):
        return True
    if not include_steam_deck:
        return False
    return any(
        marker in normalized
        for marker in (
            "steam deck",
            "steam virtual gamepad",
            "steam controller",
            "valve software",
            "neptune controller",
        )
    )


def _linux_xbox_controllers_from_records(
    records: list[linux_input_devices.LinuxInputDeviceRecord],
    *,
    max_devices: int,
    include_steam_deck: bool = False,
) -> list[XboxController]:
    by_js_index: dict[int, str] = {}
    for record in records:
        if not _is_supported_linux_controller_name(record.name, include_steam_deck=include_steam_deck):
            continue
        for js_index in record.js_indices:
            by_js_index.setdefault(js_index, record.name)

    controllers: list[XboxController] = []
    for js_index in sorted(by_js_index):
        controllers.append(XboxController(slot=js_index, name=by_js_index[js_index], subtype=None))
        if len(controllers) >= max_devices:
            break
    return controllers


def _linux_parse_xbox_devices(raw: str, *, max_devices: int, include_steam_deck: bool = False) -> list[XboxController]:
    records = linux_input_devices.parse_linux_input_device_records(raw)
    return _linux_xbox_controllers_from_records(records, max_devices=max_devices, include_steam_deck=include_steam_deck)


def _detect_linux_xbox_controllers(*, max_devices: int) -> list[XboxController]:
    try:
        records = linux_input_devices.read_linux_input_device_records()
    except OSError:
        return []
    return _linux_xbox_controllers_from_records(
        records, max_devices=max_devices, include_steam_deck=_is_steam_deck_linux()
    )


def _detect_windows_xbox_controllers(*, max_devices: int) -> list[XboxController]:
    lib = xinput.load_xinput()
    if lib is None:
        return []

    controllers: list[XboxController] = []
    for slot in range(4):
        state = xinput.read_xinput_state(lib, slot=slot)
        if state is None:
            continue
        subtype = xinput.read_xinput_subtype(lib, slot=slot)
        controllers.append(XboxController(slot=slot, name=f"XInput/{slot}", subtype=subtype))
        if len(controllers) >= max_devices:
            break
    return controllers


def _is_supported_macos_controller_name(name: str) -> bool:
    normalized = name.casefold()
    if any(marker in normalized for marker in _LINUX_NON_GAMEPAD_NAME_MARKERS):
        return False
    return any(marker in normalized for marker in ("xbox", "x-box", "xinput"))


def _macos_guid_vendor_id(guid: str | None) -> int | None:
    if guid is None:
        return None
    normalized = guid.strip()
    if len(normalized) != 32:
        return None
    try:
        raw_guid = bytes.fromhex(normalized)
    except ValueError:
        return None
    if len(raw_guid) < 6:
        return None
    return int.from_bytes(raw_guid[4:6], "little")


def _is_supported_macos_controller(device: object) -> bool:
    name = str(getattr(device, "name", "")).strip()
    normalized = name.casefold()
    if any(marker in normalized for marker in _LINUX_NON_GAMEPAD_NAME_MARKERS):
        return False
    if _is_supported_macos_controller_name(name):
        return True
    vendor_id = getattr(device, "vendor_id", None)
    if vendor_id == _MICROSOFT_VENDOR_ID:
        return True
    if vendor_id is None and _macos_guid_vendor_id(getattr(device, "guid", None)) == _MICROSOFT_VENDOR_ID:
        return True
    return False


def _detect_macos_xbox_controllers(*, max_devices: int) -> list[XboxController]:
    try:
        devices = _discover_host_sdl_joysticks()
    except Exception:
        return []
    controllers: list[XboxController] = []
    ordered_devices = sorted(
        devices,
        key=lambda device: (
            int(getattr(device, "slot", 0)),
            str(getattr(device, "name", "")).casefold(),
        ),
    )
    for device in ordered_devices:
        if not _is_supported_macos_controller(device):
            continue
        controllers.append(
            XboxController(
                slot=device.slot,
                name=device.name,
                subtype=None,
                guid=getattr(device, "guid", None),
                vendor_id=getattr(device, "vendor_id", None),
                product_id=getattr(device, "product_id", None),
            )
        )
        if len(controllers) >= max_devices:
            break
    return controllers


def is_steam_deck_linux() -> bool:
    return _is_steam_deck_linux()


def detect_xbox_controllers(*, max_devices: int = 2) -> list[XboxController]:
    if max_devices < 1:
        return []
    if sys.platform.startswith("linux"):
        return _detect_linux_xbox_controllers(max_devices=max_devices)
    if sys.platform.startswith("win"):
        return _detect_windows_xbox_controllers(max_devices=max_devices)
    if sys.platform == "darwin":
        return _detect_macos_xbox_controllers(max_devices=max_devices)
    return []
