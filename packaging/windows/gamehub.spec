# Use with: pyinstaller --noconfirm packaging/windows/gamehub.spec

from pathlib import Path

block_cipher = None
# PyInstaller executes spec files via `exec(...)`, so `__file__` is not guaranteed.
# `SPECPATH` and `SPEC` are injected by PyInstaller in spec globals.
SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parents[1]

a = Analysis(
    [str(SPEC_DIR / "entrypoint.py")],
    pathex=[
        str(REPO_ROOT),
        str(REPO_ROOT / "src"),
    ],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="gamehub-windows-amd64",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="gamehub-windows-amd64",
)

