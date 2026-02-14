from __future__ import annotations

from dataclasses import dataclass
import io
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urljoin
from urllib.request import urlopen
import zipfile

from gamehub_common.models import LibraryIndex

from .emulators import resolve_emulator_executable
from .fsops import replace_file

try:
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    httpx = None


DEFAULT_CORE_BY_SYSTEM: dict[str, str] = {
    # General-purpose defaults for systems that use RetroArch.
    "GB": "gambatte_libretro",
    "GBA": "mgba_libretro",
    "GBC": "gambatte_libretro",
    "GEN_MD": "genesis_plus_gx_libretro",
    "N64": "mupen64plus_next_libretro",
    "NDS": "melondsds_libretro",
    "NES": "fceumm_libretro",
    "PSX": "swanstation_libretro",
    "SNES": "snes9x_libretro",
}

_CORE_TOKEN_RE = re.compile(r"-L\s+(?P<token>[^\"\s]+)")


@dataclass(frozen=True)
class RetroArchPaths:
    cores_dir: Path
    info_dir: Path


def _core_suffix() -> str:
    if os.name == "nt":
        return ".dll"
    if sys.platform.startswith("linux"):
        return ".so"
    return ""


def _core_base_url(explicit_override: str | None = None) -> str | None:
    override = os.environ.get("GAMEHUB_RETROARCH_CORES_BASE_URL")
    if not override and explicit_override:
        override = explicit_override
    if override:
        return override.rstrip("/") + "/"
    if os.name == "nt":
        return "https://buildbot.libretro.com/nightly/windows/x86_64/latest/"
    if sys.platform.startswith("linux"):
        machine = os.uname().machine.lower() if hasattr(os, "uname") else ""
        if machine in {"x86_64", "amd64"}:
            return "https://buildbot.libretro.com/nightly/linux/x86_64/latest/"
    return None


def _assets_url() -> str:
    return "https://buildbot.libretro.com/assets/frontend/info.zip"


def _parse_core_name(token: str) -> str | None:
    normalized = token.strip().strip('"').replace("\\", "/")
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    if normalized.endswith(".dll"):
        normalized = normalized[:-4]
    elif normalized.endswith(".so"):
        normalized = normalized[:-3]
    if not normalized.endswith("_libretro"):
        return None
    return normalized


def _extract_system_core(system_name: str, launch_template: str) -> str | None:
    match = _CORE_TOKEN_RE.search(launch_template)
    if match:
        core_name = _parse_core_name(match.group("token"))
        if core_name:
            return core_name
    return DEFAULT_CORE_BY_SYSTEM.get(system_name)


def required_retroarch_cores(index: LibraryIndex) -> dict[str, str]:
    """Return mapping of system -> core base name."""
    required: dict[str, str] = {}
    # Prefer explicit systems present in index metadata.
    for system in index.systems:
        if "retroarch" not in system.default_emulator.casefold():
            continue
        core_name = _extract_system_core(system.name, system.launch_template)
        if core_name:
            required[system.name] = core_name
    # Fallback to title launch template if needed.
    for title in index.titles:
        if "retroarch" not in title.emulator.casefold():
            continue
        if title.system in required:
            continue
        core_name = _extract_system_core(title.system, title.launch_template)
        if core_name:
            required[title.system] = core_name
    return required


def _linux_flatpak_retroarch_root() -> Path:
    return Path.home() / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch"


def _is_flatpak_retroarch_command(path: Path) -> bool:
    value = path.as_posix().lower()
    return value.endswith("/org.libretro.retroarch") or "flatpak/exports/bin/org.libretro.retroarch" in value


def _retroarch_cfg_candidates(explicit_cfg_path: Path | None = None) -> list[Path]:
    values: list[Path] = []
    env_override = os.environ.get("GAMEHUB_RETROARCH_CFG_PATH")
    if env_override:
        values.append(Path(env_override).expanduser())
    if explicit_cfg_path is not None:
        values.append(explicit_cfg_path.expanduser())
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(Path(appdata) / "RetroArch" / "retroarch.cfg")
    home = Path.home()
    values.append(home / ".config" / "retroarch" / "retroarch.cfg")
    values.append(_linux_flatpak_retroarch_root() / "retroarch.cfg")
    deduped: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        candidate = value.expanduser()
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def _parse_cfg(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip().lower()] = value.strip().strip('"').strip("'")
    return values


def resolve_retroarch_paths(
    explicit_cores_dir: Path | None = None,
    explicit_info_dir: Path | None = None,
    explicit_cfg_path: Path | None = None,
) -> RetroArchPaths | None:
    explicit_cores = os.environ.get("GAMEHUB_RETROARCH_CORES_DIR")
    explicit_info = os.environ.get("GAMEHUB_RETROARCH_INFO_DIR")
    if not explicit_cores and explicit_cores_dir is not None:
        explicit_cores = str(explicit_cores_dir)
    if not explicit_info and explicit_info_dir is not None:
        explicit_info = str(explicit_info_dir)
    if explicit_cores:
        cores_dir = Path(explicit_cores).expanduser()
        info_dir = Path(explicit_info).expanduser() if explicit_info else cores_dir.parent / "info"
        return RetroArchPaths(cores_dir=cores_dir, info_dir=info_dir)

    config_cores: Path | None = None
    config_info: Path | None = None
    for cfg_path in _retroarch_cfg_candidates(explicit_cfg_path=explicit_cfg_path):
        parsed = _parse_cfg(cfg_path)
        raw_core = parsed.get("libretro_directory")
        raw_info = parsed.get("libretro_info_path")
        if raw_core:
            candidate = Path(raw_core)
            if not candidate.is_absolute():
                candidate = cfg_path.parent / candidate
            config_cores = candidate
        if raw_info:
            candidate = Path(raw_info)
            if not candidate.is_absolute():
                candidate = cfg_path.parent / candidate
            config_info = candidate
        if config_cores:
            break

    if config_cores:
        return RetroArchPaths(cores_dir=config_cores, info_dir=config_info or config_cores.parent / "info")

    exe_raw = resolve_emulator_executable("retroarch").strip('"')
    exe = Path(exe_raw)
    flatpak_hint = _is_flatpak_retroarch_command(exe) or "org.libretro.retroarch" in exe_raw.casefold()
    if exe.exists() and os.name == "nt":
        return RetroArchPaths(cores_dir=exe.parent / "cores", info_dir=exe.parent / "info")
    if sys.platform.startswith("linux") and flatpak_hint:
        root = _linux_flatpak_retroarch_root()
        return RetroArchPaths(cores_dir=root / "cores", info_dir=root / "info")

    # Best-effort platform defaults.
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            root = Path(appdata) / "RetroArch"
            return RetroArchPaths(cores_dir=root / "cores", info_dir=root / "info")
    if sys.platform.startswith("linux"):
        native_root = Path.home() / ".config" / "retroarch"
        flatpak_root = _linux_flatpak_retroarch_root()
        prefer_flatpak = flatpak_hint
        roots = [flatpak_root, native_root] if prefer_flatpak else [native_root, flatpak_root]
        for root in roots:
            if (root / "cores").exists() or (root / "info").exists():
                return RetroArchPaths(cores_dir=root / "cores", info_dir=root / "info")
        fallback = roots[0]
        return RetroArchPaths(cores_dir=fallback / "cores", info_dir=fallback / "info")
    return None


def _download_bytes(url: str, timeout_seconds: float = 30.0) -> bytes:
    if httpx is not None:
        response = httpx.get(url, timeout=timeout_seconds, follow_redirects=True)
        response.raise_for_status()
        return bytes(response.content)
    with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
        return response.read()


def _install_from_zip_blob(zip_blob: bytes, member_name: str, destination: Path) -> bool:
    with zipfile.ZipFile(io.BytesIO(zip_blob)) as archive:
        matches = [name for name in archive.namelist() if Path(name).name == member_name]
        if not matches:
            return False
        member = matches[0]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as src:
            with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent, suffix=".tmp") as tmp:
                tmp_path = Path(tmp.name)
                while True:
                    chunk = src.read(1024 * 256)
                    if not chunk:
                        break
                    tmp.write(chunk)
        replace_file(tmp_path, destination)
    return True


def ensure_retroarch_cores(
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    explicit_cores_dir: Path | None = None,
    explicit_info_dir: Path | None = None,
    explicit_base_url: str | None = None,
    explicit_cfg_path: Path | None = None,
) -> None:
    required = required_retroarch_cores(index)
    if not required:
        return

    suffix = _core_suffix()
    if not suffix:
        print("RetroArch core auto-provision is unsupported on this platform")
        return

    if explicit_base_url is not None:
        base_url = _core_base_url(explicit_base_url)
    else:
        base_url = _core_base_url()
    if not base_url:
        print("RetroArch core auto-provision unavailable: unsupported architecture for buildbot URL")
        return

    if explicit_cores_dir or explicit_info_dir or explicit_cfg_path:
        paths = resolve_retroarch_paths(
            explicit_cores_dir=explicit_cores_dir,
            explicit_info_dir=explicit_info_dir,
            explicit_cfg_path=explicit_cfg_path,
        )
    else:
        paths = resolve_retroarch_paths()
    if paths is None:
        print("RetroArch core auto-provision unavailable: could not resolve RetroArch cores directory")
        return

    missing_core_files: dict[str, str] = {}
    missing_info_files: dict[str, str] = {}
    for system_name, core_base in sorted(required.items()):
        core_filename = f"{core_base}{suffix}"
        info_filename = f"{core_base}.info"
        if not (paths.cores_dir / core_filename).exists():
            missing_core_files[system_name] = core_base
        if not (paths.info_dir / info_filename).exists():
            missing_info_files[system_name] = core_base

    if not missing_core_files and not missing_info_files:
        if verbose:
            unique = sorted(set(required.values()))
            print(f"RetroArch cores ready: {', '.join(unique)}")
        return

    if dry_run:
        print(f"RetroArch core dry-run: cores_dir={paths.cores_dir} info_dir={paths.info_dir}")
        for system_name, core_base in sorted(missing_core_files.items()):
            print(f"retroarch-core\tmissing\t{system_name}\t{core_base}{suffix}")
        for system_name, core_base in sorted(missing_info_files.items()):
            print(f"retroarch-info\tmissing\t{system_name}\t{core_base}.info")
        return

    cores_to_download = sorted(set(missing_core_files.values()))
    infos_to_download = sorted(set(missing_info_files.values()))

    installed = 0
    failed: list[str] = []
    for core_base in cores_to_download:
        archive_name = f"{core_base}{suffix}.zip"
        target_url = urljoin(base_url, archive_name)
        target_path = paths.cores_dir / f"{core_base}{suffix}"
        try:
            payload = _download_bytes(target_url)
            ok = _install_from_zip_blob(payload, target_path.name, target_path)
        except Exception as exc:
            print(f"Warning: failed to download core {core_base} ({target_url}): {exc}")
            failed.append(core_base)
            continue
        if not ok:
            print(f"Warning: downloaded archive for {core_base} did not contain {target_path.name}")
            failed.append(core_base)
            continue
        installed += 1
        if verbose:
            print(f"retroarch-core\tinstalled\t{core_base}\t{target_path}")

    if infos_to_download:
        try:
            info_blob = _download_bytes(_assets_url())
            for core_base in infos_to_download:
                info_path = paths.info_dir / f"{core_base}.info"
                ok = _install_from_zip_blob(info_blob, info_path.name, info_path)
                if not ok:
                    print(f"Warning: info.zip missing {info_path.name}")
                    continue
                if verbose:
                    print(f"retroarch-info\tinstalled\t{core_base}\t{info_path}")
        except Exception as exc:
            print(f"Warning: failed to download RetroArch info.zip: {exc}")

    requested = len(cores_to_download)
    print(
        "RetroArch core provisioning: "
        f"requested={requested} installed={installed} failed={len(failed)} cores_dir={paths.cores_dir}"
    )
