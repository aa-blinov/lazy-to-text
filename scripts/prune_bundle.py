"""Drop the Qt this app never loads out of a built macOS bundle.

py2app copies the whole ``PySide6/Qt`` tree because ``_PACKAGES`` has to
name the bare ``"PySide6"`` package — naming submodules builds a bundle
that dies at launch on a missing ``PySide6.QtCore/__init__.pyc``, which
``tests/test_bundle_contents.py`` pins. So the wheel's full Qt arrives:
every module, every QML tree, every designer tool, and 589 MB of
QtWebEngineCore that a menu-bar widget application never opens a window
with.

The measured split, before this step existed:

    PySide6/Qt/lib/QtWebEngineCore.framework   589 MB
    PySide6/Qt/lib                             901 MB  in total
    PySide6/Qt/qml                              55 MB
    PySide6/Qt/plugins                          38 MB
    ... and the bundle                          1.5 GB

This runs after py2app and before codesign, so the signature covers what
is actually shipped. The keep-list below is deliberately a list of
*names the app uses*, not a denylist of names it doesn't: a Qt release
that adds a module should not change what ships by accident, and an
import added later should fail the manifest test rather than the app.

Usage:
    python scripts/prune_bundle.py "dist/Lazy to Text.app"            # prune
    python scripts/prune_bundle.py "dist/Lazy to Text.app" --dry-run  # report
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Qt frameworks the bundle keeps. Everything else under ``Qt/lib`` goes.
#
# QtCore/Gui/Widgets/Svg is what ``app/`` imports — pinned by
# ``test_bundle_contents.py`` against the real AST of the source tree,
# so this list cannot drift from the code without a test failing.
# The rest are what those four link or load on a Mac: QtNetwork for
# QtGui's TLS and image loading, QtPrintSupport and QtOpenGL because
# QtWidgets resolves them on some styles, and the small state-machine
# and XML libraries Qt pulls in through its own plugins.
KEEP_QT_FRAMEWORKS = frozenset(
    {
        "QtCore",
        "QtDBus",
        "QtGui",
        "QtNetwork",
        "QtNetworkAuth",
        "QtOpenGL",
        "QtOpenGLWidgets",
        "QtPrintSupport",
        "QtStateMachine",
        "QtSvg",
        "QtSvgWidgets",
        "QtWidgets",
        "QtXml",
    }
)

# Plugin directories that survive. ``platforms`` is handled separately:
# the wheel also ships ``minimal`` and ``offscreen``, which exist for
# headless test runs and which the bundle deliberately does not carry
# (``tests`` is in py2app's ``excludes``).
KEEP_QT_PLUGIN_DIRS = frozenset(
    {
        "generic",
        "iconengines",
        "imageformats",
        "networkinformation",
        "platforminputcontexts",
        "platforms",
        "styles",
        "tls",
    }
)

# Qt directories nothing in a widgets app reads: QML and its metatypes
# belong to QtQml, and ``libexec`` holds uic/rcc/qml compiler tools for
# building from source.
PRUNE_QT_DIRS = ("qml", "metatypes", "libexec")

# Developer tools py2app sweeps in alongside the library.
PRUNE_PYSIDE_TOOLS = (
    "Assistant.app",
    "Designer.app",
    "Linguist.app",
    "lrelease",
    "lupdate",
    "qmlformat",
    "qmlls",
)

# Qt's bundled ffmpeg, which exists only for QtWebEngine's codecs and
# ships each library twice — once under its SONAME, once fully versioned
# — because the link step materialised the symlinks as copies.
PRUNE_QT_LIB_PREFIXES = ("libavcodec.", "libavformat.", "libavutil.", "libswresample.", "libswscale.")


def kept_pyside_modules() -> frozenset[str]:
    """The ``PySide6/*.abi3.so`` modules to keep.

    Derived from :data:`KEEP_QT_FRAMEWORKS` rather than listed: a
    framework kept without its binding, or a binding kept without its
    framework, is exactly the kind of half-removed state that only
    shows up as an import error on someone else's machine.
    """
    return KEEP_QT_FRAMEWORKS | {"QtConcurrent"}


def _size(path: Path) -> int:
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    return sum(f.lstat().st_size for f in path.rglob("*") if f.is_file() or f.is_symlink())


def _format(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB" if n >= 1024 * 1024 else f"{n / 1024:.0f} KB"


def collect_targets(pyside_root: Path) -> list[Path]:
    """Every path this script would remove, deepest first."""
    qt = pyside_root / "Qt"
    qt_lib = qt / "lib"
    targets: list[Path] = []

    for framework in sorted(qt_lib.glob("*.framework")):
        if framework.stem not in KEEP_QT_FRAMEWORKS:
            targets.append(framework)

    for plugin_dir in sorted((qt / "plugins").iterdir() if (qt / "plugins").is_dir() else []):
        if plugin_dir.name not in KEEP_QT_PLUGIN_DIRS:
            targets.append(plugin_dir)
            continue
        if plugin_dir.name == "platforms":
            targets.extend(
                p for p in sorted(plugin_dir.glob("*"))
                if p.name != "libqcocoa.dylib"
            )

    for name in PRUNE_QT_DIRS:
        if (qt / name).is_dir():
            targets.append(qt / name)

    for name in PRUNE_PYSIDE_TOOLS:
        if (pyside_root / name).exists():
            targets.append(pyside_root / name)

    for module in sorted(pyside_root.glob("*.abi3.so")):
        if module.name[: -len(".abi3.so")] not in kept_pyside_modules():
            targets.append(module)

    if qt_lib.is_dir():
        targets.extend(
            p for p in sorted(qt_lib.iterdir())
            if p.is_file() and p.name.startswith(PRUNE_QT_LIB_PREFIXES)
        )

    # Deepest first, so a parent never disappears before its children.
    return sorted(set(targets), key=lambda p: len(p.parts), reverse=True)


def prune(bundle: Path, *, dry_run: bool = False) -> tuple[int, int]:
    candidates = sorted(
        (bundle / "Contents" / "Resources" / "lib").glob("python3.*/PySide6")
    )
    if not candidates:
        raise SystemExit(
            f"no PySide6 in {bundle} — nothing to prune. Refusing to report "
            f"a clean bundle for one that was never built."
        )
    pyside_root = candidates[0]

    targets = collect_targets(pyside_root)
    bundle_before = _size(bundle)
    if not targets:
        print(f"nothing to prune — bundle is {_format(bundle_before)}")
        return 0, bundle_before

    before = sum(_size(t) for t in targets)
    if dry_run:
        for target in targets:
            print(f"  would remove {_size(target) / (1024 * 1024):7.1f} MB  "
                  f"{target.relative_to(bundle)}")
        return before, bundle_before

    for target in targets:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()

    return before, _size(bundle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="path to the built .app")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report what would be removed without touching the bundle",
    )
    args = parser.parse_args(argv)

    if not args.bundle.is_dir():
        raise SystemExit(f"{args.bundle} is not a bundle")

    freed, bundle_after = prune(args.bundle, dry_run=args.dry_run)
    if args.dry_run:
        print(f"would free {_format(freed)} of {_format(freed + _size(args.bundle))}")
    else:
        print(
            f"pruned {_format(freed)} — bundle is now {_format(bundle_after)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())