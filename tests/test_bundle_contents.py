"""Tests for what the release bundle is allowed to contain.

Two things about the macOS bundle are only knowable by building it,
and both of them cost a 1.5 GB build to learn:

1. ``_PACKAGES`` must name the bare ``"PySide6"``. Naming the
   submodules — ``"PySide6.QtCore"`` and friends — reads like it would
   bundle less, and it builds without a word, but the bundle does not
   start: py2app looks for a directory literally named
   ``PySide6.QtCore`` and the wheel has no such thing. The failure is
   a ``FileNotFoundError`` for a ``__init__.pyc`` at launch.

2. The bare name is what drags QtWebEngineCore — 589 MB — into a
   widgets application that never opens a web view, and nothing here
   changes that. py2app copies the whole ``PySide6/Qt`` tree either
   way. The download is 539 MB zipped; the installed bundle is 1.5 GB.

Neither fact is discoverable from the test suite, and neither is
enforced by the build failing. So they are written down here.
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
    missing ``.pyc`` in a 1.5 GB artifact that only a human launching
    it would hit.
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


def test_the_macos_bundle_carries_qt_it_never_imports():
    """The dead weight is real, measured, and still there.

    Written as a measurement rather than a wish, because the belief
    that a better ``_PACKAGES`` list would remove it was tested and
    wrong: 1.5 GB with the bare package, 1.5 GB with the submodules.
    Skipped unless a built bundle is present to look at — a test that
    asserts a number it cannot reach quietly stops being a test.

    If this ever fails, a prune step has landed and the size figures in
    ``setup.py``, ``README.md`` and ``docs/index.html`` are now wrong in
    the other direction.
    """
    resources = (
        _ROOT / "dist" / "Lazy to Text.app" / "Contents" / "Resources"
    )
    if not resources.is_dir():
        pytest.skip("no built bundle in dist/ — nothing to measure")

    qt_lib = next(iter(resources.glob("lib/python3.*/PySide6/Qt/lib")), None)
    if qt_lib is None or not qt_lib.is_dir():
        pytest.skip("this bundle carries no Qt libraries to measure")

    assert (qt_lib / "QtWebEngineCore.framework").is_dir(), (
        "QtWebEngineCore is gone from the bundle — good news, and it means "
        "the prune step landed. Re-measure and update the size figures."
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
