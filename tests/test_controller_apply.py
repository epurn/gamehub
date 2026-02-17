from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import shutil
from uuid import uuid4

from gamehub_cli.config import ControllersConfig, GamehubConfig
from gamehub_cli.controller_apply import apply_controller_profile, apply_named_controller_profile
from gamehub_cli.controller_profiles import seed_default_profiles


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


def test_apply_controller_profile_pcsx2_kbm_preserves_unmanaged_sections() -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        base = _config(temp_root)
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=ini_path))
        seed_default_profiles(config)
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text("[Audio]\nLatency = 42\n", encoding="utf-8")

        profile = apply_controller_profile(config, emulator_name="pcsx2", controller_count=0)
        text = ini_path.read_text(encoding="utf-8")

        assert profile == "kbm"
        assert "[Audio]" in text
        assert "Latency = 42" in text
        assert "OpenPauseMenu = Keyboard/Escape" in text
        assert "Cross = Keyboard/K" in text


def test_apply_controller_profile_pcsx2_xbox_modes() -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        base = _config(temp_root)
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=ini_path))
        seed_default_profiles(config)

        profile_1 = apply_controller_profile(config, emulator_name="pcsx2", controller_count=1)
        text_1 = ini_path.read_text(encoding="utf-8")
        assert profile_1 == "xbox_1p"
        assert "Cross = SDL-0/A" in text_1
        assert "Cross = Keyboard/Num0" in text_1
        assert "OpenPauseMenu = SDL-0/Back & SDL-0/Start" in text_1

        profile_2 = apply_controller_profile(config, emulator_name="pcsx2", controller_count=2)
        text_2 = ini_path.read_text(encoding="utf-8")
        assert profile_2 == "xbox_2p"
        assert "Cross = SDL-0/A" in text_2
        assert "Cross = SDL-1/A" in text_2


def test_apply_controller_profile_accepts_emulator_family_alias() -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        base = _config(temp_root)
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=ini_path))
        seed_default_profiles(config)

        profile = apply_controller_profile(config, emulator_name="PCSX2-nightly", controller_count=1)
        text = ini_path.read_text(encoding="utf-8")

        assert profile == "xbox_1p"
        assert "Cross = SDL-0/A" in text


def test_apply_controller_profile_dolphin_xbox_writes_managed_sections(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "GCPadNew.ini").write_text("[User]\nFoo = Bar\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root)
        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root])

        profile = apply_controller_profile(config, emulator_name="dolphin", controller_count=2)

        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")
        hotkeys_text = (config_dir / "Hotkeys.ini").read_text(encoding="utf-8")
        assert profile == "xbox_2p"
        assert "[User]" in gcpad_text
        assert "Foo = Bar" in gcpad_text
        assert "Device = XInput/0/Gamepad" in gcpad_text
        assert "Device = XInput/1/Gamepad" in gcpad_text
        assert "General/Stop = @(SELECT+START)" in hotkeys_text


def test_apply_controller_profile_azahar_kbm(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text("custom_key=keep\n", encoding="utf-8")
        monkeypatch.setattr("gamehub_cli.controller_apply._default_azahar_qt_config_path", lambda: qt_config)

        profile = apply_named_controller_profile(config, emulator_name="azahar", profile_name="kbm")
        text = qt_config.read_text(encoding="utf-8")

        assert profile == "kbm"
        assert "custom_key=keep" in text
        assert r'profiles\1\button_a="code:65,engine:keyboard"' in text


@contextmanager
def _workspace_tempdir(prefix: str):
    temp_root = Path(".pytest_tmp_local") / f"{prefix}{uuid4().hex}"
    temp_root.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_root
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
