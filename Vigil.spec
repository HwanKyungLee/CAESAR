# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['vigil/run_vigil.py'],
    pathex=['.'],
    binaries=[],
    datas=[('vigil/profiles/_schema.json', 'vigil/profiles'), ('vigil/profiles/caesar_cold.example.json', 'vigil/profiles'), ('vigil/profiles/caesar_cold_6174.example.json', 'vigil/profiles'), ('vigil/profiles/caesar_hot.example.json', 'vigil/profiles'), ('tools/channel_map.json', 'tools')],
    hiddenimports=['tools.optimize_params'],
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
    name='Vigil',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    name='Vigil',
)
