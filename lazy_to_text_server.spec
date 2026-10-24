# PyInstaller spec -- the headless runtime behind the Electron interface.
#
# Build through the wrapper, which also does what a spec cannot (patched
# PortAudio on macOS, a smoke run of the result):
#     uv run --frozen --with "pyinstaller>=6.0" python scripts/build_server.py
# or directly:
#     uv run --frozen --with "pyinstaller>=6.0" pyinstaller lazy_to_text_server.spec
#
# Output is dist/lazy-to-text-server/ on every platform: a folder bundle
# whose executable is ``lazy-to-text-server`` (``.exe`` on Windows).
# electron-builder copies that folder to ``resources/backend``, which is
# where desktop/electron/backend.cjs looks for it.
#
# This is a separate spec from lazy_to_text.spec on purpose. That one ships
# the Qt application and keeps its own tray, window and style data; this one
# is the same domain stack with no front end, and the whole point of it is
# what it leaves out. PySide6 is in ``excludes`` so that a Qt import which
# creeps back into the runtime fails the build's smoke run instead of
# quietly adding a few hundred megabytes. tests/test_desktop_packaging.py
# holds both facts.

import importlib.util
import os
import sys
from pathlib import Path

try:
    spec_file_path = Path(__file__).resolve()  # type: ignore[name-defined]
except NameError:
    cwd = Path.cwd()
    candidate = cwd / "lazy_to_text_server.spec"
    spec_file_path = candidate if candidate.exists() else cwd

project_root = spec_file_path.parent
app_dir = project_root / "app"

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

# ---- data ------------------------------------------------------------------
#
# Only what the runtime reads: the sounds the recording cues play and the
# tray icons. The Qt style sheets and the Qt translation catalogues are not
# shipped, because nothing in the runtime opens them. The destination keeps
# the ``app/assets`` prefix so ``resolve_asset_path`` (which walks from
# ``app/utils.py``) finds them in the frozen layout.
datas = []
for p in (app_dir / "assets").rglob("*"):
    if p.is_file():
        datas.append((str(p), str(p.relative_to(project_root).parent)))

# onnx_asr reads its own version through importlib.metadata at import and
# dies without its .dist-info; PyInstaller does not collect those.
for dist_name in ("onnx-asr", "imageio-ffmpeg"):
    try:
        datas += copy_metadata(dist_name)
    except Exception as exc:
        print(f"[spec] no metadata for {dist_name}: {exc!r}")

# onnx_asr loads small ONNX graphs from ``preprocessors/data`` by path, so
# they are data, not imports.
for sp in sys.path:
    pkg = Path(sp) / "onnx_asr"
    if not pkg.is_dir():
        continue
    for f in pkg.rglob("*"):
        if (f.is_file() and f.suffix not in (".py", ".pyc")
                and "__pycache__" not in f.parts):
            datas.append((str(f), str(f.relative_to(sp).parent)))
    break

# ---- imports the analyser cannot see ---------------------------------------
#
# The RPC registry imports ``app.server.handlers.*`` with pkgutil, so no
# import statement names them.
hiddenimports = collect_submodules("app.server.handlers")

for pkg in ("onnx_asr", "onnxruntime"):
    if importlib.util.find_spec(pkg) is not None:
        try:
            hiddenimports += collect_submodules(pkg)
        except Exception as exc:
            print(f"[spec] collect_submodules({pkg!r}) failed: {exc!r}")

# Platform modules that are loaded late or only on one OS. A name that is
# not installed here is skipped, the same rule lazy_to_text.spec follows.
for name in (
    "win32timezone",   # pywin32 helper, imported by string
    "global_hotkeys",  # Windows hotkey listener
    "win32api",
    "win32con",
):
    if importlib.util.find_spec(name) is not None:
        hiddenimports.append(name)

# ---- what must not be here -------------------------------------------------
excludes = [
    "PySide6", "shiboken6", "PyQt5", "PyQt6",
    "tkinter", "_tkinter",
    "tests", "pytest", "pytest_qt", "xdist",
    "pyinstaller", "py2app", "setuptools",
]

runtime_hooks = []
_hook = project_root / "scripts" / "pyi_runtime_hook.py"
if _hook.is_file():
    runtime_hooks.append(str(_hook))

analysis = Analysis(
    [str(app_dir / "server" / "__main__.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=excludes,
    # Source is kept beside the bytecode for the same reason the Qt bundle
    # keeps it: onnx_asr and huggingface_hub call ``inspect.getsource`` on
    # a few helpers, and a zipped archive answers with nothing.
    noarchive=True,
)

pyz = PYZ(analysis.pure, analysis.zipped_data)

# Console on every platform. The parent reads the ready line from stdout,
# and on Windows ``console=False`` replaces stdout with nothing. Electron
# starts the child with ``windowsHide``, so no console window appears.
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="lazy-to-text-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=False,
    name="lazy-to-text-server",
)
