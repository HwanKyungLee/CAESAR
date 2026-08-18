# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['oculus/run_oculus.py'],
    pathex=['.'],
    binaries=[],
    datas=[('oculus/profiles/_schema.json', 'oculus/profiles'), ('oculus/profiles/caesar_cold.example.json', 'oculus/profiles'), ('oculus/profiles/caesar_hot.example.json', 'oculus/profiles'), ('tools/channel_map.json', 'tools')],
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
    name='Oculus',
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
    name='Oculus',
)
