from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import gamehub_cli.shortcuts.shortcut_launch as launch_module
from gamehub_cli.common.config import ControllersConfig, GamehubConfig, SaveSyncConfig
from gamehub_cli.common.shortcut_payload_registry import save_shortcut_payload_registry_atomic
from gamehub_cli.shortcuts.shortcut_launch import encode_shortcut_payload, run_shortcut_launch


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
    assert "pre-launch save sync failed; continuing launch" in capsys.readouterr().err


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
    assert "post-exit save sync failed" in capsys.readouterr().err


def test_run_shortcut_launch_spawn_failure_warns_and_persists_prelaunch_state(monkeypatch, capsys) -> None:
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
        lambda payload: (_ for _ in ()).throw(launch_module.ShortcutLaunchError("launch failed (command=open)")),
    )

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 1
    assert "launch failed (command=open)" in capsys.readouterr().err
    assert saved == [(config.state_path, state)]


def test_run_shortcut_launch_loads_payload_from_registry_ref(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-shortcut-launch-registry-") as temp_root:
        token = encode_shortcut_payload(
            {
                "v": 1,
                "emulator": "dolphin",
                "target_exe": "/Users/tester/Applications/Dolphin.app/Contents/MacOS/DolphinQt",
                "target_args": ["-b", "-e", "/Users/tester/Games/Super Mario Galaxy.rvz"],
                "title_id": "title_wii_mario",
                "system": "Wii",
                "rom_rel_path": "roms/Wii/Super Mario Galaxy.rvz",
                "config_path": str(temp_root / "config.toml"),
                "macos_open_app": "/Users/tester/Applications/Dolphin.app",
                "macos_open_args": ["-b", "-e", "/Users/tester/Games/Super Mario Galaxy.rvz"],
            }
        )
        registry_path = temp_root / "shortcut_payloads.json"
        save_shortcut_payload_registry_atomic(registry_path, {"title_wii_mario": token})

        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=Path("/Users/tester/GameHub"),
            firmware_dir=Path("/Users/tester/GameHub/firmware"),
            state_path=Path("/Users/tester/GameHub/state.json"),
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=Path("/Users/tester/GameHub/cache"),
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        launched: list[launch_module.ShortcutLaunchPayload] = []

        monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.shortcut_launch._run_target_with_optional_exit_hook",
            lambda payload: launched.append(payload) or 0,
        )

        exit_code = run_shortcut_launch(
            payload_ref="title_wii_mario",
            payload_registry_path=registry_path,
        )

        assert exit_code == 0
        assert launched[0].emulator == "dolphin"
        assert launched[0].macos_open_app == "/Users/tester/Applications/Dolphin.app"


def test_run_shortcut_launch_unexpected_launch_error_returns_nonzero_and_warns(monkeypatch, capsys) -> None:
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

    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.shortcuts.shortcut_launch._load_shortcut_state", lambda path: state)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_shortcut_prelaunch_save_sync",
        lambda **kwargs: (
            launch_module._ShortcutSaveContext(save_snapshots={}, exact_binding_snapshots={}, tree_snapshots={}),
            False,
        ),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.shortcut_launch._run_target_with_optional_exit_hook",
        lambda payload: (_ for _ in ()).throw(RuntimeError("unexpected launch error")),
    )

    exit_code = run_shortcut_launch(payload_token=token)

    assert exit_code == 1
    assert "unexpected shortcut launch error (RuntimeError: unexpected launch error)" in capsys.readouterr().err


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
