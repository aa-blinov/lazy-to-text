"""The sidebar icons are drawn from tokens, in the colour their row needs.

The icons were the last place in the app with no route to the palette.
Each SVG carried a baked stroke — ``#f5f6f8``, from the palette that
shipped before Gruvbox — and nothing could reach it: QSS ``color`` never
paints a ``QIcon``'s pixels, and the ``::item`` colour rules that darken
a selected row's *label* left its *icon* at the old near-white. On a
cream ``accent_focus`` pill that is 1.51:1, and it is why the sidebar
read as washed out.

The fix is that the stroke in the file is a placeholder like any other
and the pixmap is rasterised in the colour the row calls for. These
tests pin the three things that made that true:

1. No SVG carries a hex stroke (the tray templates are the one documented
   exception — macOS tints those itself).
2. The resolver refuses a hex and takes a token name, so the second
   source of truth cannot be reintroduced through the new API.
3. A selected row's icon is the *ground*, not Ink Primary — which is the
   exact regression, asserted on rendered pixels.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QListWidget, QWidget

from app.gui.theme import TOKENS, _STYLES_DIR, resolve_icon_svg

# These three are rendered as macOS template images: pure black on
# transparent, flagged QIcon.setIsMask(True), and the OS tints them per
# appearance. `currentColor` is how they are meant to be read — it is not
# an unresolved placeholder that someone forgot.
TRAY_TEMPLATES = {"microphone.svg", "microphone-solid.svg", "arrow-path.svg"}


@pytest.fixture(autouse=True)
def _qapp(qtbot):
    """Offscreen Qt aborts without a QApplication."""


@pytest.fixture
def sidebar(qtbot):
    from app.gui.theme import load_stylesheet
    from app.gui.widgets.sidebar import Sidebar

    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(load_stylesheet("dark"))
    try:
        window = QWidget()
        qtbot.addWidget(window)
        window.resize(320, 700)
        side = Sidebar(parent=window)
        window.show()
        window.activateWindow()
        QApplication.processEvents()
        yield side
    finally:
        app.setStyleSheet(previous)


# --- the assets ---------------------------------------------------------


def test_no_bundled_svg_carries_a_hex_stroke():
    """The file is a template; the colour arrives at raster time.

    A hex here is the bug this whole module exists for, and it is
    invisible in review — the file looks complete and renders fine, it
    is just permanently one palette behind.
    """
    offenders = []
    for svg in sorted((_STYLES_DIR / "icons").glob("*.svg")):
        source = svg.read_text(encoding="utf-8")
        stroke = re.search(r'stroke="([^"]*)"', source)
        if not stroke:
            continue
        value = stroke.group(1)
        if value in ("none", "currentColor"):
            continue
        if re.fullmatch(r"#[0-9a-fA-F]{3,8}", value):
            offenders.append(f"{svg.name}: {value}")
    assert offenders == [], f"baked hex strokes: {offenders}"


def test_icons_that_need_a_colour_declare_one():
    """Each stroke is either a tray template or a token placeholder."""
    missing = []
    for svg in sorted((_STYLES_DIR / "icons").glob("*.svg")):
        if svg.name in TRAY_TEMPLATES:
            continue
        source = svg.read_text(encoding="utf-8")
        stroke = re.search(r'stroke="([^"]*)"', source)
        if stroke is None or not stroke.group(1).startswith("{{color."):
            missing.append(svg.name)
    assert missing == [], f"no token placeholder in: {missing}"


# --- the resolver -------------------------------------------------------


def test_resolver_takes_a_token_name_and_refuses_a_hex():
    """The API is the thing that keeps hexes out.

    ``resolve_icon_svg(..., "#83a598")`` is the obvious future caller and
    it would quietly restore the bug, so it raises instead.
    """
    with pytest.raises(KeyError):
        resolve_icon_svg("models.svg", "#83a598")


def test_resolver_substitutes_the_requested_token():
    svg = resolve_icon_svg("models.svg", "bg_primary")
    assert TOKENS.colors["bg_primary"] in svg
    assert "{{color." not in svg


def test_resolver_leaves_the_file_untouched_on_disk():
    """Resolution is in memory or in the cache, never in the bundle.

    A frozen build's styles directory is read-only, and a dev checkout's
    is not ours to rewrite — the placeholder has to survive a round trip.
    """
    source = (Path(_STYLES_DIR) / "icons" / "models.svg").read_text(
        encoding="utf-8"
    )
    assert "{{color." in source


# --- the rendering ------------------------------------------------------


def _icon_colours(item) -> set[str]:
    """Every exact colour painted in an item's Normal and Selected pixmap."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon

    seen = set()
    for mode in (QIcon.Normal, QIcon.Selected):
        pm = item.icon().pixmap(QSize(20, 20), mode)
        if pm.isNull():
            continue
        img = pm.toImage()
        for y in range(img.height()):
            for x in range(img.width()):
                seen.add(img.pixelColor(x, y).name())
    return seen


def test_selected_row_icon_is_the_ground_not_ink_primary(sidebar):
    """The regression, stated as pixels.

    The selected row's fill is the accent — or accent_focus under
    keyboard focus, which is a light cream. Ink Primary on that fill is
    2.37:1 at best and 1.51:1 at worst. The ground is 6.09:1 and 9.56:1.
    """
    nav = sidebar._list
    item = nav.item(0)
    colours = _icon_colours(item)

    assert TOKENS.colors["bg_primary"] in colours, (
        "the selected row's icon is not the ground colour"
    )
    assert TOKENS.colors["text_primary"] not in colours, (
        "Ink Primary is on a saturated fill; that is the Ink-on-Fill "
        "violation this row is supposed to be the counter-example to"
    )


def test_resting_icon_is_ink_secondary(sidebar):
    """Resting nav items stay quiet — the accent is rationed."""
    colours = _icon_colours(sidebar._list.item(0))
    assert TOKENS.colors["text_secondary"] in colours


def test_hover_tints_the_icon_to_ink_primary(sidebar):
    """Hover moves the icon with the label, not behind it.

    Qt documents ``QIcon::Active`` as the mode for a hovered item and
    this list never reaches it — measured against a three-colour icon
    under a real ``QTest.mouseMove``, the delegate rendered a hovered
    row with ``Normal`` and a selected row with ``Selected``, and
    ``Active`` never appeared. So the sidebar applies it directly.
    """
    from app.gui.widgets.sidebar import _ICON_HOVER

    nav = sidebar._list
    item = nav.item(0)
    sidebar._apply_icon_hover(item)
    QApplication.processEvents()

    assert TOKENS.colors[_ICON_HOVER] in _icon_colours(item)

    sidebar._apply_icon_hover(None)
    QApplication.processEvents()
    assert TOKENS.colors[_ICON_HOVER] not in _icon_colours(item), (
        "the row that lost the pointer kept the hover tint"
    )


def test_every_nav_item_has_an_icon(sidebar):
    """Five labels, five glyphs — a missing file degrades to a blank
    slot, which is a visible hole in a keyboard-first nav."""
    nav = sidebar._list
    for row in range(nav.count()):
        assert not nav.item(row).icon().isNull(), f"row {row} has no icon"
