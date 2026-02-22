from __future__ import annotations

from pathlib import Path

from gamehub_cli.common.config import ControllersConfig, LinuxConfig, default_config_path, load_config
from gamehub_cli.sync.state import SyncState, load_state, save_state_atomic


def test_load_config_uses_defaults_when_file_is_missing(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        monkeypatch.delenv("GAMEHUB_SGDB_API_KEY", raising=False)
        config_home = temp_root / "cfg-home"
        state_home = temp_root / "state-home"
        monkeypatch.setattr("gamehub_cli.common.config.user_config_dir", lambda appname: str(config_home / appname))
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
        assert loaded.controllers == ControllersConfig()


def test_load_config_prefers_workspace_config_when_present(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        monkeypatch.delenv("GAMEHUB_SGDB_API_KEY", raising=False)
        config_home = temp_root / "cfg-home"
        state_home = temp_root / "state-home"
        monkeypatch.setattr("gamehub_cli.common.config.user_config_dir", lambda appname: str(config_home / appname))
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
        monkeypatch.setattr(
            "gamehub_cli.common.config.user_config_dir", lambda appname: str(temp_root / "legacy-config" / appname)
        )

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
        monkeypatch.setattr(
            "gamehub_cli.common.config.user_config_dir", lambda appname: str(temp_root / "legacy-config" / appname)
        )

        loaded = load_config()

        assert loaded.server_url == "http://home-default.invalid:8123"
        assert loaded.library_dir == Path("D:/HomeDefaultGamehub")
        assert loaded.firmware_dir == Path("D:/HomeDefaultGamehub/firmware")
        assert loaded.state_path == Path("D:/HomeDefaultGamehub/state.json")


def test_default_config_path_uses_legacy_when_present(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-legacy-") as temp_root:
        home = temp_root / "home"
        legacy_config = temp_root / "legacy-config" / "gamehub" / "config.toml"
        legacy_config.parent.mkdir(parents=True, exist_ok=True)
        legacy_config.write_text("[server]\nurl='http://legacy.invalid:8123'\n", encoding="utf-8")
        monkeypatch.chdir(temp_root)
        monkeypatch.setattr("gamehub_cli.common.config.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr(
            "gamehub_cli.common.config.user_config_dir", lambda appname: str(temp_root / "legacy-config" / appname)
        )

        resolved = default_config_path()

        assert resolved == legacy_config


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


def test_load_config_supports_legacy_path_keys(monkeypatch, workspace_tempdir) -> None:
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

        loaded = load_config(config_path)

        assert loaded.library_dir == Path("C:/legacy-library")
        assert loaded.firmware_dir == Path("C:/legacy-firmware")
        assert loaded.state_path == Path("C:/legacy/state.json")


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
            tombstones=["title_old"],
            last_sync="2026-02-14T18:00:00+00:00",
        )

        save_state_atomic(state_path, state)
        loaded = load_state(state_path)

        assert loaded.to_dict() == state.to_dict()


def test_load_config_supports_roms_output_dir_and_alias(workspace_tempdir) -> None:
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


def test_load_config_prefers_roms_output_env_override(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text('[paths]\noutput_dir = "C:/config/output"\n', encoding="utf-8")
        monkeypatch.setenv("GAMEHUB_ROMS_DIR", "D:/env/output")

        loaded = load_config(config_path)

        assert loaded.roms_dir == Path("D:/env/output")
