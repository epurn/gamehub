from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4

from gamehub_cli.config import ControllersConfig, GamehubConfig
from gamehub_cli.controller_profiles import (
    PROFILE_KBM,
    PROFILE_XBOX_1P,
    PROFILE_XBOX_2P,
    load_profile_file,
    profile_name_for_controller_count,
    resolve_profiles_root,
    seed_default_profiles,
)


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
        controllers=ControllersConfig(profiles_dir=root / "profiles"),
    )


def test_profile_name_for_controller_count() -> None:
    assert profile_name_for_controller_count(0) == PROFILE_KBM
    assert profile_name_for_controller_count(1) == PROFILE_XBOX_1P
    assert profile_name_for_controller_count(2) == PROFILE_XBOX_2P
    assert profile_name_for_controller_count(99) == PROFILE_XBOX_2P


def test_seed_default_profiles_creates_profile_tree() -> None:
    with _workspace_tempdir("gamehub-controller-profiles-") as temp_root:
        config = _config(temp_root)

        created = seed_default_profiles(config)
        root = resolve_profiles_root(config)

        assert created
        assert (root / "pcsx2" / "kbm" / "PCSX2.ini").exists()
        assert (root / "pcsx2" / "xbox_1p" / "PCSX2.ini").exists()
        assert (root / "pcsx2" / "xbox_2p" / "PCSX2.ini").exists()
        assert (root / "dolphin" / "kbm" / "GCPadNew.ini").exists()
        assert (root / "dolphin" / "xbox_1p" / "WiimoteNew.ini").exists()
        assert (root / "azahar" / "xbox_2p" / "qt-config.ini").exists()


def test_load_profile_file_prefers_user_override() -> None:
    with _workspace_tempdir("gamehub-controller-profiles-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        root = resolve_profiles_root(config)
        profile_file = root / "pcsx2" / "kbm" / "PCSX2.ini"
        profile_file.write_text("[Hotkeys]\nOpenPauseMenu = Keyboard/F1\n", encoding="utf-8")

        lines = load_profile_file(
            config,
            emulator_name="pcsx2",
            profile_name="kbm",
            filename="PCSX2.ini",
        )

        assert "OpenPauseMenu = Keyboard/F1" in "\n".join(lines)


@contextmanager
def _workspace_tempdir(prefix: str):
    temp_root = Path(".pytest_tmp_local") / f"{prefix}{uuid4().hex}"
    temp_root.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_root
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

