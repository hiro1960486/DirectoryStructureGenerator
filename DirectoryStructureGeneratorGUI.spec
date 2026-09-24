# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_submodules

hiddenimports = collect_submodules('hachoir')
openpyxl_datas, openpyxl_binaries, openpyxl_hiddenimports = collect_all('openpyxl')
hiddenimports += openpyxl_hiddenimports


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=openpyxl_binaries,
    datas=[('DirectoryStructureGenerator_AppIcon.ico', '.')] + openpyxl_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DirectoryStructureGeneratorGUI',
    icon='DirectoryStructureGenerator_AppIcon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DirectoryStructureGeneratorGUI',
)
