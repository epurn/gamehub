from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse

from ..common.http import open_url
from . import install_common
from .resolution import _is_emulator_available, _resolve_winget_command, resolve_emulator_executable

_WINGET_ID_CANDIDATES = {
    "retroarch": ("Libretro.RetroArch",),
    "pcsx2": ("PCSX2Team.PCSX2",),
}

_DOLPHIN_DOWNLOAD_PAGE_URL = "https://dolphin-emu.org/download/"
_DOLPHIN_WINGET_PATH_VERSION_RE = re.compile(r"(?i)dolphin(?:emu|emulator)\.dolphin_(?P<value>[^\\/_]+)")
_DOLPHIN_WINDOWS_ARCHIVE_URL_RE = re.compile(
    r"https://dl\.dolphin-emu\.org/releases/(?P<version>\d+)/dolphin-(?P=version)-x64\.7z",
    re.IGNORECASE,
)
_AZAHAR_WINDOWS_DEFAULT_INSTALLER_URL = (
    "https://github.com/azahar-emu/azahar/releases/download/2124.3/azahar-2124.3-windows-msys2-installer.exe"
)
_AZAHAR_WINDOWS_INSTALLER_URL_ENV = "GAMEHUB_AZAHAR_WINDOWS_INSTALLER_URL"
_AZAHAR_WINDOWS_SILENT_INSTALL_FLAGS: tuple[tuple[str, ...], ...] = (
    ("/S",),
    ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"),
    ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"),
)


def _latest_dolphin_windows_archive_url() -> tuple[str | None, str | None]:
    try:
        with open_url(_DOLPHIN_DOWNLOAD_PAGE_URL, timeout=20) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except (URLError, TimeoutError, OSError):
        return None, None
    candidates = _DOLPHIN_WINDOWS_ARCHIVE_URL_RE.findall(html)
    if not candidates:
        return None, None
    version = max(candidates, key=lambda item: install_common._version_key(item))
    url = f"https://dl.dolphin-emu.org/releases/{version}/dolphin-{version}-x64.7z"
    return url, version


def _required_has_dolphin(required: list[str]) -> bool:
    for value in required:
        normalized = value.strip().strip('"').casefold()
        if normalized in {"dolphin", "dolphin-emu"}:
            return True
    return False


def _validate_windows_dolphin_runtime(required: list[str]) -> None:
    if install_common._OS_NAME != "nt":
        return
    if not _required_has_dolphin(required):
        return
    if not _is_emulator_available("dolphin"):
        return
    resolved = resolve_emulator_executable("dolphin").strip().strip('"')
    if not resolved:
        return
    normalized = resolved.replace("/", "\\")
    match = _DOLPHIN_WINGET_PATH_VERSION_RE.search(normalized)
    if match is None:
        return
    version_text = match.group("value").strip()
    legacy = install_common._is_version_at_or_below_5_0(version_text)
    if legacy is not True:
        return
    raise RuntimeError(
        "Unsupported legacy Dolphin build detected "
        f"({resolved}, version={version_text}). "
        "Install a modern Dolphin build (newer than 5.0) and re-run sync."
    )


def _install_dolphin_from_official_release_archive(*, verbose: bool) -> bool:
    if install_common._OS_NAME != "nt":
        return False
    archive_url, version = _latest_dolphin_windows_archive_url()
    if not archive_url or not version:
        return False
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        install_root = install_common._safe_path(local_app_data) / "Programs" / "Dolphin"
    else:
        install_root = install_common._HOST_PATH_TYPE.home() / "AppData" / "Local" / "Programs" / "Dolphin"

    with tempfile.TemporaryDirectory(prefix="gamehub-dolphin-release-") as temp_dir:
        temp_root = install_common._safe_path(temp_dir)
        archive_path = temp_root / f"dolphin-{version}-x64.7z"
        extract_root = temp_root / "extract"
        extract_root.mkdir(parents=True, exist_ok=True)
        try:
            with open_url(archive_url, timeout=60) as response:
                archive_path.write_bytes(response.read())
        except (URLError, TimeoutError, OSError):
            return False

        try:
            tar_result = subprocess.run(
                ["tar", "-xf", str(archive_path), "-C", str(extract_root)],
                check=False,
                capture_output=not verbose,
                text=True,
            )
        except OSError:
            return False
        if tar_result.returncode != 0:
            return False
        exe_candidates = sorted(extract_root.rglob("Dolphin.exe"), key=lambda item: len(item.parts))
        if not exe_candidates:
            return False
        source_root = exe_candidates[0].parent
        try:
            install_root.parent.mkdir(parents=True, exist_ok=True)
            if install_root.exists():
                shutil.rmtree(install_root)
            shutil.copytree(source_root, install_root)
        except OSError:
            return False
    return (install_root / "Dolphin.exe").exists()


def _azahar_windows_installer_url() -> str:
    override = os.environ.get(_AZAHAR_WINDOWS_INSTALLER_URL_ENV, "").strip()
    return override or _AZAHAR_WINDOWS_DEFAULT_INSTALLER_URL


def _download_azahar_windows_installer(url: str) -> Path | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    filename = parsed.path.rsplit("/", 1)[-1].strip() or "azahar-windows-installer.exe"
    if not filename.casefold().endswith(".exe"):
        filename = f"{filename}.exe"
    cache_dir = install_common._safe_path(tempfile.gettempdir()) / "gamehub-azahar-installer-cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        installer_path = cache_dir / filename
        with open_url(url, timeout=120) as response:
            installer_path.write_bytes(response.read())
    except (URLError, TimeoutError, OSError):
        return None
    return installer_path


def _install_azahar_from_windows_installer(*, verbose: bool) -> tuple[bool, Path | None, str]:
    if install_common._OS_NAME != "nt":
        return False, None, ""
    installer_url = _azahar_windows_installer_url()
    installer_path = _download_azahar_windows_installer(installer_url)
    if installer_path is None:
        return False, None, installer_url
    if _is_emulator_available("azahar"):
        return True, installer_path, installer_url
    for flags in _AZAHAR_WINDOWS_SILENT_INSTALL_FLAGS:
        result = install_common._run_install_command([str(installer_path), *flags], verbose=verbose)
        if result == install_common._WINERROR_ELEVATION_REQUIRED:
            print("Azahar installer requires administrator elevation. Accept the UAC prompt to continue.")
            result = install_common._run_windows_elevated_command(installer_path, flags, verbose=verbose)
        if result == 0 and _is_emulator_available("azahar"):
            return True, installer_path, installer_url
        if _is_emulator_available("azahar"):
            return True, installer_path, installer_url
    return False, installer_path, installer_url


def _install_windows(missing: list[str], *, verbose: bool) -> None:
    winget_cmd = _resolve_winget_command()

    for emulator in missing:
        if emulator.lower() == "dolphin":
            print("Installing emulator 'dolphin' via official Dolphin release archive...")
            archive_ok = _install_dolphin_from_official_release_archive(verbose=verbose)
            if archive_ok and _is_emulator_available("dolphin"):
                print("Installed emulator: dolphin")
                continue
            if archive_ok:
                print("Warning: Dolphin archive install completed but Dolphin executable was not detected.")
            else:
                print("Warning: official Dolphin release archive install failed.")
            print("Warning: install the latest Dolphin manually from dolphin-emu.org and re-run sync.")
            continue
        if emulator.lower() == "azahar":
            print("Installing emulator 'azahar' via GitHub release installer...")
            installed, installer_path, installer_url = _install_azahar_from_windows_installer(verbose=verbose)
            if installed and _is_emulator_available("azahar"):
                print("Installed emulator: azahar")
                continue
            if installer_path is not None:
                print("Warning: automatic silent Azahar install failed.")
                installer_path_display = str(installer_path).replace("\\", "/")
                print(f"Warning: run installer manually: {installer_path_display}")
            else:
                print("Warning: Azahar installer download failed.")
            print(f"Warning: install Azahar manually from {installer_url} and re-run sync.")
            continue

        winget_ids = _WINGET_ID_CANDIDATES.get(emulator.lower())
        if not winget_ids:
            print(f"No installer mapping for emulator '{emulator}'; install it manually")
            continue
        if winget_cmd is None:
            print("winget not found; cannot auto-install missing emulators")
            continue
        last_result = 0
        installed = False
        for idx, winget_id in enumerate(winget_ids, start=1):
            print(f"Installing emulator '{emulator}' via winget ({winget_id})...")
            result = install_common._run_install_command(
                [
                    winget_cmd,
                    "install",
                    "--id",
                    winget_id,
                    "-e",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                    "--silent",
                ],
                verbose=verbose,
            )
            last_result = result
            if result == 0:
                if not _is_emulator_available(emulator):
                    print(f"Warning: {emulator} install command completed but executable not found yet")
                    continue
                print(f"Installed emulator: {emulator}")
                installed = True
                break
            if _is_emulator_available(emulator):
                print(f"Detected installed emulator despite winget non-zero exit: {emulator}")
                installed = True
                break
            if idx < len(winget_ids):
                print(
                    f"Warning: winget install failed for {emulator} via {winget_id} (exit {result}); trying fallback id."
                )

        if not installed:
            print(
                f"Warning: winget install failed for {emulator} (exit {last_result}). Install manually and re-run sync."
            )
