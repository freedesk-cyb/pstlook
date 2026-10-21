# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

datas = [("assets/pstlook.ico", "assets")]
binaries = []
hiddenimports = ["pypff"]

for paquete in ("PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"):
    datos_paquete, binarios_paquete, ocultos_paquete = collect_all(paquete)
    datas += datos_paquete
    binaries += binarios_paquete
    hiddenimports += ocultos_paquete

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PSTReader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/pstlook.ico"],
    version="packaging/version_info.txt",
)
