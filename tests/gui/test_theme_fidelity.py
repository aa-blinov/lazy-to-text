"""The bars follow the theme that is active, not the one that was active
at import.

Found by measuring pixels in a screenshot of the running app: on the
light theme the CPU and RAM bars carried the dark palette's green
(``#b8bb26``, measured ``#b4b704``), its amber (``#d79921``, measured
``#e19605``) and its near-black track (``#282828``, measured
``#282826``) — on a cream window.

The cause is the ordinary kind. These colours were module-level
``QColor`` objects, so they were resolved once, at import, while the
dark palette was live; the theme swap replaces the *contents* of
``TOKENS.colors`` in place, so a reference to the dict stays correct and
a copy of its values does not.

What made this invisible to the suite is that the offscreen legs run one
theme per test file. Reading the constant, or calling the helper and
comparing against the same frozen object, passes on both themes without
ever asking which theme is in force.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def light_theme(qapp):
    """Switch to light and hand the palette back afterwards.

    Restored through ``load_stylesheet``, not by writing ``TOKENS`` by
    hand: the token swap is the code under test's neighbour and the
    identity ``TOKENS.colors`` keeps is the whole reason this bug was
    possible.
    """
    from app.gui.theme import load_stylesheet

    try:
        yield load_stylesheet("light")
    finally:
        load_stylesheet("dark")


def _pixels(image):
    return {image.pixelColor(x, y).name() for x in range(image.width())
            for y in range(image.height())}


def _bar_rows(widget):
    """The y band the progress bars occupy, derived not hard-coded.

    ``_paint_block`` puts the bar below the label half; recomputing it
    here means a change to the layout moves the probe with it instead of
    quietly sampling the label text and finding nothing.
    """
    block = widget._block_specs()[0]
    assert block is not None
    top_h = widget.height() // 2
    return range(top_h + 2, top_h + 7)


def test_the_cpu_bar_is_painted_with_the_light_palette(light_theme, qtbot):
    from app.gui.theme import TOKENS
    from app.gui.widgets.resource_widget import ResourceWidget

    widget = ResourceWidget()
    qtbot.addWidget(widget)
    widget.set_metrics({"cpu_percent": 50.0, "ram_percent": 50.0})
    widget.resize(widget.sizeHint())
    widget.show()

    painted = _pixels(widget.grab().toImage())
    light = TOKENS.colors
    dark_only = {
        value
        for key, value in (("bg_secondary", "#282828"), ("success", "#b8bb26"))
    }
    assert not (painted & dark_only), (
        f"dark-palette colours on a light widget: {sorted(painted & dark_only)}"
    )
    assert light["bg_secondary"] in painted
    assert light["success"] in painted
    assert light["bg_elevated"] in painted


def test_the_same_widget_under_dark_keeps_the_dark_palette(qtbot):
    """The other half of the pair, so the test above cannot pass by the
    widget simply having no colours at all."""
    from app.gui.theme import load_stylesheet
    from app.gui.widgets.resource_widget import ResourceWidget

    load_stylesheet("dark")
    widget = ResourceWidget()
    qtbot.addWidget(widget)
    widget.set_metrics({"cpu_percent": 50.0, "ram_percent": 50.0})
    widget.resize(widget.sizeHint())
    widget.show()

    painted = _pixels(widget.grab().toImage())
    assert "#282828" in painted
    assert "#b8bb26" in painted


def test_a_log_line_is_baked_in_the_palette_that_is_active(light_theme):
    """``_format_record_html`` writes colours into HTML.

    QPlainTextEdit does not honour QSS, so the values are inlined as
    ``style="color:#..."`` and there is nothing to repaint afterwards —
    a line rendered before a theme switch keeps its old ink forever.
    """
    from app.gui.theme import TOKENS
    from app.gui.views.logs_view import _format_record_html

    html = _format_record_html("12:00:00", "INFO", "app.state_manager", "hi", True)
    assert TOKENS.colors["accent"] in html
    assert TOKENS.colors["text_primary"] in html
    assert "#b8bb26" not in html and "#83a598" not in html


def test_the_vu_meter_is_painted_with_the_light_palette(light_theme, qtbot):
    from app.gui.theme import TOKENS
    from app.gui.widgets.vu_meter import VUMeter

    meter = VUMeter()
    qtbot.addWidget(meter)
    meter.set_level(0.3)   # below the 0.5 threshold, so the green band
    meter.show()

    painted = _pixels(meter.grab().toImage())
    assert TOKENS.colors["bg_elevated"] in painted
    assert TOKENS.colors["success"] in painted
    assert "#b8bb26" not in painted