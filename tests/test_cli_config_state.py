from __future__ import annotations

import json
from pathlib import Path

import pytest

from gamehub_cli.common.config import (
    BackupsConfig,
    ControllersConfig,
    LinuxConfig,
    MacOSConfig,
    SaveSyncConfig,
    default_config_path,
    default_gamehub_dir,
    load_config,
)
from gamehub_cli.common.platform_paths import (
    macos_application_support_root,
    macos_dolphin_root,
    macos_pcsx2_root,
    macos_retroarch_root,
    macos_system_applications_dir,
    macos_user_applications_dir,
)
from gamehub_cli.sync.state import SyncState, load_state, save_state_atomic


@pytest.fixture(autouse=True)
def _clear_removed_output_dir_alias(monkeypatch) -> None:
    monkeypatch.delenv("GAMEHUB_OUTPUT_DIR", raising=False)


def test_load_config_uses_defaults_when_file_is_missing(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        monkeypatch.delenv("GAMEHUB_SGDB_API_KEY", raising=False)
        state_home = temp_root / "state-home"
        monkeypatch.setattr("gamehub_cli.common.config.user_state_dir", lambda appname: str(state_home / appname))

        loaded = load_config(temp_root / "missing.toml")

        expected_state_root = state_home / "gamehub"
        assert loaded.server_url == "http://127.0.0.1:8000"
        assert loaded.library_dir == expected_state_root
        assert loaded.firmware_dir == expected_state_root / "firmware"
        assert loaded.state_path == expected_state_root / "state.json"
        assert loaded.index_timeout_seconds is None
        assert loaded.index_fetch_attempts == 3
        assert loaded.index_retry_backoff_seconds == 1.5
        assert loaded.steam_userdata_dir is None
        assert loaded.steam_id is None
        assert loaded.steam_exe is None
        assert loaded.sgdb_api_key is None
        assert loaded.sgdb_cache_dir == expected_state_root / "artwork_cache" / "sgdb"
        assert loaded.sgdb_enabled_kinds == ("grid", "hero", "logo", "icon")
        assert loaded.linux == LinuxConfig()
        assert loaded.macos == MacOSConfig()
        assert loaded.controllers == ControllersConfig()
        assert loaded.backups == BackupsConfig()


def test_load_config_prefers_workspace_config_when_present(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        monkeypatch.delenv("GAMEHUB_SGDB_API_KEY", raising=False)
        state_home = temp_root / "state-home"
        monkeypatch.setattr("gamehub_cli.common.config.user_state_dir", lambda appname: str(state_home / appname))
        monkeypatch.chdir(temp_root)
        (temp_root / "config.toml").write_text(
            "\n".join(
                [
                    "[server]",
                    'url = "http://example.invalid:9999"',
                    "",
                    "[paths]",
                    'gamehub_dir = "D:/GamehubOutput"',
                    "",
                    "[steam]",
                    'steam_id = "76561198000000001"',
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config()

        assert loaded.server_url == "http://example.invalid:9999"
        assert loaded.library_dir == Path("D:/GamehubOutput")
        assert loaded.firmware_dir == Path("D:/GamehubOutput/firmware")
        assert loaded.state_path == Path("D:/GamehubOutput/state.json")
        assert loaded.steam_id == "76561198000000001"


def test_default_config_path_prefers_home_dot_gamehub(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-home-") as temp_root:
        home = temp_root / "home"
        home_config = home / ".gamehub" / "config.toml"
        home_config.parent.mkdir(parents=True, exist_ok=True)
        home_config.write_text("[server]\nurl='http://example.invalid:8123'\n", encoding="utf-8")
        monkeypatch.chdir(temp_root)
        monkeypatch.setattr("gamehub_cli.common.config.Path.home", classmethod(lambda cls: home))

        resolved = default_config_path()

        assert resolved == home_config


def test_load_config_uses_home_dot_gamehub_default_when_workspace_missing(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-home-load-") as temp_root:
        home = temp_root / "home"
        home_config = home / ".gamehub" / "config.toml"
        home_config.parent.mkdir(parents=True, exist_ok=True)
        home_config.write_text(
            "\n".join(
                [
                    "[server]",
                    'url = "http://home-default.invalid:8123"',
                    "",
                    "[paths]",
                    'gamehub_dir = "D:/HomeDefaultGamehub"',
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(temp_root)
        monkeypatch.setattr("gamehub_cli.common.config.Path.home", classmethod(lambda cls: home))

        loaded = load_config()

        assert loaded.server_url == "http://home-default.invalid:8123"
        assert loaded.library_dir == Path("D:/HomeDefaultGamehub")
        assert loaded.firmware_dir == Path("D:/HomeDefaultGamehub/firmware")
        assert loaded.state_path == Path("D:/HomeDefaultGamehub/state.json")


def test_default_config_path_defaults_to_home_when_missing(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-home-default-") as temp_root:
        home = temp_root / "home"
        monkeypatch.chdir(temp_root)
        monkeypatch.setattr("gamehub_cli.common.config.Path.home", classmethod(lambda cls: home))

        resolved = default_config_path()

        assert resolved == home / ".gamehub" / "config.toml"


def test_load_config_toml_overrides_defaults(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        monkeypatch.delenv("GAMEHUB_SGDB_API_KEY", raising=False)
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[server]",
                    'url = "http://example.invalid:9000"',
                    "index_timeout_seconds = 45",
                    "index_fetch_attempts = 4",
                    "index_retry_backoff_seconds = 0.75",
                    "",
                    "[paths]",
                    'gamehub_dir = "C:/gamehub"',
                    "",
                    "[steam]",
                    'userdata_dir = "C:/Steam/userdata"',
                    'steam_id = "76561198000000001"',
                    'steam_exe = "C:/Steam/steam.exe"',
                    "",
                    "[sgdb]",
                    'api_key = "from-config-key"',
                    'cache_dir = "C:/cache/sgdb"',
                    'enabled_kinds = ["grid", "icon"]',
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.server_url == "http://example.invalid:9000"
        assert loaded.index_timeout_seconds == 45.0
        assert loaded.index_fetch_attempts == 4
        assert loaded.index_retry_backoff_seconds == 0.75
        assert loaded.library_dir == Path("C:/gamehub")
        assert loaded.firmware_dir == Path("C:/gamehub/firmware")
        assert loaded.state_path == Path("C:/gamehub/state.json")
        assert loaded.steam_userdata_dir == Path("C:/Steam/userdata")
        assert loaded.steam_id == "76561198000000001"
        assert loaded.steam_exe == Path("C:/Steam/steam.exe")
        assert loaded.sgdb_api_key == "from-config-key"
        assert loaded.sgdb_cache_dir == Path("C:/cache/sgdb")
        assert loaded.sgdb_enabled_kinds == ("grid", "icon")


def test_load_config_rejects_removed_legacy_path_keys(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        monkeypatch.delenv("GAMEHUB_SGDB_API_KEY", raising=False)
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[paths]",
                    'library_dir = "C:/legacy-library"',
                    'firmware_dir = "C:/legacy-firmware"',
                    'state_path = "C:/legacy/state.json"',
                ]
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Unsupported \\[paths\\] keys"):
            load_config(config_path)


def test_load_config_prefers_sgdb_api_key_from_env(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[sgdb]",
                    'api_key = "from-config-key"',
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GAMEHUB_SGDB_API_KEY", "from-env-key")

        loaded = load_config(config_path)

        assert loaded.sgdb_api_key == "from-env-key"


def test_load_config_supports_server_index_fetch_env_overrides(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[server]",
                    'url = "http://example.invalid:9000"',
                    "index_timeout_seconds = 40",
                    "index_fetch_attempts = 2",
                    "index_retry_backoff_seconds = 1.0",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GAMEHUB_INDEX_TIMEOUT_SECONDS", "55")
        monkeypatch.setenv("GAMEHUB_INDEX_FETCH_ATTEMPTS", "6")
        monkeypatch.setenv("GAMEHUB_INDEX_RETRY_BACKOFF_SECONDS", "2.5")

        loaded = load_config(config_path)

        assert loaded.index_timeout_seconds == 55.0
        assert loaded.index_fetch_attempts == 6
        assert loaded.index_retry_backoff_seconds == 2.5


def test_load_config_supports_controllers_block(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[controllers]",
                    "launch_autoconfig = false",
                    'profiles_dir = "D:/GameHub/controller_profiles"',
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.controllers.launch_autoconfig is False
        assert loaded.controllers.profiles_dir == Path("D:/GameHub/controller_profiles")


def test_load_config_supports_linux_overrides_block(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[linux]",
                    'emulator_install_backend = "flatpak"',
                    'emulator_install_command = "sudo apt install -y {package}"',
                    'flatpak_remote = "flathub"',
                    'retroarch_cfg_path = "~/.config/retroarch/retroarch.cfg"',
                    'retroarch_system_dir = "~/.config/retroarch/system"',
                    'retroarch_cores_dir = "~/.config/retroarch/cores"',
                    'retroarch_info_dir = "~/.config/retroarch/info"',
                    'retroarch_cores_base_url = "https://example.invalid/cores/"',
                    'pcsx2_ini_path = "~/.config/PCSX2/inis/PCSX2.ini"',
                    'pcsx2_bios_dir = "~/.config/PCSX2/bios"',
                    'dolphin_user_path = "~/.local/share/dolphin-emu"',
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.linux.emulator_install_backend == "flatpak"
        assert loaded.linux.emulator_install_command == "sudo apt install -y {package}"
        assert loaded.linux.flatpak_remote == "flathub"
        assert loaded.linux.retroarch_cfg_path == Path("~/.config/retroarch/retroarch.cfg").expanduser()
        assert loaded.linux.retroarch_system_dir == Path("~/.config/retroarch/system").expanduser()
        assert loaded.linux.retroarch_cores_dir == Path("~/.config/retroarch/cores").expanduser()
        assert loaded.linux.retroarch_info_dir == Path("~/.config/retroarch/info").expanduser()
        assert loaded.linux.retroarch_cores_base_url == "https://example.invalid/cores/"
        assert loaded.linux.pcsx2_ini_path == Path("~/.config/PCSX2/inis/PCSX2.ini").expanduser()
        assert loaded.linux.pcsx2_bios_dir == Path("~/.config/PCSX2/bios").expanduser()
        assert loaded.linux.dolphin_user_path == Path("~/.local/share/dolphin-emu").expanduser()


def test_load_config_supports_macos_overrides_block(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[macos]",
                    'emulator_install_backend = "official"',
                    'emulator_install_command = "brew install --cask {package}"',
                    "disable_pcsx2_rosetta = true",
                    'retroarch_cfg_path = "~/.config/retroarch/retroarch.cfg"',
                    'retroarch_system_dir = "~/Library/Application Support/RetroArch/system"',
                    'retroarch_cores_dir = "~/Library/Application Support/RetroArch/cores"',
                    'retroarch_info_dir = "~/Library/Application Support/RetroArch/info"',
                    'retroarch_cores_base_url = "https://example.invalid/apple-silicon/"',
                    'pcsx2_ini_path = "~/Library/Application Support/PCSX2/inis/PCSX2.ini"',
                    'pcsx2_bios_dir = "~/Library/Application Support/PCSX2/bios"',
                    'dolphin_user_path = "~/Library/Application Support/Dolphin"',
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.macos.emulator_install_backend == "official"
        assert loaded.macos.emulator_install_command == "brew install --cask {package}"
        assert loaded.macos.disable_pcsx2_rosetta is True
        assert loaded.macos.retroarch_cfg_path == Path("~/.config/retroarch/retroarch.cfg").expanduser()
        assert loaded.macos.retroarch_system_dir == Path("~/Library/Application Support/RetroArch/system").expanduser()
        assert loaded.macos.retroarch_cores_dir == Path("~/Library/Application Support/RetroArch/cores").expanduser()
        assert loaded.macos.retroarch_info_dir == Path("~/Library/Application Support/RetroArch/info").expanduser()
        assert loaded.macos.retroarch_cores_base_url == "https://example.invalid/apple-silicon/"
        assert loaded.macos.pcsx2_ini_path == Path("~/Library/Application Support/PCSX2/inis/PCSX2.ini").expanduser()
        assert loaded.macos.pcsx2_bios_dir == Path("~/Library/Application Support/PCSX2/bios").expanduser()
        assert loaded.macos.dolphin_user_path == Path("~/Library/Application Support/Dolphin").expanduser()


def test_load_config_supports_centralized_env_precedence(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[steam]",
                    'userdata_dir = "C:/Steam/config-value"',
                    "",
                    "[linux]",
                    'emulator_install_backend = "flatpak"',
                    'emulator_install_command = "echo config {package}"',
                    'flatpak_remote = "config-remote"',
                    'retroarch_cfg_path = "C:/RetroArch/config.cfg"',
                    'retroarch_system_dir = "C:/RetroArch/system"',
                    'retroarch_cores_dir = "C:/RetroArch/cores"',
                    'retroarch_info_dir = "C:/RetroArch/info"',
                    'retroarch_cores_base_url = "https://config.example/cores/"',
                    'pcsx2_ini_path = "C:/PCSX2/PCSX2.ini"',
                    'pcsx2_bios_dir = "C:/PCSX2/bios"',
                    'dolphin_user_path = "C:/Dolphin/User"',
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GAMEHUB_STEAM_USERDATA_DIR", "D:/Steam/env-value")
        monkeypatch.setenv("GAMEHUB_LINUX_EMULATOR_INSTALL_BACKEND", "command")
        monkeypatch.setenv("GAMEHUB_LINUX_EMULATOR_INSTALL_COMMAND", "sudo apt-get install -y {package}")
        monkeypatch.setenv("GAMEHUB_LINUX_FLATPAK_REMOTE", "env-remote")
        monkeypatch.setenv("GAMEHUB_RETROARCH_CFG_PATH", "D:/RetroArch/env.cfg")
        monkeypatch.setenv("RETROARCH_SYSTEM_DIR", "D:/RetroArch/system")
        monkeypatch.setenv("GAMEHUB_RETROARCH_CORES_DIR", "D:/RetroArch/cores")
        monkeypatch.setenv("GAMEHUB_RETROARCH_INFO_DIR", "D:/RetroArch/info")
        monkeypatch.setenv("GAMEHUB_RETROARCH_CORES_BASE_URL", "https://env.example/cores/")
        monkeypatch.setenv("GAMEHUB_PCSX2_INI_PATH", "D:/PCSX2/PCSX2.ini")
        monkeypatch.setenv("PCSX2_BIOS_DIR", "D:/PCSX2/bios")
        monkeypatch.setenv("DOLPHIN_EMU_USERPATH", "D:/Dolphin/User")
        monkeypatch.setenv("GAMEHUB_CONTROLLER_LAUNCH_AUTOCONFIG", "false")
        monkeypatch.setenv("GAMEHUB_CONTROLLER_PROFILES_DIR", "D:/GameHub/profiles")

        loaded = load_config(config_path)

        assert loaded.steam_userdata_dir == Path("D:/Steam/env-value")
        assert loaded.linux.emulator_install_backend == "command"
        assert loaded.linux.emulator_install_command == "sudo apt-get install -y {package}"
        assert loaded.linux.flatpak_remote == "env-remote"
        assert loaded.linux.retroarch_cfg_path == Path("D:/RetroArch/env.cfg")
        assert loaded.linux.retroarch_system_dir == Path("D:/RetroArch/system")
        assert loaded.linux.retroarch_cores_dir == Path("D:/RetroArch/cores")
        assert loaded.linux.retroarch_info_dir == Path("D:/RetroArch/info")
        assert loaded.linux.retroarch_cores_base_url == "https://env.example/cores/"
        assert loaded.linux.pcsx2_ini_path == Path("D:/PCSX2/PCSX2.ini")
        assert loaded.linux.pcsx2_bios_dir == Path("D:/PCSX2/bios")
        assert loaded.linux.dolphin_user_path == Path("D:/Dolphin/User")
        assert loaded.controllers.launch_autoconfig is False
        assert loaded.controllers.profiles_dir == Path("D:/GameHub/profiles")


def test_load_config_supports_macos_env_precedence(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[linux]",
                    'emulator_install_backend = "flatpak"',
                    'retroarch_cfg_path = "C:/RetroArch/linux.cfg"',
                    "",
                    "[macos]",
                    'emulator_install_backend = "auto"',
                    'emulator_install_command = "echo config {package}"',
                    "disable_pcsx2_rosetta = true",
                    'retroarch_cfg_path = "~/Library/Application Support/RetroArch/config/retroarch.cfg"',
                    'retroarch_system_dir = "~/Library/Application Support/RetroArch/system"',
                    'retroarch_cores_dir = "~/Library/Application Support/RetroArch/cores"',
                    'retroarch_info_dir = "~/Library/Application Support/RetroArch/info"',
                    'retroarch_cores_base_url = "https://config.example/apple-silicon/"',
                    'pcsx2_ini_path = "~/Library/Application Support/PCSX2/inis/PCSX2.ini"',
                    'pcsx2_bios_dir = "~/Library/Application Support/PCSX2/bios"',
                    'dolphin_user_path = "~/Library/Application Support/Dolphin"',
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GAMEHUB_MACOS_EMULATOR_INSTALL_BACKEND", "command")
        monkeypatch.setenv("GAMEHUB_MACOS_EMULATOR_INSTALL_COMMAND", "brew install --cask {package}")
        monkeypatch.setenv("GAMEHUB_MACOS_DISABLE_PCSX2_ROSETTA", "false")
        monkeypatch.setenv("GAMEHUB_RETROARCH_CFG_PATH", "/Volumes/GameHub/RetroArch/retroarch.cfg")
        monkeypatch.setenv("RETROARCH_SYSTEM_DIR", "/Volumes/GameHub/RetroArch/system")
        monkeypatch.setenv("GAMEHUB_RETROARCH_CORES_DIR", "/Volumes/GameHub/RetroArch/cores")
        monkeypatch.setenv("GAMEHUB_RETROARCH_INFO_DIR", "/Volumes/GameHub/RetroArch/info")
        monkeypatch.setenv("GAMEHUB_RETROARCH_CORES_BASE_URL", "https://env.example/apple-silicon/")
        monkeypatch.setenv("GAMEHUB_PCSX2_INI_PATH", "/Users/tester/Library/Application Support/PCSX2/inis/PCSX2.ini")
        monkeypatch.setenv("PCSX2_BIOS_DIR", "/Users/tester/Library/Application Support/PCSX2/bios")
        monkeypatch.setenv("DOLPHIN_EMU_USERPATH", "/Users/tester/Library/Application Support/Dolphin")

        loaded = load_config(config_path)

        assert loaded.linux.emulator_install_backend == "flatpak"
        assert loaded.linux.retroarch_cfg_path == Path("/Volumes/GameHub/RetroArch/retroarch.cfg")
        assert loaded.macos.emulator_install_backend == "command"
        assert loaded.macos.emulator_install_command == "brew install --cask {package}"
        assert loaded.macos.disable_pcsx2_rosetta is False
        assert loaded.macos.retroarch_cfg_path == Path("/Volumes/GameHub/RetroArch/retroarch.cfg")
        assert loaded.macos.retroarch_system_dir == Path("/Volumes/GameHub/RetroArch/system")
        assert loaded.macos.retroarch_cores_dir == Path("/Volumes/GameHub/RetroArch/cores")
        assert loaded.macos.retroarch_info_dir == Path("/Volumes/GameHub/RetroArch/info")
        assert loaded.macos.retroarch_cores_base_url == "https://env.example/apple-silicon/"
        assert loaded.macos.pcsx2_ini_path == Path("/Users/tester/Library/Application Support/PCSX2/inis/PCSX2.ini")
        assert loaded.macos.pcsx2_bios_dir == Path("/Users/tester/Library/Application Support/PCSX2/bios")
        assert loaded.macos.dolphin_user_path == Path("/Users/tester/Library/Application Support/Dolphin")


def test_load_config_defaults_keep_linux_unchanged_when_macos_missing(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[linux]",
                    'emulator_install_backend = "flatpak"',
                    'emulator_install_command = "sudo apt install -y {package}"',
                    'flatpak_remote = "flathub"',
                    'retroarch_cfg_path = "~/.config/retroarch/retroarch.cfg"',
                    'retroarch_system_dir = "~/.config/retroarch/system"',
                    'retroarch_cores_dir = "~/.config/retroarch/cores"',
                    'retroarch_info_dir = "~/.config/retroarch/info"',
                    'retroarch_cores_base_url = "https://example.invalid/cores/"',
                    'pcsx2_ini_path = "~/.config/PCSX2/inis/PCSX2.ini"',
                    'pcsx2_bios_dir = "~/.config/PCSX2/bios"',
                    'dolphin_user_path = "~/.local/share/dolphin-emu"',
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.linux == LinuxConfig(
            emulator_install_backend="flatpak",
            emulator_install_command="sudo apt install -y {package}",
            flatpak_remote="flathub",
            retroarch_cfg_path=Path("~/.config/retroarch/retroarch.cfg").expanduser(),
            retroarch_system_dir=Path("~/.config/retroarch/system").expanduser(),
            retroarch_cores_dir=Path("~/.config/retroarch/cores").expanduser(),
            retroarch_info_dir=Path("~/.config/retroarch/info").expanduser(),
            retroarch_cores_base_url="https://example.invalid/cores/",
            pcsx2_ini_path=Path("~/.config/PCSX2/inis/PCSX2.ini").expanduser(),
            pcsx2_bios_dir=Path("~/.config/PCSX2/bios").expanduser(),
            dolphin_user_path=Path("~/.local/share/dolphin-emu").expanduser(),
        )
        assert loaded.macos == MacOSConfig()


def test_load_config_defaults_disable_pcsx2_rosetta_to_false(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        loaded = load_config(temp_root / "missing.toml")

        assert loaded.macos.disable_pcsx2_rosetta is False


def test_load_config_normalizes_quoted_sgdb_api_key(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[sgdb]",
                    'api_key = "  \\"quoted-config-key\\"  "',
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.delenv("GAMEHUB_SGDB_API_KEY", raising=False)

        loaded = load_config(config_path)

        assert loaded.sgdb_api_key == "quoted-config-key"


def test_state_round_trip_with_atomic_save(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-state-") as temp_root:
        state_path = temp_root / "state.json"
        state = SyncState(
            downloaded_checksums={"file_1": "a" * 64},
            firmware_checksums={"PSX/scph5501.bin": "b" * 64},
            last_sync="2026-02-14T18:00:00+00:00",
            bootstrap_version=1,
        )

        save_state_atomic(state_path, state)
        loaded = load_state(state_path)

        assert loaded.to_dict() == state.to_dict()


def test_state_overwrite_creates_backup(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-state-") as temp_root:
        state_path = temp_root / "state.json"
        first = SyncState(downloaded_checksums={"file_1": "a" * 64})
        second = SyncState(downloaded_checksums={"file_2": "b" * 64})

        save_state_atomic(state_path, first)
        save_state_atomic(state_path, second)

        backups = list(state_path.parent.glob("state.json.*.bak"))
        assert len(backups) == 1
        backup_payload = json.loads(backups[0].read_text(encoding="utf-8"))
        assert backup_payload == first.to_dict()
        assert load_state(state_path).to_dict() == second.to_dict()


def test_load_state_defaults_bootstrap_version_when_missing(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-state-") as temp_root:
        state_path = temp_root / "state.json"
        state_path.write_text(
            '{\n  "downloaded_checksums": {},\n  "firmware_checksums": {},\n  "tombstones": [],\n  "last_sync": null\n}\n',
            encoding="utf-8",
        )

        loaded = load_state(state_path)

        assert loaded.bootstrap_version is None


def test_load_state_ignores_legacy_tombstones(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-state-") as temp_root:
        state_path = temp_root / "state.json"
        state_path.write_text(
            "\n".join(
                [
                    "{",
                    '  "downloaded_checksums": {},',
                    '  "firmware_checksums": {},',
                    '  "tombstones": ["title_old"],',
                    '  "last_sync": "2026-02-14T18:00:00+00:00",',
                    '  "bootstrap_version": 1',
                    "}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        loaded = load_state(state_path)

        assert "tombstones" not in loaded.to_dict()
        assert loaded.last_sync == "2026-02-14T18:00:00+00:00"


def test_load_config_supports_roms_dir(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[paths]",
                    'gamehub_dir = "C:/gamehub"',
                    'roms_dir = "E:/sdcard/roms"',
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.library_dir == Path("C:/gamehub")
        assert loaded.roms_dir == Path("E:/sdcard/roms")


def test_load_config_prefers_roms_env_override(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text('[paths]\nroms_dir = "C:/config/output"\n', encoding="utf-8")
        monkeypatch.setenv("GAMEHUB_ROMS_DIR", "D:/env/output")

        loaded = load_config(config_path)

        assert loaded.roms_dir == Path("D:/env/output")


def test_load_config_rejects_removed_output_dir_alias(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text('[paths]\noutput_dir = "C:/config/output"\n', encoding="utf-8")

        with pytest.raises(ValueError, match=r"paths\.output_dir"):
            load_config(config_path)


def test_load_config_rejects_removed_output_dir_env_alias(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text("", encoding="utf-8")
        monkeypatch.setenv("GAMEHUB_OUTPUT_DIR", "D:/legacy-output")

        with pytest.raises(ValueError, match="GAMEHUB_OUTPUT_DIR"):
            load_config(config_path)


def test_load_config_save_sync_defaults_disabled(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        monkeypatch.delenv("GAMEHUB_SGDB_API_KEY", raising=False)
        config_path = temp_root / "missing.toml"

        loaded = load_config(config_path)

        assert loaded.save_sync == SaveSyncConfig()
        assert loaded.save_sync.conflict_policy == "manual"


def test_load_config_supports_save_sync_block(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[save_sync]",
                    "enabled = true",
                    'mode = "bidirectional"',
                    'conflict_policy = "manual"',
                    'systems = ["ps2", " Wii ", "ps2"]',
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.save_sync.enabled is True
        assert loaded.save_sync.mode == "bidirectional"
        assert loaded.save_sync.conflict_policy == "manual"
        assert loaded.save_sync.systems == ("PS2", "WII")


def test_load_config_defaults_save_sync_conflict_policy_to_manual_when_omitted(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[save_sync]",
                    "enabled = true",
                    'mode = "bidirectional"',
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.save_sync.enabled is True
        assert loaded.save_sync.mode == "bidirectional"
        assert loaded.save_sync.conflict_policy == "manual"


def test_load_config_normalizes_invalid_save_sync_values(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[save_sync]",
                    'enabled = "nope"',
                    'mode = "download-only"',
                    'conflict_policy = "unexpected"',
                    'systems = ["", 123, "  nEs  "]',
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.save_sync.enabled is False
        assert loaded.save_sync.mode == "download"
        assert loaded.save_sync.conflict_policy == "manual"
        assert loaded.save_sync.systems == ("NES",)


def test_load_config_supports_backups_block(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[backups]",
                    "keep_limit = 5",
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.backups.keep_limit == 5


def test_load_config_prefers_backup_keep_limit_from_env(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text("[backups]\nkeep_limit = 4\n", encoding="utf-8")
        monkeypatch.setenv("GAMEHUB_BACKUP_KEEP_LIMIT", "7")

        loaded = load_config(config_path)

        assert loaded.backups.keep_limit == 7


def test_load_config_normalizes_invalid_backup_keep_limit_to_default(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text("[backups]\nkeep_limit = 0\n", encoding="utf-8")
        monkeypatch.setenv("GAMEHUB_BACKUP_KEEP_LIMIT", "invalid")

        loaded = load_config(config_path)

        assert loaded.backups.keep_limit == 3


def test_default_gamehub_dir_supports_macos_state_root(monkeypatch) -> None:
    monkeypatch.setattr(
        "gamehub_cli.common.config.user_state_dir",
        lambda appname: f"/Users/tester/Library/Application Support/{appname}",
    )

    assert default_gamehub_dir() == Path("/Users/tester/Library/Application Support/gamehub")


def test_macos_platform_path_helpers_use_expected_roots(monkeypatch) -> None:
    home = Path("/Users/tester")
    monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))

    assert macos_application_support_root() == home / "Library" / "Application Support"
    assert macos_user_applications_dir() == home / "Applications"
    assert macos_system_applications_dir().as_posix() == "/Applications"
    assert macos_retroarch_root() == home / "Library" / "Application Support" / "RetroArch"
    assert macos_pcsx2_root() == home / "Library" / "Application Support" / "PCSX2"
    assert macos_dolphin_root() == home / "Library" / "Application Support" / "Dolphin"


def test_load_state_defaults_save_sync_keys_when_missing(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-state-") as temp_root:
        state_path = temp_root / "state.json"
        state_path.write_text(
            "\n".join(
                [
                    "{",
                    '  "downloaded_checksums": {},',
                    '  "firmware_checksums": {},',
                    '  "tombstones": [],',
                    '  "last_sync": null,',
                    '  "bootstrap_version": 1',
                    "}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        loaded = load_state(state_path)

        assert loaded.save_checksums == {}
        assert loaded.save_lineage == {}
        assert loaded.save_binding_roots == {}
        assert loaded.offline_shortcut_titles == {}
        assert loaded.unresolved_save_conflicts == {}


def test_state_round_trip_persists_save_sync_lineage(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-state-") as temp_root:
        state_path = temp_root / "state.json"
        state = SyncState(
            downloaded_checksums={"file_1": "a" * 64},
            firmware_checksums={"PSX/scph5501.bin": "b" * 64},
            save_checksums={"save_1": "c" * 64},
            save_lineage={
                "save_1": {
                    "local_sha256": "d" * 64,
                    "remote_sha256": "c" * 64,
                    "local_updated_at": "2026-02-14T18:00:00+00:00",
                    "remote_updated_at": "2026-02-14T18:30:00+00:00",
                    "synced_at": "2026-02-14T19:00:00+00:00",
                }
            },
            save_binding_roots={
                "savebind_1": {
                    "canonical_root": "title/00000001/00000002/data",
                    "materialized_root": "Nintendo 3DS/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/title/00000001/00000002/data",
                }
            },
            offline_shortcut_titles={"title_gbc_pokemon": "2026-02-14T18:05:00+00:00"},
            unresolved_save_conflicts={"save_2": "both-changed-manual"},
            last_sync="2026-02-14T18:00:00+00:00",
            bootstrap_version=1,
        )

        save_state_atomic(state_path, state)
        loaded = load_state(state_path)

        assert loaded.to_dict() == state.to_dict()
