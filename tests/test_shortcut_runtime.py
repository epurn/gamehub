from __future__ import annotations

import os

import pytest

import gamehub_cli.shortcuts.runtime as runtime_module
from gamehub_cli.common.shortcut_payload import ShortcutLaunchPayload
from gamehub_cli.controllers.detection import XboxController
from tests.shortcut_test_helpers import default_shortcut_config


def _payload(
    *,
    emulator: str,
    target_exe: str,
    target_args: tuple[str, ...],
    start_dir: str = "",
    macos_open_app: str | None = None,
    macos_open_args: tuple[str, ...] = (),
) -> ShortcutLaunchPayload:
    return ShortcutLaunchPayload(
        version=1,
        emulator=emulator,
        target_exe=target_exe,
        target_args=target_args,
        start_dir=start_dir,
        macos_open_app=macos_open_app,
        macos_open_args=macos_open_args,
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


def test_run_target_with_optional_exit_hook_uses_azahar_macos_exit_hook(monkeypatch) -> None:
    hook_calls: list[str] = []

    monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
    monkeypatch.setenv("GAMEHUB_AZAHAR_MACOS_EXIT_HOOK", "true")
    monkeypatch.setattr(
        runtime_module,
        "_run_macos_azahar_target_with_exit_hook",
        lambda payload: hook_calls.append(payload.emulator) or 12,
    )
    monkeypatch.setattr(
        runtime_module,
        "_run_target",
        lambda payload: (_ for _ in ()).throw(AssertionError("managed launch should not be used")),
    )

    exit_code = runtime_module._run_target_with_optional_exit_hook(
        _payload(
            emulator="azahar",
            target_exe="/Users/tester/Applications/Azahar.app/Contents/MacOS/azahar",
            target_args=("-f", "rom.3ds"),
            macos_open_app="/Users/tester/Applications/Azahar.app",
            macos_open_args=("-f", "rom.3ds"),
        )
    )

    assert exit_code == 12
    assert hook_calls == ["azahar"]


def test_run_macos_azahar_target_with_exit_hook_uses_bundle_document_launch(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Process:
        def wait(self) -> int:
            captured["wait_called"] = True
            return 0

    class _Thread:
        def __init__(self, *, target=None, args=(), kwargs=None, daemon=None):
            captured["thread_target"] = target
            captured["thread_args"] = args
            captured["thread_kwargs"] = kwargs or {}
            captured["thread_daemon"] = daemon

        def start(self) -> None:
            captured["thread_started"] = True

    monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        runtime_module,
        "_spawn_shortcut_process",
        lambda command, *, cwd: captured.update({"command": command, "cwd": cwd}) or _Process(),
    )
    monkeypatch.setattr(runtime_module.azahar_exit_hook, "_resolve_select_and_start_buttons", lambda: (8, 10))
    monkeypatch.setattr(runtime_module.azahar_exit_hook, "_resolve_port_from_config", lambda: 0)
    monkeypatch.setattr(
        runtime_module.azahar_exit_hook,
        "_resolve_macos_bundle_identifier",
        lambda app_bundle: "org.azahar-emu.azahar",
    )
    monkeypatch.setattr(
        runtime_module.azahar_exit_hook,
        "_discover_process_ids_by_name",
        lambda process_name: {101},
    )
    monkeypatch.setattr(runtime_module.threading, "Thread", _Thread)

    exit_code = runtime_module._run_macos_azahar_target_with_exit_hook(
        _payload(
            emulator="azahar",
            target_exe="/Users/tester/Applications/Azahar.app/Contents/MacOS/azahar",
            target_args=("-f", "/Users/tester/Games/Pilotwings Resort.3ds"),
            macos_open_app="/Users/tester/Applications/Azahar.app",
            macos_open_args=("-f", "/Users/tester/Games/Pilotwings Resort.3ds"),
        )
    )

    assert exit_code == 0
    assert captured["command"] == [
        "/usr/bin/open",
        "-W",
        "-a",
        "/Users/tester/Applications/Azahar.app",
        "/Users/tester/Games/Pilotwings Resort.3ds",
    ]
    assert captured["cwd"] is None
    assert captured["wait_called"] is True
    assert captured["thread_started"] is True
    assert captured["thread_kwargs"] == {
        "select_button": 8,
        "start_button": 10,
        "controller_port": 0,
        "bundle_id": "org.azahar-emu.azahar",
        "process_name": "azahar",
        "prelaunch_pids": {101},
    }


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


def test_run_target_with_optional_exit_hook_can_disable_azahar_macos_exit_hook(monkeypatch) -> None:
    monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
    monkeypatch.setenv("GAMEHUB_AZAHAR_MACOS_EXIT_HOOK", "false")
    monkeypatch.setattr(
        runtime_module,
        "_run_macos_azahar_target_with_exit_hook",
        lambda payload: (_ for _ in ()).throw(AssertionError("hook should be disabled")),
    )
    monkeypatch.setattr(runtime_module, "_run_target", lambda payload: 13)

    exit_code = runtime_module._run_target_with_optional_exit_hook(
        _payload(
            emulator="azahar",
            target_exe="/Users/tester/Applications/Azahar.app/Contents/MacOS/azahar",
            target_args=("-f", "rom.3ds"),
            macos_open_app="/Users/tester/Applications/Azahar.app",
            macos_open_args=("-f", "rom.3ds"),
        )
    )

    assert exit_code == 13


def test_run_target_macos_uses_bundle_safe_open_command(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Process:
        def wait(self) -> int:
            captured["wait_called"] = True
            return 0

    def _fake_popen(command, cwd=None, stdin=None):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["stdin"] = stdin
        return _Process()

    monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
    monkeypatch.setattr(runtime_module.subprocess, "Popen", _fake_popen)

    exit_code = runtime_module._run_target(
        _payload(
            emulator="retroarch",
            target_exe="/Users/tester/Applications/RetroArch.app/Contents/MacOS/retroarch-metal",
            target_args=("-f", "-L", "cores/gambatte_libretro.dylib", "/Users/tester/Games/Pokemon.gbc"),
            macos_open_app="/Users/tester/Applications/RetroArch.app",
            macos_open_args=("-f", "-L", "cores/gambatte_libretro.dylib", "/Users/tester/Games/Pokemon.gbc"),
        )
    )

    assert exit_code == 0
    assert captured["command"] == [
        "/usr/bin/open",
        "-W",
        "-a",
        "/Users/tester/Applications/RetroArch.app",
        "--args",
        "-f",
        "-L",
        "cores/gambatte_libretro.dylib",
        "/Users/tester/Games/Pokemon.gbc",
    ]
    assert captured["cwd"] is None
    assert captured["stdin"] is runtime_module.subprocess.DEVNULL
    assert captured["wait_called"] is True


def test_run_target_macos_managed_launch_without_shell_wrapper_preserves_wait_behavior(monkeypatch) -> None:
    call_order: list[str] = []
    captured: dict[str, object] = {}

    class _Process:
        def wait(self) -> int:
            call_order.append("wait")
            return 37

    def _fake_popen(command, cwd=None, stdin=None):
        call_order.append("popen")
        captured["command"] = command
        captured["cwd"] = cwd
        captured["stdin"] = stdin
        return _Process()

    monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
    monkeypatch.setattr(runtime_module.subprocess, "Popen", _fake_popen)

    exit_code = runtime_module._run_target_with_optional_exit_hook(
        _payload(
            emulator="dolphin",
            target_exe="/Users/tester/Applications/Dolphin.app/Contents/MacOS/DolphinQt",
            target_args=("-b", "-e", "/Users/tester/Games/Super Mario Galaxy.rvz"),
            macos_open_app="/Users/tester/Applications/Dolphin.app",
            macos_open_args=("-b", "-e", "/Users/tester/Games/Super Mario Galaxy.rvz"),
        )
    )
    call_order.append("returned")

    assert exit_code == 37
    assert call_order == ["popen", "wait", "returned"]
    assert captured["command"] == [
        "/usr/bin/open",
        "-W",
        "-a",
        "/Users/tester/Applications/Dolphin.app",
        "--args",
        "-b",
        "-e",
        "/Users/tester/Games/Super Mario Galaxy.rvz",
    ]
    assert captured["cwd"] is None
    assert captured["stdin"] is runtime_module.subprocess.DEVNULL


def test_run_target_macos_uses_explicit_azahar_user_bundle_path(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-azahar-runtime-") as temp_root:
        captured: dict[str, object] = {}
        executable = temp_root / "Applications" / "Azahar.app" / "Contents" / "MacOS" / "azahar"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")

        class _Process:
            def wait(self) -> int:
                captured["wait_called"] = True
                return 0

        def _fake_popen(command, cwd=None, stdin=None):
            captured["command"] = command
            captured["cwd"] = cwd
            captured["stdin"] = stdin
            return _Process()

        monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
        monkeypatch.setattr(runtime_module.subprocess, "Popen", _fake_popen)

        exit_code = runtime_module._run_target(
            _payload(
                emulator="azahar",
                target_exe=str(executable),
                target_args=("-f", "/Users/tester/Games/Pilotwings Resort.3ds"),
                macos_open_app=str(executable.parents[2]),
                macos_open_args=("-f", "/Users/tester/Games/Pilotwings Resort.3ds"),
            )
        )

        assert exit_code == 0
        assert captured["command"] == [
            "/usr/bin/open",
            "-W",
            "-a",
            str(executable.parents[2]),
            "/Users/tester/Games/Pilotwings Resort.3ds",
        ]
        assert captured["cwd"] is None
        assert captured["stdin"] is runtime_module.subprocess.DEVNULL
        assert captured["wait_called"] is True


def test_run_target_macos_azahar_falls_back_to_direct_launch_when_document_launch_fails(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-azahar-runtime-fallback-") as temp_root:
        commands: list[list[str]] = []
        executable = temp_root / "Applications" / "Azahar.app" / "Contents" / "MacOS" / "azahar"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")

        class _Process:
            def wait(self) -> int:
                return 0

        def _fake_spawn(command: list[str], *, cwd: str | None):
            commands.append(command)
            if len(commands) == 1:
                raise runtime_module.ShortcutLaunchError("document launch boom")
            assert cwd == str(executable.parent)
            return _Process()

        monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
        monkeypatch.setattr(runtime_module, "_spawn_shortcut_process", _fake_spawn)

        exit_code = runtime_module._run_target(
            _payload(
                emulator="azahar",
                target_exe=str(executable),
                target_args=("-f", "/Users/tester/Games/Pilotwings Resort.3ds"),
                macos_open_app=str(executable.parents[2]),
                macos_open_args=("-f", "/Users/tester/Games/Pilotwings Resort.3ds"),
            )
        )

        assert exit_code == 0
        assert commands == [
            [
                "/usr/bin/open",
                "-W",
                "-a",
                str(executable.parents[2]),
                "/Users/tester/Games/Pilotwings Resort.3ds",
            ],
            [
                str(executable),
                "-f",
                "/Users/tester/Games/Pilotwings Resort.3ds",
            ],
        ]


def test_run_target_macos_azahar_falls_back_to_bundle_launch_when_document_and_direct_fail(monkeypatch) -> None:
    commands: list[list[str]] = []

    class _Process:
        def wait(self) -> int:
            return 0

    def _fake_spawn(command: list[str], *, cwd: str | None):
        commands.append(command)
        if len(commands) == 1:
            raise runtime_module.ShortcutLaunchError("document launch boom")
        if len(commands) == 2:
            raise runtime_module.ShortcutLaunchError("direct exec boom")
        assert cwd is None
        return _Process()

    monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
    monkeypatch.setattr(runtime_module, "_spawn_shortcut_process", _fake_spawn)

    exit_code = runtime_module._run_target(
        _payload(
            emulator="azahar",
            target_exe="/Users/tester/Applications/Azahar.app/Contents/MacOS/azahar",
            target_args=("-f", "/Users/tester/Games/Pilotwings Resort.3ds"),
            macos_open_app="/Users/tester/Applications/Azahar.app",
            macos_open_args=("-f", "/Users/tester/Games/Pilotwings Resort.3ds"),
        )
    )

    assert exit_code == 0
    assert commands == [
        [
            "/usr/bin/open",
            "-W",
            "-a",
            "/Users/tester/Applications/Azahar.app",
            "/Users/tester/Games/Pilotwings Resort.3ds",
        ],
        [
            "/Users/tester/Applications/Azahar.app/Contents/MacOS/azahar",
            "-f",
            "/Users/tester/Games/Pilotwings Resort.3ds",
        ],
        [
            "/usr/bin/open",
            "-W",
            "/Users/tester/Applications/Azahar.app",
            "--args",
            "-f",
            "/Users/tester/Games/Pilotwings Resort.3ds",
        ],
    ]


def test_run_target_macos_launch_failure_raises_shortcut_launch_error(monkeypatch) -> None:
    monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        runtime_module.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("open missing")),
    )

    with pytest.raises(runtime_module.ShortcutLaunchError, match="launch failed"):
        runtime_module._run_target(
            _payload(
                emulator="azahar",
                target_exe="/Users/tester/Applications/Azahar.app/Contents/MacOS/azahar",
                target_args=("-f", "/Users/tester/Games/Pilotwings Resort.3ds"),
                macos_open_app="/Users/tester/Applications/Azahar.app",
                macos_open_args=("-f", "/Users/tester/Games/Pilotwings Resort.3ds"),
            )
        )


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


def test_warn_shortcut_runtime_swallows_broken_pipe(monkeypatch) -> None:
    class _BrokenStderr:
        def write(self, _text: str) -> int:
            raise BrokenPipeError("closed pipe")

        def flush(self) -> None:
            raise BrokenPipeError("closed pipe")

    monkeypatch.setattr(runtime_module.sys, "stderr", _BrokenStderr())

    runtime_module.warn_shortcut_runtime("controller autoconfig failed")
