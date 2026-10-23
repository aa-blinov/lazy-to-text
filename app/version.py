"""The one place that answers "which version is this?".

The string lives in ``pyproject.toml`` and the About dialog used to
re-derive it inline every time it was needed, with a hardcoded
fallback duplicated on each of its two failure branches. Adding a
second reader meant either a third copy or a second way to be wrong.

``tests/test_version.py`` pins the fallback here, which is why this
module owns it rather than the widget that happens to display it.
"""

from __future__ import annotations

# Used when the distribution metadata cannot be read: a raw checkout
# (``uv run`` without an install) and any environment where
# ``importlib.metadata`` itself is unavailable. Pinned by
# ``tests/test_version.py`` against ``pyproject.toml``.
_FALLBACK = "0.1.20"


def current_version() -> str:
    """The installed version, or the pinned fallback.

    Never raises: this is read from a footer label and from a dialog,
    and a version string that crashes the UI is worse than one that is
    approximate. ``importlib.metadata`` is imported inside the guard
    because its absence is exactly one of the cases being handled.
    """
    try:
        from importlib.metadata import version as _pkg_version

        try:
            return _pkg_version("lazy-to-text")
        except Exception:
            # PackageNotFoundError, and whatever a partial install
            # raises instead of it.
            return _FALLBACK
    except Exception:
        return _FALLBACK
