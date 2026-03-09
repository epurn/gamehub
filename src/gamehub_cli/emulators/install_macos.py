from __future__ import annotations

import html
import re
import shlex
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
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
_AZAHAR_RELEASES_LATEST_URL = "https://github.com/azahar-emu/azahar/releases/latest"
_PCSX2_DOWNLOADS_URL = "https://pcsx2.net/downloads/"

_MACOS_COMMAND_PACKAGES = {
    "retroarch": "retroarch",
    "pcsx2": "pcsx2",
    "dolphin": "dolphin",
    "azahar": "azahar",
}

_MACOS_BUNDLE_NAMES = {
    "retroarch": "RetroArch.app",
    "dolphin": "Dolphin.app",
    "azahar": "Azahar.app",
}

_MANUAL_SOURCE_BY_EMULATOR = {
    "retroarch": _RETROARCH_INSTALL_DOC_URL,
    "pcsx2": _PCSX2_DOWNLOADS_URL,
    "dolphin": _DOLPHIN_DOWNLOAD_PAGE_URL,
    "azahar": _AZAHAR_RELEASES_LATEST_URL,
}

_RETROARCH_MACOS_DMG_URL_RE = re.compile(
    r"(?P<url>https://buildbot\.libretro\.com/"
    r"(?P<channel>stable|nightly)/"
    r'(?:(?P<version>[^/"\']+)/)?'
    r"apple/osx/(?P<kind>universal|arm64)/RetroArch_Metal\.dmg)"
)
_DOLPHIN_MACOS_DMG_URL_RE = re.compile(
    r"(?P<url>https://dl\.dolphin-emu\.org/releases/"
    r"(?P<version>\d+)/dolphin-(?P=version)-(?P<kind>universal|arm64)\.dmg)",
    re.IGNORECASE,
)
_AZAHAR_MACOS_ZIP_URL_RE = re.compile(
    r"(?P<href>(?:https://github\.com)?/azahar-emu/azahar/releases/download/"
    r'(?P<tag>[^/"\']+)/azahar-[^/"\']+-macos-(?P<kind>arm64|universal)\.zip)',
    re.IGNORECASE,
)
_MACH_O_ARCH_RE = re.compile(r"\b(arm64e|arm64|x86_64|i386)\b")


def _download_text(url: str, *, timeout_seconds: float = 20.0) -> str | None:
    try:
        with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
            return str(response.read(), encoding="utf-8", errors="ignore")
    except (URLError, TimeoutError, OSError):
        return None


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


def _latest_retroarch_macos_asset() -> MacOSOfficialAsset | None:
    page_html = _download_text(_RETROARCH_INSTALL_DOC_URL)
    if not page_html:
        return None
    candidates: list[tuple[tuple[int, tuple[int, ...]], str, str]] = []
    for match in _RETROARCH_MACOS_DMG_URL_RE.finditer(page_html):
        channel = match.group("channel").lower()
        version = match.group("version") or "0"
        priority = 0 if channel == "stable" else 1
        candidates.append(
            (
                (priority, tuple(-part for part in install_common._version_key(version))),
                match.group("url"),
                match.group("kind"),
            )
        )
    if not candidates:
        return None
    _sort_key, download_url, asset_kind = sorted(candidates, key=lambda item: item[0])[0]
    return MacOSOfficialAsset(
        emulator="retroarch",
        archive_kind="dmg",
        bundle_name=_MACOS_BUNDLE_NAMES["retroarch"],
        download_url=download_url,
        source_url=_RETROARCH_INSTALL_DOC_URL,
        asset_label=asset_kind,
    )


def _latest_dolphin_macos_asset() -> MacOSOfficialAsset | None:
    page_html = _download_text(_DOLPHIN_DOWNLOAD_PAGE_URL)
    if not page_html:
        return None
    candidates: list[tuple[tuple[int, ...], str, str]] = []
    for match in _DOLPHIN_MACOS_DMG_URL_RE.finditer(page_html):
        candidates.append(
            (install_common._version_key(match.group("version")), match.group("url"), match.group("kind"))
        )
    if not candidates:
        return None
    _version, download_url, asset_kind = max(candidates, key=lambda item: item[0])
    return MacOSOfficialAsset(
        emulator="dolphin",
        archive_kind="dmg",
        bundle_name=_MACOS_BUNDLE_NAMES["dolphin"],
        download_url=download_url,
        source_url=_DOLPHIN_DOWNLOAD_PAGE_URL,
        asset_label=asset_kind,
    )


def _latest_azahar_macos_asset() -> MacOSOfficialAsset | None:
    page_html = _download_text(_AZAHAR_RELEASES_LATEST_URL)
    if not page_html:
        return None
    candidates: list[tuple[int, str]] = []
    for match in _AZAHAR_MACOS_ZIP_URL_RE.finditer(page_html):
        href = html.unescape(match.group("href"))
        download_url = urljoin("https://github.com", href)
        kind = match.group("kind").lower()
        priority = 0 if kind == "arm64" else 1
        candidates.append((priority, download_url))
    if not candidates:
        return None
    _priority, download_url = sorted(candidates, key=lambda item: item[0])[0]
    asset_kind = "arm64" if "macos-arm64" in download_url.casefold() else "universal"
    return MacOSOfficialAsset(
        emulator="azahar",
        archive_kind="zip",
        bundle_name=_MACOS_BUNDLE_NAMES["azahar"],
        download_url=download_url,
        source_url=_AZAHAR_RELEASES_LATEST_URL,
        asset_label=asset_kind,
    )


def _resolve_macos_official_asset(emulator: str) -> tuple[MacOSOfficialAsset | None, str | None]:
    canonical = _canonical_emulator_name(emulator)
    if canonical == "steam":
        return None, "Steam must be installed manually; GAMEHUB never auto-installs Steam"
    if canonical == "pcsx2":
        return (
            None,
            "current upstream does not provide a reliable native Apple Silicon or universal macOS asset",
        )
    if canonical == "retroarch":
        asset = _latest_retroarch_macos_asset()
    elif canonical == "dolphin":
        asset = _latest_dolphin_macos_asset()
    elif canonical == "azahar":
        asset = _latest_azahar_macos_asset()
    else:
        asset = None
    if asset is None:
        return None, "no supported native Apple Silicon or universal upstream asset was found"
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


def _extract_app_bundle_from_zip(
    zip_path: Path, expected_bundle: str, *, temp_root: Path, verbose: bool
) -> Path | None:
    extract_root = temp_root / "extract"
    extract_root.mkdir(parents=True, exist_ok=True)
    if not _extract_zip_archive(zip_path, extract_root, verbose=verbose):
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
        print(
            f"Installing emulator '{emulator}' via official macOS {asset.asset_label} upstream asset "
            "into ~/Applications..."
        )
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
