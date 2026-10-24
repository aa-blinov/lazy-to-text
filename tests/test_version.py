"""Tests for the project version.

The version lives in six places, and the release only works if they
agree.  Nothing in the build fails when they don't: ``pyproject.toml``
drives the wheel, ``setup.py`` drives the py2app bundle, and
``CFBundleShortVersionString`` is what Finder and the macOS privacy
pane show.  A bundle that calls itself 0.0.1 inside a release tagged
v0.1.0 ships a wrong answer to the only question a user can check
without running anything — and the version footer at the bottom of
Settings is that question, asked where users actually look.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert match, "pyproject.toml has no top-level version"
    return match.group(1)


def _exactly_one(pattern: str, text: str, where: str) -> str:
    """The single version *text* names for *where*.

    ``findall`` and a count, not ``search``: ``search`` returns the
    first match and says nothing about the rest, so a second version in
    the same file is a version the test never looks at.
    """
    found = re.findall(pattern, text)
    assert len(found) == 1, (
        f"{where} matches {pattern!r} {len(found)} times ({found}) — the "
        f"test can only hold one of them to the version, so make the "
        f"pattern unambiguous"
    )
    return found[0]


def _setup_py_versions() -> dict[str, str]:
    text = (_ROOT / "setup.py").read_text(encoding="utf-8")
    found = {}
    for key in ("CFBundleVersion", "CFBundleShortVersionString"):
        found[key] = re.search(rf'"{key}":\s*"([^"]+)"', text).group(1)
    found["setup()"] = _exactly_one(r'version="([^"]+)"', text, "setup.py")
    return found


def _version_fallback() -> str:
    """The hardcoded fallback in ``app/version.py``.

    It used to live in the About dialog, twice — once on the
    ``PackageNotFoundError`` branch and once on the outer
    ``except Exception`` — and reading only the first let the second
    drift. The logic now has one home, so there is one string, and
    this is an exact-count match rather than a search: a second copy
    is the bug this function was written to catch, and it would come
    back the day someone adds a third reader.
    """
    text = (_ROOT / "app" / "version.py").read_text(encoding="utf-8")
    found = re.findall(r'_FALLBACK = "([^"]+)"', text)
    assert len(found) == 1, (
        f"app/version.py declares {len(found)} hardcoded fallbacks "
        f"({found}) — there is one answer to \"which version is this?\" "
        "and it lives in current_version()"
    )
    return found[0]


def test_every_place_that_names_the_version_agrees():
    """pyproject, both Info.plist keys, the py2app version, the
    version helper's fallback and the Electron package must all be
    the same string."""
    canonical = _pyproject_version()
    others = _setup_py_versions()
    others["app/version.py fallback"] = _version_fallback()
    others["desktop/package.json"] = json.loads(
        (_ROOT / "desktop" / "package.json").read_text(encoding="utf-8"))["version"]

    wrong = {where: v for where, v in others.items() if v != canonical}
    assert not wrong, (
        f"pyproject.toml says {canonical} but {wrong} — the wheel, the "
        f"macOS bundle and the UI would each report a "
        f"different version"
    )


def test_the_version_matches_the_newest_release_tag():
    """A tag is a promise about a version.

    Only checked when a ``v*`` tag exists — a source checkout with no
    release yet has nothing to disagree with.  Sorted by *version*, not
    by creation date: a back-port tag cut after a newer release is older
    code but a later ``creatordate``, and asking the tree for that older
    version would fail every commit from then on.
    """
    try:
        out = subprocess.run(
            ["git", "tag", "--list", "v*", "--sort=-version:refname"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.split()
    except (subprocess.SubprocessError, OSError):
        pytest.skip("git is unavailable, so the tags cannot be read")

    if not out:
        pytest.skip("no release tag yet — nothing for the version to match")

    newest = out[0]
    assert newest.lstrip("v") == _pyproject_version(), (
        f"the newest release tag is {newest} but the tree says "
        f"{_pyproject_version()} — cut the next tag, or say so here"
    )


def test_the_runtime_reports_the_version_the_tree_declares():
    """What the footer and the About dialog show has to be the real one.

    ``importlib.metadata`` answers from whatever distribution metadata
    it reaches first, which is not always this checkout: a venv
    installed before a version bump keeps serving the old number, and
    this test's first run read 0.1.3 from a tree that declared 0.1.4.

    That is the failure worth naming. Every other test here compares
    strings in the repository, and all of them passed while the app
    confidently displayed the wrong build to the user — who then quotes
    it in a bug report. A version that lies is worse than none, because
    it is believed.

    Passes both ways round: an uninstalled checkout has no metadata and
    ``current_version()`` falls back to the pinned string, which this
    same file already holds to pyproject.
    """
    from app.version import current_version

    reported = current_version()
    assert reported == _pyproject_version(), (
        f"the running app would report {reported!r} but pyproject.toml "
        f"says {_pyproject_version()!r} — stale installed metadata. "
        "Run `uv sync --frozen`; the venv is serving a pre-bump install."
    )
