"""The card every settings-shaped screen is built from.

Extracted from ``shortcuts_view`` rather than copied into it and
``profiles_view`` both. The card carries a page of hard-won layout
decisions — the explicit alignments below, and the row-wrap policy whose
comment records the measured numbers — and a second copy of it is a
second set of those decisions to keep in step. A rule written into one
card is a rule the other card quietly lacks, which is the same failure
this module exists to avoid.

Import from here. ``shortcuts_view`` re-exports ``_make_section_card``
so the name it has always had still resolves there.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)


def _slug(title: str) -> str:
    """"Audio input" -> "AudioInput", for an object name."""
    return "".join(ch for ch in title.title() if ch.isalnum())


def _make_section_card(title: str, parent: QWidget) -> tuple[QFrame, QFormLayout]:
    """Build a card-styled QFrame with a section title and an empty
    QFormLayout ready for rows.

    Returns ``(card, form)`` so the caller can keep adding rows. The
    title sits inside the card, above the form, with consistent
    padding.
    """
    card = QFrame(parent)
    card.setProperty("role", "card")
    # Named after the section it holds. The overflow tests report which
    # widget is setting this view's minimum width, and an unnamed
    # ``QFrame`` is not a thing anyone can go and look at — the two
    # cards that already set their own names are the only two the
    # failure message could name.
    card.setObjectName(_slug(title) + "Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(12)

    header = QLabel(title, card)
    header.setProperty("role", "section-header")
    layout.addWidget(header)

    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    # Both of these used to be written as
    # ``setLabelAlignment(labelAlignment())`` — read the default, hand it
    # straight back, and call it a setting. The catch is that the
    # default is a *platform* default, and the two platforms disagree.
    # Measured on this machine with this source and nothing else changed:
    #
    #   cocoa (what ships)   labelAlignment=2  AlignRight
    #   offscreen (CI)      labelAlignment=1  AlignLeft
    #
    # so on macOS every label on this page was pushed to the right edge
    # of its column — a flush right margin against ragged left, with
    # "Model", "Server" and "API key" each starting somewhere different.
    # On Windows and Linux it has always been left. The test suite could
    # not have caught it: it runs under ``QT_QPA_PLATFORM=offscreen``,
    # which is the one platform that already agreed with the intent.
    # The card looked fine in every test and in every offscreen render.
    #
    # Named outright, so the layout is the same shape everywhere and a
    # screenshot of the shipped app is a screenshot of what CI tested.
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)
    # WrapLongRows, not DontWrapRows. A form row's minimum width is
    # normally "label + spacing + field" — the label is a QLabel with
    # wordWrap off, so it reserves the full width of its text whether or
    # not there is anything to say next to it. On the Settings page that
    # made the minimum depend on the *sum* of three text widths, and the
    # sum is exactly the thing that differs between machines: measured on
    # Windows CI at text scale 1.75, 'Microphone' is 129px where a Mac
    # with the same stylesheet and the same bundled font measures 125px,
    # the test button 226 against 216, the combo 211 against 203. Same
    # +22px, same story, and the page overflowed its 900px floor by
    # exactly 2px. Nothing about that is a layout mistake; it is three
    # strings measuring 3-6% wider and a design that let them add up.
    #
    # With WrapLongRows a row is as wide as the *wider* of its two
    # halves, so a long field stops paying for a short label. Measured,
    # at every window width from 900 to 1920 and at both text scales:
    # the AudioInputCard's minimum drops 612 -> 487 at 1.75 (480 -> 350
    # at 1.0), and all nine labels stay beside their fields — the policy
    # only stacks a label above its field when the label is the wider of
    # the two, which no label on this page is. 487 is also the floor for
    # this card: the width is now exactly its widest field row, with
    # nothing left to remove without shortening a control's text.
    #
    # The behaviour this replaces is graceful rather than abrupt: a
    # window too narrow for both halves stacks the label above the field
    # instead of pushing a horizontal scrollbar onto the page.
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    layout.addLayout(form)
    return card, form
