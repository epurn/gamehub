from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from ..common.platform_paths import macos_user_applications_dir, resolve_macos_app_bundle_executable
from . import install_common
from .resolution import _canonical_emulator_name, _is_emulator_available


@dataclass(frozen=True)
class MacOSOfficialAsset:
    emulator: str
    archive_kind: str
    bundle_name: str
    download_url: str
    source_url: str
    asset_label: str


_RETROARCH_INSTALL_DOC_URL = "https://docs.libretro.com/guides/install-macos/"
_DOLPHIN_DOWNLOAD_PAGE_URL = "https://dolphin-emu.org/download/"
_AZAHAR_RELEASES_TAG_URL = "https://github.com/azahar-emu/azahar/releases/tag/2124.3"
_PCSX2_DOWNLOADS_URL = "https://pcsx2.net/downloads/"
_RETROARCH_MACOS_DMG_URL = "https://buildbot.libretro.com/stable/1.22.2/apple/osx/universal/RetroArch_Metal.dmg"
_DOLPHIN_MACOS_DMG_URL = "https://dl.dolphin-emu.org/releases/2512/dolphin-2512-universal.dmg"
_AZAHAR_MACOS_ZIP_URL = (
    "https://github.com/azahar-emu/azahar/releases/download/2124.3/azahar-2124.3-macos-universal.zip"
)
_PCSX2_MACOS_ARCHIVE_URL = "https://github.com/PCSX2/pcsx2/releases/download/v2.6.3/pcsx2-v2.6.3-macos-Qt.tar.xz"

_MACOS_COMMAND_PACKAGES = {
    "retroarch": "retroarch",
    "pcsx2": "pcsx2",
    "dolphin": "dolphin",
    "azahar": "azahar",
}

_MACOS_BUNDLE_NAMES = {
    "retroarch": "RetroArch.app",
    "pcsx2": "PCSX2.app",
    "dolphin": "Dolphin.app",
    "azahar": "Azahar.app",
}

_MANUAL_SOURCE_BY_EMULATOR = {
    "retroarch": _RETROARCH_INSTALL_DOC_URL,
    "pcsx2": _PCSX2_DOWNLOADS_URL,
    "dolphin": _DOLPHIN_DOWNLOAD_PAGE_URL,
    "azahar": _AZAHAR_RELEASES_TAG_URL,
}
_MACH_O_ARCH_RE = re.compile(r"\b(arm64e|arm64|x86_64|i386)\b")
_PINNED_MACOS_OFFICIAL_ASSETS = {
    "retroarch": MacOSOfficialAsset(
        emulator="retroarch",
        archive_kind="dmg",
        bundle_name=_MACOS_BUNDLE_NAMES["retroarch"],
        download_url=_RETROARCH_MACOS_DMG_URL,
        source_url=_RETROARCH_MACOS_DMG_URL,
        asset_label="universal",
    ),
    "dolphin": MacOSOfficialAsset(
        emulator="dolphin",
        archive_kind="dmg",
        bundle_name=_MACOS_BUNDLE_NAMES["dolphin"],
        download_url=_DOLPHIN_MACOS_DMG_URL,
        source_url=_DOLPHIN_MACOS_DMG_URL,
        asset_label="universal",
    ),
    "azahar": MacOSOfficialAsset(
        emulator="azahar",
        archive_kind="zip",
        bundle_name=_MACOS_BUNDLE_NAMES["azahar"],
        download_url=_AZAHAR_MACOS_ZIP_URL,
        source_url=_AZAHAR_RELEASES_TAG_URL,
        asset_label="universal",
    ),
    "pcsx2": MacOSOfficialAsset(
        emulator="pcsx2",
        archive_kind="tar_xz",
        bundle_name=_MACOS_BUNDLE_NAMES["pcsx2"],
        download_url=_PCSX2_MACOS_ARCHIVE_URL,
        source_url=_PCSX2_MACOS_ARCHIVE_URL,
        asset_label="archive",
    ),
}


def _download_file(url: str, destination: Path, *, timeout_seconds: float = 120.0) -> bool:
    try:
        with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
            destination.write_bytes(response.read())
    except (URLError, TimeoutError, OSError):
        return False
    return True


def _manual_install_source(emulator: str) -> str:
    canonical = _canonical_emulator_name(emulator)
    return _MANUAL_SOURCE_BY_EMULATOR.get(canonical, "")


def _resolve_macos_official_asset(emulator: str) -> tuple[MacOSOfficialAsset | None, str | None]:
    canonical = _canonical_emulator_name(emulator)
    if canonical == "steam":
        return None, "Steam must be installed manually; GAMEHUB never auto-installs Steam"
    asset = _PINNED_MACOS_OFFICIAL_ASSETS.get(canonical)
    if asset is None:
        return None, "no supported official macOS asset is pinned for this emulator"
    return asset, None


def _find_app_bundle(root: Path, bundle_name: str) -> Path | None:
    exact_candidates: list[Path] = []
    fallback_candidates: list[Path] = []
    lowered = bundle_name.casefold()
    for candidate in sorted(root.rglob("*.app"), key=lambda item: (len(item.parts), str(item))):
        if not candidate.is_dir():
            continue
        fallback_candidates.append(candidate)
        if candidate.name.casefold() == lowered:
            exact_candidates.append(candidate)
    if exact_candidates:
        return exact_candidates[0]
    if len(fallback_candidates) == 1:
        return fallback_candidates[0]
    return None


def _extract_zip_archive(zip_path: Path, destination: Path, *, verbose: bool) -> bool:
    ditto_cmd = shutil.which("ditto")
    if ditto_cmd:
        result = subprocess.run(  # noqa: S603
            [ditto_cmd, "-x", "-k", str(zip_path), str(destination)],
            check=False,
            capture_output=not verbose,
            text=True,
        )
        if result.returncode == 0:
            return True
    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(destination)
    except (OSError, zipfile.BadZipFile):
        return False
    return True


def _extract_tar_archive(archive_path: Path, destination: Path, *, verbose: bool) -> bool:
    tar_cmd = shutil.which("tar")
    if not tar_cmd:
        return False
    result = subprocess.run(  # noqa: S603
        [tar_cmd, "-xf", str(archive_path), "-C", str(destination)],
        check=False,
        capture_output=not verbose,
        text=True,
    )
    return result.returncode == 0


def _extract_app_bundle_from_zip(
    zip_path: Path, expected_bundle: str, *, temp_root: Path, verbose: bool
) -> Path | None:
    extract_root = temp_root / "extract"
    extract_root.mkdir(parents=True, exist_ok=True)
    if not _extract_zip_archive(zip_path, extract_root, verbose=verbose):
        return None
    return _find_app_bundle(extract_root, expected_bundle)


def _extract_app_bundle_from_tar_archive(
    archive_path: Path, expected_bundle: str, *, temp_root: Path, verbose: bool
) -> Path | None:
    extract_root = temp_root / "extract"
    extract_root.mkdir(parents=True, exist_ok=True)
    if not _extract_tar_archive(archive_path, extract_root, verbose=verbose):
        return None
    return _find_app_bundle(extract_root, expected_bundle)


def _extract_app_bundle_from_dmg(
    dmg_path: Path, expected_bundle: str, *, temp_root: Path, verbose: bool
) -> Path | None:
    mount_root = temp_root / "mount"
    mount_root.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(  # noqa: S603
        ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount_root), str(dmg_path)],
        check=False,
        capture_output=not verbose,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return _find_app_bundle(mount_root, expected_bundle)
    finally:
        subprocess.run(  # noqa: S603
            ["hdiutil", "detach", str(mount_root)],
            check=False,
            capture_output=not verbose,
            text=True,
        )


def _bundle_architectures(bundle_path: Path) -> set[str]:
    executable = resolve_macos_app_bundle_executable(bundle_path)
    if executable is None:
        return set()
    outputs: list[str] = []
    for command in (["lipo", "-archs", str(executable)], ["file", str(executable)]):
        try:
            completed = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            continue
        if completed.returncode != 0:
            continue
        outputs.append(f"{completed.stdout}\n{completed.stderr}")
    architectures = set()
    for output in outputs:
        for token in _MACH_O_ARCH_RE.findall(output):
            architectures.add("arm64" if token == "arm64e" else token)
    return architectures


def _bundle_supports_apple_silicon(bundle_path: Path) -> tuple[bool, str | None]:
    architectures = _bundle_architectures(bundle_path)
    if not architectures:
        return False, "could not verify app bundle architecture from upstream asset"
    if "arm64" in architectures:
        return True, None
    joined = ", ".join(sorted(architectures))
    return False, f"upstream asset is not native Apple Silicon or universal (architectures: {joined})"


def _copy_app_bundle(source_bundle: Path, destination_bundle: Path, *, verbose: bool) -> bool:
    ditto_cmd = shutil.which("ditto")
    if ditto_cmd:
        result = subprocess.run(  # noqa: S603
            [ditto_cmd, str(source_bundle), str(destination_bundle)],
            check=False,
            capture_output=not verbose,
            text=True,
        )
        if result.returncode == 0:
            return True
    try:
        shutil.copytree(source_bundle, destination_bundle, symlinks=True, copy_function=shutil.copy2)
    except OSError:
        return False
    return True


def _install_bundle_into_applications(source_bundle: Path, *, bundle_name: str, verbose: bool) -> Path | None:
    install_root = macos_user_applications_dir()
    try:
        install_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    final_bundle = install_root / bundle_name
    try:
        with tempfile.TemporaryDirectory(prefix=".gamehub-install-", dir=install_root) as temp_dir:
            temp_root = install_common._safe_path(temp_dir)
            staging_bundle = temp_root / bundle_name
            if not _copy_app_bundle(source_bundle, staging_bundle, verbose=verbose):
                return None
            if resolve_macos_app_bundle_executable(staging_bundle) is None:
                return None
            backup_bundle = temp_root / f"{bundle_name}.backup"
            if final_bundle.exists():
                final_bundle.rename(backup_bundle)
            try:
                staging_bundle.rename(final_bundle)
            except OSError:
                if backup_bundle.exists():
                    backup_bundle.rename(final_bundle)
                return None
    except OSError:
        return None
    return final_bundle


def _install_macos_official_asset(
    asset: MacOSOfficialAsset,
    *,
    verbose: bool,
) -> tuple[str, str | None]:
    parsed = urlparse(asset.download_url)
    filename = Path(parsed.path).name.strip() or f"{asset.emulator}.{asset.archive_kind}"
    with tempfile.TemporaryDirectory(prefix="gamehub-macos-emulator-") as temp_dir:
        temp_root = install_common._safe_path(temp_dir)
        archive_path = temp_root / filename
        if not _download_file(asset.download_url, archive_path):
            return "failed", f"download failed for {asset.download_url}"
        if asset.archive_kind == "dmg":
            source_bundle = _extract_app_bundle_from_dmg(
                archive_path,
                asset.bundle_name,
                temp_root=temp_root,
                verbose=verbose,
            )
        elif asset.archive_kind == "zip":
            source_bundle = _extract_app_bundle_from_zip(
                archive_path,
                asset.bundle_name,
                temp_root=temp_root,
                verbose=verbose,
            )
        elif asset.archive_kind == "tar_xz":
            source_bundle = _extract_app_bundle_from_tar_archive(
                archive_path,
                asset.bundle_name,
                temp_root=temp_root,
                verbose=verbose,
            )
        else:
            return "failed", f"unsupported archive kind: {asset.archive_kind}"
        if source_bundle is None:
            return "failed", f"upstream archive did not contain {asset.bundle_name}"
        supported, unsupported_reason = _bundle_supports_apple_silicon(source_bundle)
        if not supported:
            return "unsupported", unsupported_reason
        installed_bundle = _install_bundle_into_applications(
            source_bundle,
            bundle_name=asset.bundle_name,
            verbose=verbose,
        )
        if installed_bundle is None:
            return "failed", f"failed to install {asset.bundle_name} into {macos_user_applications_dir()}"
        if resolve_macos_app_bundle_executable(installed_bundle) is None:
            return "failed", f"installed bundle is missing a runnable executable: {installed_bundle}"
    return "installed", None


def _install_macos_official(missing: list[str], *, verbose: bool) -> None:
    for emulator in missing:
        canonical = _canonical_emulator_name(emulator)
        asset, unsupported_reason = _resolve_macos_official_asset(canonical)
        source_url = _manual_install_source(canonical)
        if asset is None:
            print(
                "Warning: official macOS Apple Silicon install unavailable for "
                f"{emulator}: {unsupported_reason}. Install manually and re-run sync."
            )
            if source_url:
                print(f"Warning: install {emulator} manually from {source_url} and re-run sync.")
            continue
        print(f"Installing emulator '{emulator}' via official macOS asset into ~/Applications...")
        status, detail = _install_macos_official_asset(asset, verbose=verbose)
        if status == "installed" and _is_emulator_available(emulator):
            print(f"Installed emulator: {emulator}")
            continue
        if status == "unsupported":
            print(
                "Warning: official macOS Apple Silicon install unavailable for "
                f"{emulator}: {detail}. Install manually and re-run sync."
            )
        else:
            print(f"Warning: official macOS install failed for {emulator}: {detail}.")
        print(f"Warning: install {emulator} manually from {asset.source_url} and re-run sync.")


def _install_macos_command(missing: list[str], command_template: str, *, verbose: bool) -> None:
    template = command_template.strip()
    if not template:
        print("macOS emulator auto-install command is empty; install missing emulators manually and re-run sync.")
        return
    for emulator in missing:
        canonical = _canonical_emulator_name(emulator)
        if canonical == "steam":
            print("Warning: Steam must be installed manually on macOS; GAMEHUB never auto-installs Steam.")
            continue
        package = _MACOS_COMMAND_PACKAGES.get(canonical)
        if not package:
            print(f"No macOS install command mapping for emulator '{emulator}'; install it manually")
            continue
        command = [token.format(package=package, emulator=emulator) for token in shlex.split(template)]
        if not command:
            print("macOS emulator auto-install command resolved to an empty command; skipping")
            return
        print(f"Installing emulator '{emulator}' via configured macOS install command...")
        result = install_common._run_install_command(command, verbose=verbose)
        if result != 0:
            print(
                "Warning: configured macOS install command failed for "
                f"{emulator} (exit {result}). Install manually and re-run sync."
            )
            continue
        if _is_emulator_available(emulator):
            print(f"Installed emulator: {emulator}")
        else:
            print(f"Warning: {emulator} install command completed but executable not found yet")
