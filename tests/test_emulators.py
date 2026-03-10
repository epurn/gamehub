from __future__ import annotations

import plistlib
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import gamehub_cli.emulators.install_macos as install_macos_module
from gamehub_cli.common.config import load_config
from gamehub_cli.emulators import ensure_emulators, resolve_emulator_executable
from gamehub_cli.emulators.install_macos import MacOSOfficialAsset
from gamehub_cli.emulators.save_resolution import (
    canonical_suffix_for_learned_path,
    default_emulator_for_system,
    discover_local_exact_save_candidates,
    learn_binding_root,
    resolve_emulator_save_root,
    resolve_exact_local_save_destination,
    resolve_system_save_root,
    snapshot_binding_tree,
)
from gamehub_common.models import LibraryIndex, SaveBindingSpec, SystemSpec


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


def _write_macos_app_bundle(bundle_path: Path, executable_name: str) -> Path:
    info_plist = bundle_path / "Contents" / "Info.plist"
    executable_path = bundle_path / "Contents" / "MacOS" / executable_name
    info_plist.parent.mkdir(parents=True, exist_ok=True)
    executable_path.parent.mkdir(parents=True, exist_ok=True)
    info_plist.write_bytes(plistlib.dumps({"CFBundleExecutable": executable_name}))
    executable_path.write_bytes(b"exe")
    return executable_path


def test_ensure_emulators_dry_run_reports_missing(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", lambda name: None)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "win32")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "fedora")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.os.geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "ubuntu debian")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.os.geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

    ensure_emulators(index=index, dry_run=False, verbose=False)

    assert commands
    assert commands[0][:5] == ["sudo", "apt-get", "install", "-y", "retroarch"]
    assert "Installed emulator: retroarch" in capsys.readouterr().out


def test_ensure_emulators_linux_apt_backend_requires_apt(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "ubuntu")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", lambda name: None)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())

    ensure_emulators(index=index, dry_run=False, verbose=False, linux_install_backend="apt")

    out = capsys.readouterr().out
    assert "apt-get not found" in out


def test_ensure_emulators_linux_non_fedora_reports_unsupported(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "ubuntu")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", lambda name: None)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "bazzite")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "bazzite fedora")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.installer._flatpak_app_export_candidates",
        lambda app_id: (),
    )
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "bazzite fedora")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.installer._flatpak_app_export_candidates",
        lambda app_id: (),
    )
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "bazzite fedora")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "bazzite")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "bazzite")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "bazzite")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "bazzite")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "linux")
    monkeypatch.setattr("gamehub_cli.emulators.installer._linux_dist_id", lambda: "ubuntu")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

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


def test_ensure_emulators_macos_auto_uses_official_backend(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")
    calls: list[tuple[list[str], bool]] = []

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "darwin")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", lambda name: None)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.installer._install_macos_official",
        lambda missing, verbose: calls.append((missing, verbose)),
    )

    ensure_emulators(index=index, dry_run=False, verbose=False, macos_install_backend="auto")

    assert calls == [(["retroarch"], False)]
    assert "Missing emulators: retroarch" in capsys.readouterr().out


def test_ensure_emulators_macos_none_backend_reports_disabled(monkeypatch, capsys) -> None:
    index = _index_with_emulators("retroarch")

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "darwin")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", lambda name: None)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())

    ensure_emulators(index=index, dry_run=False, verbose=False, macos_install_backend="none")

    out = capsys.readouterr().out
    assert "Missing emulators: retroarch" in out
    assert "macOS emulator auto-install disabled by configuration" in out


def test_ensure_emulators_macos_command_backend_runs_template(monkeypatch, capsys) -> None:
    index = _index_with_emulators("dolphin")
    state = {"installed": False}
    commands: list[list[str]] = []

    class FakeCompleted:
        returncode = 0

    def fake_which(name: str) -> str | None:
        if name in {"dolphin", "dolphin-emu"}:
            return "/Users/tester/Applications/Dolphin.app/Contents/MacOS/DolphinQt" if state["installed"] else None
        return None

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        del check, capture_output, text
        commands.append(cmd)
        state["installed"] = True
        return FakeCompleted()

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "darwin")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

    ensure_emulators(
        index=index,
        dry_run=False,
        verbose=False,
        macos_install_backend="command",
        macos_install_command="brew install --cask {package}",
    )

    assert commands == [["brew", "install", "--cask", "dolphin"]]
    assert "Installed emulator: dolphin" in capsys.readouterr().out


def test_ensure_emulators_macos_official_backend_rejects_non_native_asset(monkeypatch, capsys) -> None:
    index = _index_with_emulators("dolphin")

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "darwin")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", lambda name: None)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.install_macos._resolve_macos_official_asset",
        lambda emulator: (
            MacOSOfficialAsset(
                emulator=emulator,
                archive_kind="dmg",
                bundle_name="Dolphin.app",
                download_url="https://dl.dolphin-emu.org/releases/2509/dolphin-2509-universal.dmg",
                source_url="https://dolphin-emu.org/download/",
                asset_label="universal",
            ),
            None,
        ),
    )
    monkeypatch.setattr(
        "gamehub_cli.emulators.install_macos._install_macos_official_asset",
        lambda asset, verbose: (
            "unsupported",
            "upstream asset is not native Apple Silicon or universal (architectures: x86_64)",
        ),
    )

    ensure_emulators(index=index, dry_run=False, verbose=False, macos_install_backend="official")

    out = capsys.readouterr().out
    assert "official macOS Apple Silicon install unavailable for dolphin" in out
    assert "architectures: x86_64" in out
    assert "install dolphin manually from https://dolphin-emu.org/download/ and re-run sync." in out


def test_resolve_macos_official_asset_returns_pinned_urls() -> None:
    expected_assets = {
        "retroarch": MacOSOfficialAsset(
            emulator="retroarch",
            archive_kind="dmg",
            bundle_name="RetroArch.app",
            download_url="https://buildbot.libretro.com/stable/1.22.2/apple/osx/universal/RetroArch_Metal.dmg",
            source_url="https://buildbot.libretro.com/stable/1.22.2/apple/osx/universal/RetroArch_Metal.dmg",
            asset_label="universal",
        ),
        "dolphin": MacOSOfficialAsset(
            emulator="dolphin",
            archive_kind="dmg",
            bundle_name="Dolphin.app",
            download_url="https://dl.dolphin-emu.org/releases/2512/dolphin-2512-universal.dmg",
            source_url="https://dl.dolphin-emu.org/releases/2512/dolphin-2512-universal.dmg",
            asset_label="universal",
        ),
        "azahar": MacOSOfficialAsset(
            emulator="azahar",
            archive_kind="zip",
            bundle_name="Azahar.app",
            download_url="https://github.com/azahar-emu/azahar/releases/download/2124.3/azahar-2124.3-macos-universal.zip",
            source_url="https://github.com/azahar-emu/azahar/releases/tag/2124.3",
            asset_label="universal",
        ),
        "pcsx2": MacOSOfficialAsset(
            emulator="pcsx2",
            archive_kind="tar_xz",
            bundle_name="PCSX2.app",
            download_url="https://github.com/PCSX2/pcsx2/releases/download/v2.6.3/pcsx2-v2.6.3-macos-Qt.tar.xz",
            source_url="https://github.com/PCSX2/pcsx2/releases/download/v2.6.3/pcsx2-v2.6.3-macos-Qt.tar.xz",
            asset_label="archive",
        ),
    }

    for emulator, expected in expected_assets.items():
        asset, reason = install_macos_module._resolve_macos_official_asset(emulator)
        assert reason is None
        assert asset == expected


def test_install_macos_official_asset_supports_tar_xz_archive(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-macos-tar-asset-") as temp_root:
        source_bundle = temp_root / "PCSX2.app"
        installed_bundle = temp_root / "Applications" / "PCSX2.app"
        captured: dict[str, Path] = {}

        def fake_extract(
            archive_path: Path,
            expected_bundle: str,
            *,
            temp_root: Path,
            verbose: bool,
        ) -> Path:
            del temp_root, verbose
            captured["archive_path"] = archive_path
            assert expected_bundle == "PCSX2.app"
            return source_bundle

        monkeypatch.setattr(
            "gamehub_cli.emulators.install_macos._download_file",
            lambda url, destination, timeout_seconds=120.0: destination.write_bytes(b"tar") or True,
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.install_macos._extract_app_bundle_from_tar_archive",
            fake_extract,
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.install_macos._bundle_supports_apple_silicon",
            lambda bundle_path: (bundle_path == source_bundle, None),
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.install_macos._install_bundle_into_applications",
            lambda source_bundle, bundle_name, verbose: installed_bundle,
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.install_macos.resolve_macos_app_bundle_executable",
            lambda bundle_path: bundle_path / "Contents" / "MacOS" / "pcsx2-qt",
        )

        status, detail = install_macos_module._install_macos_official_asset(
            MacOSOfficialAsset(
                emulator="pcsx2",
                archive_kind="tar_xz",
                bundle_name="PCSX2.app",
                download_url="https://github.com/PCSX2/pcsx2/releases/download/v2.6.3/pcsx2-v2.6.3-macos-Qt.tar.xz",
                source_url="https://github.com/PCSX2/pcsx2/releases/download/v2.6.3/pcsx2-v2.6.3-macos-Qt.tar.xz",
                asset_label="archive",
            ),
            verbose=False,
        )

        assert status == "installed"
        assert detail is None
        assert captured["archive_path"].name == "pcsx2-v2.6.3-macos-Qt.tar.xz"


def test_install_macos_official_asset_accepts_universal_label_when_probe_is_inconclusive(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-macos-dmg-asset-") as temp_root:
        source_bundle = temp_root / "Dolphin.app"
        installed_bundle = temp_root / "Applications" / "Dolphin.app"

        monkeypatch.setattr(
            "gamehub_cli.emulators.install_macos._download_file",
            lambda url, destination, timeout_seconds=120.0: destination.write_bytes(b"dmg") or True,
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.install_macos._extract_app_bundle_from_dmg",
            lambda archive_path, expected_bundle, temp_root, verbose: source_bundle,
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.install_macos._bundle_supports_apple_silicon",
            lambda bundle_path: (
                False,
                "could not verify app bundle architecture from upstream asset",
            ),
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.install_macos._install_bundle_into_applications",
            lambda source_bundle, bundle_name, verbose: installed_bundle,
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.install_macos.resolve_macos_app_bundle_executable",
            lambda bundle_path: bundle_path / "Contents" / "MacOS" / "Dolphin",
        )

        status, detail = install_macos_module._install_macos_official_asset(
            MacOSOfficialAsset(
                emulator="dolphin",
                archive_kind="dmg",
                bundle_name="Dolphin.app",
                download_url="https://dl.dolphin-emu.org/releases/2512/dolphin-2512-universal.dmg",
                source_url="https://dl.dolphin-emu.org/releases/2512/dolphin-2512-universal.dmg",
                asset_label="universal",
            ),
            verbose=False,
        )

        assert status == "installed"
        assert detail is None


def test_extract_app_bundle_from_dmg_stages_bundle_before_detach(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-macos-dmg-stage-") as temp_root:
        commands: list[list[str]] = []
        copied: list[tuple[Path, Path]] = []

        class FakeCompleted:
            def __init__(self, returncode: int = 0) -> None:
                self.returncode = returncode
                self.stdout = ""
                self.stderr = ""

        def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
            del check, capture_output, text
            commands.append(cmd)
            return FakeCompleted(0)

        def fake_copy(source_bundle: Path, destination_bundle: Path, *, verbose: bool) -> bool:
            del verbose
            copied.append((source_bundle, destination_bundle))
            destination_bundle.mkdir(parents=True, exist_ok=True)
            return True

        monkeypatch.setattr("gamehub_cli.emulators.install_macos.subprocess.run", fake_run)
        monkeypatch.setattr(
            "gamehub_cli.emulators.install_macos._find_app_bundle",
            lambda root, expected_bundle: root / expected_bundle,
        )
        monkeypatch.setattr("gamehub_cli.emulators.install_macos._copy_app_bundle", fake_copy)

        staged = install_macos_module._extract_app_bundle_from_dmg(
            temp_root / "Dolphin.dmg",
            "Dolphin.app",
            temp_root=temp_root,
            verbose=False,
        )

        assert staged == temp_root / "extract" / "Dolphin.app"
        assert copied == [
            (
                temp_root / "mount" / "Dolphin.app",
                temp_root / "extract" / "Dolphin.app",
            )
        ]
        assert commands[0][:2] == ["hdiutil", "attach"]
        assert commands[1][:2] == ["hdiutil", "detach"]


def test_ensure_emulators_detects_known_install_without_winget(monkeypatch, capsys, workspace_tempdir) -> None:
    index = _index_with_emulators("retroarch")
    with workspace_tempdir("gamehub-emulator-detect-") as temp_root:
        exe = temp_root / "retroarch.exe"
        exe.write_bytes(b"exe")
        monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", lambda name: None)
        monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: (exe,))

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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)
    monkeypatch.setattr(
        "gamehub_cli.emulators.installer._install_dolphin_from_official_release_archive",
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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "win32")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.installer._install_azahar_from_windows_installer",
        fake_azahar_install,
    )

    ensure_emulators(index=index, dry_run=False, verbose=False)

    out = capsys.readouterr().out
    assert "Installing emulator 'azahar' via GitHub release installer..." in out
    assert "Installed emulator: azahar" in out


def test_ensure_emulators_windows_azahar_installer_failure_warns_manual_fallback(monkeypatch, capsys) -> None:
    index = _index_with_emulators("azahar")

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "win32")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", lambda name: None)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.installer._install_azahar_from_windows_installer",
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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.installer._SYS_PLATFORM", "win32")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.installer._download_azahar_windows_installer",
        lambda url: Path("C:/Temp/azahar-2124.3-windows-msys2-installer.exe"),
    )
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)

    ensure_emulators(index=index, dry_run=False, verbose=False)

    out = capsys.readouterr().out
    assert "Azahar installer requires administrator elevation" in out
    assert "Installed emulator: azahar" in out
    assert any(command and "powershell" in command[0].lower() for command in commands)


def test_ensure_emulators_windows_dolphin_archive_failure_warns(monkeypatch, capsys) -> None:
    index = _index_with_emulators("dolphin")

    def fake_which(name: str) -> str | None:
        return None

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr(
        "gamehub_cli.emulators.installer._install_dolphin_from_official_release_archive",
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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.installer.subprocess.run", fake_run)
    monkeypatch.setattr(
        "gamehub_cli.emulators.installer._install_dolphin_from_official_release_archive",
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

    monkeypatch.setattr("gamehub_cli.emulators.installer._OS_NAME", "nt")
    monkeypatch.setattr("gamehub_cli.emulators.installer.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())

    with pytest.raises(RuntimeError, match="Unsupported legacy Dolphin build detected"):
        ensure_emulators(index=index, dry_run=False, verbose=False)


def test_resolve_emulator_executable_prefers_shutil_which(monkeypatch) -> None:
    monkeypatch.setattr("gamehub_cli.emulators.resolution.shutil.which", lambda cmd: "C:\\Emulators\\retroarch.exe")
    monkeypatch.setattr("gamehub_cli.emulators.resolution._known_install_candidates", lambda value: ())
    resolved = resolve_emulator_executable("retroarch")
    assert resolved == "C:\\Emulators\\retroarch.exe"


def test_resolve_emulator_executable_falls_back_to_known_paths(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-emulator-resolve-") as temp_root:
        candidate = temp_root / "Programs" / "RetroArch" / "retroarch.exe"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"exe")
        monkeypatch.setattr("gamehub_cli.emulators.resolution._OS_NAME", "nt")
        monkeypatch.setenv("LOCALAPPDATA", str(temp_root))
        monkeypatch.delenv("ProgramFiles", raising=False)
        monkeypatch.setattr("gamehub_cli.emulators.resolution.shutil.which", lambda cmd: None)

        resolved = resolve_emulator_executable("retroarch")

        assert resolved == str(candidate)


def test_resolve_emulator_executable_falls_back_to_known_azahar_paths(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-emulator-resolve-") as temp_root:
        candidate = temp_root / "Programs" / "Azahar" / "azahar.exe"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"exe")
        monkeypatch.setattr("gamehub_cli.emulators.resolution._OS_NAME", "nt")
        monkeypatch.setenv("LOCALAPPDATA", str(temp_root))
        monkeypatch.delenv("ProgramFiles", raising=False)
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        monkeypatch.setattr("gamehub_cli.emulators.resolution.shutil.which", lambda cmd: None)

        resolved = resolve_emulator_executable("azahar")

        assert resolved == str(candidate)


def test_resolve_emulator_executable_macos_prefers_user_applications_bundle(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-emulator-resolve-macos-") as temp_root:
        home = temp_root / "home"
        user_executable = _write_macos_app_bundle(
            home / "Applications" / "RetroArch.app",
            "retroarch-metal",
        )
        _write_macos_app_bundle(
            temp_root / "Applications" / "RetroArch.app",
            "retroarch-system",
        )

        monkeypatch.setattr("gamehub_cli.emulators.resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.resolution._SYS_PLATFORM", "darwin")
        monkeypatch.setattr("gamehub_cli.emulators.resolution.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr(
            "gamehub_cli.emulators.resolution.shutil.which",
            lambda cmd: "/opt/homebrew/bin/retroarch",
        )
        monkeypatch.setattr(
            "gamehub_cli.common.platform_paths.macos_system_applications_dir",
            lambda: temp_root / "Applications",
        )

        resolved = resolve_emulator_executable("retroarch")

        assert resolved == str(user_executable)


def test_resolve_emulator_executable_macos_falls_back_to_system_applications_bundle(
    monkeypatch,
    workspace_tempdir,
) -> None:
    with workspace_tempdir("gamehub-emulator-resolve-macos-") as temp_root:
        home = temp_root / "home"
        system_executable = _write_macos_app_bundle(
            temp_root / "Applications" / "Dolphin.app",
            "DolphinQt",
        )

        monkeypatch.setattr("gamehub_cli.emulators.resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.resolution._SYS_PLATFORM", "darwin")
        monkeypatch.setattr("gamehub_cli.emulators.resolution.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr(
            "gamehub_cli.emulators.resolution.shutil.which",
            lambda cmd: "/opt/homebrew/bin/dolphin",
        )
        monkeypatch.setattr(
            "gamehub_cli.common.platform_paths.macos_system_applications_dir",
            lambda: temp_root / "Applications",
        )

        resolved = resolve_emulator_executable("dolphin")

        assert resolved == str(system_executable)


def test_resolve_emulator_executable_prefers_known_path_over_windowsapps_alias(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-emulator-resolve-") as temp_root:
        candidate = temp_root / "Programs" / "RetroArch" / "retroarch.exe"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"exe")
        monkeypatch.setattr("gamehub_cli.emulators.resolution._OS_NAME", "nt")
        monkeypatch.setenv("LOCALAPPDATA", str(temp_root))
        monkeypatch.delenv("ProgramFiles", raising=False)
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        monkeypatch.setattr(
            "gamehub_cli.emulators.resolution.shutil.which",
            lambda cmd: "C:\\Users\\evanp\\AppData\\Local\\Microsoft\\WindowsApps\\retroarch.exe",
        )

        resolved = resolve_emulator_executable("retroarch")

        assert resolved == str(candidate)


def test_resolve_emulator_executable_linux_uses_matching_flatpak_export(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-emulator-linux-flatpak-") as temp_root:
        export_dir = temp_root / ".local" / "share" / "flatpak" / "exports" / "bin"
        export_dir.mkdir(parents=True, exist_ok=True)
        retroarch_export = export_dir / "org.libretro.RetroArch"
        pcsx2_export = export_dir / "net.pcsx2.PCSX2"
        retroarch_export.write_bytes(b"exe")
        pcsx2_export.write_bytes(b"exe")

        monkeypatch.setattr("gamehub_cli.emulators.resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.resolution._SYS_PLATFORM", "linux")
        monkeypatch.setattr("gamehub_cli.emulators.resolution.Path.home", lambda: temp_root)
        monkeypatch.setattr("gamehub_cli.emulators.resolution.shutil.which", lambda cmd: None)

        resolved = resolve_emulator_executable("pcsx2")

        assert resolved == str(pcsx2_export)


def test_resolve_emulator_executable_linux_uses_azahar_flatpak_export(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-emulator-linux-flatpak-") as temp_root:
        export_dir = temp_root / ".local" / "share" / "flatpak" / "exports" / "bin"
        export_dir.mkdir(parents=True, exist_ok=True)
        azahar_export = export_dir / "org.azahar_emu.Azahar"
        azahar_export.write_bytes(b"exe")

        monkeypatch.setattr("gamehub_cli.emulators.resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.resolution._SYS_PLATFORM", "linux")
        monkeypatch.setattr("gamehub_cli.emulators.resolution.Path.home", lambda: temp_root)
        monkeypatch.setattr("gamehub_cli.emulators.resolution.shutil.which", lambda cmd: None)

        resolved = resolve_emulator_executable("azahar")

        assert resolved == str(azahar_export)


def test_default_emulator_for_system_returns_expected_values() -> None:
    assert default_emulator_for_system("PS2") == "pcsx2"
    assert default_emulator_for_system("wii") == "dolphin"
    assert default_emulator_for_system("UNKNOWN") is None


def test_resolve_emulator_save_root_windows_pcsx2_memcards(monkeypatch) -> None:
    with TemporaryDirectory(prefix="gamehub-save-root-") as temp_dir:
        temp_root = Path(temp_dir)
        memcards = temp_root / "Documents" / "PCSX2" / "memcards"
        memcards.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "nt")
        monkeypatch.setenv("USERPROFILE", str(temp_root))

        resolved = resolve_emulator_save_root("pcsx2", resolve_executable=lambda _name: "")

        assert resolved == memcards


def test_resolve_emulator_save_root_windows_pcsx2_memcards_from_ini(monkeypatch) -> None:
    with TemporaryDirectory(prefix="gamehub-save-root-") as temp_dir:
        temp_root = Path(temp_dir)
        appdata_root = temp_root / "AppData" / "Roaming"
        ini_path = appdata_root / "PCSX2" / "inis" / "PCSX2.ini"
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text("Folders.MemoryCards = profile_memcards\n", encoding="utf-8")
        memcards = appdata_root / "PCSX2" / "profile_memcards"
        memcards.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "nt")
        monkeypatch.setenv("APPDATA", str(appdata_root))
        monkeypatch.delenv("USERPROFILE", raising=False)

        resolved = resolve_emulator_save_root("pcsx2", resolve_executable=lambda _name: "")

        assert resolved == memcards


def test_resolve_emulator_save_root_windows_pcsx2_memcards_fallbacks_to_appdata(monkeypatch) -> None:
    with TemporaryDirectory(prefix="gamehub-save-root-") as temp_dir:
        temp_root = Path(temp_dir)
        appdata_root = temp_root / "AppData" / "Roaming"
        memcards = appdata_root / "PCSX2" / "memcards"
        memcards.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "nt")
        monkeypatch.setenv("APPDATA", str(appdata_root))
        monkeypatch.delenv("USERPROFILE", raising=False)

        resolved = resolve_emulator_save_root("pcsx2", resolve_executable=lambda _name: "")

        assert resolved == memcards


def test_resolve_system_save_root_windows_prefers_portable_dolphin_user_gc(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-root-") as temp_root:
        dolphin_root = temp_root / "Programs" / "Dolphin"
        dolphin_root.mkdir(parents=True, exist_ok=True)
        exe = dolphin_root / "Dolphin.exe"
        exe.write_bytes(b"exe")
        portable_gc = dolphin_root / "User" / "GC"
        portable_gc.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "nt")
        monkeypatch.setenv("LOCALAPPDATA", str(temp_root))
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.delenv("USERPROFILE", raising=False)

        resolved = resolve_system_save_root("GC", resolve_executable=lambda _name: str(exe))

        assert resolved == portable_gc


def test_resolve_emulator_save_root_windows_retroarch_drive_relative_save_dir(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-root-") as temp_root:
        exe = temp_root / "retroarch.exe"
        exe.write_bytes(b"exe")
        cfg = temp_root / "retroarch.cfg"
        cfg.write_text('savefile_directory = ":\\\\saves"\n', encoding="utf-8")
        saves = temp_root / "saves"
        saves.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "nt")
        monkeypatch.delenv("APPDATA", raising=False)

        resolved = resolve_emulator_save_root("retroarch", resolve_executable=lambda _name: str(exe))

        assert resolved == saves


def test_resolve_emulator_save_root_returns_none_when_runtime_path_missing(monkeypatch) -> None:
    with TemporaryDirectory(prefix="gamehub-save-root-") as temp_dir:
        temp_root = Path(temp_dir)
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "nt")
        monkeypatch.setenv("USERPROFILE", str(temp_root))
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)

        resolved = resolve_emulator_save_root("dolphin", resolve_executable=lambda _name: "")

        assert resolved is None


def test_resolve_emulator_save_root_linux_flatpak_retroarch(monkeypatch) -> None:
    with TemporaryDirectory(prefix="gamehub-save-root-") as temp_dir:
        temp_root = Path(temp_dir)
        saves = temp_root / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "saves"
        saves.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: temp_root)
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: temp_root))
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "linux")

        resolved = resolve_emulator_save_root(
            "retroarch",
            resolve_executable=lambda _name: str(
                temp_root / ".local" / "share" / "flatpak" / "exports" / "bin" / "org.libretro.RetroArch"
            ),
        )

        assert resolved == saves


def test_resolve_system_save_root_macos_retroarch(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-root-macos-") as temp_root:
        home = temp_root / "home"
        saves = home / "Documents" / "RetroArch" / "saves"
        saves.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "darwin")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: home)
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))

        resolved = resolve_system_save_root("GBC", resolve_executable=lambda _name: "")

        assert resolved == saves


def test_resolve_system_save_root_macos_pcsx2(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-root-macos-") as temp_root:
        home = temp_root / "home"
        memcards = home / "Library" / "Application Support" / "PCSX2" / "memcards"
        memcards.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "darwin")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: home)
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))

        resolved = resolve_system_save_root("PS2", resolve_executable=lambda _name: "")

        assert resolved == memcards


def test_resolve_system_save_root_macos_dolphin(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-root-macos-") as temp_root:
        home = temp_root / "home"
        gc_root = home / "Library" / "Application Support" / "Dolphin" / "GC"
        gc_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "darwin")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: home)
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))

        resolved = resolve_system_save_root("GC", resolve_executable=lambda _name: "")

        assert resolved == gc_root


def test_resolve_system_save_root_macos_azahar(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-root-macos-") as temp_root:
        home = temp_root / "home"
        sdmc_root = home / "Library" / "Application Support" / "Azahar" / "sdmc"
        sdmc_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "darwin")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: home)
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))

        resolved = resolve_system_save_root("N3DS", resolve_executable=lambda _name: "")

        assert resolved == sdmc_root


def test_resolve_emulator_save_root_macos_retroarch_prefers_configured_cfg_path(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-root-macos-") as temp_root:
        home = temp_root / "home"
        retroarch_root = temp_root / "custom-retroarch"
        saves = retroarch_root / "portable-saves"
        saves.mkdir(parents=True, exist_ok=True)
        cfg_path = retroarch_root / "retroarch.cfg"
        cfg_path.write_text('savefile_directory = "portable-saves"\n', encoding="utf-8")
        config_path = temp_root / "config.toml"
        config_path.write_text(f'[macos]\nretroarch_cfg_path = "{cfg_path}"\n', encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "darwin")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: home)
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))

        def resolver(_name: str) -> str:
            return "/Applications/RetroArch.app/Contents/MacOS/RetroArch"

        setattr(resolver, "_gamehub_config", load_config(config_path))

        resolved = resolve_emulator_save_root("retroarch", resolve_executable=resolver)

        assert resolved == saves


def test_resolve_system_save_root_macos_dolphin_prefers_configured_user_path(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-root-macos-") as temp_root:
        home = temp_root / "home"
        dolphin_root = temp_root / "custom-dolphin"
        gc_root = dolphin_root / "GC"
        gc_root.mkdir(parents=True, exist_ok=True)
        config_path = temp_root / "config.toml"
        config_path.write_text(f'[macos]\ndolphin_user_path = "{dolphin_root}"\n', encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "darwin")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: home)
        monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))

        def resolver(_name: str) -> str:
            return "/Applications/Dolphin.app/Contents/MacOS/Dolphin"

        setattr(resolver, "_gamehub_config", load_config(config_path))

        resolved = resolve_system_save_root("GC", resolve_executable=resolver)

        assert resolved == gc_root


def test_discover_local_exact_save_candidates_finds_sorted_retroarch_subdir(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-root-") as temp_root:
        exe = temp_root / "retroarch.exe"
        exe.write_bytes(b"exe")
        cfg = temp_root / "retroarch.cfg"
        cfg.write_text(
            'savefile_directory = ":\\\\saves"\n'
            'sort_savefiles_enable = "true"\n'
            'sort_savefiles_by_content_enable = "false"\n',
            encoding="utf-8",
        )
        save_path = temp_root / "saves" / "Gambatte" / "Pokemon.srm"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(b"save")

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "nt")
        monkeypatch.delenv("APPDATA", raising=False)

        candidates = discover_local_exact_save_candidates(
            (
                SaveBindingSpec(
                    binding_id="savebind_gb",
                    title_id="title_gb",
                    system="GB",
                    kind="battery",
                    server_rel_dir="saves/GB/Pokemon/battery",
                    local_root="retroarch_saves",
                    strategy="exact_files",
                    candidate_filenames=("Pokemon.srm",),
                    learn_rule=None,
                    portable=True,
                ),
            ),
            resolve_executable=lambda _name: str(exe),
        )

        assert len(candidates) == 1
        assert candidates[0].path == save_path


def test_resolve_exact_local_save_destination_prefers_existing_sorted_retroarch_subdir(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-save-root-") as temp_root:
        exe = temp_root / "retroarch.exe"
        exe.write_bytes(b"exe")
        cfg = temp_root / "retroarch.cfg"
        cfg.write_text(
            'savefile_directory = ":\\\\saves"\n'
            'sort_savefiles_enable = "true"\n'
            'sort_savefiles_by_content_enable = "false"\n',
            encoding="utf-8",
        )
        save_root = temp_root / "saves"
        save_path = save_root / "Gambatte" / "Pokemon.srm"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(b"save")

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "nt")
        monkeypatch.delenv("APPDATA", raising=False)

        resolved = resolve_exact_local_save_destination(
            system="GB",
            kind="battery",
            root=save_root,
            filename="Pokemon.srm",
            resolve_executable=lambda _name: str(exe),
        )

        assert resolved == save_path


def test_resolve_exact_local_save_destination_prefers_flatpak_runtime_cfg_on_linux(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-save-root-") as temp_root:
        home = temp_root / "home"
        native_cfg = home / ".config" / "retroarch" / "retroarch.cfg"
        flatpak_cfg = home / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "retroarch.cfg"
        native_cfg.parent.mkdir(parents=True, exist_ok=True)
        flatpak_cfg.parent.mkdir(parents=True, exist_ok=True)
        native_cfg.write_text(
            'sort_savefiles_enable = "false"\n',
            encoding="utf-8",
        )
        flatpak_cfg.write_text(
            'sort_savefiles_enable = "true"\nsort_savefiles_by_content_enable = "false"\n',
            encoding="utf-8",
        )
        save_root = temp_root / "saves"

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "linux")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: home)

        resolved = resolve_exact_local_save_destination(
            system="PSX",
            kind="memory_card",
            root=save_root,
            filename="GH_title_test_1.mcd",
            resolve_executable=lambda _name: str(
                home / ".local" / "share" / "flatpak" / "exports" / "bin" / "org.libretro.RetroArch"
            ),
        )

        assert resolved == save_root / "SwanStation" / "GH_title_test_1.mcd"


def test_resolve_exact_local_save_destination_finds_psx_card_in_system_dir_on_windows(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-save-root-") as temp_root:
        exe = temp_root / "retroarch.exe"
        exe.write_bytes(b"exe")
        cfg = temp_root / "retroarch.cfg"
        cfg.write_text(
            'savefile_directory = ":\\\\saves"\n'
            'system_directory = ":\\\\system"\n'
            'sort_savefiles_enable = "true"\n'
            'sort_savefiles_by_content_enable = "false"\n',
            encoding="utf-8",
        )
        save_root = temp_root / "saves"
        save_root.mkdir(parents=True, exist_ok=True)
        system_card = temp_root / "system" / "SwanStation" / "GH_title_psx_ctr_1.mcd"
        system_card.parent.mkdir(parents=True, exist_ok=True)
        system_card.write_bytes(b"memcard")

        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "nt")
        monkeypatch.delenv("APPDATA", raising=False)

        resolved = resolve_exact_local_save_destination(
            system="PSX",
            kind="memory_card",
            root=save_root,
            filename="GH_title_psx_ctr_1.mcd",
            resolve_executable=lambda _name: str(exe),
        )

        assert resolved == system_card


def test_learned_tree_discovers_single_dolphin_gc_root() -> None:
    binding = SaveBindingSpec(
        binding_id="savebind_gc",
        title_id="title_gc",
        system="GC",
        kind="per_game",
        server_rel_dir="saves/GC/WindWaker/per_game",
        local_root="dolphin_gc",
        strategy="learned_tree",
        candidate_filenames=(),
        learn_rule="dolphin_gc_gci_tree",
        portable=False,
    )

    learned = learn_binding_root(
        binding,
        (
            "USA/Card A/01-GZLE-gczelda.gci",
            "USA/Card A/01-GZLE-banner.gci",
        ),
    )

    assert learned == ("USA/Card A", "USA/Card A")


def test_canonical_suffix_for_dolphin_gc_learned_path() -> None:
    binding = SaveBindingSpec(
        binding_id="savebind_gc",
        title_id="title_gc",
        system="GC",
        kind="per_game",
        server_rel_dir="saves/GC/WindWaker/per_game",
        local_root="dolphin_gc",
        strategy="learned_tree",
        candidate_filenames=(),
        learn_rule="dolphin_gc_gci_tree",
        portable=False,
    )

    suffix = canonical_suffix_for_learned_path(
        binding,
        "USA/Card A/01-GZLE-gczelda.gci",
        materialized_root="USA/Card A",
    )

    assert suffix == "USA/Card A/01-GZLE-gczelda.gci"


def test_snapshot_binding_tree_ignores_global_dolphin_gc_files(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-root-") as temp_root:
        (temp_root / "SRAM.raw").write_bytes(b"sram")
        save_path = temp_root / "USA" / "Card A" / "01-GP5E-MARIPA5.gci"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(b"gci")
        binding = SaveBindingSpec(
            binding_id="savebind_gc",
            title_id="title_gc",
            system="GC",
            kind="per_game",
            server_rel_dir="saves/GC/MarioParty5/per_game",
            local_root="dolphin_gc",
            strategy="learned_tree",
            candidate_filenames=(),
            learn_rule="dolphin_gc_gci_tree",
            portable=False,
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.save_resolution.resolve_binding_local_root",
            lambda *_args, **_kwargs: temp_root,
        )

        snapshot = snapshot_binding_tree(binding)

        assert tuple(snapshot) == ("USA/Card A/01-GP5E-MARIPA5.gci",)


def test_resolve_system_save_root_uses_default_emulator(monkeypatch) -> None:
    with TemporaryDirectory(prefix="gamehub-save-root-") as temp_dir:
        temp_root = Path(temp_dir)
        gc_root = temp_root / ".local" / "share" / "dolphin-emu" / "GC"
        gc_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "linux")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: temp_root)

        resolved = resolve_system_save_root("GC", resolve_executable=lambda _name: "")

        assert resolved == gc_root


def test_resolve_system_save_root_uses_wii_directory_for_wii(monkeypatch) -> None:
    with TemporaryDirectory(prefix="gamehub-save-root-") as temp_dir:
        temp_root = Path(temp_dir)
        wii_root = temp_root / ".local" / "share" / "dolphin-emu" / "Wii"
        wii_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "linux")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: temp_root)

        resolved = resolve_system_save_root("Wii", resolve_executable=lambda _name: "")

        assert resolved == wii_root


def test_resolve_system_save_root_uses_azahar_for_n3ds(monkeypatch) -> None:
    with TemporaryDirectory(prefix="gamehub-save-root-") as temp_dir:
        temp_root = Path(temp_dir)
        sdmc_root = temp_root / ".local" / "share" / "azahar-emu" / "sdmc"
        sdmc_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._OS_NAME", "posix")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution._SYS_PLATFORM", "linux")
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.Path.home", lambda: temp_root)

        resolved = resolve_system_save_root("N3DS", resolve_executable=lambda _name: "")

        assert resolved == sdmc_root
