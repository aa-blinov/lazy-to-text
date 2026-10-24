"""``mark``: flag a source string for the translation catalogue.

The headless runtime imports the model catalogue and the hotkey rules, which
mark their strings, so the marker has to be a plain function with no
translator behind it. ``scripts/check_translations.py`` reads the calls.
"""

from __future__ import annotations


def mark(context: str, source: str) -> str:
    """Return ``source`` unchanged; marks it for the catalogue extractor."""
    return source
