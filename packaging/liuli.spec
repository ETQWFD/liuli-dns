# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for the Windows desktop client.

Build on Windows with:
    .venv\\Scripts\\python -m PyInstaller --noconfirm --clean packaging\\liuli.spec

The resulting payload is dist\\LiuliDNS\\LiuliDNS.exe.  No secret, token,
private key or API credential is embedded in the executable or the QML payload.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
APP_ICON = ROOT / "client" / "resources" / "app-icon.ico"

datas = [
    (str(ROOT / "client" / "app" / "qml"), "client/app/qml"),
    (str(ROOT / "client" / "resources"), "client/resources"),
]

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    "PySide6.QtWidgets",
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.macOS",
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LiuliDNS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(APP_ICON),
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LiuliDNS",
)
