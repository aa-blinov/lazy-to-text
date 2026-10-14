"""UI language: English (the source strings) or Russian, switched at runtime.

Strings in the code are the English source, marked for translation with
``self.tr(...)`` or ``QCoreApplication.translate(context, ...)``. Russian is
a compiled Qt catalogue, ``app/i18n/app_ru.qm``, built from
``app/i18n/app_ru.ts``.

Switching installs a different ``QTranslator``. Qt then sends
``LanguageChange`` to every QWidget, so widgets that set their text in
``__init__`` re-read it. QObjects that Qt does not reach that way (the tray
menu, list items) listen to ``bus.language_changed`` instead.
"""

from __future__ import annotations

import logging
import weakref
from typing import Any, Optional

from PySide6.QtCore import QCoreApplication, QObject, QTranslator, Signal

from app.utils import resolve_asset_path

log = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "en"
SUPPORTED: tuple[str, ...] = ("en", "ru")

# Names as they are written in each language, so a user who has landed on
# the wrong language can still find their own in the list.
NATIVE_NAMES: dict[str, str] = {"en": "English", "ru": "Русский"}


class _LanguageBus(QObject):
    language_changed = Signal(str)


bus = _LanguageBus()

_translator: Optional[QTranslator] = None
_current: str = DEFAULT_LANGUAGE


def normalise_language(value: object) -> str:
    """Unknown or empty values fall back to English, never raise."""
    code = str(value or "").strip().lower()
    return code if code in SUPPORTED else DEFAULT_LANGUAGE


def current_language() -> str:
    return _current


def apply_language(app, value: object) -> str:
    """Make ``value`` the UI language and return the language now in effect.

    A catalogue that is missing or unreadable leaves the UI in English and
    says so in the log, rather than failing the switch.
    """
    global _translator, _current

    code = normalise_language(value)
    if _translator is not None:
        app.removeTranslator(_translator)
        _translator = None

    if code != DEFAULT_LANGUAGE:
        translator = QTranslator(app)
        catalogue = resolve_asset_path(f"i18n/app_{code}.qm")
        if translator.load(catalogue):
            app.installTranslator(translator)
            _translator = translator
        else:
            log.warning("Translation catalogue not readable: %s", catalogue)
            code = DEFAULT_LANGUAGE

    _current = code
    bus.language_changed.emit(code)
    return code


# ---- live text bindings ----------------------------------------------------
#
# Qt re-sends LanguageChange to widgets, but a widget only reacts if it
# handles it. Most views here set their text once, in __init__. ``bind``
# records where a text came from, so a switch can re-apply every such text
# without rebuilding the view or losing its state.

_bindings: list[tuple[Any, str, str, str]] = []


def tr_text(context: str, source: str) -> str:
    return QCoreApplication.translate(context, source)


def bind(obj: Any, setter: str, context: str, source: str) -> None:
    """Apply ``source`` through ``obj.<setter>`` now and on every switch.

    ``context`` and ``source`` are literals: ``scripts/update_translations.py``
    reads them from the call sites to build the catalogue.
    """
    getattr(obj, setter)(tr_text(context, source))
    _bindings.append((weakref.ref(obj), setter, context, source))


def _reapply(_language: str = "") -> None:
    alive = []
    for ref, setter, context, source in _bindings:
        obj = ref()
        if obj is None:
            continue
        try:
            getattr(obj, setter)(tr_text(context, source))
        except RuntimeError:
            # The C++ object was deleted while the Python wrapper lived on.
            continue
        alive.append((ref, setter, context, source))
    _bindings[:] = alive


bus.language_changed.connect(_reapply)
