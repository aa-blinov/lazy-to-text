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


def _top_level_imports(path: Path) -> set[str]:
    """Every top-level module name the AST of *path* imports.

    Absolute imports only, reduced to the first dotted component: the
    prune's Python-package list names directories, and a relative
    ``from . import x`` names nothing the bundle resolves by name.

    Parsed rather than grepped for the reason
    :func:`_pyside6_submodules` documents — this repository writes
    package names in prose often enough that a substring search would
    report its own documentation.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
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


def test_the_prune_manifest_keeps_every_python_package_the_app_imports():
    """A cut list is only safe for as long as nothing imports what it cuts.

    The same question the Qt keep-list is asked, asked of the cut side
    instead — because these are removed by directory name. A new import
    of a pruned package would not fail the build, or this file: it would
    be an ``ImportError`` at launch, on a user's Mac, in a bundle nobody
    re-measures.
    """
    manifest = _prune_manifest()
    used: set[str] = set()
    for path in _runtime_sources():
        used |= _top_level_imports(path)

    pruned = set(manifest.PRUNE_PYTHON_PACKAGES)
    clash = sorted(used & pruned)
    assert not clash, (
        f"the app imports {clash} but scripts/prune_bundle.py prunes them. "
        f"Remove them from PRUNE_PYTHON_PACKAGES or the release bundle will "
        f"not start."
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

    # Pure-Python packages ship beside PySide6, not inside it. Two the
    # manifest cuts and one it must leave alone, so the prune can be
    # caught failing in either direction.
    packages = pyside.parent
    for name in (
        "setuptools/__init__.py",
        "setuptools/command/__init__.py",
        "pygments/__init__.py",
        "pygments/lexers/__init__.py",
        "platformdirs/__init__.py",
    ):
        target = packages / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"p")

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
    assert any(p.endswith("platformdirs/__init__.py") for p in kept), (
        "the prune removed a Python package whose name is not on the cut list"
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
        "setuptools/__init__.py",
        "setuptools/command/__init__.py",
        "pygments/__init__.py",
        "pygments/lexers/__init__.py",
    ):
        assert not any(p.endswith(gone) for p in after), f"{gone} survived the prune"

    # And it touched nothing it has no rule for: a file inside PySide6
    # that no list names, and the packages list itself.
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


def test_the_bundle_ships_the_patched_portaudio():
    """The bundle must carry PortAudio with the CoreAudio fix applied.

    The ``sounddevice`` wheel's own ``libportaudio.dylib`` deadlocks when
    a stream is stopped (PortAudio/portaudio#1174). The deadlock holds
    the microphone for the rest of the session and stops the app from
    quitting, because ``Pa_Terminate`` waits on the same lock.

    The patched library is built by
    ``scripts/build_patched_portaudio.py`` and writes a marker next to
    the dylib naming the PortAudio commit and the patch. Without the
    marker the bundle ships the deadlock, and nothing else in the build
    notices: the app still starts, still records, and only breaks hours
    later, in the field.

    Skipped unless a built bundle exists, same as the Qt-weight test.
    """
    import json

    resources = _ROOT / "dist" / "Lazy to Text.app" / "Contents" / "Resources"
    dylibs = list(resources.glob(
        "lib/python3.*/_sounddevice_data/portaudio-binaries/libportaudio.dylib"
    ))
    if not dylibs:
        pytest.skip("no built bundle in dist/ — nothing to check")

    dylib = dylibs[0]
    marker = dylib.with_suffix(dylib.suffix + ".patched.json")
    assert marker.is_file(), (
        f"the bundle ships the unpatched {dylib.name} from the "
        f"sounddevice wheel — the CoreAudio stop deadlock "
        f"(PortAudio/portaudio#1174) is still in it. Run "
        f"scripts/build_patched_portaudio.py --bundle <bundle> before "
        f"signing the bundle."
    )

    recorded = json.loads(marker.read_text())
    assert recorded["portaudio_commit"] == (
        "147dd722548358763a8b649b3e4b41dfffbcfbb6"
    ), (
        f"the bundle's PortAudio is {recorded['portaudio_commit']}, "
        f"not the pinned v19.7.0 commit the patch was written against"
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



# ---- signing: the one check that makes permissions survive a rebuild
#
# macOS keys every TCC grant — Accessibility, Microphone — to the app's
# designated requirement. Measured on this machine:
#
#   ad-hoc  →  cdhash H"24517fd…"            new every build
#   signed  →  certificate root = H"b6327a…" identical across three
#               different payloads
#
# So an ad-hoc release costs the user both permissions on every
# reinstall, while a certificate-anchored one costs them nothing after
# the first grant. The failure is invisible either way: `codesign` exits
# 0 for both, and the bundle installs and runs.

def _codesign_available() -> bool:
    import shutil
    import sys

    return sys.platform == "darwin" and shutil.which("codesign") is not None


def test_the_build_refuses_an_ad_hoc_bundle_when_an_identity_was_chosen():
    """``codesign`` exiting 0 does not say *which* signature it wrote.

    The release that motivated all of this shipped ad-hoc from a machine
    that already carried a self-signed identity, because the only check
    was the exit status. The identity is overridable from the environment,
    so "it found an identity" and "it signed with one" are different
    facts, and the designated requirement is what tells them apart.
    """
    script = _ROOT / "scripts" / "build-macos.sh"
    src = script.read_text(encoding="utf-8")

    # Match the assignment itself, not the command name: the same string
    # appears in the error message further down, so a bare
    # ``"codesign -d -r-" in src`` still passes with the check deleted.
    assert 'bundle_requirement="$(codesign -d -r-' in src, (
        "build-macos.sh must inspect the designated requirement, not just "
        "codesign's exit status"
    )
    # And the comparison that turns it into a decision.
    assert 'bundle_requirement == *"cdhash"*' in src, (
        "a cdhash requirement is the tell for an ad-hoc signature; the "
        "build has to act on it, not merely look"
    )


def test_setup_signing_does_not_try_to_derive_the_keychain_password():
    """It passed ``-k "$(security show-keychain-info … | sed …)"``.

    That command prints ``Keychain "…" no-timeout`` — the substring
    ``password:`` never appears — so the substitution yielded an empty
    string, ``-k ""`` failed, and a ``|| { … }`` arm printed "skipped"
    and carried on. The identity was installed and unusable, and every
    later run reported "already installed" and exited before the repair
    could be attempted.
    """
    src = (_ROOT / "scripts" / "setup-signing.sh").read_text(
        encoding="utf-8"
    )
    # Strip comments first: the explanation of *why* this is wrong quotes
    # the very command it forbids, and a substring check over the raw file
    # would then fail on its own documentation.
    code = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "show-keychain-info" not in code, (
        "show-keychain-info does not print the password; deriving -k from "
        "it silently yields an empty string and skips the partition list"
    )
    assert "set-key-partition-list" in code
    # The grant must reach the keychain password prompt rather than a
    # value spliced into the command line.
    assert "-l " in code, "scope the grant to this identity with -l"

    # And it must not swallow its own failure. That swallow is what kept
    # the broken state alive: the script printed "skipped", exited 0, and
    # every later run reported "already installed". Checked per line —
    # looking for "||" in the surrounding prose matches nothing useful
    # and hides the case where it is bolted onto the command itself.
    partition_lines = [
        line for line in code.splitlines()
        if "set-key-partition-list" in line and not line.strip().startswith("echo")
    ]
    assert partition_lines, "no set-key-partition-list call found"
    for line in partition_lines:
        assert "||" not in line, (
            "a failing partition list must be fatal, not swallowed:\n"
            f"    {line.strip()}"
        )


@pytest.mark.skipif(not _codesign_available(), reason="needs macOS codesign")
def test_a_certified_signature_anchors_and_ad_hoc_does_not(tmp_path):
    """Run the build's own decision against two real signatures.

    Skipped where codesign is absent, and it needs an identity to sign
    with; without one it falls back to proving the ad-hoc half, which is
    the direction that has to be right in either case.
    """
    import subprocess

    adhoc = tmp_path / "adhoc"
    adhoc.write_bytes(b"x")
    subprocess.run(["codesign", "-f", "-s", "-", str(adhoc)],
                   check=True, capture_output=True)
    adhoc_req = subprocess.run(
        ["codesign", "-d", "-r-", str(adhoc)],
        capture_output=True, text=True,
    ).stdout.strip().splitlines()[-1]

    assert "cdhash" in adhoc_req, (
        f"ad-hoc should anchor on a cdhash, got: {adhoc_req!r}"
    )

    # Find an identity; skip rather than fail when the machine has none,
    # because "no identity" is a legitimate state for a fresh Mac.
    found = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True, text=True,
    ).stdout
    import re

    names = re.findall(r'"([^"]+)"', found)
    if not names:
        pytest.skip("no codesigning identity on this machine")

    signed = tmp_path / "signed"
    signed.write_bytes(b"y")
    result = subprocess.run(
        ["codesign", "-f", "-s", names[0], str(signed)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"cannot sign with {names[0]!r} here: {result.stderr}")
    signed_req = subprocess.run(
        ["codesign", "-d", "-r-", str(signed)],
        capture_output=True, text=True,
    ).stdout.strip().splitlines()[-1]

    assert "cdhash" not in signed_req, (
        f"a certified signature must not anchor on a cdhash, got: "
        f"{signed_req!r}"
    )
    assert "certificate" in signed_req, signed_req


# ---- the hardened runtime: what notarization actually gates on
#
# Apple requires it outright — "To upload a macOS app to be notarized,
# you must enable the Hardened Runtime capability" — and the release
# signature this machine produced did not have it:
#
#     CodeDirectory v=20400 flags=0x0(none)
#
# The runtime also denies whatever it does not explicitly permit, so a
# dictation app needs the microphone entitlement declared before the mic
# opens. Both halves are pinned here, and both were free to settle: the
# runtime flag is testable against the self-signed identity, so none of
# this needed a paid Developer ID to find out.

def _entitlements(name: str) -> dict:
    import plistlib

    path = _ROOT / "scripts" / name
    assert path.is_file(), (
        f"scripts/{name} is missing. The hardened runtime blocks the "
        "microphone without com.apple.security.device.audio-input, so a "
        "release signed with the runtime and no entitlements dictates "
        "nothing."
    )
    return plistlib.loads(path.read_bytes())


_MICROPHONE = "com.apple.security.device.audio-input"
_LIBRARY_VALIDATION = "com.apple.security.cs.disable-library-validation"


def test_the_developer_id_entitlements_declare_the_microphone_and_nothing_else():
    """Both directions are the point.

    Dropping ``com.apple.security.device.audio-input`` is a dictation app
    that records nothing, and it fails as a silent error rather than a
    crash. Adding entitlements the app never needed is the opposite
    failure and the easier one to do by accident while chasing the first:
    Apple's guidance is to enable only what is strictly necessary, and
    ``disable-library-validation`` in particular turns off a real
    protection against a tampered dylib. Nothing here is granted at
    runtime anyway — Accessibility and Microphone *permissions* are TCC
    grants, not entitlements.
    """
    assert _entitlements("entitlements.plist") == {_MICROPHONE: True}


def test_the_local_entitlements_add_library_validation_and_explain_why():
    """The one key a Developer ID does not get, for a measured reason.

    The hardened runtime matches every loaded library against the
    loading process's Team ID, and a self-signed certificate has none —
    so dyld refuses the bundle's own libpython and the inference worker
    dies while the window still opens. The alternative was tried and
    does not work: putting a Team ID in the OU of a self-signed
    certificate leaves ``TeamIdentifier=not set``, because only Apple
    issues them. So this key is the only route, and it is paid for only
    on the build that cannot ship.

    Asserting the difference rather than just the local set, because the
    wrong fix is easy and silent: adding it to
    ``entitlements.plist`` turns off a protection on the artifact people
    actually download, and no test that only read the local file would
    notice.
    """
    local = _entitlements("entitlements-local.plist")
    release = _entitlements("entitlements.plist")

    assert local == {_MICROPHONE: True, _LIBRARY_VALIDATION: True}
    assert _LIBRARY_VALIDATION not in release, (
        "disable-library-validation has no place in a Developer ID build: "
        "its nested code shares the bundle's Team ID and validation passes "
        "without it"
    )
    assert local[_MICROPHONE] == release[_MICROPHONE] == True  # noqa: E712


def _build_script_code() -> str:
    """``build-macos.sh`` with the commentary removed.

    Stripping comments is not tidiness: this file explains at length why
    ``-perm -u+x`` is the wrong predicate and what it would silently drop,
    so a substring search over the raw script matches its own warning.
    """
    src = (_ROOT / "scripts" / "build-macos.sh").read_text(encoding="utf-8")
    return "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )


def test_the_release_build_signs_with_the_hardened_runtime():
    """The flag and the entitlements have to be on the same sign call."""
    code = _build_script_code()

    assert "--options runtime" in code, (
        "the release build does not pass --options runtime. Apple rejects "
        "notarization without it, and a Developer ID would be paid for a "
        "submission that cannot be accepted."
    )
    assert "--entitlements" in code, (
        "the release build signs without --entitlements, so the hardened "
        "runtime denies the microphone the app exists to use"
    )
    # Which entitlements file is not a preference either: the local build
    # needs one the Developer ID build must not have, and swapping them
    # breaks the worker on one path or weakens the other.
    assert 'entitlements="scripts/entitlements.plist"' in code, (
        "a Developer ID build must sign with scripts/entitlements.plist"
    )
    assert 'entitlements="scripts/entitlements-local.plist"' in code, (
        "a self-signed build must sign with scripts/entitlements-local.plist"
    )
    # The predicate is pinned whole, not just named: a test that only
    # looks for `_developer_id` in the file survives replacing its body
    # with ``return 1``, which is exactly the mutant that silently ships
    # the local entitlements on a Developer ID build.
    assert '_developer_id() { [[ "$signing_identity" == "Developer ID"* ]]; }' in code, (
        "the entitlement choice has to follow the identity: a self-signed "
        "certificate has no Team ID, so the runtime cannot validate the "
        "bundle's own libpython without the extra key. Inverting this "
        "predicate ships local entitlements to users, or kills the worker "
        "on a Developer ID machine."
    )
    # The runtime belongs to the release path only. An alias build's
    # Python is symlinked back to the venv, and library validation would
    # refuse to load those unsigned dylibs — the flag would break the
    # dev loop rather than protect anything.
    assert '[[ "$mode" != "release" ]]' in code, (
        "the hardened runtime is applied unconditionally; an alias build "
        "must keep its old --deep sign or it will not launch"
    )


def test_the_build_selects_code_by_what_it_is_not_by_whether_it_is_executable():
    """``-perm -u+x`` drops the files the app cannot run without.

    27 Mach-O files in this bundle carry no execute bit, and they are
    load-bearing: ``Contents/Frameworks/libpython3.12.dylib``, which the
    worker interpreter links against, and every ``lib-dynload/*.so``
    pyobjc module behind the autopaste and the permission checks. Signed
    around them, they fail library validation at load — a worker that
    will not start, and a paste that quietly does nothing.

    Extension-based selection is what catches both the bit-less files and
    the ones with no extension at all (``ffmpeg-macos-aarch64-v7.1``, Qt
    framework binaries at ``Versions/A/QtCore``).
    """
    code = _build_script_code()

    assert "-perm -u+x" not in code, (
        "the build selects executable code by its execute bit. 27 Mach-O "
        "files in the bundle have none, including libpython3.12.dylib and "
        "the pyobjc lib-dynload modules, and would ship unsigned."
    )
    assert "-name '*.so'" in code and "-name '*.dylib'" in code
    assert "-name 'ffmpeg-*'" in code, (
        "ffmpeg ships as an extensionless executable; extension matching "
        "alone leaves it unsigned and the fallback decoder broken"
    )
    assert "-name '*.framework'" in code, (
        "Qt's framework binaries live at Versions/A/<Name> with no "
        "extension; the wrapper has to be signed as a wrapper"
    )


def test_the_release_build_refuses_a_bundle_that_cannot_verify():
    """``codesign`` succeeding and the bundle verifying are two facts.

    Measured on this machine: a bundle whose designated requirement was
    a real certificate and whose build was green failed
    ``codesign --verify`` with "a sealed resource is missing or
    invalid", listing ``.pyc`` files that a hand-run cleanup deleted
    after the build had signed them. Notarization rejects a bundle that
    cannot verify, so this has to fail the build rather than the upload.
    """
    code = _build_script_code()

    assert "codesign --verify" in code, (
        "the build never asks codesign to verify its own output; a broken "
        "seal is only discovered by Apple's notary service"
    )
    assert '--verify --deep --strict' in code, (
        "verification without --deep --strict skips nested code and "
        "loose references, which is where the bundle this was written "
        "for actually failed"
    )


@pytest.mark.skipif(not _codesign_available(), reason="needs macOS codesign")
def test_the_built_bundle_carries_the_runtime_and_the_microphone_entitlement(tmp_path):
    """What the flags in the script are supposed to produce, measured.

    Skipped where codesign is absent and where no bundle has been built,
    for the same reason as the tests above it: it reads an artifact that
    only exists on the machine that ran the release build.
    """
    import plistlib
    import subprocess

    bundle = _ROOT / "dist" / "Lazy to Text.app"
    if not bundle.is_dir():
        pytest.skip("no built bundle in dist/ — nothing to measure")

    def _run(*args):
        return subprocess.run(args, capture_output=True, text=True)

    verbose = _run("codesign", "-d", "--verbose=4", str(bundle)).stderr
    assert "runtime" in verbose, (
        "the built bundle is not signed with the hardened runtime:\n"
        f"{verbose.strip()}\n"
        "Apple will not notarize it."
    )

    # ``--xml`` is not optional. Without it codesign picks its output
    # format by signature type, and the self-signed release falls back to
    # the legacy ``[Dict] / [Key]`` rendering that plistlib cannot read —
    # so the test would fail on the very build it is meant to check.
    dump = _run("codesign", "-d", "--entitlements", "-", "--xml", str(bundle))
    if dump.returncode != 0:
        pytest.skip(f"codesign would not dump entitlements: {dump.stderr}")
    applied = plistlib.loads(dump.stdout.encode())
    assert applied.get(_MICROPHONE) is True, (
        f"the runtime is on but the microphone entitlement is not: {applied}"
    )

    # The third entitlement is not a fixed list — it depends on who
    # signed. Read the identity back off the bundle and hold the bundle
    # to the file the build promises for it, so a Developer ID build
    # cannot quietly ship with the local build's extra key.
    signer = _run("codesign", "-dvvv", str(bundle)).stderr
    developer_id = "Developer ID Application" in signer
    expected = {_MICROPHONE: True}
    if not developer_id:
        expected[_LIBRARY_VALIDATION] = True
    assert applied == expected, (
        f"the bundle was signed by a {'Developer ID' if developer_id else 'non-Developer ID'} "
        f"identity but declares {sorted(applied)}; expected "
        f"{sorted(expected)}"
    )


@pytest.mark.skipif(not _codesign_available(), reason="needs macOS codesign")
def test_the_built_inference_worker_actually_runs():
    """The interpreter has to start, not merely exist and link.

    This is the test that the hardened runtime made necessary. The
    runtime validates every library against the loading process's Team
    ID; a self-signed certificate has none, so with the runtime on and
    the wrong entitlements ``Contents/MacOS/python`` dies on its first
    instruction —

        dyld: Library not loaded: @executable_path/../lib/libpython3.12.dylib
        Reason: … have different Team IDs

    — and the failure is invisible from outside. The app catches a dead
    worker, falls back to the in-process backend, and keeps opening
    windows; the only symptom is that dictation no longer runs in its
    own process and gets noticeably worse under load.

    ``otool -L`` cannot see this. It reports the link, not whether dyld
    will honour it, which is why the existing linkage test passes
    against a bundle whose worker cannot start.
    """
    import os
    import subprocess

    contents = _ROOT / "dist" / "Lazy to Text.app" / "Contents"
    stub = contents / "MacOS" / "python"
    if not stub.is_file():
        pytest.skip("no built bundle in dist/ — nothing to run")

    # The same environment SubprocessBackend hands the child.
    env = dict(os.environ)
    env["PYTHONHOME"] = str(contents / "Resources")
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [str(stub), "-c", "import sys; print(sys.version.split()[0])"],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert result.returncode == 0 and result.stdout.strip(), (
        "the bundled interpreter does not run. This is what the hardened "
        "runtime's library validation looks like when the entitlements do "
        "not match the signing identity:\n"
        f"{(result.stderr or result.stdout).strip()[:600]}"
    )


def test_the_build_signs_the_worker_with_its_own_entitlements():
    """Entitlements on the bundle do not reach the inference worker.

    ``Contents/MacOS/`` holds the app's entry points, and each is a
    separate process with its own signature. Signing the bundle covers
    the launcher; the worker is ``exec``'d in its own right, so
    ``disable-library-validation`` has to be on *its* signature too.

    Measured both ways on this machine. With the entitlement on the
    bundle only, the worker dies on library validation and the window
    keeps opening — the app catches a dead worker, falls back to the
    in-process backend, and reports nothing. With it on the worker, the
    same bundle loads Python 3.12.11, PySide6, onnxruntime 1.30.0 and
    ``scipy.signal`` under the hardened runtime.
    """
    code = _build_script_code()

    # The definition whole, not just its name: a check for the bare
    # ``sign_entry`` survives dropping the entitlement from it, which is
    # precisely the mutant that leaves the worker unsigned.
    assert 'sign_entry() { _sign "$1" --entitlements "$entitlements"; }' in code, (
        "the build needs a signing path that attaches the entitlements to an "
        "entry point rather than only to the bundle"
    )
    assert '*/Contents/MacOS/*' in code, (
        "entry points are not distinguished from other nested code, so the "
        "inference worker is signed without the entitlements it needs"
    )


@pytest.mark.skipif(not _codesign_available(), reason="needs macOS codesign")
def test_every_mach_o_file_the_app_loads_is_signed():
    """Inside-out signing has to reach the files with no execute bit.

    The build selects nested code by extension and by Mach-O magic, not
    by permission — 27 files under ``Contents`` carry no execute bit and
    they are the load-bearing ones: the interpreter's dylib starts the
    inference worker, the pyobjc modules carry the autopaste and the
    permission probes, ONNX Runtime carries every transcription, and
    ffmpeg decodes everything libsndfile will not.
    """
    import subprocess

    contents = _ROOT / "dist" / "Lazy to Text.app" / "Contents"
    libpython = contents / "Frameworks" / "libpython3.12.dylib"
    if not libpython.is_file():
        pytest.skip("no built bundle in dist/ — nothing to check")

    py_version = next(contents.glob("Resources/lib/python3.*"), None)
    if py_version is None:
        pytest.skip("bundle carries no bundled Python")
    site = py_version

    groups = {
        "interpreter": [libpython],
        "pyobjc": sorted(site.glob("lib-dynload/Quartz/CoreGraphics/*.so"))[:1],
        "onnxruntime": sorted(
            site.glob("onnxruntime/capi/*.so"))[:1] + sorted(
            site.glob("onnxruntime/capi/*.dylib"))[:1],
        "ffmpeg": sorted(site.glob("imageio_ffmpeg/binaries/ffmpeg-*"))[:1],
        "shiboken": sorted(site.glob("shiboken6/*.so"))[:1],
    }

    bit_less = False
    for group, files in groups.items():
        present = [f for f in files if f.is_file()]
        if not present:
            pytest.skip(f"bundle has no {group} to check")
        for path in present:
            bit_less |= not (path.stat().st_mode & 0o111)
            verify = subprocess.run(
                ["codesign", "--verify", "--strict", str(path)],
                capture_output=True, text=True,
            )
            assert verify.returncode == 0, (
                f"{group}: {path.name} is not signed "
                f"({verify.stderr.strip()}). Library validation refuses to "
                "load it, so the worker will not start, the autopaste will "
                "do nothing, or transcription will fail."
            )

    # Only meaningful while the sample still contains the files this was
    # written about. ONNX Runtime and shiboken ship executable; the
    # pyobjc lib-dynload modules and libpython3.12.dylib do not, and those
    # are exactly what an execute-bit selection drops.
    assert bit_less, (
        "none of the checked files lacks an execute bit any more, so this "
        "test no longer covers the selection bug it was written for"
    )
