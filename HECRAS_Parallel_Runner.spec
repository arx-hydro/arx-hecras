# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ['src/hecras_runner/gui.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        *collect_data_files('PyQt6', subdir='Qt6/plugins'),
        ('src/hecras_runner/resources', 'resources'),
    ],
    hiddenimports=[
        'win32com', 'win32com.client', 'pythoncom', 'pywintypes',
        'psycopg', 'psycopg.adapt', 'psycopg._encodings',
        'psycopg_pool', 'psycopg_binary',
        *collect_submodules('PyQt6'),
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'PyQt6.QtWebEngine', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets',
        'PyQt6.QtBluetooth',
        'PyQt6.Qt3DCore', 'PyQt6.Qt3DRender', 'PyQt6.Qt3DInput',
        'PyQt6.QtQuick', 'PyQt6.QtQuick3D', 'PyQt6.QtQml',
        'PyQt6.QtSensors', 'PyQt6.QtSerialPort',
        'PyQt6.QtSpatialAudio', 'PyQt6.QtRemoteObjects',
        'PyQt6.QtNfc', 'PyQt6.QtPositioning',
        'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets',
    ],
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
    name='HECRAS_Parallel_Runner',
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
    icon='src/hecras_runner/resources/arx_icon.ico',
)
