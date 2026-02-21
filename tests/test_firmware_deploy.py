from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import shutil
from uuid import uuid4

from gamehub_cli.config import GamehubConfig
from gamehub_cli.firmware.deploy import (
    _default_azahar_qt_config_path,
    _default_dolphin_ini_path,
    _default_pcsx2_ini_path,
    _resolve_retroarch_system_dirs,
    _target_dirs_for_system,
    deploy_firmware_to_emulators,
)
from gamehub_common.models import FirmwareSpec, LibraryIndex, SystemSpec


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

        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy._target_dirs_for_system", lambda _name, config=None: [target_dir]
        )
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
        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy._target_dirs_for_system", lambda _name, config=None: [target_dir]
        )

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

        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy._target_dirs_for_system", lambda _name, config=None: [target_dir]
        )
        deploy_firmware_to_emulators(config=config, index=index, dry_run=True, verbose=True, writer=logs.append)

        assert not (target_dir / "scph5501.bin").exists()
        assert any("Firmware deployment dry-run targets: 1" in line for line in logs)


def test_target_dirs_support_env_overrides(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        base = _config(temp_root)
        config = replace(
            base,
            linux=replace(
                base.linux,
                retroarch_system_dir=Path("D:/RetroArch/system"),
                pcsx2_bios_dir=Path("D:/PCSX2/bios"),
                dolphin_user_path=Path("D:/Dolphin/User"),
            ),
        )

        psx_dirs = _target_dirs_for_system("PSX", config=config)
        ps2_dirs = _target_dirs_for_system("PS2", config=config)
        wii_dirs = _target_dirs_for_system("Wii", config=config)

        assert Path("D:/RetroArch/system") in psx_dirs
        assert Path("D:/PCSX2/bios") in ps2_dirs
        assert Path("D:/Dolphin/User/Wii") in wii_dirs


def test_deploy_firmware_n3ds_configures_azahar_fullscreen_without_firmware(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        config = _config(temp_root)
        appdata = temp_root / "AppData" / "Roaming"
        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "nt")
        monkeypatch.setenv("APPDATA", str(appdata))
        index = LibraryIndex(
            index_version=1,
            systems=(
                SystemSpec(
                    name="N3DS",
                    rom_extensions=(".3ds", ".cci", ".cxi"),
                    default_emulator="azahar",
                    launch_template='"{emulator}" "{rom}"',
                    firmware=(),
                ),
            ),
            titles=(),
        )

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)

        qt_config = appdata / "Azahar" / "config" / "qt-config.ini"
        assert qt_config.exists()
        text = qt_config.read_text(encoding="utf-8")
        assert "fullscreen=true" in text
        assert r"fullscreen\default=false" in text
        assert "confirmClose=false" in text
        assert r"confirmClose\default=false" in text
        assert not (appdata / "Azahar" / "sysdata").exists()


def test_deploy_firmware_n3ds_dry_run_does_not_mutate_fullscreen_config(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        config = _config(temp_root)
        appdata = temp_root / "AppData" / "Roaming"
        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "nt")
        monkeypatch.setenv("APPDATA", str(appdata))
        index = LibraryIndex(
            index_version=1,
            systems=(
                SystemSpec(
                    name="N3DS",
                    rom_extensions=(".3ds", ".cci", ".cxi"),
                    default_emulator="azahar",
                    launch_template='"{emulator}" "{rom}"',
                    firmware=(),
                ),
            ),
            titles=(),
        )
        logs: list[str] = []

        deploy_firmware_to_emulators(config=config, index=index, dry_run=True, verbose=True, writer=logs.append)

        assert not (appdata / "Azahar" / "sysdata").exists()
        assert not (appdata / "Azahar" / "config" / "qt-config.ini").exists()
        assert any("azahar\tdry-run\tconfigure" in line for line in logs)


def test_default_azahar_qt_config_path_prefers_flatpak_config_root(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-azahar-") as temp_root:
        home = temp_root / "home"
        export = home / ".local" / "share" / "flatpak" / "exports" / "bin" / "org.azahar_emu.Azahar"
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_bytes(b"#!/bin/sh")

        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware.deploy.resolve_emulator_executable", lambda _name: str(export))

        qt_config = _default_azahar_qt_config_path()

        assert qt_config == home / ".var" / "app" / "org.azahar_emu.Azahar" / "config" / "azahar-emu" / "qt-config.ini"


def test_deploy_firmware_n3ds_linux_keeps_controller_bindings(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-azahar-") as temp_root:
        home = temp_root / "home"
        config = _config(temp_root)
        export = home / ".local" / "share" / "flatpak" / "exports" / "bin" / "org.azahar_emu.Azahar"
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_bytes(b"#!/bin/sh")
        qt_config = home / ".var" / "app" / "org.azahar_emu.Azahar" / "config" / "azahar-emu" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text(
            "\n".join(
                [
                    "[Controls]",
                    "profile=0",
                    r"profile\default=true",
                    r'profiles\1\button_a="code:65,engine:keyboard"',
                    r"profiles\1\button_a\default=true",
                    r'profiles\1\button_b="code:83,engine:keyboard"',
                    r"profiles\1\button_b\default=true",
                    r'profiles\1\button_start="code:77,engine:keyboard"',
                    r"profiles\1\button_start\default=true",
                    r'profiles\1\button_up="code:84,engine:keyboard"',
                    r"profiles\1\button_up\default=true",
                    r'profiles\1\circle_pad="down:code$016777237$1engine$0keyboard"',
                    r"profiles\1\circle_pad\default=true",
                    r'profiles\1\c_stick="down:code$075$1engine$0keyboard"',
                    r"profiles\1\c_stick\default=true",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        index = LibraryIndex(
            index_version=1,
            systems=(
                SystemSpec(
                    name="N3DS",
                    rom_extensions=(".3ds", ".cci", ".cxi"),
                    default_emulator="azahar",
                    launch_template='"{emulator}" "{rom}"',
                    firmware=(),
                ),
            ),
            titles=(),
        )

        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware.deploy.resolve_emulator_executable", lambda _name: str(export))

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)

        text = qt_config.read_text(encoding="utf-8")
        assert "fullscreen=true" in text
        assert r"fullscreen\default=false" in text
        assert "confirmClose=false" in text
        assert r"confirmClose\default=false" in text
        assert r'profiles\1\button_a="code:65,engine:keyboard"' in text
        assert "engine:sdl" not in text


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
        monkeypatch.setattr("gamehub_cli.firmware.deploy._pcsx2_ini_candidates", lambda config=None: [ini_path])

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)

        text = ini_path.read_text(encoding="utf-8")
        assert "SetupWizardIncomplete = false" in text
        assert f"Bios = {config.firmware_dir / 'PS2'}" in text


def test_deploy_firmware_dry_run_reports_pcsx2_config(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        config = _config(temp_root)
        index = _index("PS2", "scph10000.bin")
        ini_path = temp_root / "Documents" / "PCSX2" / "inis" / "PCSX2.ini"
        monkeypatch.setattr("gamehub_cli.firmware.deploy._pcsx2_ini_candidates", lambda config=None: [ini_path])
        logs: list[str] = []

        deploy_firmware_to_emulators(config=config, index=index, dry_run=True, verbose=True, writer=logs.append)

        assert any("pcsx2\tdry-run\tconfigure" in line for line in logs)


def test_deploy_firmware_configures_retroarch_menu_combo(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        config = _config(temp_root)
        index = _index("PSX", "scph5501.bin")
        source = config.firmware_dir / "PSX" / "scph5501.bin"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"bios")
        target_dir = temp_root / "retroarch" / "system"
        cfg_path = temp_root / "retroarch" / "retroarch.cfg"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            'input_menu_toggle_gamepad_combo = "0"\ninput_remapping_directory = "config/remaps"\n', encoding="utf-8"
        )
        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy._target_dirs_for_system", lambda _name, config=None: [target_dir]
        )
        monkeypatch.setattr("gamehub_cli.firmware.deploy._retroarch_cfg_candidates", lambda config=None: [cfg_path])
        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "posix")

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)

        text = cfg_path.read_text(encoding="utf-8")
        assert 'input_menu_toggle_gamepad_combo = "4"' in text
        assert 'all_users_control_menu = "true"' in text
        for index in range(1, 9):
            assert f'input_player{index}_analog_dpad_mode = "0"' in text
        assert 'input_libretro_device_p1 = "261"' in text
        for index in range(2, 9):
            assert f'input_libretro_device_p{index} = "1"' in text
        for index in range(1, 9):
            assert f'input_remap_port_p{index} = "{index - 1}"' in text
        assert 'input_turbo_allow_dpad = "false"' in text
        assert 'input_turbo_bind = "-1"' in text
        assert 'input_turbo_button = "0"' in text
        assert 'input_turbo_duty_cycle = "0"' in text
        assert 'input_turbo_enable = "true"' in text
        assert 'input_turbo_mode = "0"' in text
        assert 'input_turbo_period = "6"' in text
        remap_path = cfg_path.parent / "config" / "remaps" / "SwanStation" / "SwanStation.rmp"
        remap_text = remap_path.read_text(encoding="utf-8")
        assert 'input_libretro_device_p1 = "261"' in remap_text
        assert 'input_libretro_device_p2 = "1"' in remap_text
        core_opts = cfg_path.with_name("retroarch-core-options.cfg").read_text(encoding="utf-8")
        assert 'swanstation_Controller1.Type = "AnalogController"' in core_opts
        assert 'swanstation_Controller2.Type = "AnalogController"' in core_opts


def test_deploy_firmware_dry_run_reports_retroarch_menu_combo(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        config = _config(temp_root)
        index = _index("PSX", "scph5501.bin")
        cfg_path = temp_root / "retroarch" / "retroarch.cfg"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text('input_menu_toggle_gamepad_combo = "0"\n', encoding="utf-8")
        logs: list[str] = []

        monkeypatch.setattr("gamehub_cli.firmware.deploy._retroarch_cfg_candidates", lambda config=None: [cfg_path])
        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "posix")
        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy._target_dirs_for_system",
            lambda _name, config=None: [temp_root / "retroarch" / "system"],
        )

        deploy_firmware_to_emulators(config=config, index=index, dry_run=True, verbose=True, writer=logs.append)

        assert any("retroarch\tdry-run\tconfigure" in line for line in logs)
        assert any("menu_combo=Start+Select" in line for line in logs)
        assert any("all_users_menu=true" in line for line in logs)
        assert any("analog_dpad_mode=0" in line for line in logs)
        assert any("retroarch\tdry-run\tcore-options" in line for line in logs)
        assert any("retroarch\tdry-run\tremap" in line for line in logs)


def test_deploy_firmware_windows_avoids_psx_cfg_overrides(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        config = _config(temp_root)
        index = _index("PSX", "scph5501.bin")
        source = config.firmware_dir / "PSX" / "scph5501.bin"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"bios")
        target_dir = temp_root / "retroarch" / "system"
        cfg_path = temp_root / "retroarch" / "retroarch.cfg"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            'input_menu_toggle_gamepad_combo = "0"\ninput_remapping_directory = ":/config/remaps"\n', encoding="utf-8"
        )
        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy._target_dirs_for_system", lambda _name, config=None: [target_dir]
        )
        monkeypatch.setattr("gamehub_cli.firmware.deploy._retroarch_cfg_candidates", lambda config=None: [cfg_path])
        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "nt")

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)

        text = cfg_path.read_text(encoding="utf-8")
        assert 'input_menu_toggle_gamepad_combo = "4"' in text
        assert 'all_users_control_menu = "true"' in text
        assert "input_libretro_device_p1" not in text
        assert "input_player1_analog_dpad_mode" not in text
        assert "input_remap_port_p1" not in text
        assert "input_turbo_allow_dpad" not in text
        remap_path = cfg_path.parent / "config" / "remaps" / "SwanStation" / "SwanStation.rmp"
        remap_text = remap_path.read_text(encoding="utf-8")
        assert 'input_libretro_device_p1 = "261"' in remap_text


def test_default_dolphin_ini_path_prefers_existing_flatpak_ini(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-dolphin-") as temp_root:
        flatpak_root = temp_root / ".var" / "app" / "org.DolphinEmu.dolphin-emu" / "data" / "dolphin-emu"
        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy._resolve_dolphin_runtime_user_dir", lambda config=None: flatpak_root
        )

        ini_path = _default_dolphin_ini_path()

        assert ini_path == flatpak_root / "Config" / "Dolphin.ini"


def test_deploy_firmware_configures_dolphin_fullscreen_ini(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-dolphin-") as temp_root:
        monkeypatch.setattr("gamehub_cli.firmware.deploy.sys.platform", "win32")
        config = _config(temp_root)
        index = LibraryIndex(
            index_version=1,
            systems=(
                SystemSpec(
                    name="GC",
                    rom_extensions=(".iso",),
                    default_emulator="dolphin",
                    launch_template='"{emulator}" -b -e "{rom}"',
                    firmware=(),
                ),
            ),
            titles=(),
        )
        dolphin_root = temp_root / "dolphin-user"
        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy._resolve_dolphin_config_dirs",
            lambda config=None: [dolphin_root],
        )

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)

        ini_path = dolphin_root / "Config" / "Dolphin.ini"
        text = ini_path.read_text(encoding="utf-8")
        assert "[Display]" in text
        assert "Fullscreen = True" in text
        assert "[Interface]" in text
        assert "ConfirmStop = False" in text
        assert "BackgroundInput = True" in text
        assert not (dolphin_root / "Config" / "GCPadNew.ini").exists()
        assert not (dolphin_root / "Config" / "WiimoteNew.ini").exists()
        assert not (dolphin_root / "Config" / "Hotkeys.ini").exists()


def test_deploy_firmware_dry_run_reports_dolphin_config(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-dolphin-") as temp_root:
        config = _config(temp_root)
        index = LibraryIndex(
            index_version=1,
            systems=(
                SystemSpec(
                    name="Wii",
                    rom_extensions=(".rvz",),
                    default_emulator="dolphin",
                    launch_template='"{emulator}" -b -e "{rom}"',
                    firmware=(),
                ),
            ),
            titles=(),
        )
        dolphin_root = temp_root / "dolphin-user"
        logs: list[str] = []
        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy._resolve_dolphin_config_dirs",
            lambda config=None: [dolphin_root],
        )

        deploy_firmware_to_emulators(config=config, index=index, dry_run=True, verbose=True, writer=logs.append)

        assert any("dolphin\tdry-run\tconfigure" in line for line in logs)
        assert not (dolphin_root / "Config" / "Dolphin.ini").exists()
        assert not (dolphin_root / "Config" / "GCPadNew.ini").exists()
        assert not (dolphin_root / "Config" / "WiimoteNew.ini").exists()
        assert not (dolphin_root / "Config" / "Hotkeys.ini").exists()


def test_resolve_retroarch_system_dirs_includes_portable_exe_system(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        portable_root = temp_root / "RetroArch-Win64"
        portable_root.mkdir(parents=True, exist_ok=True)
        portable_exe = portable_root / "retroarch.exe"
        portable_exe.write_bytes(b"exe")
        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy.resolve_emulator_executable",
            lambda _name: str(portable_exe),
        )

        dirs = _resolve_retroarch_system_dirs()

        assert portable_root / "system" in dirs


def test_resolve_retroarch_system_dirs_linux_ignores_usr_bin_parent(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        home = temp_root / "home"
        home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("gamehub_cli.firmware.deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.sys.platform", "linux")
        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy.resolve_emulator_executable", lambda _name: "/usr/bin/retroarch"
        )
        monkeypatch.setattr("gamehub_cli.firmware.deploy._retroarch_cfg_candidates", lambda config=None: [])

        dirs = _resolve_retroarch_system_dirs()

        assert Path("/usr/bin/system") not in dirs


def test_resolve_retroarch_system_dirs_expands_tilde_cfg_values(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        home = temp_root / "home"
        cfg_path = home / ".config" / "retroarch" / "retroarch.cfg"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            'system_directory = "~/.var/app/org.libretro.RetroArch/config/retroarch/system"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr("gamehub_cli.firmware.deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.sys.platform", "linux")
        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy.resolve_emulator_executable", lambda _name: "/usr/bin/retroarch"
        )
        monkeypatch.setattr("gamehub_cli.firmware.deploy._retroarch_cfg_candidates", lambda config=None: [cfg_path])

        dirs = _resolve_retroarch_system_dirs()

        assert home / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "system" in dirs


def test_resolve_retroarch_system_dirs_windows_colon_prefix(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-retroarch-colon-") as temp_root:
        cfg_path = temp_root / "retroarch.cfg"
        cfg_path.write_text('system_directory = ":/system"\n', encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "nt")
        monkeypatch.setattr(
            "gamehub_cli.firmware.targets.retroarch_cfg_candidates", lambda explicit_cfg_path=None: [cfg_path]
        )

        dirs = _resolve_retroarch_system_dirs()

        assert temp_root / "system" in dirs
        assert all("/~/" not in path.as_posix() for path in dirs)


def test_default_pcsx2_ini_path_prefers_flatpak_when_detected(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-firmware-deploy-") as temp_root:
        home = temp_root / "home"
        export = home / ".local" / "share" / "flatpak" / "exports" / "bin" / "net.pcsx2.PCSX2"
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_bytes(b"#!/bin/sh")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware.deploy.resolve_emulator_executable", lambda _name: str(export))
        monkeypatch.setattr("gamehub_cli.firmware.deploy._pcsx2_ini_candidates", lambda config=None: [])

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
        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware.deploy.resolve_emulator_executable", lambda _name: str(export))

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

        monkeypatch.setattr("gamehub_cli.firmware.deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr(
            "gamehub_cli.firmware.deploy.resolve_emulator_executable",
            lambda _name: "/home/deck/.local/share/flatpak/exports/bin/net.pcsx2.PCSX2",
        )
        monkeypatch.setattr("gamehub_cli.firmware.deploy._default_pcsx2_ini_path", lambda config=None: ini_path)

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

        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware.deploy.resolve_emulator_executable", lambda _name: str(export))

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)

        flatpak_bios_dir = home / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2" / "bios"
        target = flatpak_bios_dir / "scph10000.bin"
        ini_path = home / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2" / "inis" / "PCSX2.ini"
        assert target.exists()
        assert target.read_bytes() == b"bios"
        text = ini_path.read_text(encoding="utf-8")
        assert f"Bios = {flatpak_bios_dir}" in text
        assert "SetupWizardIncomplete = false" in text


def test_deploy_firmware_flatpak_pcsx2_preserves_existing_pad_bindings(monkeypatch) -> None:
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
        ini_path = home / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2" / "inis" / "PCSX2.ini"
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text(
            "\n".join(
                [
                    "[Pad1]",
                    "Type = DualShock2",
                    "Cross = SDL-0/B",
                    "",
                    "[Pad2]",
                    "Type = None",
                    "Cross = None",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware.deploy.resolve_emulator_executable", lambda _name: str(export))

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)

        text = ini_path.read_text(encoding="utf-8")
        assert "Cross = SDL-0/B" in text
        assert "Type = DualShock2" in text
        assert "Cross = None" in text


def test_deploy_firmware_flatpak_pcsx2_preserves_existing_controller_hotkey(monkeypatch) -> None:
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
        ini_path = home / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2" / "inis" / "PCSX2.ini"
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text(
            "\n".join(
                [
                    "[Hotkeys]",
                    "OpenPauseMenu = SDL-1/Back & SDL-1/Start",
                    "",
                    "[Pad1]",
                    "Type = DualShock2",
                    "Cross = SDL-0/A",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("gamehub_cli.firmware.deploy.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.firmware.deploy.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware.deploy.resolve_emulator_executable", lambda _name: str(export))

        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=False)

        text = ini_path.read_text(encoding="utf-8")
        assert "OpenPauseMenu = SDL-1/Back & SDL-1/Start" in text
