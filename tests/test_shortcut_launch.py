from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import gamehub_cli.shortcuts.shortcut_launch as launch_module
from gamehub_cli.common.config import ControllersConfig, GamehubConfig, SaveSyncConfig
from gamehub_cli.controllers.detection import XboxController
from gamehub_cli.shortcuts.shortcut_launch import (
    encode_shortcut_payload,
    parse_shortcut_payload,
    run_shortcut_launch,
)
from gamehub_cli.sync.state import MISSED_POSTEXIT_UPLOAD_REASON
from gamehub_cli.sync.transfer import SaveUploadConflictError
from gamehub_common.ids import make_save_id
from gamehub_common.models import LibraryIndex, SaveBindingSpec, SaveSpec


def _config() -> GamehubConfig:
    return GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=True),
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_parse_shortcut_payload_round_trip() -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "pcsx2",
            "target_exe": "flatpak",
            "target_args": ["run", "--file-forwarding", "net.pcsx2.PCSX2"],
            "start_dir": "",
            "config_path": "D:/GameHub/config.toml",
            "title_id": "title_ps2_ffx",
            "system": "PS2",
            "rom_rel_path": "roms/PS2/Final Fantasy X.iso",
        }
    )

    payload = parse_shortcut_payload(token)

    assert payload.version == 1
    assert payload.emulator == "pcsx2"
    assert payload.target_exe == "flatpak"
    assert payload.target_args == ("run", "--file-forwarding", "net.pcsx2.PCSX2")
    assert payload.config_path == "D:/GameHub/config.toml"
    assert payload.title_id == "title_ps2_ffx"
    assert payload.system == "PS2"
    assert payload.rom_rel_path == "roms/PS2/Final Fantasy X.iso"


def test_parse_shortcut_payload_strips_wrapping_quotes_from_args() -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": '"C:/Emu/Dolphin.exe"',
            "target_args": ['"-b"', '"C:/Games/Path With Spaces/game.iso"'],
            "start_dir": '"C:/Emu"',
        }
    )

    payload = parse_shortcut_payload(token)

    assert payload.target_exe == '"C:/Emu/Dolphin.exe"'
    assert payload.target_args == ("-b", "C:/Games/Path With Spaces/game.iso")


def test_ensure_managed_memory_card_paths_prefers_payload_retroarch_cfg_on_windows(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-psx-managed-card-") as temp_root:
        portable_root = temp_root / "portable-ra"
        portable_root.mkdir(parents=True, exist_ok=True)
        portable_exe = portable_root / "retroarch.exe"
        portable_exe.write_bytes(b"exe")
        portable_cfg = portable_root / "retroarch.cfg"
        portable_cfg.write_text("", encoding="utf-8")
        portable_core_options = portable_root / "retroarch-core-options.cfg"
        portable_core_options.write_text("", encoding="utf-8")

        appdata_root = temp_root / "appdata-ra"
        appdata_root.mkdir(parents=True, exist_ok=True)
        appdata_cfg = appdata_root / "retroarch.cfg"
        appdata_cfg.write_text("", encoding="utf-8")
        appdata_core_options = appdata_root / "retroarch-core-options.cfg"
        appdata_core_options.write_text("", encoding="utf-8")

        monkeypatch.setattr(
            "gamehub_cli.firmware.targets.retroarch_cfg_candidates_for_config",
            lambda config=None: [appdata_cfg],
        )

        payload = launch_module.ShortcutLaunchPayload(
            version=1,
            emulator="retroarch",
            target_exe=str(portable_exe),
            target_args=(),
            title_id="title_psx_ctr",
            system="PSX",
            rom_rel_path="roms/PSX/Crash Team Racing.chd",
        )
        changed = launch_module._ensure_managed_memory_card_paths(payload, _config())

        assert changed is True
        portable_text = portable_core_options.read_text(encoding="utf-8")
        appdata_text = appdata_core_options.read_text(encoding="utf-8")
        assert 'swanstation_MemoryCard1Path = "GH_title_psx_ctr_1.mcd"' in portable_text
        assert 'swanstation_MemoryCard2Path = "GH_title_psx_ctr_2.mcd"' in portable_text
        assert "swanstation_MemoryCard1Path" not in appdata_text


def test_run_shortcut_launch_sets_azahar_sdl_dir_env(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-azahar-sdl-") as temp_root:
        azahar_dir = temp_root / "Azahar"
        azahar_dir.mkdir(parents=True, exist_ok=True)
        azahar_exe = azahar_dir / "azahar.exe"
        azahar_exe.write_text("", encoding="utf-8")

        token = encode_shortcut_payload(
            {
                "v": 1,
                "emulator": "azahar",
                "target_exe": str(azahar_exe),
                "target_args": ["-f", "rom.3ds"],
            }
        )
        config = _config()
        observed: dict[str, str] = {}

        monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
        monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.detect_xbox_controllers", lambda max_devices=2: [])
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch.apply_controller_profile",
            lambda *args, **kwargs: observed.setdefault("sdl_dir", os.environ.get("GAMEHUB_AZAHAR_SDL_DIR", "")),
        )
        monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target", lambda payload: 0)
        monkeypatch.delenv("GAMEHUB_AZAHAR_SDL_DIR", raising=False)

        run_shortcut_launch(payload_token=token)

        assert observed["sdl_dir"] == str(azahar_dir)


def test_run_shortcut_launch_fail_open_uses_kbm_fallback(monkeypatch) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "dolphin",
            "target_args": ["-b", "-e", "rom.iso"],
        }
    )
    config = _config()
    fallback_calls: list[str] = []

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch.detect_xbox_controllers",
        lambda max_devices=2: [XboxController(slot=0, name="XInput/0", subtype=0)],
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch.apply_controller_profile",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch.apply_named_controller_profile",
        lambda config, emulator_name, profile_name: fallback_calls.append(f"{emulator_name}:{profile_name}"),
    )
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target", lambda payload: 7)

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 7
    assert fallback_calls == ["dolphin:kbm"]


def test_run_shortcut_launch_detection_failure_falls_back_to_kbm_profile_selection(monkeypatch) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "pcsx2",
            "target_exe": "pcsx2-qt.exe",
            "target_args": ["--nogui", "game.iso"],
        }
    )
    config = _config()
    applied_counts: list[int] = []

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.is_steam_deck_linux", lambda: False)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch.detect_xbox_controllers",
        lambda max_devices=2: (_ for _ in ()).throw(RuntimeError("detect failed")),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch.apply_controller_profile",
        lambda cfg, emulator_name, controller_count: applied_counts.append(controller_count),
    )
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target", lambda payload: 3)

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 3
    assert applied_counts == [0]


def test_run_shortcut_launch_uses_azahar_windows_exit_hook(monkeypatch) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "azahar",
            "target_exe": "C:/Emu/Azahar.exe",
            "target_args": ["-f", "rom.3ds"],
        }
    )
    config = _config()
    hook_calls: list[str] = []

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.apply_controller_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.sys.platform", "win32")
    monkeypatch.setenv("GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK", "true")
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_windows_azahar_target_with_exit_hook",
        lambda payload: hook_calls.append(payload.emulator) or 11,
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_target",
        lambda payload: (_ for _ in ()).throw(AssertionError("direct launch should not be used")),
    )

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 11
    assert hook_calls == ["azahar"]


def test_run_shortcut_launch_uses_dolphin_linux_exit_hook_for_flatpak(monkeypatch) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "flatpak",
            "target_args": ["run", "--device=all", "org.DolphinEmu.dolphin-emu", "-b", "-e", "game.iso"],
        }
    )
    config = _config()
    hook_calls: list[str] = []

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.apply_controller_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.sys.platform", "linux")
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_linux_dolphin_target_with_exit_hook",
        lambda payload: hook_calls.append(payload.emulator) or 9,
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_target",
        lambda payload: (_ for _ in ()).throw(AssertionError("direct launch should not be used")),
    )

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 9
    assert hook_calls == ["dolphin"]


def test_run_shortcut_launch_audit_enables_verbose_profile_logs(monkeypatch) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "dolphin",
            "target_args": ["-b", "-e", "rom.iso"],
        }
    )
    config = _config()
    observed: dict[str, object] = {}

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.detect_xbox_controllers", lambda max_devices=2: [])

    def _fake_apply(*args, **kwargs):
        observed["verbose"] = kwargs.get("verbose")
        return "kbm"

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.apply_controller_profile", _fake_apply)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target", lambda payload: 0)

    exit_code = run_shortcut_launch(payload_token=token, audit=True)

    assert exit_code == 0
    assert observed["verbose"] is True


def test_run_shortcut_launch_can_disable_dolphin_linux_exit_hook(monkeypatch) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "flatpak",
            "target_args": ["run", "--device=all", "org.DolphinEmu.dolphin-emu", "-b", "-e", "game.iso"],
        }
    )
    config = _config()

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.apply_controller_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.sys.platform", "linux")
    monkeypatch.setenv("GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK", "false")
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_linux_dolphin_target_with_exit_hook",
        lambda payload: (_ for _ in ()).throw(AssertionError("hook should be disabled")),
    )
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target", lambda payload: 4)

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 4


def test_run_shortcut_launch_deck_zero_detect_defaults_to_xbox_1p(monkeypatch, capsys) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "dolphin",
            "target_args": ["-b", "-e", "rom.iso"],
        }
    )
    config = _config()
    observed: dict[str, int] = {}

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.is_steam_deck_linux", lambda: True)

    def _apply(cfg, emulator_name, controller_count, verbose=False):
        observed["count"] = controller_count
        return "xbox_1p"

    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch.apply_controller_profile",
        _apply,
    )
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target", lambda payload: 0)

    exit_code = run_shortcut_launch(payload_token=token, audit=True)

    assert exit_code == 0
    assert observed["count"] == 1
    out = capsys.readouterr().out
    assert "zero_detect_policy=xbox_1p" in out
    assert "effective_controller_count=1" in out


def test_run_shortcut_launch_non_deck_zero_detect_behavior_unchanged(monkeypatch) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "dolphin",
            "target_args": ["-b", "-e", "rom.iso"],
        }
    )
    config = _config()
    observed: dict[str, int] = {}

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.is_steam_deck_linux", lambda: False)

    def _apply(cfg, emulator_name, controller_count, verbose=False):
        observed["count"] = controller_count
        return "kbm"

    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch.apply_controller_profile",
        _apply,
    )
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target", lambda payload: 0)

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 0
    assert observed["count"] == 0


def test_run_shortcut_launch_passes_payload_executable_resolver_to_save_sync(monkeypatch) -> None:
    target_exe = "C:/PortableRetroArch/retroarch.exe"
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "retroarch",
            "target_exe": target_exe,
            "target_args": ["-f", "game.chd"],
            "title_id": "title_psx_ctr",
            "system": "PSX",
            "rom_rel_path": "roms/PSX/Crash Team Racing.chd",
        }
    )
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
    )
    state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})
    observed: dict[str, str] = {}

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._load_shortcut_state", lambda path: state)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._ensure_managed_memory_card_paths",
        lambda payload, cfg: False,
    )

    def _fake_prelaunch(**kwargs):
        resolver = kwargs["resolve_executable"]
        observed["prelaunch"] = resolver("retroarch")
        return launch_module._ShortcutSaveContext(
            save_snapshots={}, exact_binding_snapshots={}, tree_snapshots={}
        ), False

    def _fake_postexit(**kwargs):
        resolver = kwargs["resolve_executable"]
        observed["postexit"] = resolver("retroarch")
        return False

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_shortcut_prelaunch_save_sync", _fake_prelaunch)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_shortcut_postexit_save_sync", _fake_postexit)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target_with_optional_exit_hook", lambda payload: 0)

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 0
    assert observed["prelaunch"] == target_exe
    assert observed["postexit"] == target_exe


def test_run_shortcut_launch_passes_flatpak_app_resolver_to_save_sync(monkeypatch) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "pcsx2",
            "target_exe": "flatpak",
            "target_args": [
                "run",
                "--file-forwarding",
                "net.pcsx2.PCSX2",
                "-fullscreen",
                "--",
                "@@",
                "/var/home/deck/GameHub/roms/PS2/Gran Turismo 4.iso",
                "@@",
            ],
            "title_id": "title_ps2_gt4",
            "system": "PS2",
            "rom_rel_path": "roms/PS2/Gran Turismo 4.iso",
        }
    )
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
    )
    state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})
    observed: dict[str, str] = {}

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._load_shortcut_state", lambda path: state)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._ensure_managed_memory_card_paths",
        lambda payload, cfg: False,
    )

    def _fake_prelaunch(**kwargs):
        resolver = kwargs["resolve_executable"]
        observed["prelaunch"] = resolver("pcsx2")
        return launch_module._ShortcutSaveContext(
            save_snapshots={}, exact_binding_snapshots={}, tree_snapshots={}
        ), False

    def _fake_postexit(**kwargs):
        resolver = kwargs["resolve_executable"]
        observed["postexit"] = resolver("pcsx2")
        return False

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_shortcut_prelaunch_save_sync", _fake_prelaunch)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_shortcut_postexit_save_sync", _fake_postexit)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target_with_optional_exit_hook", lambda payload: 0)

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 0
    assert observed["prelaunch"].endswith("/flatpak/exports/bin/net.pcsx2.PCSX2")
    assert observed["postexit"].endswith("/flatpak/exports/bin/net.pcsx2.PCSX2")


def test_run_shortcut_launch_passes_azahar_exit_hook_app_resolver_to_save_sync(monkeypatch) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "azahar",
            "target_exe": "/usr/bin/python3",
            "target_args": [
                "-m",
                "gamehub_cli.controllers.azahar_exit_hook",
                "--app-id",
                "org.azahar_emu.Azahar",
                "--rom",
                "/var/home/deck/GameHub/roms/N3DS/Pilotwings Resort.3ds",
            ],
            "title_id": "title_n3ds_pilotwings_resort",
            "system": "N3DS",
            "rom_rel_path": "roms/N3DS/Pilotwings Resort.3ds",
        }
    )
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
    )
    state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})
    observed: dict[str, str] = {}

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._load_shortcut_state", lambda path: state)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._ensure_managed_memory_card_paths",
        lambda payload, cfg: False,
    )

    def _fake_prelaunch(**kwargs):
        resolver = kwargs["resolve_executable"]
        observed["prelaunch"] = resolver("azahar")
        return launch_module._ShortcutSaveContext(
            save_snapshots={}, exact_binding_snapshots={}, tree_snapshots={}
        ), False

    def _fake_postexit(**kwargs):
        resolver = kwargs["resolve_executable"]
        observed["postexit"] = resolver("azahar")
        return False

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_shortcut_prelaunch_save_sync", _fake_prelaunch)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_shortcut_postexit_save_sync", _fake_postexit)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target_with_optional_exit_hook", lambda payload: 0)

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 0
    assert observed["prelaunch"].endswith("/flatpak/exports/bin/org.azahar_emu.Azahar")
    assert observed["postexit"].endswith("/flatpak/exports/bin/org.azahar_emu.Azahar")


def test_snapshot_exact_binding_tracks_remote_missing_local_file(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        save_path = temp_root / "GH_title_ps2_test_1.ps2"
        save_path.write_bytes(b"memcard")
        binding = SaveBindingSpec(
            binding_id="savebind_ps2",
            title_id="title_ps2_test",
            system="PS2",
            kind="memory_card",
            server_rel_dir="saves/PS2/Test/memory_card",
            local_root="pcsx2_memcards",
            strategy="exact_files",
            candidate_filenames=("GH_title_ps2_test_1.ps2", "GH_title_ps2_test_2.ps2"),
            learn_rule=None,
            portable=True,
        )

        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch.resolve_binding_local_root",
            lambda _binding, **_kwargs: temp_root,
        )

        snapshot = launch_module._snapshot_exact_binding(
            binding,
            remote_save_ids=set(),
            resolve_executable=lambda _name: "",
        )

        assert snapshot is not None
        assert snapshot.local_sha256_by_suffix["GH_title_ps2_test_1.ps2"] == _sha256_bytes(b"memcard")
        assert snapshot.local_sha256_by_suffix["GH_title_ps2_test_2.ps2"] is None


def test_shortcut_postexit_exact_binding_sync_creates_remote_missing_save(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        save_path = temp_root / "Pokemon - Crystal Version.srm"
        save_path.write_bytes(b"battery")
        binding = SaveBindingSpec(
            binding_id="savebind_gbc",
            title_id="title_gbc_test",
            system="GBC",
            kind="battery",
            server_rel_dir="saves/GBC/Pokemon - Crystal Version/battery",
            local_root="retroarch_saves",
            strategy="exact_files",
            candidate_filenames=("Pokemon - Crystal Version.srm",),
            learn_rule=None,
            portable=True,
        )
        state = SimpleNamespace(save_checksums={}, save_lineage={}, unresolved_save_conflicts={})
        created_ids: list[str] = []

        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch.resolve_binding_local_root",
            lambda _binding, **_kwargs: temp_root,
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch.resolve_exact_local_save_destination",
            lambda **kwargs: temp_root / kwargs["filename"],
        )

        def _fake_upload_new(**kwargs):
            created_ids.append(kwargs["save_id"])
            return SaveSpec(
                save_id=kwargs["save_id"],
                title_id=binding.title_id,
                system=binding.system,
                kind=binding.kind,
                rel_path=f"{binding.server_rel_dir}/{kwargs['canonical_suffix']}",
                sha256=_sha256_bytes(b"battery"),
                size_bytes=len(b"battery"),
                updated_at=datetime(2026, 3, 4, 12, 0, tzinfo=UTC),
                portable=True,
            )

        monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._upload_new_save_from_path", _fake_upload_new)

        changed = launch_module._run_shortcut_postexit_exact_binding_sync(
            state=state,
            current_saves={},
            exact_snapshots={
                binding.binding_id: launch_module._ShortcutExactBindingSnapshot(
                    binding=binding,
                    local_sha256_by_suffix={"Pokemon - Crystal Version.srm": None},
                )
            },
            resolve_executable=lambda _name: "",
            server_url="http://localhost:8000",
            timeout_seconds=30.0,
            verbose=False,
            audit=False,
        )

        save_id = make_save_id("saves/GBC/Pokemon - Crystal Version/battery/Pokemon - Crystal Version.srm")
        assert changed is True
        assert created_ids == [save_id]
        assert state.save_checksums[save_id] == _sha256_bytes(b"battery")


def test_run_shortcut_launch_prelaunch_save_sync_failure_does_not_block_launch(monkeypatch, capsys) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "retroarch",
            "target_exe": "C:/RetroArch/retroarch.exe",
            "target_args": ["-f", "game.gbc"],
            "title_id": "title_gbc_pokemon",
            "system": "GBC",
            "rom_rel_path": "roms/GBC/Pokemon Crystal.gbc",
        }
    )
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
    )
    state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._load_shortcut_state", lambda path: state)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_shortcut_prelaunch_save_sync",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("server unavailable")),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_shortcut_postexit_save_sync", lambda **kwargs: False
    )
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target_with_optional_exit_hook", lambda payload: 17)

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 17
    assert "pre-launch save sync failed; continuing launch" in capsys.readouterr().out


def test_run_shortcut_launch_postexit_save_sync_failure_does_not_replace_exit_code(monkeypatch, capsys) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "retroarch",
            "target_exe": "C:/RetroArch/retroarch.exe",
            "target_args": ["-f", "game.gbc"],
            "title_id": "title_gbc_pokemon",
            "system": "GBC",
            "rom_rel_path": "roms/GBC/Pokemon Crystal.gbc",
        }
    )
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
    )
    state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._load_shortcut_state", lambda path: state)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_shortcut_prelaunch_save_sync",
        lambda **kwargs: (launch_module._ShortcutSaveContext({}, {}, {}), False),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_shortcut_postexit_save_sync",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("upload failed")),
    )
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target_with_optional_exit_hook", lambda payload: 23)

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 23
    assert "post-exit save sync failed" in capsys.readouterr().out


def test_shortcut_prelaunch_save_sync_skips_when_server_unreachable(monkeypatch) -> None:
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
    )
    payload = launch_module.ShortcutLaunchPayload(
        version=1,
        emulator="retroarch",
        target_exe="retroarch",
        target_args=("-f", "game.gbc"),
        title_id="title_gbc_pokemon",
        system="GBC",
        rom_rel_path="roms/GBC/Pokemon Crystal.gbc",
    )
    state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._shortcut_server_reachable", lambda _config: False)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._load_shortcut_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("index fetch should be skipped")),
    )

    context, changed = launch_module._run_shortcut_prelaunch_save_sync(
        payload=payload,
        config=config,
        state=state,
        resolve_executable=lambda _name: "retroarch",
        verbose=False,
        audit=False,
    )

    assert changed is False
    assert context.save_snapshots == {}
    assert context.exact_binding_snapshots == {}
    assert context.tree_snapshots == {}


def test_shortcut_postexit_save_sync_skips_when_server_unreachable(monkeypatch) -> None:
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
    )
    payload = launch_module.ShortcutLaunchPayload(
        version=1,
        emulator="retroarch",
        target_exe="retroarch",
        target_args=("-f", "game.gbc"),
        title_id="title_gbc_pokemon",
        system="GBC",
        rom_rel_path="roms/GBC/Pokemon Crystal.gbc",
    )
    context = launch_module._ShortcutSaveContext(
        save_snapshots={
            "save_1": launch_module._ShortcutSaveSnapshot(
                destination=Path("D:/GameHub/save.sav"),
                local_sha256="a" * 64,
                remote_sha256="b" * 64,
                allow_postexit_upload=True,
            )
        },
        exact_binding_snapshots={},
        tree_snapshots={},
    )
    state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._shortcut_server_reachable", lambda _config: False)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._load_shortcut_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("index fetch should be skipped")),
    )

    changed = launch_module._run_shortcut_postexit_save_sync(
        payload=payload,
        config=config,
        state=state,
        context=context,
        resolve_executable=lambda _name: "retroarch",
        verbose=False,
        audit=False,
    )

    assert changed is False


def test_shortcut_postexit_save_sync_records_missed_upload_when_server_unreachable(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-new")
        payload = launch_module.ShortcutLaunchPayload(
            version=1,
            emulator="retroarch",
            target_exe="retroarch",
            target_args=("-f", "game.gbc"),
            title_id="title_gbc_pokemon",
            system="GBC",
            rom_rel_path="roms/GBC/Pokemon Crystal.gbc",
        )
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=Path("D:/GameHub"),
            firmware_dir=Path("D:/GameHub/firmware"),
            state_path=Path("D:/GameHub/state.json"),
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=Path("D:/GameHub/cache"),
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            controllers=ControllersConfig(launch_autoconfig=False),
            save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
        )
        context = launch_module._ShortcutSaveContext(
            save_snapshots={
                "save_gbc_1": launch_module._ShortcutSaveSnapshot(
                    destination=destination,
                    local_sha256=_sha256_bytes(b"local-old"),
                    remote_sha256=_sha256_bytes(b"remote-old"),
                    allow_postexit_upload=True,
                )
            },
            exact_binding_snapshots={},
            tree_snapshots={},
        )
        state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})

        monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._shortcut_server_reachable", lambda _config: False)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch._load_shortcut_index",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("index fetch should be skipped")),
        )

        changed = launch_module._run_shortcut_postexit_save_sync(
            payload=payload,
            config=config,
            state=state,
            context=context,
            resolve_executable=lambda _name: "retroarch",
            verbose=False,
            audit=False,
        )

        assert changed is True
        assert state.unresolved_save_conflicts["save_gbc_1"] == MISSED_POSTEXIT_UPLOAD_REASON
        assert state.save_lineage["save_gbc_1"]["local_sha256"] == _sha256_bytes(b"local-new")
        assert "local_updated_at" in state.save_lineage["save_gbc_1"]


def test_shortcut_postexit_upload_failure_records_missed_upload_when_server_drops(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-new")
        remote_save = SaveSpec(
            save_id="save_gbc_2",
            title_id="title_gbc_pokemon",
            system="GBC",
            kind="battery",
            rel_path="saves/GBC/Pokemon Crystal/battery/Pokemon.srm",
            sha256=_sha256_bytes(b"remote-old"),
            size_bytes=len(b"remote-old"),
            updated_at=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
            portable=True,
        )
        payload = launch_module.ShortcutLaunchPayload(
            version=1,
            emulator="retroarch",
            target_exe="retroarch",
            target_args=("-f", "game.gbc"),
            title_id="title_gbc_pokemon",
            system="GBC",
            rom_rel_path="roms/GBC/Pokemon Crystal.gbc",
        )
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=Path("D:/GameHub"),
            firmware_dir=Path("D:/GameHub/firmware"),
            state_path=Path("D:/GameHub/state.json"),
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=Path("D:/GameHub/cache"),
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            controllers=ControllersConfig(launch_autoconfig=False),
            save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
        )
        context = launch_module._ShortcutSaveContext(
            save_snapshots={
                "save_gbc_2": launch_module._ShortcutSaveSnapshot(
                    destination=destination,
                    local_sha256=_sha256_bytes(b"local-old"),
                    remote_sha256=remote_save.sha256,
                    allow_postexit_upload=True,
                )
            },
            exact_binding_snapshots={},
            tree_snapshots={},
        )
        state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})
        reachability_checks = {"count": 0}

        def _reachable(_config: GamehubConfig) -> bool:
            reachability_checks["count"] += 1
            return reachability_checks["count"] == 1

        monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._shortcut_server_reachable", _reachable)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch._upload_save_from_path",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("network error")),
        )

        changed = launch_module._run_shortcut_postexit_save_sync(
            payload=payload,
            config=config,
            state=state,
            context=context,
            resolve_executable=lambda _name: "retroarch",
            verbose=False,
            audit=False,
        )

        assert changed is True
        assert state.unresolved_save_conflicts["save_gbc_2"] == MISSED_POSTEXIT_UPLOAD_REASON
        assert state.save_lineage["save_gbc_2"]["local_sha256"] == _sha256_bytes(b"local-new")
        assert "local_updated_at" in state.save_lineage["save_gbc_2"]


def test_shortcut_postexit_metadata_fetch_failure_records_missed_upload(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-new")
        payload = launch_module.ShortcutLaunchPayload(
            version=1,
            emulator="retroarch",
            target_exe="retroarch",
            target_args=("-f", "game.gbc"),
            title_id="title_gbc_pokemon",
            system="GBC",
            rom_rel_path="roms/GBC/Pokemon Crystal.gbc",
        )
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=Path("D:/GameHub"),
            firmware_dir=Path("D:/GameHub/firmware"),
            state_path=Path("D:/GameHub/state.json"),
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=Path("D:/GameHub/cache"),
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            controllers=ControllersConfig(launch_autoconfig=False),
            save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
        )
        context = launch_module._ShortcutSaveContext(
            save_snapshots={
                "save_gbc_3": launch_module._ShortcutSaveSnapshot(
                    destination=destination,
                    local_sha256=_sha256_bytes(b"local-old"),
                    remote_sha256=_sha256_bytes(b"remote-old"),
                    allow_postexit_upload=True,
                )
            },
            exact_binding_snapshots={},
            tree_snapshots={},
        )
        state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})

        monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch._load_shortcut_index_or_warn",
            lambda *_args, **_kwargs: None,
        )

        changed = launch_module._run_shortcut_postexit_save_sync(
            payload=payload,
            config=config,
            state=state,
            context=context,
            resolve_executable=lambda _name: "retroarch",
            verbose=False,
            audit=False,
        )

        assert changed is True
        assert state.unresolved_save_conflicts["save_gbc_3"] == MISSED_POSTEXIT_UPLOAD_REASON
        assert state.save_lineage["save_gbc_3"]["local_sha256"] == _sha256_bytes(b"local-new")


def test_shortcut_postexit_upload_conflict_with_identical_remote_content_is_converged(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-new")
        local_sha = _sha256_bytes(b"local-new")
        remote_save = SaveSpec(
            save_id="save_gbc_4",
            title_id="title_gbc_pokemon",
            system="GBC",
            kind="battery",
            rel_path="saves/GBC/Pokemon Crystal/battery/Pokemon.srm",
            sha256=_sha256_bytes(b"remote-old"),
            size_bytes=len(b"remote-old"),
            updated_at=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
            portable=True,
        )
        payload = launch_module.ShortcutLaunchPayload(
            version=1,
            emulator="retroarch",
            target_exe="retroarch",
            target_args=("-f", "game.gbc"),
            title_id="title_gbc_pokemon",
            system="GBC",
            rom_rel_path="roms/GBC/Pokemon Crystal.gbc",
        )
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=Path("D:/GameHub"),
            firmware_dir=Path("D:/GameHub/firmware"),
            state_path=Path("D:/GameHub/state.json"),
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=Path("D:/GameHub/cache"),
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            controllers=ControllersConfig(launch_autoconfig=False),
            save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
        )
        context = launch_module._ShortcutSaveContext(
            save_snapshots={
                "save_gbc_4": launch_module._ShortcutSaveSnapshot(
                    destination=destination,
                    local_sha256=_sha256_bytes(b"local-old"),
                    remote_sha256=remote_save.sha256,
                    allow_postexit_upload=True,
                )
            },
            exact_binding_snapshots={},
            tree_snapshots={},
        )
        state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})

        monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch._upload_save_from_path",
            lambda **kwargs: (_ for _ in ()).throw(
                SaveUploadConflictError(
                    {
                        "reason": "remote-changed",
                        "current": {
                            "save_id": remote_save.save_id,
                            "title_id": remote_save.title_id,
                            "system": remote_save.system,
                            "kind": remote_save.kind,
                            "rel_path": remote_save.rel_path,
                            "sha256": local_sha,
                            "size_bytes": len(b"local-new"),
                            "updated_at": "2026-01-02T12:30:00+00:00",
                            "portable": True,
                        },
                    }
                )
            ),
        )

        changed = launch_module._run_shortcut_postexit_save_sync(
            payload=payload,
            config=config,
            state=state,
            context=context,
            resolve_executable=lambda _name: "retroarch",
            verbose=False,
            audit=False,
        )

        assert changed is True
        assert state.save_checksums["save_gbc_4"] == local_sha
        assert state.save_lineage["save_gbc_4"]["remote_sha256"] == local_sha
        assert "save_gbc_4" not in state.unresolved_save_conflicts


def test_shortcut_prelaunch_uses_missed_upload_timestamp_to_keep_newer_local(
    monkeypatch, workspace_tempdir, capsys
) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-new")
        remote_updated_at = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
        newer_seconds = remote_updated_at.timestamp() + 120.0
        os.utime(destination, (newer_seconds, newer_seconds))
        remote_save = SaveSpec(
            save_id="save_gbc_3",
            title_id="title_gbc_pokemon",
            system="GBC",
            kind="battery",
            rel_path="saves/GBC/Pokemon Crystal/battery/Pokemon.srm",
            sha256=_sha256_bytes(b"remote-old"),
            size_bytes=len(b"remote-old"),
            updated_at=remote_updated_at,
            portable=True,
        )
        payload = launch_module.ShortcutLaunchPayload(
            version=1,
            emulator="retroarch",
            target_exe="retroarch",
            target_args=("-f", "game.gbc"),
            title_id="title_gbc_pokemon",
            system="GBC",
            rom_rel_path="roms/GBC/Pokemon Crystal.gbc",
        )
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=Path("D:/GameHub"),
            firmware_dir=Path("D:/GameHub/firmware"),
            state_path=Path("D:/GameHub/state.json"),
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=Path("D:/GameHub/cache"),
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            controllers=ControllersConfig(launch_autoconfig=False),
            save_sync=SaveSyncConfig(enabled=True, mode="bidirectional", conflict_policy="prefer_server"),
        )
        state = SimpleNamespace(
            save_binding_roots={},
            save_lineage={},
            unresolved_save_conflicts={"save_gbc_3": MISSED_POSTEXIT_UPLOAD_REASON},
            save_checksums={},
        )
        download_calls: list[str] = []

        monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch.resolve_local_save_destination",
            lambda save, **kwargs: destination,
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch._download_save_to_destination",
            lambda **kwargs: download_calls.append(kwargs["save_id"]),
        )

        context, changed = launch_module._run_shortcut_prelaunch_save_sync(
            payload=payload,
            config=config,
            state=state,
            resolve_executable=lambda _name: "retroarch",
            verbose=True,
            audit=False,
        )

        assert changed is False
        assert download_calls == []
        assert context.save_snapshots["save_gbc_3"].allow_postexit_upload is True
        output = capsys.readouterr().out
        assert "shortcut-save\tprelaunch\tkeep-local\tsave_gbc_3\tmissed-upload-local-newer" in output


def test_shortcut_prelaunch_download_mode_skips_save_bindings_fetch(monkeypatch) -> None:
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="download"),
    )
    payload = launch_module.ShortcutLaunchPayload(
        version=1,
        emulator="retroarch",
        target_exe="retroarch",
        target_args=("-f", "game.gbc"),
        title_id="title_gbc_pokemon",
        system="GBC",
        rom_rel_path="roms/GBC/Pokemon Crystal.gbc",
    )
    state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._shortcut_server_reachable", lambda _config: True)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._load_shortcut_index",
        lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=()),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._load_shortcut_save_bindings",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("save bindings fetch should be skipped")),
    )

    context, changed = launch_module._run_shortcut_prelaunch_save_sync(
        payload=payload,
        config=config,
        state=state,
        resolve_executable=lambda _name: "retroarch",
        verbose=False,
        audit=False,
    )

    assert changed is False
    assert context.save_snapshots == {}
    assert context.exact_binding_snapshots == {}
    assert context.tree_snapshots == {}


def test_shortcut_metadata_fetch_uses_single_attempt_fast_profile(monkeypatch) -> None:
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
        index_timeout_seconds=45.0,
        index_fetch_attempts=6,
        index_retry_backoff_seconds=2.5,
    )
    calls: dict[str, dict[str, object]] = {}

    class _FakeIndexModule:
        @staticmethod
        def fetch_index_with_retries(**kwargs):
            calls["index"] = kwargs
            return {"index_version": 1, "systems": [], "titles": [], "saves": []}

        @staticmethod
        def fetch_save_bindings_with_retries(**kwargs):
            calls["bindings"] = kwargs
            return {"bindings": []}

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.import_module", lambda _name: _FakeIndexModule)

    index = launch_module._load_shortcut_index(config, verbose=False)
    bindings = launch_module._load_shortcut_save_bindings(config, verbose=False)

    assert index is not None
    assert bindings is not None
    assert calls["index"]["timeout_seconds"] == 5.0
    assert calls["index"]["attempts"] == 1
    assert calls["index"]["retry_backoff_seconds"] == 0.0
    assert calls["bindings"]["timeout_seconds"] == 5.0
    assert calls["bindings"]["attempts"] == 1
    assert calls["bindings"]["retry_backoff_seconds"] == 0.0


def test_run_shortcut_launch_persists_prelaunch_state_when_launch_fails(monkeypatch) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "retroarch",
            "target_exe": "retroarch",
            "target_args": ["-f", "game.gbc"],
            "title_id": "title_gbc_pokemon",
            "system": "GBC",
            "rom_rel_path": "roms/GBC/Pokemon Crystal.gbc",
        }
    )
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
    )
    state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})
    saved: list[tuple[Path, object]] = []

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._load_shortcut_state", lambda path: state)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_shortcut_prelaunch_save_sync",
        lambda **kwargs: (
            launch_module._ShortcutSaveContext(save_snapshots={}, exact_binding_snapshots={}, tree_snapshots={}),
            True,
        ),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_shortcut_postexit_save_sync",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("post-exit sync should not run when launch fails")),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._save_shortcut_state",
        lambda path, current_state: saved.append((path, current_state)),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_target_with_optional_exit_hook",
        lambda payload: (_ for _ in ()).throw(RuntimeError("launch failed")),
    )

    with pytest.raises(RuntimeError, match="launch failed"):
        run_shortcut_launch(payload_token=token)

    assert saved == [(config.state_path, state)]


def test_run_shortcut_launch_respects_save_sync_system_filter_for_memory_card_setup(monkeypatch) -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "pcsx2",
            "target_exe": "pcsx2-qt.exe",
            "target_args": ["--nogui", "game.iso"],
            "title_id": "title_ps2_gt4",
            "system": "PS2",
            "rom_rel_path": "roms/PS2/Gran Turismo 4.iso",
        }
    )
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional", systems=("GC",)),
    )
    ensure_calls: list[str] = []

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._ensure_managed_memory_card_paths",
        lambda payload, cfg: ensure_calls.append(payload.system or ""),
    )
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._run_target_with_optional_exit_hook", lambda payload: 0)

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 0
    assert ensure_calls == []
