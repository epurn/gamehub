from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import gamehub_cli.emulators.save_resolution as save_resolution_module
import gamehub_cli.shortcuts.save_session as launch_module
from gamehub_cli.common.config import ControllersConfig, GamehubConfig, SaveSyncConfig
from gamehub_cli.common.shortcut_payload import ShortcutLaunchPayload
from gamehub_cli.sync.state import MISSED_POSTEXIT_UPLOAD_REASON
from gamehub_cli.sync.transfer import SaveUploadConflictError
from gamehub_common.ids import make_save_id
from gamehub_common.models import LibraryIndex, SaveBindingSpec, SaveSpec
from tests.shortcut_test_helpers import default_shortcut_config as _config
from tests.shortcut_test_helpers import sha256_bytes as _sha256_bytes

launch_module.ShortcutLaunchPayload = ShortcutLaunchPayload
launch_module._ShortcutSaveContext = launch_module.ShortcutSaveContext
launch_module._ShortcutSaveSnapshot = launch_module.ShortcutSaveSnapshot
launch_module._ShortcutExactBindingSnapshot = launch_module.ShortcutExactBindingSnapshot
launch_module._ensure_managed_memory_card_paths = launch_module.ensure_managed_memory_card_paths
launch_module._run_shortcut_prelaunch_save_sync = launch_module.run_shortcut_prelaunch_save_sync
launch_module._run_shortcut_postexit_save_sync = launch_module.run_shortcut_postexit_save_sync


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
            "gamehub_cli.shortcuts.save_session.retroarch_cfg_candidates_for_config",
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


def test_ensure_managed_memory_card_paths_macos_uses_application_support_cfg(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-psx-managed-card-") as temp_root:
        home = temp_root / "home"
        retroarch_root = home / "Library" / "Application Support" / "RetroArch"
        retroarch_root.mkdir(parents=True, exist_ok=True)
        cfg_path = retroarch_root / "retroarch.cfg"
        cfg_path.write_text("", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.firmware.targets.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.firmware.targets.sys.platform", "darwin")
        monkeypatch.setattr("gamehub_cli.firmware.targets.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.firmware.targets.resolve_emulator_executable", lambda _name: "")

        payload = launch_module.ShortcutLaunchPayload(
            version=1,
            emulator="retroarch",
            target_exe="/Applications/RetroArch.app/Contents/MacOS/RetroArch",
            target_args=(),
            title_id="title_psx_macos",
            system="PSX",
            rom_rel_path="roms/PSX/Gran Turismo 2.chd",
        )

        changed = launch_module._ensure_managed_memory_card_paths(payload, _config())

        assert changed is True
        text = (retroarch_root / "retroarch-core-options.cfg").read_text(encoding="utf-8")
        assert 'swanstation_MemoryCard1Path = "GH_title_psx_macos_1.mcd"' in text
        assert 'swanstation_MemoryCard2Path = "GH_title_psx_macos_2.mcd"' in text


def test_build_shortcut_save_resolver_uses_payload_macos_config_overrides(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-shortcut-macos-save-") as temp_root:
        home = temp_root / "home"
        dolphin_root = temp_root / "custom-dolphin"
        gc_root = dolphin_root / "GC"
        gc_root.mkdir(parents=True, exist_ok=True)
        config_path = temp_root / "config.toml"
        config_path.write_text(
            f"[macos]\ndolphin_user_path = {json.dumps(str(dolphin_root))}\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "darwin")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: home)
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))

        payload = launch_module.ShortcutLaunchPayload(
            version=1,
            emulator="dolphin",
            target_exe="/Applications/Dolphin.app/Contents/MacOS/Dolphin",
            target_args=(),
            config_path=str(config_path),
            title_id="title_gc_macos",
            system="GC",
            rom_rel_path="roms/GC/F-Zero GX.iso",
        )

        resolver = launch_module.build_shortcut_save_resolver(payload)
        resolved = save_resolution_module.resolve_system_save_root("GC", resolve_executable=resolver)

        assert resolved == gc_root


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
            "gamehub_cli.shortcuts.save_session.resolve_binding_local_root",
            lambda _binding, **_kwargs: temp_root,
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.save_resolution.resolve_binding_local_root",
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
            "gamehub_cli.shortcuts.save_session.resolve_binding_local_root",
            lambda _binding, **_kwargs: temp_root,
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session.resolve_exact_local_save_destination",
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

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._upload_new_save_from_path", _fake_upload_new)

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


def test_shortcut_postexit_learned_tree_uploads_existing_local_save_without_session_change(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        save_path = temp_root / "USA" / "Card A" / "01-GZLE-gczelda.gci"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(b"gci")
        local_sha = _sha256_bytes(b"gci")
        binding = SaveBindingSpec(
            binding_id="savebind_gc",
            title_id="title_gc_windwaker",
            system="GC",
            kind="per_game",
            server_rel_dir="saves/GC/WindWaker/per_game",
            local_root="dolphin_gc",
            strategy="learned_tree",
            candidate_filenames=(),
            learn_rule="dolphin_gc_gci_tree",
            portable=False,
        )
        payload = launch_module.ShortcutLaunchPayload(
            version=1,
            emulator="dolphin",
            target_exe="dolphin",
            target_args=("--exec", "windwaker.iso"),
            title_id="title_gc_windwaker",
            system="GC",
            rom_rel_path="roms/GC/The Legend of Zelda - The Wind Waker.iso",
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
        state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})
        created_ids: list[str] = []

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=()),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_save_bindings_or_warn",
            lambda _config, verbose=False: SimpleNamespace(bindings=(binding,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session.resolve_binding_local_root",
            lambda _binding, **_kwargs: temp_root,
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.save_resolution.resolve_binding_local_root",
            lambda _binding, **_kwargs: temp_root,
        )

        def _fake_upload_new(**kwargs):
            created_ids.append(kwargs["save_id"])
            return SaveSpec(
                save_id=kwargs["save_id"],
                title_id=binding.title_id,
                system=binding.system,
                kind=binding.kind,
                rel_path=f"{binding.server_rel_dir}/{kwargs['canonical_suffix']}",
                sha256=local_sha,
                size_bytes=len(b"gci"),
                updated_at=datetime(2026, 3, 7, 12, 0, tzinfo=UTC),
                portable=False,
            )

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._upload_new_save_from_path", _fake_upload_new)

        context, changed = launch_module._run_shortcut_prelaunch_save_sync(
            payload=payload,
            config=config,
            state=state,
            resolve_executable=lambda _name: "dolphin",
            verbose=False,
            audit=False,
        )

        assert changed is False
        assert binding.binding_id in context.tree_snapshots
        assert context.tree_snapshots[binding.binding_id].before == {"USA/Card A/01-GZLE-gczelda.gci": local_sha}

        changed = launch_module._run_shortcut_postexit_save_sync(
            payload=payload,
            config=config,
            state=state,
            context=context,
            resolve_executable=lambda _name: "dolphin",
            verbose=False,
            audit=False,
        )

        save_id = make_save_id("saves/GC/WindWaker/per_game/USA/Card A/01-GZLE-gczelda.gci")
        assert changed is True
        assert created_ids == [save_id]
        assert state.save_binding_roots[binding.binding_id] == {
            "canonical_root": "USA/Card A",
            "materialized_root": "USA/Card A",
        }
        assert state.save_checksums[save_id] == local_sha
        assert "savebind_gc" not in state.unresolved_save_conflicts


def test_shortcut_postexit_learned_tree_ignores_local_gamehub_backup_files(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        local_root = temp_root / "Nintendo 3DS" / ("0" * 32) / ("1" * 32) / "title" / "00040000" / "0011c500" / "data"
    metadata_path = local_root / "00000001.metadata"
    main_path = local_root / "00000001" / "main"
    backup_path = local_root / "00000001" / "main.20260307022223.bak"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    main_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_bytes(b"metadata")
    main_path.write_bytes(b"main")
    backup_path.write_bytes(b"backup")
    expected_save_ids = {
        make_save_id("saves/N3DS/Pokemon Alpha Sapphire/per_game/title/00040000/0011c500/data/00000001/main"),
        make_save_id("saves/N3DS/Pokemon Alpha Sapphire/per_game/title/00040000/0011c500/data/00000001.metadata"),
    }
    binding = SaveBindingSpec(
        binding_id="savebind_n3ds",
        title_id="title_n3ds_alpha_sapphire",
        system="N3DS",
        kind="per_game",
        server_rel_dir="saves/N3DS/Pokemon Alpha Sapphire/per_game",
        local_root="azahar_sdmc",
        strategy="learned_tree",
        candidate_filenames=(),
        learn_rule="azahar_title_data_tree",
        portable=False,
    )
    payload = launch_module.ShortcutLaunchPayload(
        version=1,
        emulator="azahar",
        target_exe="azahar",
        target_args=("--fullscreen", "Pokemon Alpha Sapphire.cci"),
        title_id="title_n3ds_alpha_sapphire",
        system="N3DS",
        rom_rel_path="roms/N3DS/Pokemon Alpha Sapphire.cci",
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
    state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})
    created_ids: list[str] = []

    monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.save_session._load_shortcut_index",
        lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=()),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.save_session._load_shortcut_save_bindings_or_warn",
        lambda _config, verbose=False: SimpleNamespace(bindings=(binding,)),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.save_session.resolve_binding_local_root",
        lambda _binding, **_kwargs: temp_root,
    )
    monkeypatch.setattr(
        "gamehub_cli.emulators.save_resolution.resolve_binding_local_root",
        lambda _binding, **_kwargs: temp_root,
    )

    def _fake_upload_new(**kwargs):
        created_ids.append(kwargs["save_id"])
        source = kwargs["source"]
        return SaveSpec(
            save_id=kwargs["save_id"],
            title_id=binding.title_id,
            system=binding.system,
            kind=binding.kind,
            rel_path=f"{binding.server_rel_dir}/{kwargs['canonical_suffix']}",
            sha256=_sha256_bytes(source.read_bytes()),
            size_bytes=source.stat().st_size,
            updated_at=datetime(2026, 3, 8, 18, 0, tzinfo=UTC),
            portable=False,
        )

    monkeypatch.setattr("gamehub_cli.shortcuts.save_session._upload_new_save_from_path", _fake_upload_new)

    context, changed = launch_module._run_shortcut_prelaunch_save_sync(
        payload=payload,
        config=config,
        state=state,
        resolve_executable=lambda _name: "azahar",
        verbose=False,
        audit=False,
    )

    assert changed is False
    assert binding.binding_id in context.tree_snapshots
    assert set(context.tree_snapshots[binding.binding_id].before) == {
        "Nintendo 3DS/00000000000000000000000000000000/11111111111111111111111111111111/title/00040000/0011c500/data/00000001/main",
        "Nintendo 3DS/00000000000000000000000000000000/11111111111111111111111111111111/title/00040000/0011c500/data/00000001.metadata",
    }

    changed = launch_module._run_shortcut_postexit_save_sync(
        payload=payload,
        config=config,
        state=state,
        context=context,
        resolve_executable=lambda _name: "azahar",
        verbose=False,
        audit=False,
    )

    assert changed is True
    assert set(created_ids) == expected_save_ids
    assert (
        make_save_id(
            "saves/N3DS/Pokemon Alpha Sapphire/per_game/title/00040000/0011c500/data/00000001/main.20260307022223.bak"
        )
        not in created_ids
    )


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

    monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: False)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.save_session._load_shortcut_index",
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

    assert changed is True
    assert context.save_snapshots == {}
    assert context.exact_binding_snapshots == {}
    assert context.tree_snapshots == {}
    assert "title_gbc_pokemon" in state.offline_shortcut_titles


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

    monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: False)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.save_session._load_shortcut_index",
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

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: False)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
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


def test_shortcut_postexit_pending_upload_records_missed_upload_when_server_unreachable(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-pending")
        local_sha = _sha256_bytes(b"local-pending")
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
                "save_gbc_pending_1": launch_module._ShortcutSaveSnapshot(
                    destination=destination,
                    local_sha256=local_sha,
                    remote_sha256=_sha256_bytes(b"remote-old"),
                    allow_postexit_upload=True,
                    pending_postexit_upload=True,
                )
            },
            exact_binding_snapshots={},
            tree_snapshots={},
        )
        state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: False)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
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
        assert state.unresolved_save_conflicts["save_gbc_pending_1"] == MISSED_POSTEXIT_UPLOAD_REASON
        assert state.save_lineage["save_gbc_pending_1"]["local_sha256"] == local_sha
        assert "local_updated_at" in state.save_lineage["save_gbc_pending_1"]


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

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", _reachable)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._upload_save_from_path",
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


def test_shortcut_postexit_pending_upload_failure_records_missed_upload_when_server_drops(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-pending")
        local_sha = _sha256_bytes(b"local-pending")
        remote_save = SaveSpec(
            save_id="save_gbc_pending_2",
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
                "save_gbc_pending_2": launch_module._ShortcutSaveSnapshot(
                    destination=destination,
                    local_sha256=local_sha,
                    remote_sha256=remote_save.sha256,
                    allow_postexit_upload=True,
                    pending_postexit_upload=True,
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

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", _reachable)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._upload_save_from_path",
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
        assert state.unresolved_save_conflicts["save_gbc_pending_2"] == MISSED_POSTEXIT_UPLOAD_REASON
        assert state.save_lineage["save_gbc_pending_2"]["local_sha256"] == local_sha
        assert "local_updated_at" in state.save_lineage["save_gbc_pending_2"]


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

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index_or_warn",
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


def test_shortcut_postexit_pending_upload_metadata_fetch_failure_records_missed_upload(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-pending")
        local_sha = _sha256_bytes(b"local-pending")
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
                "save_gbc_pending_3": launch_module._ShortcutSaveSnapshot(
                    destination=destination,
                    local_sha256=local_sha,
                    remote_sha256=_sha256_bytes(b"remote-old"),
                    allow_postexit_upload=True,
                    pending_postexit_upload=True,
                )
            },
            exact_binding_snapshots={},
            tree_snapshots={},
        )
        state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index_or_warn",
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
        assert state.unresolved_save_conflicts["save_gbc_pending_3"] == MISSED_POSTEXIT_UPLOAD_REASON
        assert state.save_lineage["save_gbc_pending_3"]["local_sha256"] == local_sha


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

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._upload_save_from_path",
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


def test_shortcut_postexit_pending_upload_remote_drift_records_conflict(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-pending")
        local_sha = _sha256_bytes(b"local-pending")
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
                "save_gbc_pending_4": launch_module._ShortcutSaveSnapshot(
                    destination=destination,
                    local_sha256=local_sha,
                    remote_sha256=_sha256_bytes(b"remote-old"),
                    allow_postexit_upload=True,
                    pending_postexit_upload=True,
                )
            },
            exact_binding_snapshots={},
            tree_snapshots={},
        )
        state = SimpleNamespace(save_binding_roots={}, save_lineage={}, unresolved_save_conflicts={}, save_checksums={})
        remote_save = SaveSpec(
            save_id="save_gbc_pending_4",
            title_id="title_gbc_pokemon",
            system="GBC",
            kind="battery",
            rel_path="saves/GBC/Pokemon Crystal/battery/Pokemon.srm",
            sha256=_sha256_bytes(b"remote-new"),
            size_bytes=len(b"remote-new"),
            updated_at=datetime(2026, 1, 2, 12, 15, tzinfo=UTC),
            portable=True,
        )

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._upload_save_from_path",
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("upload should be skipped on remote drift")),
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
        assert state.unresolved_save_conflicts["save_gbc_pending_4"] == "remote-changed-during-session"
        assert state.save_checksums == {}


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

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session.resolve_local_save_destination",
            lambda save, **kwargs: destination,
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session.stream_to_destination_atomic",
            lambda **kwargs: download_calls.append(kwargs["url"].rsplit("/", 1)[-1]),
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
        assert context.save_snapshots["save_gbc_3"].pending_postexit_upload is True
        output = capsys.readouterr().out
        assert "shortcut-save\tprelaunch\tkeep-local\tsave_gbc_3\tmissed-upload-local-newer" in output


def test_shortcut_postexit_uploads_pending_prelaunch_keep_local_save_without_session_change(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-new")
        local_sha = _sha256_bytes(b"local-new")
        remote_sha = _sha256_bytes(b"remote-old")
        remote_save = SaveSpec(
            save_id="save_gbc_pending_5",
            title_id="title_gbc_pokemon",
            system="GBC",
            kind="battery",
            rel_path="saves/GBC/Pokemon Crystal/battery/Pokemon.srm",
            sha256=remote_sha,
            size_bytes=len(b"remote-old"),
            updated_at=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
            portable=True,
        )
        uploaded_save = SaveSpec(
            save_id=remote_save.save_id,
            title_id=remote_save.title_id,
            system=remote_save.system,
            kind=remote_save.kind,
            rel_path=remote_save.rel_path,
            sha256=local_sha,
            size_bytes=len(b"local-new"),
            updated_at=datetime(2026, 1, 2, 12, 30, tzinfo=UTC),
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
        state = SimpleNamespace(
            save_binding_roots={},
            save_lineage={"save_gbc_pending_5": {"local_sha256": remote_sha, "remote_sha256": remote_sha}},
            unresolved_save_conflicts={},
            save_checksums={},
        )
        upload_calls: list[str] = []

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_save_bindings_or_warn",
            lambda _config, verbose=False: SimpleNamespace(bindings=()),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session.resolve_local_save_destination",
            lambda save, **kwargs: destination,
        )

        def _upload(**kwargs):
            upload_calls.append(kwargs["save"].save_id)
            return uploaded_save

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._upload_save_from_path", _upload)

        context, changed = launch_module._run_shortcut_prelaunch_save_sync(
            payload=payload,
            config=config,
            state=state,
            resolve_executable=lambda _name: "retroarch",
            verbose=False,
            audit=False,
        )

        assert changed is False
        assert context.save_snapshots["save_gbc_pending_5"].pending_postexit_upload is True

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
        assert upload_calls == ["save_gbc_pending_5"]
        assert state.save_checksums["save_gbc_pending_5"] == local_sha
        assert state.save_lineage["save_gbc_pending_5"]["remote_sha256"] == local_sha
        assert "save_gbc_pending_5" not in state.unresolved_save_conflicts


def test_shortcut_postexit_uploads_missed_upload_recovery_without_session_change(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-recovered")
        local_sha = _sha256_bytes(b"local-recovered")
        remote_updated_at = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
        newer_seconds = remote_updated_at.timestamp() + 120.0
        os.utime(destination, (newer_seconds, newer_seconds))
        remote_save = SaveSpec(
            save_id="save_gbc_pending_6",
            title_id="title_gbc_pokemon",
            system="GBC",
            kind="battery",
            rel_path="saves/GBC/Pokemon Crystal/battery/Pokemon.srm",
            sha256=_sha256_bytes(b"remote-old"),
            size_bytes=len(b"remote-old"),
            updated_at=remote_updated_at,
            portable=True,
        )
        uploaded_save = SaveSpec(
            save_id=remote_save.save_id,
            title_id=remote_save.title_id,
            system=remote_save.system,
            kind=remote_save.kind,
            rel_path=remote_save.rel_path,
            sha256=local_sha,
            size_bytes=len(b"local-recovered"),
            updated_at=datetime(2026, 1, 2, 12, 30, tzinfo=UTC),
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
            unresolved_save_conflicts={"save_gbc_pending_6": MISSED_POSTEXIT_UPLOAD_REASON},
            save_checksums={},
        )
        upload_calls: list[str] = []

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_save_bindings_or_warn",
            lambda _config, verbose=False: SimpleNamespace(bindings=()),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session.resolve_local_save_destination",
            lambda save, **kwargs: destination,
        )

        def _upload(**kwargs):
            upload_calls.append(kwargs["save"].save_id)
            return uploaded_save

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._upload_save_from_path", _upload)

        context, changed = launch_module._run_shortcut_prelaunch_save_sync(
            payload=payload,
            config=config,
            state=state,
            resolve_executable=lambda _name: "retroarch",
            verbose=False,
            audit=False,
        )

        assert changed is False
        assert context.save_snapshots["save_gbc_pending_6"].pending_postexit_upload is True

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
        assert upload_calls == ["save_gbc_pending_6"]
        assert state.save_checksums["save_gbc_pending_6"] == local_sha
        assert state.save_lineage["save_gbc_pending_6"]["remote_sha256"] == local_sha
        assert "save_gbc_pending_6" not in state.unresolved_save_conflicts


def test_shortcut_postexit_uploads_offline_launch_recovery_without_session_change(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-launch-save-") as temp_root:
        destination = temp_root / "Pokemon.srm"
        destination.write_bytes(b"local-offline")
        local_sha = _sha256_bytes(b"local-offline")
        remote_updated_at = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
        newer_seconds = remote_updated_at.timestamp() + 120.0
        os.utime(destination, (newer_seconds, newer_seconds))
        remote_save = SaveSpec(
            save_id="save_gbc_pending_7",
            title_id="title_gbc_pokemon",
            system="GBC",
            kind="battery",
            rel_path="saves/GBC/Pokemon Crystal/battery/Pokemon.srm",
            sha256=_sha256_bytes(b"remote-old"),
            size_bytes=len(b"remote-old"),
            updated_at=remote_updated_at,
            portable=True,
        )
        uploaded_save = SaveSpec(
            save_id=remote_save.save_id,
            title_id=remote_save.title_id,
            system=remote_save.system,
            kind=remote_save.kind,
            rel_path=remote_save.rel_path,
            sha256=local_sha,
            size_bytes=len(b"local-offline"),
            updated_at=datetime(2026, 1, 2, 12, 30, tzinfo=UTC),
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
            unresolved_save_conflicts={},
            save_checksums={},
            offline_shortcut_titles={"title_gbc_pokemon": "2026-01-02T11:55:00+00:00"},
        )
        upload_calls: list[str] = []

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_save_bindings_or_warn",
            lambda _config, verbose=False: SimpleNamespace(bindings=()),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session.resolve_local_save_destination",
            lambda save, **kwargs: destination,
        )

        def _upload(**kwargs):
            upload_calls.append(kwargs["save"].save_id)
            return uploaded_save

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._upload_save_from_path", _upload)

        context, changed = launch_module._run_shortcut_prelaunch_save_sync(
            payload=payload,
            config=config,
            state=state,
            resolve_executable=lambda _name: "retroarch",
            verbose=False,
            audit=False,
        )

        assert changed is True
        assert context.save_snapshots["save_gbc_pending_7"].pending_postexit_upload is True
        assert state.unresolved_save_conflicts["save_gbc_pending_7"] == MISSED_POSTEXIT_UPLOAD_REASON
        assert state.offline_shortcut_titles == {}

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
        assert upload_calls == ["save_gbc_pending_7"]
        assert state.save_checksums["save_gbc_pending_7"] == local_sha
        assert state.save_lineage["save_gbc_pending_7"]["remote_sha256"] == local_sha
        assert state.offline_shortcut_titles == {}
        assert "save_gbc_pending_7" not in state.unresolved_save_conflicts


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

    monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.save_session._load_shortcut_index",
        lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=()),
    )
    monkeypatch.setattr(
        "gamehub_cli.shortcuts.save_session._load_shortcut_save_bindings",
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


def test_shortcut_prelaunch_download_mode_preserves_existing_local_drift(
    monkeypatch, capsys, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-shortcut-save-drift-") as temp_root:
        destination = temp_root / "PokemonCrystal.srm"
        destination.write_bytes(b"local-edit")
        remote_bytes = b"remote-save"
        remote_save = SaveSpec(
            save_id="save_gbc_download_drift",
            title_id="title_gbc_pokemon",
            system="GBC",
            kind="battery",
            rel_path="saves/GBC/Pokemon Crystal/battery/PokemonCrystal.srm",
            sha256=_sha256_bytes(remote_bytes),
            size_bytes=len(remote_bytes),
            updated_at=datetime(2026, 1, 3, 12, 0, tzinfo=UTC),
            portable=True,
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
        download_calls: list[str] = []

        monkeypatch.setattr("gamehub_cli.shortcuts.save_session._shortcut_server_reachable", lambda _config: True)
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session._load_shortcut_index",
            lambda _config, verbose=False: LibraryIndex(index_version=1, systems=(), titles=(), saves=(remote_save,)),
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session.resolve_local_save_destination",
            lambda save, **kwargs: destination,
        )
        monkeypatch.setattr(
            "gamehub_cli.shortcuts.save_session.stream_to_destination_atomic",
            lambda **kwargs: download_calls.append(kwargs["url"].rsplit("/", 1)[-1]),
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
        assert context.save_snapshots["save_gbc_download_drift"].destination == destination
        assert context.save_snapshots["save_gbc_download_drift"].local_sha256 == _sha256_bytes(b"local-edit")
        assert state.save_checksums == {}
        assert state.save_lineage == {}
        assert state.unresolved_save_conflicts == {}
        output = capsys.readouterr().out
        assert "shortcut-save\tprelaunch\tskip\tsave_gbc_download_drift\tdownload-mode-local-drift" in output


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

    def _fake_fetch_index(**kwargs):
        calls["index"] = kwargs
        return {"index_version": 1, "systems": [], "titles": [], "saves": []}

    def _fake_fetch_bindings(**kwargs):
        calls["bindings"] = kwargs
        return {"bindings": []}

    monkeypatch.setattr("gamehub_cli.shortcuts.save_session.fetch_index_with_retries", _fake_fetch_index)
    monkeypatch.setattr("gamehub_cli.shortcuts.save_session.fetch_save_bindings_with_retries", _fake_fetch_bindings)

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
