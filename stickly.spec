# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH)

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "assets" / "stickly-logo.jpg"), "assets"),
        (str(root / "assets" / "stickly-logo.ico"), "assets"),
        (str(root / "app" / "ui" / "styles.qss"), "app/ui"),
        (str(root / "app" / "ui" / "web"), "app/ui/web"),
        *collect_data_files("webview"),
    ],
    hiddenimports=[
        "PySide6.QtNetwork",
        "PySide6.QtSvg",
        "sqlite3",
        *collect_submodules("webview.platforms.edgechromium"),
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["test"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Stickly",
    icon=str(root / "assets" / "stickly-logo.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
