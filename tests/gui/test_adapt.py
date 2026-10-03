"""Layout adapts across window sizes and text scales — as measured, not assumed.

This suite exists because of how it was originally written. The first
attempt at these assertions reported three defects — a 380px horizontal
overflow in Settings, a 4px clip in the History table, and a language
dropdown collapsed to 16px — and **every one of them was a measurement
artifact**, not a bug:

* ``QStackedWidget`` only lays out its *current* page. Scanning widgets
  on the four non-current views returned their un-laid-out default
  geometry (a never-sized widget is 100px wide, a never-sized combo 16px),
  which reads exactly like a squeeze.
* ``HistoryView`` starts on its empty state, so the table page never
  received geometry until entries exist.
* ``InferenceSettingsPanel`` is hidden on every card until one becomes
  active, so its grid was never laid out either.

Once the views are made current and populated, all three measure clean
from 900px to 2560px at every text scale. So these tests do the setup
that makes the measurement real, and then assert the baseline — which
is both a regression guard and a guard against the next audit repeating
the false finding.
"""

from __future__ import annotations

import datetime
from typing import List

import pytest
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QScrollArea,
    QSpinBox,
    QTableView,
)

# 900x620 is the MainWindow floor (main_window.setMinimumSize); 1100x780
# is the default it opens at; the rest are ordinary desktop sizes.
WINDOW_SIZES = ((900, 620), (1100, 780), (1280, 800), (1920, 1080), (2560, 1440))
TEXT_SCALES = (1.0, 1.15, 1.3, 1.5, 1.75)

#: Below this a control is rendered but not usable — a dropdown showing
#: 16px of its first character is broken, not tight.
MIN_USABLE_COMBO_PX = 70
MIN_USABLE_SPIN_PX = 50


class _Entry:
    """Minimal stand-in for a history record."""

    def __init__(self, index: int) -> None:
        self.text = (
            f"Транскрипция номер {index} — проверка переноса длинного "
            f"текста в колонке таблицы истории."
        )
        self.timestamp = datetime.datetime(2026, 10, 3, 21, index, 0)
        self.model = "GigaAM v3 CTC (Russian, punctuated)"
        self.language = "Russian (only)"
        self.duration_s = 3.4 + index


@pytest.fixture
def laid_out(qapp, qtbot):
    """A window with every view *current, populated and visible*.

    Returns a ``show(view_index)`` callable. Everything the measurement
    depends on — the stack on the right page, the history table instead
    of its empty state, the inference panel on an active card — is set
    up here, because skipping any of it produces plausible-looking but
    meaningless geometry.
    """
    from app.gui.main_window import MainWindow
    from app.gui.theme import apply_theme, load_stylesheet, set_text_scale
    from app.gui.widgets.inference_settings_panel import (
        InferenceSettingsPanel,
    )
    from app.gui.widgets.model_card import ModelCard

    set_text_scale(1.0)
    apply_theme(qapp, "dark")
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    keys = list(window.sidebar.items())
    history = window.get_view("history")
    history.set_entries([_Entry(i) for i in range(12)])

    models = window.get_view("models")
    card = models.findChildren(ModelCard)[0]
    assert card.findChild(InferenceSettingsPanel) is not None

    def show(view_index: int) -> None:
        window.stack.setCurrentIndex(view_index)
        card.set_active(True)
        # Two passes: the first lays the stack out, the second settles
        # the child geometry inside it.
        qapp.processEvents()
        qapp.processEvents()

    show(keys.index("models"))
    # Leaving the panel expanded on a card the user is not looking at
    # would be a lying measurement in the other direction.
    window.stack.setCurrentIndex(keys.index("models"))
    card.set_active(True)
    qapp.processEvents()

    window._l2t = {
        "keys": keys,
        "history": history,
        "models": models,
        "card": card,
        "show": show,
        "set_text_scale": set_text_scale,
        "load_stylesheet": load_stylesheet,
    }
    return window


def _overflow_problems(window, view_index: int) -> List[str]:
    """Everything in the current view that is squeezed or clipped."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance().processEvents()
    view = window.stack.widget(view_index)
    problems: List[str] = []

    for area in view.findChildren(QScrollArea):
        content = area.widget()
        if content is None or content.width() <= 0:
            # Never laid out — skip rather than report a false squeeze.
            continue
        over = content.minimumSizeHint().width() - area.viewport().width()
        if over > 0:
            problems.append(f"scroll content needs {over}px more width")

    for table in view.findChildren(QTableView):
        if not table.isVisible():
            continue
        if table.horizontalScrollBar().maximum() > 0:
            problems.append(
                f"table scrolls {table.horizontalScrollBar().maximum()}px sideways"
            )

    # Only *visible* controls can be squeezed. A Models view holds nine
    # cards and each carries its own inference panel; the eight inactive
    # ones are hidden and were never laid out, so their controls report
    # Qt's never-sized defaults. Measuring them is how this suite's first
    # draft produced its three phantom defects.
    for combo in view.findChildren(QComboBox):
        if not combo.isVisible():
            continue
        if combo.width() < MIN_USABLE_COMBO_PX:
            problems.append(f"combo {combo.objectName() or '?'} is {combo.width()}px")

    spins = view.findChildren(QSpinBox) + view.findChildren(QDoubleSpinBox)
    for spin in spins:
        if not spin.isVisible():
            continue
        if spin.width() < MIN_USABLE_SPIN_PX:
            problems.append(f"spin {spin.objectName() or '?'} is {spin.width()}px")

    return problems


@pytest.mark.parametrize("width,height", WINDOW_SIZES)
def test_no_view_overflows_at_any_window_size(laid_out, width, height):
    window = laid_out
    keys, show = window._l2t["keys"], window._l2t["show"]
    window.resize(width, height)
    show(0)

    for index, key in enumerate(keys):
        show(index)
        problems = _overflow_problems(window, index)
        assert not problems, f"{key} at {width}x{height}: {'; '.join(problems)}"


@pytest.mark.parametrize("scale", TEXT_SCALES)
def test_text_scale_does_not_break_the_layout(laid_out, scale):
    """A larger text size grows the reading surface; it must never cost
    width, because that is what turns a tight row into a broken one."""
    window = laid_out
    keys, show = window._l2t["keys"], window._l2t["show"]
    set_scale = window._l2t["set_text_scale"]
    load_qss = window._l2t["load_stylesheet"]
    from PySide6.QtWidgets import QApplication

    window.resize(900, 620)
    set_scale(scale)
    QApplication.instance().setStyleSheet(load_qss("dark"))
    show(0)

    for index, key in enumerate(keys):
        show(index)
        problems = _overflow_problems(window, index)
        assert not problems, (
            f"{key} at text scale {scale}: {'; '.join(problems)}"
        )


def test_inference_panel_controls_stay_usable(laid_out):
    """Named because it is the panel most likely to regress: a long VAD
    label sharing a row with the language dropdown used to look like a
    squeeze. Asserted explicitly so the reason is on the record."""
    from app.gui.widgets.inference_settings_panel import (
        InferenceSettingsPanel,
    )

    window = laid_out
    card = window._l2t["card"]
    window.resize(900, 620)
    window._l2t["show"](window._l2t["keys"].index("models"))
    card.set_active(True)
    from PySide6.QtWidgets import QApplication

    QApplication.instance().processEvents()

    panel = card.findChild(InferenceSettingsPanel)
    assert panel is not None and panel.isVisible()

    for combo in panel.findChildren(QComboBox):
        assert combo.width() >= MIN_USABLE_COMBO_PX, combo.objectName()
    for spin in panel.findChildren(QSpinBox) + panel.findChildren(
        QDoubleSpinBox
    ):
        assert spin.width() >= MIN_USABLE_SPIN_PX, spin.objectName()
