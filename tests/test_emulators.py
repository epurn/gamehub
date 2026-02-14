from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4

from gamehub_cli.emulators import ensure_emulators, resolve_emulator_executable
from gamehub_common.models import LibraryIndex, SystemSpec


@contextmanager
def _workspace_tempdir(prefix: str):
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp_local"
    root.mkdir(parents=True, exist_ok=True)
    temp_dir = root / f"{prefix}{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


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

    class FakeCompleted:
        returncode = 0

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        commands.append(cmd)
        state["installed"] = True
        return FakeCompleted()

    monkeypatch.setattr("gamehub_cli.emulators.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.emulators.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.emulators._linux_dist_id", lambda: "bazzite")
    monkeypatch.setattr("gamehub_cli.emulators.shutil.which", fake_which)
    monkeypatch.setattr("gamehub_cli.emulators._known_install_candidates", lambda value: ())
    monkeypatch.setattr("gamehub_cli.emulators.subprocess.run", fake_run)

    ensure_emulators(index=index, dry_run=False, verbose=False)

    assert commands
    assert commands[0][:5] == ["flatpak", "install", "--user", "-y", "flathub"]
    assert commands[0][5] == "org.libretro.RetroArch"
    assert "Installed emulator: retroarch" in capsys.readouterr().out


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
