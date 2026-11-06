# Build from the source root with: python -m PyInstaller --clean smartcleaner.spec
a = Analysis(
    ["smartcleaner/gui.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="SmartCleaner",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
