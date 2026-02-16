from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.error import URLError
from urllib.request import urlopen

from gamehub_common.models import LibraryIndex

from .emulator_resolution import (
    _is_emulator_available,
    _linux_dist_id,
    _required_emulators,
    _resolve_winget_command,
    resolve_emulator_executable,
)

_WINGET_ID_CANDIDATES = {
    "retroarch": ("Libretro.RetroArch",),
    "pcsx2": ("PCSX2Team.PCSX2",),
}

_DNF_PACKAGES = {
    "retroarch": "retroarch",
    "pcsx2": "pcsx2",
    "dolphin": "dolphin-emu",
}

_APT_PACKAGES = {
    "retroarch": "retroarch",
    "pcsx2": "pcsx2",
    "dolphin": "dolphin-emu",
}

_FLATPAK_APP_IDS = {
    "retroarch": "org.libretro.RetroArch",
    "pcsx2": "net.pcsx2.PCSX2",
    "dolphin": "org.DolphinEmu.dolphin-emu",
}
_FLATPAK_FORCED_EMULATORS = frozenset({"dolphin"})
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
_DOLPHIN_DOWNLOAD_PAGE_URL = "https://dolphin-emu.org/download/"
_DOLPHIN_WINGET_PATH_VERSION_RE = re.compile(r"(?i)dolphin(?:emu|emulator)\.dolphin_(?P<value>[^\\/_]+)")
_DOLPHIN_WINDOWS_ARCHIVE_URL_RE = re.compile(
    r"https://dl\.dolphin-emu\.org/releases/(?P<version>\d+)/dolphin-(?P=version)-x64\.7z",
    re.IGNORECASE,
)


def _run_install_command(command: list[str], *, verbose: bool) -> int:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=not verbose,
        text=True,
    )
    return int(completed.returncode)


def _version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in re.split(r"[^0-9]+", value):
        if token:
            parts.append(int(token))
    return tuple(parts) if parts else (0,)


def _is_version_at_or_below_5_0(value: str) -> bool | None:
    parts = _version_key(value)
    if not parts or parts == (0,):
        return None
    major = parts[0]
    minor = parts[1] if len(parts) > 1 else 0
    if major < 5:
        return True
    if major > 5:
        return False
    if minor < 0:
        return True
    if minor > 0:
        return False
    # 5.0.x: treat non-zero patch/build as newer than plain 5.0.
    return all(part == 0 for part in parts[2:])


def _latest_dolphin_windows_archive_url() -> tuple[str | None, str | None]:
    try:
        with urlopen(_DOLPHIN_DOWNLOAD_PAGE_URL, timeout=20) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except (URLError, TimeoutError, OSError):
        return None, None
    candidates = _DOLPHIN_WINDOWS_ARCHIVE_URL_RE.findall(html)
    if not candidates:
        return None, None
    version = max(candidates, key=lambda item: _version_key(item))
    url = f"https://dl.dolphin-emu.org/releases/{version}/dolphin-{version}-x64.7z"
    return url, version


def _required_has_dolphin(required: list[str]) -> bool:
    for value in required:
        normalized = value.strip().strip('"').casefold()
        if normalized in {"dolphin", "dolphin-emu"}:
            return True
    return False


def _validate_windows_dolphin_runtime(required: list[str]) -> None:
    if os.name != "nt":
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
    legacy = _is_version_at_or_below_5_0(version_text)
    if legacy is not True:
        return
    raise RuntimeError(
        "Unsupported legacy Dolphin build detected "
        f"({resolved}, version={version_text}). "
        "Install a modern Dolphin build (newer than 5.0) and re-run sync."
    )


def _install_dolphin_from_official_release_archive(*, verbose: bool) -> bool:
    if os.name != "nt":
        return False
    archive_url, version = _latest_dolphin_windows_archive_url()
    if not archive_url or not version:
        return False
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        install_root = Path(local_app_data) / "Programs" / "Dolphin"
    else:
        install_root = Path.home() / "AppData" / "Local" / "Programs" / "Dolphin"

    with tempfile.TemporaryDirectory(prefix="gamehub-dolphin-release-") as temp_dir:
        temp_root = Path(temp_dir)
        archive_path = temp_root / f"dolphin-{version}-x64.7z"
        extract_root = temp_root / "extract"
        extract_root.mkdir(parents=True, exist_ok=True)
        try:
            with urlopen(archive_url, timeout=60) as response:
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
        Path.home() / ".local" / "share" / "flatpak" / "exports" / "bin" / app_id,
        Path("/var/lib/flatpak/exports/bin") / app_id,
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


def _flatpak_preferred_linux_backend(backend: str, dist_id: str) -> bool:
    if backend == "flatpak":
        return True
    if backend in {"auto", ""} and _prefer_flatpak_for_auto_backend(dist_id):
        return True
    return False


def _linux_missing_emulators(required: list[str], *, backend: str, dist_id: str) -> list[str]:
    force_flatpak = _flatpak_preferred_linux_backend(backend, dist_id)
    missing: list[str] = []
    for name in required:
        normalized = name.strip().strip('"').casefold()
        if force_flatpak and normalized in _FLATPAK_FORCED_EMULATORS:
            app_id = _FLATPAK_APP_IDS.get(normalized)
            if app_id and not _is_flatpak_app_available(app_id):
                missing.append(name)
            continue
        if not _is_emulator_available(name):
            missing.append(name)
    return missing


def _validate_forced_linux_flatpak_emulators(required: list[str], *, backend: str, dist_id: str) -> None:
    if not _flatpak_preferred_linux_backend(backend, dist_id):
        return
    missing_apps: list[str] = []
    for name in required:
        normalized = name.strip().strip('"').casefold()
        if normalized not in _FLATPAK_FORCED_EMULATORS:
            continue
        app_id = _FLATPAK_APP_IDS.get(normalized)
        if app_id and not _is_flatpak_app_available(app_id):
            missing_apps.append(app_id)
    if missing_apps:
        joined = ", ".join(sorted(set(missing_apps)))
        raise RuntimeError(
            "Required Flatpak emulator(s) are unavailable for this Linux backend: "
            f"{joined}. Install them via flatpak and re-run sync."
        )


def _prefer_flatpak_for_auto_backend(dist_id: str) -> bool:
    normalized = dist_id.casefold()
    if any(hint in normalized for hint in _IMMUTABLE_DISTRO_HINTS):
        return True
    for marker in (Path("/run/ostree-booted"), Path("/sysroot/ostree")):
        try:
            if marker.exists():
                return True
        except OSError:
            continue
    return False


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
            result = _run_install_command(
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
                print(f"Warning: winget install failed for {emulator} via {winget_id} (exit {result}); trying fallback id.")

        if not installed:
            print(
                f"Warning: winget install failed for {emulator} (exit {last_result}). "
                "Install manually and re-run sync."
            )


def _install_fedora(missing: list[str], *, verbose: bool) -> None:
    if shutil.which("dnf") is None:
        print("dnf not found; cannot auto-install missing emulators on Fedora")
        return
    prefix: list[str] = []
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid) and geteuid() != 0:
        if shutil.which("sudo") is None:
            print("sudo not found and not running as root; cannot auto-install emulators")
            return
        prefix = ["sudo"]

    for emulator in missing:
        package_name = _DNF_PACKAGES.get(emulator.lower())
        if not package_name:
            print(f"No Fedora package mapping for emulator '{emulator}'; install it manually")
            continue
        print(f"Installing emulator '{emulator}' via dnf ({package_name})...")
        result = _run_install_command([*prefix, "dnf", "install", "-y", package_name], verbose=verbose)
        if result != 0:
            print(f"Warning: dnf install failed for {emulator} (exit {result}). Install manually and re-run sync.")
            continue
        if _is_emulator_available(emulator):
            print(f"Installed emulator: {emulator}")
        else:
            print(f"Warning: {emulator} install command completed but executable not found yet")


def _install_apt(missing: list[str], *, verbose: bool) -> None:
    apt_cmd = shutil.which("apt-get") or shutil.which("apt")
    if apt_cmd is None:
        print("apt-get not found; cannot auto-install missing emulators on Debian/Ubuntu hosts")
        return
    prefix: list[str] = []
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid) and geteuid() != 0:
        if shutil.which("sudo") is None:
            print("sudo not found and not running as root; cannot auto-install emulators")
            return
        prefix = ["sudo"]

    apt_binary = Path(apt_cmd).name
    for emulator in missing:
        package_name = _APT_PACKAGES.get(emulator.lower())
        if not package_name:
            print(f"No Debian/Ubuntu package mapping for emulator '{emulator}'; install it manually")
            continue
        print(f"Installing emulator '{emulator}' via {apt_binary} ({package_name})...")
        result = _run_install_command([*prefix, apt_binary, "install", "-y", package_name], verbose=verbose)
        if result != 0:
            print(
                f"Warning: {apt_binary} install failed for {emulator} (exit {result}). "
                "Install manually and re-run sync."
            )
            continue
        if _is_emulator_available(emulator):
            print(f"Installed emulator: {emulator}")
        else:
            print(f"Warning: {emulator} install command completed but executable not found yet")


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
        app_id = _FLATPAK_APP_IDS.get(emulator.lower())
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
        for position, command in enumerate(deduped_commands):
            result = _run_install_command(command, verbose=verbose)
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


def _linux_package_name(emulator: str) -> str:
    return _DNF_PACKAGES.get(emulator.lower(), emulator)


def _install_linux_command(missing: list[str], command_template: str, *, verbose: bool) -> None:
    template = command_template.strip()
    if not template:
        print("Linux emulator auto-install command is empty; install missing emulators manually and re-run sync.")
        return
    for emulator in missing:
        package = _linux_package_name(emulator)
        command = [token.format(package=package, emulator=emulator) for token in shlex.split(template)]
        if not command:
            print("Linux emulator auto-install command resolved to empty command; skipping")
            return
        print(f"Installing emulator '{emulator}' via configured Linux install command...")
        result = _run_install_command(command, verbose=verbose)
        if result != 0:
            print(
                "Warning: configured Linux install command failed for "
                f"{emulator} (exit {result}). Install manually and re-run sync."
            )
            continue
        if _is_emulator_available(emulator):
            print(f"Installed emulator: {emulator}")
        else:
            print(f"Warning: {emulator} install command completed but executable not found yet")


def ensure_emulators(
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    linux_install_backend: str | None = None,
    linux_install_command: str | None = None,
    linux_flatpak_remote: str | None = None,
) -> None:
    required = sorted(_required_emulators(index))
    if not required:
        return

    linux_dist_id = ""
    linux_backend = ""
    if sys.platform.startswith("linux"):
        linux_backend = (linux_install_backend or "auto").strip().casefold()
        linux_dist_id = _linux_dist_id()
        missing = _linux_missing_emulators(required, backend=linux_backend, dist_id=linux_dist_id)
    else:
        missing = [name for name in required if not _is_emulator_available(name)]

    if not missing:
        if verbose:
            print(f"Emulators ready: {', '.join(required)}")
        if sys.platform.startswith("linux"):
            _validate_forced_linux_flatpak_emulators(required, backend=linux_backend, dist_id=linux_dist_id)
        _validate_windows_dolphin_runtime(required)
        return

    print(f"Missing emulators: {', '.join(missing)}")
    if dry_run:
        print("Dry-run: emulator auto-install skipped")
        _validate_windows_dolphin_runtime(required)
        return
    if os.name == "nt":
        _install_windows(missing, verbose=verbose)
        _validate_windows_dolphin_runtime(required)
        return

    if sys.platform.startswith("linux"):
        backend = linux_backend
        custom_command = linux_install_command
        dist_id = linux_dist_id

        if backend in {"auto", ""}:
            if _prefer_flatpak_for_auto_backend(dist_id) and shutil.which("flatpak") is not None:
                _install_flatpak(missing, verbose=verbose, remote=linux_flatpak_remote)
                _validate_forced_linux_flatpak_emulators(required, backend=backend, dist_id=dist_id)
                return
            if "fedora" in dist_id and shutil.which("dnf") is not None:
                _install_fedora(missing, verbose=verbose)
                return
            if ("ubuntu" in dist_id or "debian" in dist_id) and (shutil.which("apt-get") is not None or shutil.which("apt") is not None):
                _install_apt(missing, verbose=verbose)
                return
            if shutil.which("flatpak") is not None:
                _install_flatpak(missing, verbose=verbose, remote=linux_flatpak_remote)
                return
            if custom_command:
                _install_linux_command(missing, custom_command, verbose=verbose)
                return
            print(
                "Linux emulator auto-install is unavailable for this host. "
                "Set [linux].emulator_install_backend to 'flatpak', 'dnf', or 'command', "
                "or install manually and re-run sync."
            )
            return

        if backend == "dnf":
            _install_fedora(missing, verbose=verbose)
            return
        if backend == "apt":
            _install_apt(missing, verbose=verbose)
            return
        if backend == "flatpak":
            _install_flatpak(missing, verbose=verbose, remote=linux_flatpak_remote)
            _validate_forced_linux_flatpak_emulators(required, backend=backend, dist_id=dist_id)
            return
        if backend == "none":
            print("Linux emulator auto-install disabled by configuration")
            return
        if backend == "command":
            if not custom_command:
                print(
                    "Linux emulator install backend is 'command' but no command template is configured. "
                    "Set [linux].emulator_install_command and re-run sync."
                )
                return
            _install_linux_command(missing, custom_command, verbose=verbose)
            return

        print(
            "Unsupported Linux emulator install backend: "
            f"{backend}. Valid values: auto, dnf, apt, flatpak, none, command."
        )
        return

    print("Emulator auto-install is currently supported on Windows and Linux only")
