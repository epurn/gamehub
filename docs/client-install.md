# Client Install and Upgrade

## Linux (distro-agnostic) via pipx

### Install from GitHub Release wheel
```bash
pipx install "https://github.com/<org>/<repo>/releases/download/<tag>/gamehub-<version>-py3-none-any.whl"
```

### Upgrade
```bash
pipx upgrade gamehub
```

### Uninstall
```bash
pipx uninstall gamehub
```

### Smoke check
```bash
gamehub --help
gamehub sync --help
```

### Linux first-run config checklist
1. Set `steam.userdata_dir` in `config.toml` for deterministic profile targeting (or export `GAMEHUB_STEAM_USERDATA_DIR`).
2. Choose Linux emulator install strategy in `[linux]`:
   - `emulator_install_backend = "auto"` (default)
   - `emulator_install_backend = "flatpak"` (good default for immutable Linux hosts)
   - `emulator_install_backend = "dnf"` or `"command"` as needed
3. Optional: set `[linux]` path overrides (`retroarch_*`, `pcsx2_*`, `dolphin_user_path`) when your emulator profile paths are non-standard.
4. Run:
```bash
gamehub sync --dry-run --skip-steam --verbose
```
5. Run first non-`--skip-steam` sync from a desktop session so Steam can relaunch after config mutation.
6. If RetroArch games do not launch, set `[linux].retroarch_cfg_path` or `[linux].retroarch_cores_dir` explicitly and re-run sync.
7. If PS2 (Flatpak PCSX2) does not see BIOS/ISO on Fedora-family immutable hosts, re-run sync to rewrite PCSX2 config and Steam launch options using Flatpak-visible `/home/...` paths.

## Steam Deck notes
- Steam Deck installs may use `~/.steam/steam/userdata` or `~/.local/share/Steam/userdata`.
- Keep config explicit with `steam.userdata_dir` and optional `steam.steam_id` to avoid profile ambiguity on shared devices.
- If emulators are Flatpak-based, prefer:
```toml
[linux]
emulator_install_backend = "flatpak"
```

## Windows standalone EXE

1. Download `gamehub-windows-amd64.exe` from GitHub Releases.
2. Run from PowerShell:

```powershell
.\gamehub-windows-amd64.exe --help
.\gamehub-windows-amd64.exe sync --help
.\gamehub-windows-amd64.exe sync --config .\config.toml --dry-run --skip-steam
```

## Notes
- `--skip-steam` is recommended for first validation runs.
- For strict Steam update safety, include `--require-steam-closed`.
