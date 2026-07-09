# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all
from kicad_parts_collectors.version import APP_VERSION

datas = [('assets/app_icon.png', 'assets'), ('assets/app_icon.ico', 'assets')]
binaries = []
hiddenimports = []
if sys.platform == 'win32':
    tcl_root = Path(sys.base_prefix) / 'tcl'
    tcl_data = tcl_root / 'tcl8.6'
    tk_data = tcl_root / 'tk8.6'
    if tcl_data.exists():
        datas.append((str(tcl_data), '_tcl_data'))
    if tk_data.exists():
        datas.append((str(tk_data), '_tk_data'))
    for support_dir in ('tcl8', 'dde1.4', 'reg1.3'):
        source = tcl_root / support_dir
        if source.exists():
            datas.append((str(source), support_dir))
for package in ('tkinterdnd2', 'ttkbootstrap', 'pystray', 'easyeda2kicad'):
    try:
        tmp_ret = collect_all(package)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception:
        pass


a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if sys.platform == 'darwin':
    exe = EXE(
        pyz,
        a.scripts,
        [],
        name='KiCadPartsCollector',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        exclude_binaries=True,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='assets/app_icon.icns' if Path('assets/app_icon.icns').exists() else None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='KiCadPartsCollector',
    )

    app = BUNDLE(
        coll,
        name='KiCadPartsCollector.app',
        icon='assets/app_icon.icns' if Path('assets/app_icon.icns').exists() else None,
        bundle_identifier='com.murse2000.KiCadPartsCollector',
        info_plist={
            'CFBundleName': 'KiCad Parts Collector',
            'CFBundleDisplayName': 'KiCad Parts Collector',
            'CFBundleShortVersionString': APP_VERSION,
            'NSPrincipalClass': 'NSApplication',
            'NSHighResolutionCapable': True,
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='KiCadPartsCollector',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='assets/app_icon.ico',
    )
