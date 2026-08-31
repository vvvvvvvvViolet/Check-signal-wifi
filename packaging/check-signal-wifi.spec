# PyInstaller build spec — produces a single self-contained executable.
#
# Run from the repository root:
#     pyinstaller packaging/check-signal-wifi.spec --noconfirm
#
# The built UI must exist first (`npm --prefix frontend run build`); the spec
# fails loudly below rather than shipping an executable that serves nothing.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - SPECPATH is injected by PyInstaller

FRONTEND_DIST = ROOT / "frontend" / "dist"
if not (FRONTEND_DIST / "index.html").is_file():
    raise SystemExit(
        "frontend/dist/index.html is missing.\n"
        "Build the UI first:  npm --prefix frontend ci && npm --prefix frontend run build"
    )

datas = [
    # Served by the app at runtime; config.FRONTEND_DIST looks for this name.
    (str(FRONTEND_DIST), "frontend_dist"),
]
# ReportLab loads its built-in fonts from package data at PDF-build time, so a
# bundle without them raises only when someone exports a report.
datas += collect_data_files("reportlab")

hiddenimports = [
    # uvicorn resolves protocol implementations by string at runtime, which a
    # frozen bundle has no way to follow. launcher.py names them explicitly, so
    # these are the ones that must actually be present.
    "uvicorn.loops.asyncio",
    "uvicorn.lifespan.on",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "h11",
    "websockets",
    "websockets.legacy",
    # SQLAlchemy picks its DBAPI by dialect name, also at runtime.
    "sqlalchemy.dialects.sqlite",
]
hiddenimports += collect_submodules("backend.app.wifi")
# pysnmp's SMI/transport layers do their own dynamic lookups internally;
# collecting the whole package is cheap next to debugging a missing-module
# error that only shows up when someone actually enables controller polling.
hiddenimports += collect_submodules("pysnmp")

a = Analysis(  # noqa: F821
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Trimmed because they are large and nothing here imports them; PyInstaller
    # otherwise pulls them in through optional branches of our dependencies.
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "pytest",
        "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CheckSignalWiFi",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # Console kept on purpose: it carries the URL, the data location, and the
    # simulated-readings warning, and closing it is how the app is stopped.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
