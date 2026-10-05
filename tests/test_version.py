"""Tests for the project version.

The version lives in five places, and the release only works if they
agree.  Nothing in the build fails when they don't: ``pyproject.toml``
drives the wheel, ``setup.py`` drives the py2app bundle, and
``CFBundleShortVersionString`` is what Finder and the macOS privacy
pane show.  A bundle that calls itself 0.0.1 inside a release tagged
v0.1.0 ships a wrong answer to the only question a user can check
without running anything.
"""

from __future__ import annotations

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


def _setup_py_versions() -> dict[str, str]:
    text = (_ROOT / "setup.py").read_text(encoding="utf-8")
    found = {}
    for key in ("CFBundleVersion", "CFBundleShortVersionString"):
        found[key] = re.search(rf'"{key}":\s*"([^"]+)"', text).group(1)
    found["setup()"] = re.search(r'version="([^"]+)"', text).group(1)
    return found


def _about_fallback() -> str:
    """The hardcoded fallback the About dialog uses with no metadata."""
    text = (_ROOT / "app" / "gui" / "main_window.py").read_text(encoding="utf-8")
    found = re.findall(r'version = "([^"]+)"', text)
    assert found, "no hardcoded fallback found in the About dialog"
    return found[0]


def test_every_place_that_names_the_version_agrees():
    """pyproject, both Info.plist keys, the py2app version, and the
    About dialog's fallback must all be the same string."""
    canonical = _pyproject_version()
    others = _setup_py_versions()
    others["About fallback"] = _about_fallback()

    wrong = {where: v for where, v in others.items() if v != canonical}
    assert not wrong, (
        f"pyproject.toml says {canonical} but {wrong} — the wheel, the "
        f"macOS bundle and the About dialog would each report a "
        f"different version"
    )


def test_the_version_matches_the_newest_release_tag():
    """A tag is a promise about a version.

    Only checked when a ``v*`` tag exists — a source checkout with no
    release yet has nothing to disagree with.  The newest tag by commit
    order is the one the working tree is expected to carry, since
    ``prod`` is what gets tagged.
    """
    try:
        out = subprocess.run(
            ["git", "tag", "--list", "v*", "--sort=-creatordate"],
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
