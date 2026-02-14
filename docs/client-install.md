# Client Install and Upgrade

## Linux (Fedora-based) via pipx

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
