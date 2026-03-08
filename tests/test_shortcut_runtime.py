from __future__ import annotations

import os

import gamehub_cli.shortcuts.runtime as runtime_module
from gamehub_cli.common.shortcut_payload import ShortcutLaunchPayload
from gamehub_cli.controllers.detection import XboxController
from tests.shortcut_test_helpers import default_shortcut_config


def _payload(*, emulator: str, target_exe: str, target_args: tuple[str, ...]) -> ShortcutLaunchPayload:
    return ShortcutLaunchPayload(
        version=1,
        emulator=emulator,
        target_exe=target_exe,
        target_args=target_args,
    )


def test_prepare_shortcut_runtime_environment_sets_azahar_sdl_dir_env(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-azahar-sdl-") as temp_root:
        azahar_dir = temp_root / "Azahar"
        azahar_dir.mkdir(parents=True, exist_ok=True)
        azahar_exe = azahar_dir / "azahar.exe"
        azahar_exe.write_text("", encoding="utf-8")

        monkeypatch.delenv("GAMEHUB_AZAHAR_SDL_DIR", raising=False)
        runtime_module.prepare_shortcut_runtime_environment(
            _payload(emulator="azahar", target_exe=str(azahar_exe), target_args=("-f", "rom.3ds"))
        )

        assert os.environ["GAMEHUB_AZAHAR_SDL_DIR"] == str(azahar_dir)


def test_apply_shortcut_controller_configuration_fail_open_uses_kbm_fallback(monkeypatch) -> None:
    config = default_shortcut_config()
    fallback_calls: list[str] = []

    monkeypatch.setattr(
        runtime_module,
        "detect_xbox_controllers",
        lambda max_devices=2: [XboxController(slot=0, name="XInput/0", subtype=0)],
    )
    monkeypatch.setattr(
        runtime_module,
        "apply_controller_profile",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        runtime_module,
        "apply_named_controller_profile",
        lambda config, emulator_name, profile_name: fallback_calls.append(f"{emulator_name}:{profile_name}"),
    )

    runtime_module.apply_shortcut_controller_configuration(
        payload=_payload(emulator="dolphin", target_exe="dolphin", target_args=("-b", "-e", "rom.iso")),
        config=config,
        audit=False,
    )

    assert fallback_calls == ["dolphin:kbm"]


def test_apply_shortcut_controller_configuration_detection_failure_falls_back_to_kbm_profile_selection(
    monkeypatch,
) -> None:
    config = default_shortcut_config()
    applied_counts: list[int] = []

    monkeypatch.setattr(runtime_module, "is_steam_deck_linux", lambda: False)
    monkeypatch.setattr(
        runtime_module,
        "detect_xbox_controllers",
        lambda max_devices=2: (_ for _ in ()).throw(RuntimeError("detect failed")),
    )
    monkeypatch.setattr(
        runtime_module,
        "apply_controller_profile",
        lambda cfg, emulator_name, controller_count: applied_counts.append(controller_count),
    )

    runtime_module.apply_shortcut_controller_configuration(
        payload=_payload(emulator="pcsx2", target_exe="pcsx2-qt.exe", target_args=("--nogui", "game.iso")),
        config=config,
        audit=False,
    )

    assert applied_counts == [0]


def test_run_target_with_optional_exit_hook_uses_azahar_windows_exit_hook(monkeypatch) -> None:
    hook_calls: list[str] = []

    monkeypatch.setattr(runtime_module.sys, "platform", "win32")
    monkeypatch.setenv("GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK", "true")
    monkeypatch.setattr(
        runtime_module,
        "_run_windows_azahar_target_with_exit_hook",
        lambda payload: hook_calls.append(payload.emulator) or 11,
    )
    monkeypatch.setattr(
        runtime_module,
        "_run_target",
        lambda payload: (_ for _ in ()).throw(AssertionError("direct launch should not be used")),
    )

    exit_code = runtime_module._run_target_with_optional_exit_hook(
        _payload(emulator="azahar", target_exe="C:/Emu/Azahar.exe", target_args=("-f", "rom.3ds"))
    )

    assert exit_code == 11
    assert hook_calls == ["azahar"]


def test_run_target_with_optional_exit_hook_uses_dolphin_linux_exit_hook_for_flatpak(monkeypatch) -> None:
    hook_calls: list[str] = []

    monkeypatch.setattr(runtime_module.sys, "platform", "linux")
    monkeypatch.setattr(
        runtime_module,
        "_run_linux_dolphin_target_with_exit_hook",
        lambda payload: hook_calls.append(payload.emulator) or 9,
    )
    monkeypatch.setattr(
        runtime_module,
        "_run_target",
        lambda payload: (_ for _ in ()).throw(AssertionError("direct launch should not be used")),
    )

    exit_code = runtime_module._run_target_with_optional_exit_hook(
        _payload(
            emulator="dolphin",
            target_exe="flatpak",
            target_args=("run", "--device=all", "org.DolphinEmu.dolphin-emu", "-b", "-e", "game.iso"),
        )
    )

    assert exit_code == 9
    assert hook_calls == ["dolphin"]


def test_apply_shortcut_controller_configuration_audit_enables_verbose_profile_logs(monkeypatch) -> None:
    config = default_shortcut_config()
    observed: dict[str, object] = {}

    monkeypatch.setattr(runtime_module, "detect_xbox_controllers", lambda max_devices=2: [])

    def _fake_apply(*args, **kwargs):
        observed["verbose"] = kwargs.get("verbose")
        return "kbm"

    monkeypatch.setattr(runtime_module, "apply_controller_profile", _fake_apply)

    runtime_module.apply_shortcut_controller_configuration(
        payload=_payload(emulator="dolphin", target_exe="dolphin", target_args=("-b", "-e", "rom.iso")),
        config=config,
        audit=True,
    )

    assert observed["verbose"] is True


def test_run_target_with_optional_exit_hook_can_disable_dolphin_linux_exit_hook(monkeypatch) -> None:
    monkeypatch.setattr(runtime_module.sys, "platform", "linux")
    monkeypatch.setenv("GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK", "false")
    monkeypatch.setattr(
        runtime_module,
        "_run_linux_dolphin_target_with_exit_hook",
        lambda payload: (_ for _ in ()).throw(AssertionError("hook should be disabled")),
    )
    monkeypatch.setattr(runtime_module, "_run_target", lambda payload: 4)

    exit_code = runtime_module._run_target_with_optional_exit_hook(
        _payload(
            emulator="dolphin",
            target_exe="flatpak",
            target_args=("run", "--device=all", "org.DolphinEmu.dolphin-emu", "-b", "-e", "game.iso"),
        )
    )

    assert exit_code == 4


def test_apply_shortcut_controller_configuration_deck_zero_detect_defaults_to_xbox_1p(monkeypatch, capsys) -> None:
    config = default_shortcut_config()
    observed: dict[str, int] = {}

    monkeypatch.setattr(runtime_module, "detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr(runtime_module.sys, "platform", "linux")
    monkeypatch.setattr(runtime_module, "is_steam_deck_linux", lambda: True)

    def _apply(cfg, emulator_name, controller_count, verbose=False):
        observed["count"] = controller_count
        return "xbox_1p"

    monkeypatch.setattr(runtime_module, "apply_controller_profile", _apply)

    runtime_module.apply_shortcut_controller_configuration(
        payload=_payload(emulator="dolphin", target_exe="dolphin", target_args=("-b", "-e", "rom.iso")),
        config=config,
        audit=True,
    )

    assert observed["count"] == 1
    out = capsys.readouterr().out
    assert "zero_detect_policy=xbox_1p" in out
    assert "effective_controller_count=1" in out


def test_apply_shortcut_controller_configuration_non_deck_zero_detect_behavior_unchanged(monkeypatch) -> None:
    config = default_shortcut_config()
    observed: dict[str, int] = {}

    monkeypatch.setattr(runtime_module, "detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr(runtime_module.sys, "platform", "linux")
    monkeypatch.setattr(runtime_module, "is_steam_deck_linux", lambda: False)

    def _apply(cfg, emulator_name, controller_count, verbose=False):
        observed["count"] = controller_count
        return "kbm"

    monkeypatch.setattr(runtime_module, "apply_controller_profile", _apply)

    runtime_module.apply_shortcut_controller_configuration(
        payload=_payload(emulator="dolphin", target_exe="dolphin", target_args=("-b", "-e", "rom.iso")),
        config=config,
        audit=False,
    )

    assert observed["count"] == 0
