from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import install_common
from .resolution import _canonical_emulator_name, _is_emulator_available

_FLATPAK_APP_IDS = {
    "retroarch": "org.libretro.RetroArch",
    "pcsx2": "net.pcsx2.PCSX2",
    "dolphin": "org.DolphinEmu.dolphin-emu",
    "azahar": "org.azahar_emu.Azahar",
}
_FLATPAK_FORCED_EMULATORS = frozenset({"dolphin", "azahar"})
_IMMUTABLE_DISTRO_HINTS = (
    "atomic",
    "aurora",
    "bazzite",
    "bluefin",
    "kinoite",
    "silverblue",
    "steamdeck",
    "steamos",
    "ublue",
)


def _canonical_emulator_key(value: str) -> str:
    normalized = _canonical_emulator_name(value)
    if normalized in _FLATPAK_APP_IDS:
        return normalized
    compact = value.strip().strip('"').casefold()
    for key in _FLATPAK_APP_IDS:
        if compact == key:
            return key
        if compact.startswith(f"{key}-") or compact.startswith(f"{key}_"):
            return key
    return normalized


def _flatpak_remotes() -> list[str]:
    completed = subprocess.run(
        ["flatpak", "remotes", "--columns=name"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return []
    values: list[str] = []
    for line in completed.stdout.splitlines():
        item = line.strip()
        if not item:
            continue
        if item.casefold() in {"name", "names"}:
            continue
        values.append(item)
    return values


def _flatpak_app_export_candidates(app_id: str) -> tuple[Path, ...]:
    return (
        install_common._HOST_PATH_TYPE.home() / ".local" / "share" / "flatpak" / "exports" / "bin" / app_id,
        install_common._safe_path("/var/lib/flatpak/exports/bin") / app_id,
    )


def _is_flatpak_app_available(app_id: str) -> bool:
    if any(candidate.exists() for candidate in _flatpak_app_export_candidates(app_id)):
        return True
    if shutil.which(app_id) is not None:
        return True
    if shutil.which("flatpak") is None:
        return False
    completed = subprocess.run(
        ["flatpak", "info", "--show-ref", app_id],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def _prefer_flatpak_for_auto_backend(dist_id: str) -> bool:
    normalized = dist_id.casefold()
    if any(hint in normalized for hint in _IMMUTABLE_DISTRO_HINTS):
        return True
    for marker in (install_common._safe_path("/run/ostree-booted"), install_common._safe_path("/sysroot/ostree")):
        try:
            if marker.exists():
                return True
        except OSError:
            continue
    return False


def _flatpak_preferred_linux_backend(backend: str, dist_id: str) -> bool:
    if backend == "flatpak":
        return True
    if backend in {"auto", ""} and _prefer_flatpak_for_auto_backend(dist_id):
        return True
    return False


def _install_flatpak(missing: list[str], *, verbose: bool, remote: str | None = None) -> None:
    if shutil.which("flatpak") is None:
        print("flatpak not found; cannot auto-install missing emulators via flatpak")
        return

    configured_remote = (remote or "").strip() or None
    remotes = _flatpak_remotes()
    if configured_remote and configured_remote not in remotes:
        print(
            f"Configured flatpak remote '{configured_remote}' is not available. "
            f"Known remotes: {', '.join(remotes) if remotes else '<none>'}"
        )
        return

    for emulator in missing:
        app_id = _FLATPAK_APP_IDS.get(_canonical_emulator_key(emulator))
        if not app_id:
            print(f"No flatpak mapping for emulator '{emulator}'; install it manually")
            continue
        print(f"Installing emulator '{emulator}' via flatpak ({app_id})...")
        command_candidates: list[list[str]] = []
        if configured_remote:
            command_candidates.append(["flatpak", "install", "--user", "-y", configured_remote, app_id])
        command_candidates.append(["flatpak", "install", "--user", "-y", app_id])
        deduped_commands: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()
        for command in command_candidates:
            key = tuple(command)
            if key in seen:
                continue
            seen.add(key)
            deduped_commands.append(command)

        success = False
        result = 0
        for position, command in enumerate(deduped_commands):
            result = install_common._run_install_command(command, verbose=verbose)
            if result == 0:
                success = True
                break
            if configured_remote and position == 0 and len(deduped_commands) > 1:
                print(
                    "Warning: flatpak install via configured remote failed; retrying with automatic remote resolution."
                )

        if not success:
            if not remotes:
                print(
                    "Warning: flatpak install failed and no remotes are configured. "
                    "Add one (for example: flatpak remote-add --if-not-exists flathub "
                    "https://flathub.org/repo/flathub.flatpakrepo)."
                )
            elif configured_remote:
                print(
                    "Warning: flatpak install failed for configured remote "
                    f"'{configured_remote}'. This remote may be filtered on your distro."
                )
            print(f"Warning: flatpak install failed for {emulator} (exit {result}). Install manually and re-run sync.")
            continue
        if _is_emulator_available(emulator):
            print(f"Installed emulator: {emulator}")
        else:
            print(f"Warning: {emulator} install command completed but executable not found yet")
