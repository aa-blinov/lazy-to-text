"""The overflow diagnostics have to survive being wrong.

``explain_width`` is only ever called from inside a failing assertion,
so on a healthy machine it never runs. That is exactly how the first
version of it shipped with an ``AttributeError`` in it: the code was
wrong, the suite was green, and the mistake would only have surfaced on
the one platform whose failure message needed it. These tests run it
directly, on both kinds of form row Qt can hand back.

TRAP worth restating: ``_explain`` reports the single widest descendant,
so a form row only gets walked when *its own card* is the widest thing
in the container. Put both row shapes in one container and the second
one is never reached — which is how the first version of the test below
passed against a helper that crashed on the bare-widget row.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import (
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@pytest.fixture
def nested_field_card(qapp):
    """A card whose field holds a nested layout of two buttons.

    This is the production shape: the Settings microphone row is a
    ``QHBoxLayout`` of combo + button inside the form.
    """
    outer = QWidget()
    outer_layout = QVBoxLayout(outer)

    card = QFrame(outer)
    card.setObjectName("DemoCard")
    form = QFormLayout(card)
    form.setHorizontalSpacing(16)

    row_field = QHBoxLayout()
    row_field.setSpacing(10)
    row_field.addWidget(QPushButton("Test microphone", card))
    row_field.addWidget(QPushButton("x", card))
    form.addRow("Microphone", row_field)

    outer_layout.addWidget(card)
    return outer


@pytest.fixture
def bare_field_card(qapp):
    """A card whose field is a bare widget, not a nested layout.

    Qt wraps this one in a ``QWidgetItem``, which has no ``count()``.
    """
    outer = QWidget()
    outer_layout = QVBoxLayout(outer)

    card = QFrame(outer)
    card.setObjectName("PlainCard")
    form = QFormLayout(card)
    form.addRow("", QPushButton("A much longer bare button", card))

    outer_layout.addWidget(card)
    return outer


def test_names_the_widest_widget_and_its_row(qapp, explain_width, nested_field_card):
    ladder = explain_width(nested_field_card)
    assert "DemoCard" in ladder
    # Level two: which row of the form is setting the width.
    assert "row 0" in ladder
    assert "'Microphone'" in ladder
    # Level three: which widget inside that row's field, named by the
    # text it shows rather than by its class.
    assert "Test microphone" in ladder


def test_a_bare_widget_field_does_not_crash_the_diagnostic(
    qapp, explain_width, bare_field_card
):
    """Reaching for ``count()`` on a ``QWidgetItem`` raises
    ``AttributeError`` — inside a failure message, which is the worst
    possible place for it.
    """
    ladder = explain_width(bare_field_card)
    assert ladder != "?"
    # No ``row`` detail is owed here — a bare widget has no layout to
    # descend into — but the widget itself must still be named, by the
    # text it shows rather than by its class.
    assert "A much longer bare button" in ladder


def test_survives_a_container_with_nothing_in_it(qapp, explain_width):
    empty = QWidget()
    assert explain_width(empty) == "?"
