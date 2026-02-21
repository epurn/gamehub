from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4

import pytest

from gamehub_cli.emulators import ensure_emulators, resolve_emulator_executable
from gamehub_common.models import LibraryIndex, SystemSpec


def _index_with_emulators(*names: str) -> LibraryIndex:
    systems = tuple(
        SystemSpec(
            name=f"SYS{idx}",
            rom_extensions=(".bin",),
            default_emulator=name,
            launch_template='"{emulator}" "{rom}"',
            firmware=(),
        )
        for idx, name in enumerate(names, start=1)
    )
    return LibraryIndex(index_version=1, systems=systems, titles=())


def test_ensure_emulators_dry_run_reports_missing(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", lambda name: None)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())

    ensure_emulators(index=index, dry_run=True, verbose=False)

    out = capsys.readouterr().out
    assert "Missing emulators: retroarch" in out
    assert "Dry-run: emulator auto-install skipped" in out


def test_ensure_emulators_uses_winget_for_missing(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    state = {"retroarch_installed": False}

    def fake_which(name: str) -> str | None:
        if name == "winget":
            return "C:\\Windows\\System32\\winget.exe"
        if name == "retroarch":
            return "C:\\Emulators\\retroarch.exe" if state["retroarch_installed"] else None
        return None

    class FakeCompleted:
        returncode = 0

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        state["retroarch_installed"] = True
        return FakeCompleted()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "win32")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(index=index, dry_run=False, verbose=False)

    assert commands
    assert commands[0][0].lower().endswith("winget.exe")
    assert commands[0][1:4] == ["install", "--id", "Libretro.RetroArch"]
    assert "Installed emulator: retroarch" in capsys.readouterr().out


def test_ensure_emulators_accepts_existing_absolute_path(capsys) -> None:
    index = _index_with_emulators(str(Path(__file__).resolve()))
    ensure_emulators(index=index, dry_run=False, verbose=False)
    assert "Missing emulators" not in capsys.readouterr().out


def test_ensure_emulators_uses_fedora_dnf_for_missing(monkeypatch, capsys) -> None:
    index = _index_with_emulators("dolphin")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name == "dnf":
            return "/usr/bin/dnf"
        if name == "sudo":
            return "/usr/bin/sudo"
        if name in {"dolphin", "dolphin-emu"}:
            return "/usr/bin/dolphin-emu" if state["installed"] else None
        return None

    class FakeCompleted:
        returncode = 0

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        state["installed"] = True
        return FakeCompleted()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "fedora")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.os.geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(index=index, dry_run=False, verbose=False)

    assert commands
    assert commands[0][:5] == ["sudo", "dnf", "install", "-y", "dolphin-emu"]
    assert "Installed emulator: dolphin" in capsys.readouterr().out


def test_ensure_emulators_linux_auto_uses_apt_on_ubuntu(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name == "apt-get":
            return "/usr/bin/apt-get"
        if name == "sudo":
            return "/usr/bin/sudo"
        if name == "retroarch":
            return "/usr/bin/retroarch" if state["installed"] else None
        return None

    class FakeCompleted:
        returncode = 0

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        state["installed"] = True
        return FakeCompleted()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "ubuntu debian")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.os.geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(index=index, dry_run=False, verbose=False)

    assert commands
    assert commands[0][:5] == ["sudo", "apt-get", "install", "-y", "retroarch"]
    assert "Installed emulator: retroarch" in capsys.readouterr().out


def test_ensure_emulators_linux_apt_backend_requires_apt(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "ubuntu")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", lambda name: None)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())

    ensure_emulators(index=index, dry_run=False, verbose=False, linux_install_backend="apt")

    out = capsys.readouterr().out
    assert "apt-get not found" in out


def test_ensure_emulators_linux_non_fedora_reports_unsupported(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "ubuntu")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", lambda name: None)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())

    ensure_emulators(index=index, dry_run=False, verbose=False)

    assert "Linux emulator auto-install is unavailable" in capsys.readouterr().out


def test_ensure_emulators_linux_auto_uses_flatpak_when_available(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name == "flatpak":
            return "/usr/bin/flatpak"
        if name == "retroarch":
            return "/usr/bin/retroarch" if state["installed"] else None
        return None

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        if cmd[:3] == ["flatpak", "remotes", "--columns=name"]:
            return type("Completed", (), {"returncode": 0, "stdout": "flathub\n"})()
        if cmd[:4] == ["flatpak", "install", "--user", "-y"]:
            state["installed"] = True
            return type("Completed", (), {"returncode": 0, "stdout": ""})()
        return type("Completed", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "bazzite")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(index=index, dry_run=False, verbose=False)

    assert commands
    assert commands[0][:3] == ["flatpak", "remotes", "--columns=name"]
    assert commands[1][:4] == ["flatpak", "install", "--user", "-y"]
    assert commands[1][4] == "org.libretro.RetroArch"
    assert "Installed emulator: retroarch" in capsys.readouterr().out


def test_ensure_emulators_linux_flatpak_backend_forces_dolphin_flatpak_when_native_exists(monkeypatch, capsys) -> None:
    index = _index_with_emulators("dolphin")
    state = {"flatpak_installed": False}

    def fake_which(name: str) -> str | None:
        if name == "flatpak":
            return "/usr/bin/flatpak"
        if name in {"dolphin", "dolphin-emu"}:
            return "/usr/bin/dolphin"
        return None

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        if cmd[:3] == ["flatpak", "info", "--show-ref"]:
            code = 0 if state["flatpak_installed"] else 1
            return type("Completed", (), {"returncode": code, "stdout": ""})()
        if cmd[:3] == ["flatpak", "remotes", "--columns=name"]:
            return type("Completed", (), {"returncode": 0, "stdout": "flathub\n"})()
        if cmd[:4] == ["flatpak", "install", "--user", "-y"]:
            state["flatpak_installed"] = True
            return type("Completed", (), {"returncode": 0, "stdout": ""})()
        return type("Completed", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "bazzite fedora")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.emulator_install._flatpak_app_export_candidates",
        lambda app_id: (),
    )
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(index=index, dry_run=False, verbose=False, linux_install_backend="flatpak")

    assert ["flatpak", "info", "--show-ref", "org.DolphinEmu.dolphin-emu"] in commands
    assert ["flatpak", "install", "--user", "-y", "org.DolphinEmu.dolphin-emu"] in commands
    assert "Installing emulator 'dolphin' via flatpak (org.DolphinEmu.dolphin-emu)..." in capsys.readouterr().out


def test_ensure_emulators_linux_flatpak_backend_raises_when_forced_dolphin_still_missing(monkeypatch) -> None:
    index = _index_with_emulators("dolphin")

    def fake_which(name: str) -> str | None:
        if name == "flatpak":
            return "/usr/bin/flatpak"
        if name in {"dolphin", "dolphin-emu"}:
            return "/usr/bin/dolphin"
        return None

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        if cmd[:3] == ["flatpak", "info", "--show-ref"]:
            return type("Completed", (), {"returncode": 1, "stdout": ""})()
        if cmd[:3] == ["flatpak", "remotes", "--columns=name"]:
            return type("Completed", (), {"returncode": 0, "stdout": "flathub\n"})()
        if cmd[:4] == ["flatpak", "install", "--user", "-y"]:
            return type("Completed", (), {"returncode": 1, "stdout": ""})()
        return type("Completed", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "bazzite fedora")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.emulator_install._flatpak_app_export_candidates",
        lambda app_id: (),
    )
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="Required Flatpak emulator\\(s\\) are unavailable"):
        ensure_emulators(index=index, dry_run=False, verbose=False, linux_install_backend="flatpak")


def test_ensure_emulators_linux_auto_prefers_flatpak_for_bazzite_even_with_dnf(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name == "flatpak":
            return "/usr/bin/flatpak"
        if name == "dnf":
            return "/usr/bin/dnf"
        if name == "sudo":
            return "/usr/bin/sudo"
        if name == "retroarch":
            return "/usr/bin/retroarch" if state["installed"] else None
        return None

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        if cmd[:3] == ["flatpak", "remotes", "--columns=name"]:
            return type("Completed", (), {"returncode": 0, "stdout": "flathub\n"})()
        if cmd[:4] == ["flatpak", "install", "--user", "-y"]:
            state["installed"] = True
            return type("Completed", (), {"returncode": 0, "stdout": ""})()
        if cmd[:5] == ["sudo", "dnf", "install", "-y", "retroarch"]:
            return type("Completed", (), {"returncode": 0, "stdout": ""})()
        return type("Completed", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "bazzite fedora")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(index=index, dry_run=False, verbose=False)

    assert commands
    assert commands[0][:3] == ["flatpak", "remotes", "--columns=name"]
    assert commands[1][:4] == ["flatpak", "install", "--user", "-y"]
    assert all(command[:2] != ["sudo", "dnf"] for command in commands)
    assert "Installed emulator: retroarch" in capsys.readouterr().out


def test_ensure_emulators_linux_flatpak_remote_override(monkeypatch, capsys) -> None:
    index = _index_with_emulators("pcsx2")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name == "flatpak":
            return "/usr/bin/flatpak"
        if name in {"pcsx2", "pcsx2-qt"}:
            return "/usr/bin/pcsx2-qt" if state["installed"] else None
        return None

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        if cmd[:3] == ["flatpak", "remotes", "--columns=name"]:
            return type("Completed", (), {"returncode": 0, "stdout": "fedora\nflathub\n"})()
        if cmd[:4] == ["flatpak", "install", "--user", "-y"]:
            state["installed"] = True
            return type("Completed", (), {"returncode": 0, "stdout": ""})()
        return type("Completed", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "bazzite")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(
        index=index,
        dry_run=False,
        verbose=False,
        linux_install_backend="flatpak",
        linux_flatpak_remote="flathub",
    )

    assert commands[1][:5] == ["flatpak", "install", "--user", "-y", "flathub"]
    assert commands[1][5] == "net.pcsx2.PCSX2"
    assert "Installed emulator: pcsx2" in capsys.readouterr().out


def test_ensure_emulators_linux_flatpak_installs_azahar(monkeypatch, capsys) -> None:
    index = _index_with_emulators("azahar")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name == "flatpak":
            return "/usr/bin/flatpak"
        if name in {"azahar", "azahar-qt"}:
            return "/usr/bin/azahar" if state["installed"] else None
        if name == "org.azahar_emu.Azahar":
            return "/home/deck/.local/share/flatpak/exports/bin/org.azahar_emu.Azahar" if state["installed"] else None
        return None

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        if cmd[:3] == ["flatpak", "info", "--show-ref"]:
            code = 0 if state["installed"] else 1
            return type("Completed", (), {"returncode": code, "stdout": ""})()
        if cmd[:3] == ["flatpak", "remotes", "--columns=name"]:
            return type("Completed", (), {"returncode": 0, "stdout": "flathub\n"})()
        if cmd[:4] == ["flatpak", "install", "--user", "-y"]:
            state["installed"] = True
            return type("Completed", (), {"returncode": 0, "stdout": ""})()
        return type("Completed", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "bazzite")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(
        index=index,
        dry_run=False,
        verbose=False,
        linux_install_backend="flatpak",
        linux_flatpak_remote="flathub",
    )

    assert ["flatpak", "install", "--user", "-y", "flathub", "org.azahar_emu.Azahar"] in commands
    assert "Installing emulator 'azahar' via flatpak (org.azahar_emu.Azahar)..." in capsys.readouterr().out


def test_ensure_emulators_linux_flatpak_maps_azahar_qt_alias(monkeypatch, capsys) -> None:
    index = _index_with_emulators("azahar-qt")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name == "flatpak":
            return "/usr/bin/flatpak"
        if name in {"azahar", "azahar-qt"}:
            return "/usr/bin/azahar-qt" if state["installed"] else None
        if name == "org.azahar_emu.Azahar":
            return "/home/deck/.local/share/flatpak/exports/bin/org.azahar_emu.Azahar" if state["installed"] else None
        return None

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        if cmd[:3] == ["flatpak", "info", "--show-ref"]:
            code = 0 if state["installed"] else 1
            return type("Completed", (), {"returncode": code, "stdout": ""})()
        if cmd[:3] == ["flatpak", "remotes", "--columns=name"]:
            return type("Completed", (), {"returncode": 0, "stdout": "flathub\n"})()
        if cmd[:4] == ["flatpak", "install", "--user", "-y"]:
            state["installed"] = True
            return type("Completed", (), {"returncode": 0, "stdout": ""})()
        return type("Completed", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "bazzite")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(
        index=index,
        dry_run=False,
        verbose=False,
        linux_install_backend="flatpak",
        linux_flatpak_remote="flathub",
    )

    assert ["flatpak", "install", "--user", "-y", "flathub", "org.azahar_emu.Azahar"] in commands
    out = capsys.readouterr().out
    assert "No flatpak mapping for emulator" not in out


def test_ensure_emulators_linux_flatpak_remote_fallbacks_to_unpinned(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name == "flatpak":
            return "/usr/bin/flatpak"
        if name == "retroarch":
            return "/usr/bin/retroarch" if state["installed"] else None
        return None

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        if cmd[:3] == ["flatpak", "remotes", "--columns=name"]:
            return type("Completed", (), {"returncode": 0, "stdout": "flathub\nflathub-user\n"})()
        if cmd == ["flatpak", "install", "--user", "-y", "flathub", "org.libretro.RetroArch"]:
            return type("Completed", (), {"returncode": 1, "stdout": ""})()
        if cmd == ["flatpak", "install", "--user", "-y", "org.libretro.RetroArch"]:
            state["installed"] = True
            return type("Completed", (), {"returncode": 0, "stdout": ""})()
        return type("Completed", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "bazzite")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(
        index=index,
        dry_run=False,
        verbose=False,
        linux_install_backend="flatpak",
        linux_flatpak_remote="flathub",
    )

    assert ["flatpak", "install", "--user", "-y", "flathub", "org.libretro.RetroArch"] in commands
    assert ["flatpak", "install", "--user", "-y", "org.libretro.RetroArch"] in commands
    out = capsys.readouterr().out
    assert "retrying with automatic remote resolution" in out
    assert "Installed emulator: retroarch" in out


def test_ensure_emulators_linux_command_backend(monkeypatch, capsys) -> None:
    index = _index_with_emulators("dolphin")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name in {"dolphin", "dolphin-emu"}:
            return "/usr/bin/dolphin-emu" if state["installed"] else None
        return None

    class FakeCompleted:
        returncode = 0

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        state["installed"] = True
        return FakeCompleted()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "ubuntu")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(
        index=index,
        dry_run=False,
        verbose=False,
        linux_install_backend="command",
        linux_install_command="sudo apt install -y {package}",
    )

    assert commands
    assert commands[0] == ["sudo", "apt", "install", "-y", "dolphin-emu"]
    assert "Installed emulator: dolphin" in capsys.readouterr().out


def test_ensure_emulators_detects_known_install_without_winget(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    with _workspace_tempdir("gamehub-emulator-detect-") as temp_root:
        exe = temp_root / "retroarch.exe"
        exe.write_bytes(b"exe")
        monkeypatch.setattr("gamehub_cli.emulators.shutil.which", lambda name: None)
        monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: (exe,))

        ensure_emulators(index=index, dry_run=False, verbose=False)

        assert "Missing emulators" not in capsys.readouterr().out


def test_ensure_emulators_windows_dolphin_uses_official_release_without_winget(monkeypatch, capsys) -> None:
    index = _index_with_emulators("dolphin")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name in {"dolphin", "dolphin-emu"}:
            return "C:\\Emulators\\Dolphin.exe" if state["installed"] else None
        return None

    class FakeCompleted:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        return FakeCompleted(1, stdout="")

    def fake_release_install(*, verbose: bool) -> bool:
        state["installed"] = True
        return True

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)
    monkeypatch.setattr(
        "gamehub_cli.emulators.emulator_install._install_dolphin_from_official_release_archive",
        fake_release_install,
    )

    ensure_emulators(index=index, dry_run=False, verbose=False)

    out = capsys.readouterr().out
    assert "Installing emulator 'dolphin' via official Dolphin release archive..." in out
    assert "Installed emulator: dolphin" in out
    assert not commands


def test_ensure_emulators_windows_azahar_uses_github_release_installer(monkeypatch, capsys) -> None:
    index = _index_with_emulators("azahar")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name in {"azahar", "azahar-qt"}:
            return "C:\\Emulators\\Azahar\\azahar.exe" if state["installed"] else None
        return None

    def fake_azahar_install(*, verbose: bool):
        state["installed"] = True
        return (
            True,
            Path("C:/Temp/azahar-installer.exe"),
            "https://github.com/azahar-emu/azahar/releases/download/2124.3/example.exe",
        )

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "win32")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.emulator_install._install_azahar_from_windows_installer",
        fake_azahar_install,
    )

    ensure_emulators(index=index, dry_run=False, verbose=False)

    out = capsys.readouterr().out
    assert "Installing emulator 'azahar' via GitHub release installer..." in out
    assert "Installed emulator: azahar" in out


def test_ensure_emulators_windows_azahar_installer_failure_warns_manual_fallback(monkeypatch, capsys) -> None:
    index = _index_with_emulators("azahar")

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "win32")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", lambda name: None)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.emulator_install._install_azahar_from_windows_installer",
        lambda *args, **kwargs: (
            False,
            Path("C:/Temp/azahar-2124.3-windows-msys2-installer.exe"),
            "https://github.com/azahar-emu/azahar/releases/download/2124.3/azahar-2124.3-windows-msys2-installer.exe",
        ),
    )

    ensure_emulators(index=index, dry_run=False, verbose=False)

    out = capsys.readouterr().out
    assert "automatic silent Azahar install failed" in out
    assert "run installer manually: C:/Temp/azahar-2124.3-windows-msys2-installer.exe" in out
    assert (
        "install Azahar manually from https://github.com/azahar-emu/azahar/releases/download/2124.3/azahar-2124.3-windows-msys2-installer.exe and re-run sync"
        in out
    )


def test_ensure_emulators_windows_azahar_installer_retries_with_uac_elevation(monkeypatch, capsys) -> None:
    index = _index_with_emulators("azahar")
    state = {"installed": False}
    commands: list[list[str]] = []

    class FakeCompleted:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_which(name: str) -> str | None:
        if name in {"azahar", "azahar-qt"}:
            return "C:\\Emulators\\Azahar\\azahar.exe" if state["installed"] else None
        if name == "powershell":
            return "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
        return None

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        if cmd and cmd[0].lower().endswith("installer.exe"):
            err = OSError("elevation required")
            setattr(err, "winerror", 740)
            raise err
        if cmd and "powershell" in cmd[0].lower():
            state["installed"] = True
            return FakeCompleted(0)
        return FakeCompleted(0)

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "win32")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.emulator_install._download_azahar_windows_installer",
        lambda url: Path("C:/Temp/azahar-2124.3-windows-msys2-installer.exe"),
    )
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(index=index, dry_run=False, verbose=False)

    out = capsys.readouterr().out
    assert "Azahar installer requires administrator elevation" in out
    assert "Installed emulator: azahar" in out
    assert any(command and "powershell" in command[0].lower() for command in commands)


def test_ensure_emulators_windows_dolphin_archive_failure_warns(monkeypatch, capsys) -> None:
    index = _index_with_emulators("dolphin")

    def fake_which(name: str) -> str | None:
        return None

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.emulator_install._install_dolphin_from_official_release_archive",
        lambda *args, **kwargs: False,
    )

    ensure_emulators(index=index, dry_run=False, verbose=False)

    out = capsys.readouterr().out
    assert "official Dolphin release archive install failed" in out
    assert "install the latest Dolphin manually from dolphin-emu.org and re-run sync" in out


def test_ensure_emulators_windows_dolphin_uses_official_release_fallback(monkeypatch, capsys) -> None:
    index = _index_with_emulators("dolphin")
    state = {"installed": False}

    def fake_which(name: str) -> str | None:
        if name in {"dolphin", "dolphin-emu"}:
            return "C:\\Emulators\\Dolphin.exe" if state["installed"] else None
        return None

    class FakeCompleted:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        # Dolphin path should not invoke winget commands.
        return FakeCompleted(0, stdout="")

    def fake_manifest_fallback(*, verbose: bool) -> bool:
        state["installed"] = True
        return True

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)
    monkeypatch.setattr(
        "gamehub_cli.emulators.emulator_install._install_dolphin_from_official_release_archive",
        fake_manifest_fallback,
    )

    ensure_emulators(index=index, dry_run=False, verbose=False)

    out = capsys.readouterr().out
    assert "Installing emulator 'dolphin' via official Dolphin release archive..." in out
    assert "Installed emulator: dolphin" in out


def test_ensure_emulators_windows_dolphin_fails_fast_on_legacy_parser_path(monkeypatch) -> None:
    index = _index_with_emulators("dolphin")

    legacy_path = (
        "C:\\Users\\evanp\\AppData\\Local\\Microsoft\\WinGet\\Packages\\"
        "DolphinEmulator.Dolphin_5.0_x64__abc123\\Dolphin.exe"
    )

    def fake_which(name: str) -> str | None:
        if name == "dolphin":
            return legacy_path
        return None

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())

    with pytest.raises(RuntimeError, match="Unsupported legacy Dolphin build detected"):
        ensure_emulators(index=index, dry_run=False, verbose=False)


def test_resolve_emulator_executable_prefers_shutil_which(monkeypatch) -> None:
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", lambda cmd: "C:\\Emulators\\retroarch.exe")
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    resolved = resolve_emulator_executable("retroarch")
    assert resolved == "C:\\Emulators\\retroarch.exe"


def test_resolve_emulator_executable_falls_back_to_known_paths(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-emulator-resolve-") as temp_root:
        candidate = temp_root / "Programs" / "RetroArch" / "retroarch.exe"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"exe")
        monkeypatch.setattr("gamehub_cli.emulators.os.name", "nt")
        monkeypatch.setenv("LOCALAPPDATA", str(temp_root))
        monkeypatch.delenv("ProgramFiles", raising=False)
        monkeypatch.setattr("gamehub_cli.emulators.shutil.which", lambda cmd: None)

        resolved = resolve_emulator_executable("retroarch")

        assert resolved == str(candidate)


def test_resolve_emulator_executable_falls_back_to_known_azahar_paths(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-emulator-resolve-") as temp_root:
        candidate = temp_root / "Programs" / "Azahar" / "azahar.exe"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"exe")
        monkeypatch.setattr("gamehub_cli.emulators.os.name", "nt")
        monkeypatch.setenv("LOCALAPPDATA", str(temp_root))
        monkeypatch.delenv("ProgramFiles", raising=False)
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        monkeypatch.setattr("gamehub_cli.emulators.shutil.which", lambda cmd: None)

        resolved = resolve_emulator_executable("azahar")

        assert resolved == str(candidate)


def test_resolve_emulator_executable_prefers_known_path_over_windowsapps_alias(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-emulator-resolve-") as temp_root:
        candidate = temp_root / "Programs" / "RetroArch" / "retroarch.exe"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"exe")
        monkeypatch.setattr("gamehub_cli.emulators.os.name", "nt")
        monkeypatch.setenv("LOCALAPPDATA", str(temp_root))
        monkeypatch.delenv("ProgramFiles", raising=False)
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        monkeypatch.setattr(
            "gamehub_cli.emulators.shutil.which",
            lambda cmd: "C:\\Users\\evanp\\AppData\\Local\\Microsoft\\WindowsApps\\retroarch.exe",
        )

        resolved = resolve_emulator_executable("retroarch")

        assert resolved == str(candidate)


def test_resolve_emulator_executable_linux_uses_matching_flatpak_export(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-emulator-linux-flatpak-") as temp_root:
        export_dir = temp_root / ".local" / "share" / "flatpak" / "exports" / "bin"
        export_dir.mkdir(parents=True, exist_ok=True)
        retroarch_export = export_dir / "org.libretro.RetroArch"
        pcsx2_export = export_dir / "net.pcsx2.PCSX2"
        retroarch_export.write_bytes(b"exe")
        pcsx2_export.write_bytes(b"exe")

        monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.emulators.Path.home", lambda: temp_root)
        monkeypatch.setattr("gamehub_cli.emulators.shutil.which", lambda cmd: None)

        resolved = resolve_emulator_executable("pcsx2")

        assert resolved == str(pcsx2_export)


def test_resolve_emulator_executable_linux_uses_azahar_flatpak_export(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-emulator-linux-flatpak-") as temp_root:
        export_dir = temp_root / ".local" / "share" / "flatpak" / "exports" / "bin"
        export_dir.mkdir(parents=True, exist_ok=True)
        azahar_export = export_dir / "org.azahar_emu.Azahar"
        azahar_export.write_bytes(b"exe")

        monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.emulators.Path.home", lambda: temp_root)
        monkeypatch.setattr("gamehub_cli.emulators.shutil.which", lambda cmd: None)

        resolved = resolve_emulator_executable("azahar")

        assert resolved == str(azahar_export)
