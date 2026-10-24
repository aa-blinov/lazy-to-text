"""The Russian catalogue is the renderer's JSON; nothing else feeds it.

``scripts/check_translations.py`` finds every string the renderer passes to
``$t`` and every sentence Python marks with ``mark()``; each must have a
Russian entry, or it ships in English.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_translations", ROOT / "scripts" / "check_translations.py"
)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def test_every_marked_and_rendered_string_has_a_russian_entry():
    absent = check.missing()
    assert not absent, "no Russian entry for: " + "; ".join(sorted(absent))


def test_the_check_sees_both_kinds_of_string():
    # A scanner that finds nothing would pass the test above for the wrong reason.
    assert len(check.renderer_strings()) > 100
    assert len(check.python_strings()) > 20


def test_the_check_notices_a_missing_entry(monkeypatch):
    monkeypatch.setattr(check, "catalogue", lambda: {})
    assert check.missing()


def test_a_translation_keeps_the_placeholders_of_its_source():
    broken = []
    for source, target in check.catalogue().items():
        for pattern in (r"%\d", r"\{\w+\}"):
            if sorted(re.findall(pattern, source)) != sorted(re.findall(pattern, target)):
                broken.append(source)
    assert not broken, broken


def test_no_entry_is_empty():
    assert all(v.strip() for v in check.catalogue().values())


def test_the_qt_catalogue_is_gone():
    assert not (ROOT / "app" / "i18n").exists()
