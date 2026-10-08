"""Tests for what the release bundle is allowed to contain.

Two things about the macOS bundle are only knowable by building it:

1. ``_PACKAGES`` must name the bare ``"PySide6"``. Naming the
   submodules — ``"PySide6.QtCore"`` and friends — reads like it would
   bundle less, and it builds without a word, but the bundle does not
   start: py2app looks for a directory literally named
   ``PySide6.QtCore`` and the wheel has no such thing. The failure is
   a ``FileNotFoundError`` for a ``__init__.pyc`` at launch.

2. The bare name is also what drags QtWebEngineCore — 589 MB, plus the
   ffmpeg it ships twice — into a widgets application that never opens
   a web view. Changing ``_PACKAGES`` does not help: the tree is copied
   either way, and both spellings measured the same. That is why
   ``scripts/prune_bundle.py`` exists and runs after py2app.

Neither fact is discoverable from the test suite, and neither is
enforced by the build failing. So they are written down here, and the
prune's keep-list is checked against the app's real imports so a new
Qt dependency fails here rather than on a user's Mac.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Where a bundled app can import PySide6 from. ``tests/`` is excluded on
# purpose: it drives QtTest and the offscreen platform, neither of which
# a Finder-launched bundle carries.
_RUNTIME_ROOTS = ("app", "scripts")
_RUNTIME_FILES = ("lazy-to-text-ui.py",)

# What the app uses today. Not a whitelist so much as a tripwire: a new
# heavy Qt module lands in the dependency graph and the bundle, and
# nobody notices until someone asks why the download is 1.5 GB.
_WIDGETS_SUBSET = {"QtCore", "QtGui", "QtSvg", "QtWidgets"}


def _runtime_sources() -> list[Path]:
    found: list[Path] = []
    for root in _RUNTIME_ROOTS:
        found.extend(p for p in (_ROOT / root).rglob("*.py") if p.is_file())
    for name in _RUNTIME_FILES:
        path = _ROOT / name
        if path.is_file():
            found.append(path)
    return found


def _pyside6_submodules(path: Path) -> set[str]:
    """Submodules named by real imports in *path*.

    Parsed from the AST rather than grepped, so the string
    ``"PySide6.QtWebEngine"`` in a comment or a docstring — both of
    which this repository has plenty of — cannot pass for an import.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("PySide6"):
                rest = node.module[len("PySide6"):].lstrip(".")
                if rest:
                    found.add(rest.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("PySide6."):
                    found.add(alias.name[len("PySide6."):].split(".")[0])
    return found


def _packages_in_setup_py() -> list[str]:
    """The ``_PACKAGES`` list, read from the AST.

    Not grepped: the comment above the list explains this very
    regression and writes ``"PySide6.QtCore"`` in prose, so a regex
    would find the name in the warning and report the bug it describes.
    """
    source = (_ROOT / "setup.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="setup.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "_PACKAGES" in targets:
                return [
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                ]
    raise AssertionError("could not find _PACKAGES in setup.py")


def test_pyside6_must_be_named_as_the_bare_package():
    """The submodule form builds and then fails to launch.

    Worth its own test because nothing else notices: the build is
    silent, the bundle is a plausible size, and the failure is a
    missing ``.pyc`` deep inside a half-gigabyte artifact that only a
    human launching it would hit.
    """
    listed = _packages_in_setup_py()
    assert "PySide6" in listed, (
        "_PACKAGES no longer names the bare 'PySide6' package. If it was "
        "replaced with submodule names, the bundle will build and then "
        "die at launch on a missing PySide6.QtCore/__init__.pyc — py2app "
        "looks for a directory with that literal name."
    )
    as_submodules = [p for p in listed if p.startswith("PySide6.")]
    assert not as_submodules, (
        f"_PACKAGES names PySide6 by submodule ({as_submodules}); that form "
        f"does not launch. Use the bare 'PySide6'."
    )


def test_the_app_stays_on_the_widgets_subset_of_qt():
    """A new heavy Qt import should be a decision, not an accident."""
    used: dict[str, str] = {}
    for path in _runtime_sources():
        for name in _pyside6_submodules(path):
            used.setdefault(name, str(path.relative_to(_ROOT)))

    heavy = set(used) - _WIDGETS_SUBSET
    assert not heavy, (
        f"the app now imports PySide6.{sorted(heavy)} "
        f"(first seen in {used[sorted(heavy)[0]]}). That is allowed, but it "
        f"has to be deliberate: the bundle already ships all of Qt, so the "
        f"cost is invisible until the download is measured. Say so in the "
        f"size note in setup.py and on the landing page."
    )


def _prune_manifest():
    """The keep/prune lists in ``scripts/prune_bundle.py``.

    Imported rather than parsed so the test and the build step cannot
    disagree about what the list *is*; the module guards its entry point,
    so importing it has no side effects on the bundle.
    """
    import importlib.util

    path = _ROOT / "scripts" / "prune_bundle.py"
    spec = importlib.util.spec_from_file_location("prune_bundle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_prune_manifest_keeps_every_qt_module_the_app_imports():
    """Adding a Qt import must fail here, not on someone else's Mac.

    The manifest is the only thing standing between a new ``QtCharts``
    import and a bundle that prunes the framework out from under it: the
    prune step runs by name, so the failure would be an import error at
    launch rather than anything the build could see.
    """
    manifest = _prune_manifest()
    used: set[str] = set()
    for path in _runtime_sources():
        used |= _pyside6_submodules(path)

    kept = manifest.kept_pyside_modules()
    missing = sorted(used - kept)
    assert not missing, (
        f"the app imports PySide6.{missing} but scripts/prune_bundle.py does "
        f"not keep {missing}. Add the framework to KEEP_QT_FRAMEWORKS (the "
        f"binding is derived from it) or the pruned release will not start."
    )


def test_the_prune_manifest_cannot_keep_and_remove_the_same_thing():
    """A name on both lists is decided by whichever line runs last.

    Not hypothetical: ``kept_pyside_modules()`` is derived from the
    framework list while the module list is filtered separately, so the
    two can drift into naming the same module and the build would delete
    what it just decided to keep.
    """
    manifest = _prune_manifest()
    kept = manifest.kept_pyside_modules()

    pruned = {name[: -len(".abi3.so")] for name in manifest.PRUNE_PYSIDE_TOOLS}
    overlap = kept & pruned
    assert not overlap, f"the manifest both keeps and prunes {sorted(overlap)}"

    # The derived binding set has to cover every kept framework, or a
    # kept framework loses its Python binding at the next Qt release
    # that stops shipping them together.
    assert manifest.KEEP_QT_FRAMEWORKS <= kept, (
        "KEEP_QT_FRAMEWORKS names a module that kept_pyside_modules() "
        "does not return"
    )


def _fake_bundle(tmp_path: Path) -> Path:
    """A miniature of the shape py2app produces, files and all.

    Built rather than borrowed because the real one is 400 MB and exists
    only on the machine that built it — which is why every assertion
    about *what the prune does* has to live here, on a tree small enough
    to run on all three CI legs.
    """
    pyside = (
        tmp_path / "Lazy to Text.app" / "Contents" / "Resources"
        / "lib" / "python3.12" / "PySide6"
    )
    qt = pyside / "Qt"

    for framework in ("QtCore", "QtWidgets", "QtSvg", "QtWebEngineCore", "QtQuick"):
        target = qt / "lib" / f"{framework}.framework" / "Versions" / "A"
        target.mkdir(parents=True)
        (target / framework).write_bytes(b"x" * 64)
    for dylib in ("libavcodec.61.dylib", "libavcodec.61.19.101.dylib"):
        (qt / "lib" / dylib).write_bytes(b"x" * 64)
    (qt / "lib" / "libsqlite3.dylib").write_bytes(b"x" * 64)

    for name, payload in (
        ("qml/QtQuick/qmldir", b"qml"),
        ("metatypes/QtQuick.json", b"{}"),
        ("libexec/uic", b"uic"),
    ):
        target = qt / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    for directory, plugin in (
        ("platforms", "libqcocoa.dylib"),
        ("platforms", "libqoffscreen.dylib"),
        ("platforms", "libqminimal.dylib"),
        ("styles", "libqmacstyle.dylib"),
        ("imageformats", "libqsvg.dylib"),
        ("sqldrivers", "libqsqlite.dylib"),
    ):
        target = qt / "plugins" / directory / plugin
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"p")

    for module in ("QtCore", "QtWidgets", "QtSvg", "QtCharts", "QtWebEngineCore"):
        (pyside / f"{module}.abi3.so").write_bytes(b"m")
    for tool in ("Designer.app", "qmlls", "lupdate"):
        target = pyside / tool
        target.mkdir() if tool.endswith(".app") else target.write_bytes(b"t")
    (pyside / "Designer'siaera").write_bytes(b"untouched")

    return tmp_path / "Lazy to Text.app"


def _relative_set(root: Path) -> set[str]:
    """Relative paths under *root*, always spelled with forward slashes.

    ``as_posix()`` rather than ``str()``: on Windows the native form is
    backslash-separated, so every comparison below stopped matching.
    Half of this test then failed for a reason that had nothing to do
    with the prune, and the other half passed without checking
    anything at all — the removed-files loop could not match its own
    names, so it reported "nothing survived" while nothing had been
    removed. A separator is not a cosmetic detail in a path assertion.
    """
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() or p.is_symlink()
    }


def test_the_prune_removes_exactly_what_the_manifest_says(tmp_path):
    """The whole contract, on a tree small enough to assert exactly.

    Asserting both directions is the point: a prune that removed nothing
    would satisfy "QtWebEngineCore is gone" the same way one that
    removed QtCore entirely would satisfy it.
    """
    manifest = _prune_manifest()
    bundle = _fake_bundle(tmp_path)
    pyside = next(
        (bundle / "Contents" / "Resources" / "lib").glob("python3.*/PySide6")
    )

    before = _relative_set(bundle)
    freed, _ = manifest.prune(bundle)
    after = _relative_set(bundle)

    removed = before - after
    kept = before & after

    assert freed > 0, "prune reported freeing nothing"
    assert removed, "prune removed nothing at all"

    # Everything the app imports survives.
    assert any(
        p.endswith("QtCore.framework/Versions/A/QtCore") for p in kept
    ), "the prune removed QtCore"
    assert any(p.endswith("QtWidgets.abi3.so") for p in kept)
    assert any(p.endswith("QtSvg.abi3.so") for p in kept)
    assert any(p.endswith("libqcocoa.dylib") for p in kept), (
        "the prune removed the only platform plugin the app can load"
    )
    assert any(p.endswith("libqmacstyle.dylib") for p in kept)
    assert any(p.endswith("libqsvg.dylib") for p in kept), (
        "the prune removed the imageformats plugin"
    )
    assert any(p.endswith("libsqlite3.dylib") for p in kept), (
        "the prune deleted a dylib that is not one of Qt's ffmpeg ones"
    )

    # Everything it does not goes.
    for gone in (
        "QtWebEngineCore.framework/Versions/A/QtWebEngineCore",
        "QtQuick.framework/Versions/A/QtQuick",
        "libavcodec.61.dylib",
        "libavcodec.61.19.101.dylib",
        "qml/QtQuick/qmldir",
        "metatypes/QtQuick.json",
        "libexec/uic",
        "platforms/libqoffscreen.dylib",
        "platforms/libqminimal.dylib",
        "sqldrivers/libqsqlite.dylib",
        "QtCharts.abi3.so",
        "QtWebEngineCore.abi3.so",
        "Designer.app",
        "qmlls",
        "lupdate",
    ):
        assert not any(p.endswith(gone) for p in after), f"{gone} survived the prune"

    # And it touched nothing outside Qt.
    assert any(p.endswith("Designer'siaera") for p in after)


def test_the_prune_refuses_a_bundle_it_cannot_find_qt_in(tmp_path):
    """Reporting a clean bundle for one that was never built is a lie.

    The build calls this after py2app and would otherwise carry on to
    codesign whatever it found.
    """
    import pytest as _pytest

    manifest = _prune_manifest()
    empty = tmp_path / "Lazy to Text.app" / "Contents" / "Resources"
    empty.mkdir(parents=True)

    with _pytest.raises(SystemExit):
        manifest.prune(tmp_path / "Lazy to Text.app")


def test_the_macos_bundle_no_longer_carries_qt_it_never_imports():
    """The dead weight is gone, and what replaced it is still there.

    Written as a measurement rather than a wish. The belief that a
    better ``_PACKAGES`` list would remove it was tested and wrong —
    1.5 GB with the bare package, 1.5 GB with the submodules — so it took
    a prune step to move it, and this is what holds that step honest.

    Both halves matter. Asserting only that WebEngine is gone would pass
    against a script that emptied the whole Qt tree, and the bundle would
    no longer start.
    """
    resources = (
        _ROOT / "dist" / "Lazy to Text.app" / "Contents" / "Resources"
    )
    qt_lib = next(iter(resources.glob("lib/python3.*/PySide6/Qt/lib")), None)
    if qt_lib is None or not qt_lib.is_dir():
        pytest.skip("no built bundle in dist/ — nothing to measure")

    manifest = _prune_manifest()
    shipped = {p.stem for p in qt_lib.glob("*.framework")}

    assert "QtWebEngineCore" not in shipped, (
        "QtWebEngineCore is back in the bundle — the prune step did not run "
        "(is this an alias build?) or its keep-list grew."
    )

    missing = sorted(manifest.KEEP_QT_FRAMEWORKS - shipped)
    assert not missing, (
        f"the bundle is missing {missing}. Either the prune script removed "
        f"something it keeps, or the build did not run scripts/prune_bundle.py."
    )

    # Plugins are pruned by directory, and ``platforms`` a second time
    # from the inside: the wheel ships ``minimal`` and ``offscreen`` for
    # headless runs, which the bundle excludes with the test suite. A
    # framework-only check would not notice either half of that.
    plugins_dir = qt_lib.parent / "plugins"
    if not plugins_dir.is_dir():
        pytest.skip("this bundle carries no Qt plugins to measure")

    plugin_dirs = {p.name for p in plugins_dir.iterdir() if p.is_dir()}
    assert plugin_dirs <= manifest.KEEP_QT_PLUGIN_DIRS, (
        f"unexpected plugin directories shipped: "
        f"{sorted(plugin_dirs - manifest.KEEP_QT_PLUGIN_DIRS)}"
    )
    assert plugin_dirs >= manifest.KEEP_QT_PLUGIN_DIRS, (
        f"the prune removed plugin directories it keeps: "
        f"{sorted(manifest.KEEP_QT_PLUGIN_DIRS - plugin_dirs)}"
    )

    platforms = {p.name for p in (plugins_dir / "platforms").iterdir()}
    assert platforms == {"libqcocoa.dylib"}, (
        f"platform plugins shipped: {sorted(platforms)} — only the macOS one "
        f"is loadable by a Finder-launched app"
    )


def test_the_bundle_interpreter_can_actually_resolve_its_dylib():
    """The worker interpreter must run, not merely exist.

    ``Contents/MacOS/python`` is what ``SubprocessBackend`` spawns the
    inference worker with. It links ``libpython3.12.dylib`` through
    ``@executable_path/../lib/`` — a path py2app does not create,
    because it puts the dylib in ``Contents/Frameworks``. Shipped like
    that, the stub dies on its first instruction with ``dyld: Library
    not loaded`` and the worker never starts.

    Runs the stub's own dynamic dependencies against what the bundle
    actually contains, rather than trusting that the file is present.
    Skipped unless a built bundle exists, same as the Qt-weight test.
    """
    import shutil
    import subprocess

    contents = _ROOT / "dist" / "Lazy to Text.app" / "Contents"
    stub = contents / "MacOS" / "python"
    if not stub.is_file():
        pytest.skip("no built bundle in dist/ — nothing to check")

    otool = shutil.which("otool")
    if otool is None:
        pytest.skip("otool unavailable — cannot inspect linkage")

    out = subprocess.run(
        [otool, "-L", str(stub)], capture_output=True, text=True,
    ).stdout

    # The py2app launcher is a Mach-O executable with no @rpath to a
    # Python at all, so this doubles as "is this the interpreter stub
    # and not the launcher renamed".
    assert "libpython3.12.dylib" in out, (
        "Contents/MacOS/python does not link libpython3.12.dylib — the "
        "inference worker cannot start with it"
    )

    linked = next(
        line.strip().split(" ")[0]
        for line in out.splitlines()
        if "libpython3.12.dylib" in line
    )
    resolved = contents / "lib" / "libpython3.12.dylib"
    assert resolved.exists(), (
        f"the bundle's interpreter links {linked} but that path does not "
        f"exist in the bundle; scripts/build-macos.sh is supposed to "
        f"stage it at Contents/lib/"
    )


def test_the_documented_download_size_agrees_across_surfaces():
    """README.md and the landing page both publish the same number.

    Both quote the download size of the macOS archive, and the two had
    no reason to stay in step: one was edited to "553 MB" while a
    third place still said "539 MB", and nothing noticed because the
    third place was a comment. A comment cannot be tested, so the fix
    was to stop the comment restating a measurement and instead point
    at these two — which leaves these two as the surfaces worth
    pinning to each other.

    Compared as the exact byte count rather than the rounded figure:
    553 MB and 539 MB are the kind of difference that survives a re-
    read, while 553,281,120 is either there or it is not.

    The invariant is that the two files never *disagree* about a figure
    they both state. The README tabulates every release asset while the
    landing page quotes just the macOS download, so one is naturally a
    superset of the other — insisting on equality would make adding a
    row to the README look like a bug. Both ``bytes`` and the table's
    ``B`` suffix are accepted, since either is how a size gets written
    down.
    """
    import re

    documented = {}
    for name in ("README.md", "docs/index.html"):
        text = (_ROOT / name).read_text(encoding="utf-8")
        documented[name] = {int(v.replace(",", ""))
                            for v in re.findall(r"([\d,]+)\s*(?:bytes|\bB\b)", text)}

    assert all(documented.values()), (
        f"a documented file names no download size: {documented}"
    )

    readme, page = documented["README.md"], documented["docs/index.html"]
    shared = readme & page
    assert shared, (
        f"the two surfaces name no figure in common, so they cannot be "
        f"checked against each other: {documented}"
    )
    assert shared == min(readme, page, key=len), (
        f"every figure one surface states must also be stated by the "
        f"other, or the pair can drift: {documented}"
    )
