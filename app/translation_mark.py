"""``mark``: flag a source string for the translation catalogue.

Lives apart from ``app.language`` because that module is built on Qt's
translator, and the headless runtime has to import the model catalogue
(which marks its strings) without importing PySide6.
"""

from __future__ import annotations


def mark(context: str, source: str) -> str:
    """Return ``source`` unchanged; marks it for the catalogue extractor."""
    return source
