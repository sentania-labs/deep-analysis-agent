# PyInstaller spec for Deep Analysis Agent — Windows only.
# Produces a one-folder build (dist/deep-analysis-agent/) for Squirrel delta-update compatibility.
# Run via: uv run pyinstaller build/windows/deep-analysis-agent.spec --noconfirm
# Or via the wrapper: pwsh build/windows/build_pyinstaller.ps1

block_cipher = None

a = Analysis(
    ['../../src/deep_analysis_agent/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[('../../icons/*.png', 'icons'), ('../../icons/*.ico', 'icons')],
    hiddenimports=[
        'pystray._win32',
        'watchdog.observers.winapi',
        'httpx',
        'pydantic',
        'pydantic_settings',
        'structlog',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'ruff', 'mypy', 'pyinstaller'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DeepAnalysisAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window — tray app
    icon='../../icons/app.ico',  # Multi-size installer/app icon (built from C pip)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='deep-analysis-agent',  # Output: dist/deep-analysis-agent/
)
