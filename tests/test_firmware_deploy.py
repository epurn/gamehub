from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4

from gamehub_cli.config import GamehubConfig
from gamehub_cli.firmware_deploy import (
    _default_pcsx2_ini_path,
    _resolve_retroarch_system_dirs,
    _target_dirs_for_system,
    deploy_firmware_to_emulators,
)
from gamehub_common.models import FirmwareSpec, LibraryIndex, SystemSpec


@contextmanager
def _workspace_tempdir(prefix: str):
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp_local"
    root.mkdir(parents=True, exist_ok=True)
    temp_dir = root / f"{prefix}{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _config(root: Path) -> GamehubConfig:
    return GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=root / "library",
        firmware_dir=root / "firmware",
        state_path=root / "state.json",
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=root / "cache",
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )


def _index(system_name: str, firmware_name: str) -> LibraryIndex:
    return LibraryIndex(
        index_version=1,
        systems=(
            SystemSpec(
                name=system_name,
                rom_extensions=(".bin",),
                default_emulator="retroarch",
                launch_template='"{emulator}" "{rom}"',
                firmware=(FirmwareSpec(filename=firmware_name, sha256="a" * 64, required=True),),
            ),
        ),
        titles=(),
    )


def test_deploy_firmware_copies_to_target(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        config = _config(temp_root)
        index = _index("PSX", "scph5501.bin")
        source = config.firmware_dir / "PSX" / "scph5501.bin"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"bios")
        target_dir = temp_root / "emulators" / "retroarch" / "system"
        logs: list[str] = []

        monkeypatch.setattr("gamehub_cli.firmware_deploy._target_dirs_for_system", lambda _name, config=None: [target_dir])
        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=True, writer=logs.append)

        target = target_dir / "scph5501.bin"
        assert target.exists()
        assert target.read_bytes() == b"bios"
        assert any("Firmware deployment: targets=1 applied=1" in line for line in logs)


def test_deploy_firmware_skips_when_up_to_date(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        config = _config(temp_root)
        index = _index("PSX", "scph5501.bin")
        source = config.firmware_dir / "PSX" / "scph5501.bin"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"bios")
        target_dir = temp_root / "emulators" / "retroarch" / "system"
        monkeypatch.setattr("gamehub_cli.firmware_deploy._target_dirs_for_system", lambda _name, config=None: [target_dir])

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)
        logs: list[str] = []
        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False, writer=logs.append)

        assert any("applied=0 skipped=1" in line for line in logs)


def test_deploy_firmware_dry_run_does_not_mutate(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        config = _config(temp_root)
        index = _index("PSX", "scph5501.bin")
        source = config.firmware_dir / "PSX" / "scph5501.bin"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"bios")
        target_dir = temp_root / "emulators" / "retroarch" / "system"
        logs: list[str] = []

        monkeypatch.setattr("gamehub_cli.firmware_deploy._target_dirs_for_system", lambda _name, config=None: [target_dir])
        deploy_firmware_to_emulators(config=config, index=index, dry_run=True, verbose=True, writer=logs.append)

        assert not (target_dir / "scph5501.bin").exists()
        assert any("Firmware deployment dry-run targets: 1" in line for line in logs)


def test_target_dirs_support_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("RETROARCH_SYSTEM_DIR", "D:/RetroArch/system")
    monkeypatch.setenv("PCSX2_BIOS_DIR", "D:/PCSX2/bios")
    monkeypatch.setenv("DOLPHIN_EMU_USERPATH", "D:/Dolphin/User")

    psx_dirs = _target_dirs_for_system("PSX")
    ps2_dirs = _target_dirs_for_system("PS2")
    wii_dirs = _target_dirs_for_system("Wii")

    assert Path("D:/RetroArch/system") in psx_dirs
    assert Path("D:/PCSX2/bios") in ps2_dirs
    assert Path("D:/Dolphin/User/Wii") in wii_dirs


def test_deploy_firmware_configures_pcsx2_ini_to_gamehub_firmware(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        config = _config(temp_root)
        index = _index("PS2", "scph10000.bin")
        ini_path = temp_root / "Documents" / "PCSX2" / "inis" / "PCSX2.ini"
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text(
            "[UI]\nSetupWizardIncomplete = true\n\n[Folders]\nBios = bios\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("gamehub_cli.firmware_deploy._pcsx2_ini_candidates", lambda config=None: [ini_path])

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)

        text = ini_path.read_text(encoding="utf-8")
        assert "SetupWizardIncomplete = false" in text
        assert f"Bios = {config.firmware_dir / 'PS2'}" in text


def test_deploy_firmware_dry_run_reports_pcsx2_config(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        config = _config(temp_root)
        index = _index("PS2", "scph10000.bin")
        ini_path = temp_root / "Documents" / "PCSX2" / "inis" / "PCSX2.ini"
        monkeypatch.setattr("gamehub_cli.firmware_deploy._pcsx2_ini_candidates", lambda config=None: [ini_path])
        logs: list[str] = []

        deploy_firmware_to_emulators(config=config, index=index, dry_run=True, verbose=True, writer=logs.append)

        assert any("pcsx2\tdry-run\tconfigure" in line for line in logs)


def test_resolve_retroarch_system_dirs_includes_portable_exe_system(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        portable_root = temp_root / "RetroArch-Win64"
        portable_root.mkdir(parents=True, exist_ok=True)
        portable_exe = portable_root / "retroarch.exe"
        portable_exe.write_bytes(b"exe")
        monkeypatch.setattr(
            "gamehub_cli.firmware_deploy.resolve_emulator_executable",
            lambda _name: str(portable_exe),
        )

        dirs = _resolve_retroarch_system_dirs()

        assert portable_root / "system" in dirs


def test_resolve_retroarch_system_dirs_linux_ignores_usr_bin_parent(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        home = temp_root / "home"
        home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("gamehub_cli.firmware_deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware_deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware_deploy.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.firmware_deploy.resolve_emulator_executable", lambda _name: "/usr/bin/retroarch")
        monkeypatch.setattr("gamehub_cli.firmware_deploy._retroarch_cfg_candidates", lambda config=None: [])

        dirs = _resolve_retroarch_system_dirs()

        assert Path("/usr/bin/system") not in dirs


def test_default_pcsx2_ini_path_prefers_flatpak_when_detected(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        home = temp_root / "home"
        export = home / ".local" / "share" / "flatpak" / "exports" / "bin" / "net.pcsx2.PCSX2"
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_bytes(b"#!/bin/sh")
        monkeypatch.setattr("gamehub_cli.firmware_deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware_deploy.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.firmware_deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware_deploy.resolve_emulator_executable", lambda _name: str(export))
        monkeypatch.setattr("gamehub_cli.firmware_deploy._pcsx2_ini_candidates", lambda config=None: [])

        ini_path = _default_pcsx2_ini_path()

        assert ini_path == home / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2" / "inis" / "PCSX2.ini"


def test_default_pcsx2_ini_path_prefers_flatpak_over_existing_native_ini(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        home = temp_root / "home"
        export = home / ".local" / "share" / "flatpak" / "exports" / "bin" / "net.pcsx2.PCSX2"
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_bytes(b"#!/bin/sh")
        native_ini = home / ".config" / "PCSX2" / "inis" / "PCSX2.ini"
        native_ini.parent.mkdir(parents=True, exist_ok=True)
        native_ini.write_text("[UI]\nSetupWizardIncomplete = true\n", encoding="utf-8")
        monkeypatch.setattr("gamehub_cli.firmware_deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware_deploy.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.firmware_deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware_deploy.resolve_emulator_executable", lambda _name: str(export))

        ini_path = _default_pcsx2_ini_path()

        assert ini_path == home / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2" / "inis" / "PCSX2.ini"


def test_deploy_firmware_dry_run_reports_flatpak_pcsx2_bios_target(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        home = Path("/var/home/deck")
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=Path("/var/home/deck/GameHub/firmware"),
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )
        index = _index("PS2", "scph10000.bin")
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        logs: list[str] = []

        monkeypatch.setattr("gamehub_cli.firmware_deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr(
            "gamehub_cli.firmware_deploy.resolve_emulator_executable",
            lambda _name: "/home/deck/.local/share/flatpak/exports/bin/net.pcsx2.PCSX2",
        )
        monkeypatch.setattr("gamehub_cli.firmware_deploy._default_pcsx2_ini_path", lambda config=None: ini_path)

        deploy_firmware_to_emulators(config=config, index=index, dry_run=True, verbose=True, writer=logs.append)

        pcsx2_logs = [line.replace("\\", "/") for line in logs if line.startswith("pcsx2\tdry-run")]
        assert any("/var/home/deck/.var/app/net.pcsx2.PCSX2/config/PCSX2/bios" in line for line in pcsx2_logs)


def test_deploy_firmware_flatpak_pcsx2_mirrors_bios_and_updates_ini(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        home = temp_root / "home"
        config = _config(temp_root)
        index = _index("PS2", "scph10000.bin")
        source = config.firmware_dir / "PS2" / "scph10000.bin"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"bios")
        export = home / ".local" / "share" / "flatpak" / "exports" / "bin" / "net.pcsx2.PCSX2"
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_bytes(b"#!/bin/sh")

        monkeypatch.setattr("gamehub_cli.firmware_deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware_deploy.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.firmware_deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware_deploy.resolve_emulator_executable", lambda _name: str(export))

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)

        flatpak_bios_dir = home / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2" / "bios"
        target = flatpak_bios_dir / "scph10000.bin"
        ini_path = home / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2" / "inis" / "PCSX2.ini"
        assert target.exists()
        assert target.read_bytes() == b"bios"
        text = ini_path.read_text(encoding="utf-8")
        assert f"Bios = {flatpak_bios_dir}" in text
        assert "SetupWizardIncomplete = false" in text
