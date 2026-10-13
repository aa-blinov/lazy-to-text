"""Tests for the theme tokens and QSS loader."""

import re

import pytest

from app.gui.theme import TOKENS as _TOKENS


@pytest.fixture(autouse=True)
def _restore_the_active_palette():
    """Every test in this module starts and ends on the dark palette.

    ``TOKENS.colors`` is swapped **in place** by the theme code — that is
    deliberate, because the widget tree holds the object rather than the
    name. The cost is that a test which loads a theme and does not put it
    back leaves the whole module-global palette changed for whatever runs
    next, and the symptom appears in a file that has nothing to do with
    them: a widget asserting on ``text_primary`` quietly starts asserting
    on the light value.

    Which is what happened here once already — a failure four files away
    from the theme code that caused it.
    """
    saved = dict(_TOKENS.colors)
    try:
        yield
    finally:
        _TOKENS.colors.clear()
        _TOKENS.colors.update(saved)


def test_tokens_expose_required_color_keys():
    from app.gui.theme import TOKENS

    required = {
        "bg_primary",
        "bg_secondary",
        "bg_elevated",
        "accent",
        "text_primary",
        "text_secondary",
        "border",
        "success",
        "danger",
        "warning",
    }
    assert required.issubset(TOKENS.colors.keys())


def test_tokens_expose_spacing_and_radius():
    from app.gui.theme import TOKENS

    for key in ("xs", "sm", "md", "lg", "xl"):
        assert key in TOKENS.spacing, f"missing spacing.{key}"
        assert isinstance(TOKENS.spacing[key], int)

    for key in ("sm", "md", "lg"):
        assert key in TOKENS.radius
        assert isinstance(TOKENS.radius[key], int)


def test_tokens_expose_font_family_and_sizes():
    from app.gui.theme import TOKENS

    assert isinstance(TOKENS.fonts["family"], str)
    assert TOKENS.fonts["family"]
    for key in ("size_title", "size_body", "size_small"):
        assert key in TOKENS.fonts
        assert isinstance(TOKENS.fonts[key], int)


def test_load_stylesheet_returns_non_empty_string_for_dark_theme():
    from app.gui.theme import load_stylesheet

    qss = load_stylesheet("dark")
    assert isinstance(qss, str)
    assert qss.strip()


def test_load_stylesheet_resolves_all_token_placeholders():
    """No unresolved {{token}} markers should remain after loading."""
    from app.gui.theme import load_stylesheet

    qss = load_stylesheet("dark")
    assert "{{" not in qss
    assert "}}" not in qss


def test_load_stylesheet_substitutes_actual_colors():
    from app.gui.theme import TOKENS, load_stylesheet

    qss = load_stylesheet("dark")
    assert TOKENS.colors["bg_primary"] in qss


def test_an_unknown_theme_falls_back_to_the_default():
    """It used to raise, and raising was the wrong call.

    ``config.yaml`` is a file people open and edit. A typo in a cosmetic
    setting refusing to start the app — with the traceback naming a
    theme nobody chose — trades a wrong-looking window for a window that
    does not open. The default is the documented fallback for exactly
    that reason, and this pins it so a future "be strict again" is a
    decision somebody makes on purpose.
    """
    from app.gui.theme import DEFAULT_THEME, load_stylesheet, resolve_theme

    assert resolve_theme("does-not-exist") == resolve_theme(DEFAULT_THEME)
    assert load_stylesheet("does-not-exist") == load_stylesheet(DEFAULT_THEME)


def test_the_default_follows_the_system_rather_than_being_dark():
    """The bare call used to mean "dark". It now means "system".

    There are two palettes, so a default that hardcodes one of them is a
    default that ignores the OS unless the user goes and finds the
    setting. Under the offscreen platform the system reports no
    preference, which reads as light — and the point of the test is the
    wiring, not which way the unknown resolves.
    """
    from app.gui.theme import active_theme, load_stylesheet, resolve_theme

    assert load_stylesheet() == load_stylesheet("system")
    assert active_theme() in {"light", "dark"}
    assert active_theme() == resolve_theme("system")


def test_the_light_and_dark_palettes_differ_only_in_colour(qtbot):
    """Two stylesheets would have to be kept from drifting apart.

    ``base.qss`` is shared, so the entire structural difference between
    the themes is the token values. If a future theme needed a
    rule that only one of them had, this is the test that makes it
    visible rather than letting the two files diverge quietly.
    """
    from app.gui.theme import load_stylesheet

    def rules(qss):
        return re.sub(r"/\*.*?\*/", "", qss, flags=re.S)

    dark = rules(load_stylesheet("dark"))
    light = rules(load_stylesheet("light"))

    assert dark != light, "the two themes paint identically"
    # Only colour values differ — same selectors, same declarations
    # with every hex swapped.
    assert re.sub(r"#[0-9a-fA-F]{3,8}", "#", dark) == re.sub(
        r"#[0-9a-fA-F]{3,8}", "#", light
    )


def test_apply_theme_sets_stylesheet_on_qapplication(qapp):
    from app.gui.theme import apply_theme, load_stylesheet

    apply_theme(qapp, "dark")
    assert qapp.styleSheet() == load_stylesheet("dark")


# --- the bundled font is really the one being used -------------------------
#
# `load_bundled_fonts` registers `InterVariable.ttf` and the family stack
# asks for it first, so the UI is meant to look the same on a machine
# where the user has never installed Inter. That was a docstring, not a
# claim anything checked. It matters more than "the font is pretty":
# every layout minimum in the app is a sum of text widths, so which face
# those widths come from is what decides whether a window fits — and the
# Settings page measures 3-6% wider on Windows CI than on a Mac, which
# is what its 2px overflow at text scale 1.75 turned out to be.


def test_the_bundled_font_family_is_registered(qapp):
    from PySide6.QtGui import QFontDatabase
    from app.gui.theme import load_bundled_fonts

    load_bundled_fonts()
    assert "Inter Variable" in QFontDatabase.families()


def test_widgets_resolve_to_the_bundled_font(qapp):
    """The head of the family stack, not whatever came back from it.

    TRAP: a widget created *after* the stylesheet is applied still
    reports the application default until something forces a repolish —
    it answers "Sans Serif" here and "Inter Variable" after a
    ``processEvents()``. And a widget created before the theme is applied
    never answers at all. So: build the host first, then read.
    """
    from PySide6.QtGui import QFontInfo
    from PySide6.QtWidgets import QLabel, QWidget
    from app.gui.theme import TOKENS, apply_theme

    apply_theme(qapp, "dark")
    host = QWidget()
    label = QLabel("Microphone", host)
    qapp.processEvents()

    wanted = TOKENS.fonts["family"].split(",")[0].strip().strip('"')
    resolved = QFontInfo(label.font()).family()
    assert resolved == wanted, (
        f"a widget under the theme resolved to {resolved!r}, "
        f"not the bundled {wanted!r} — every text measurement in the app "
        f"is now made in a font this project does not ship"
    )


# --- text scale ---------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_text_scale():
    """Keep the module-level multiplier out of neighbouring tests."""
    from app.gui.theme import set_text_scale

    yield
    set_text_scale(1.0)


def test_text_scale_defaults_to_the_design_baseline():
    from app.gui.theme import set_text_scale, text_scale

    set_text_scale(1.0)
    assert text_scale() == 1.0


def test_text_scale_clamps_to_the_supported_band():
    from app.gui.theme import TEXT_SCALE_MAX, TEXT_SCALE_MIN, set_text_scale

    assert set_text_scale(0.1) == TEXT_SCALE_MIN
    assert set_text_scale(99.0) == TEXT_SCALE_MAX


def test_text_scale_rejects_junk_without_raising():
    from app.gui.theme import set_text_scale

    assert set_text_scale(None) == 1.0
    assert set_text_scale("not a number") == 1.0
    assert set_text_scale(float("nan")) == 1.0


def test_text_scale_multiplies_every_size_token():
    """The four UI sizes plus the transcribe reading size must all
    scale together, or the type scale loses its ratios."""
    import re
    from pathlib import Path

    from app.gui.theme import set_text_scale

    def sizes(scale):
        set_text_scale(scale)
        qss = load_dark()
        return sorted({int(n) for n in re.findall(r"font-size: (\d+)px", qss)})

    base = sizes(1.0)
    assert base == [11, 13, 14, 17, 22]

    scaled = sizes(1.5)
    assert scaled == [16, 20, 21, 26, 33]
    assert all(large > small for large, small in zip(scaled, base))


def test_text_scale_leaves_radius_and_spacing_alone():
    """Only the type scale is user-adjustable. Radii and spacing stay
    put so a larger text size grows the reading surface without
    breaking the four-step layout rhythm.

    Asserted at the substitution layer rather than by searching the
    rendered QSS, because not every token is referenced by a rule
    (``radius.xl`` is reserved and intentionally unused) and a
    substring search would say nothing about the ones that are.
    """
    from app.gui.theme import _build_substitutions, set_text_scale

    set_text_scale(1.0)
    baseline = _build_substitutions()
    set_text_scale(1.75)
    at_max = _build_substitutions()

    changed = {
        key
        for key in baseline
        if baseline[key] != at_max[key]
    }
    assert changed, "the scale had no effect at all"
    assert all(key.startswith("font.size_") for key in changed), (
        f"non-type tokens moved with the text scale: {sorted(changed)}"
    )


def test_every_font_size_in_qss_comes_from_a_token():
    """A hard-coded px size escapes the text scale, so the scale is only
    as good as the token coverage. The transcribe view used to carry two
    such rules."""
    import re
    from pathlib import Path
    from pathlib import Path

    from app.gui.theme import _STYLES_DIR, set_text_scale

    set_text_scale(1.0)
    raw = (_STYLES_DIR / "base.qss").read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in raw.splitlines()
        if re.match(r"^\s*font-size:\s*\d+px", line)
    ]
    assert offenders == [], f"hard-coded font sizes: {offenders}"


def test_no_hex_literal_survives_in_qss_rules():
    """A colour written into a rule is a colour the palette cannot change.

    Comments are exempt on purpose: the Ink-on-Fill and log-console notes
    quote measured values and the hexes they were measured from, which is
    the documentation doing its job. What must not happen is a hex in a
    live declaration, because ``{{color.*}}`` substitution never touches
    it and the next palette change silently skips that rule.
    """
    import re

    from app.gui.theme import _STYLES_DIR

    raw = (_STYLES_DIR / "base.qss").read_text(encoding="utf-8")
    without_comments = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    offenders = [
        line.strip()
        for line in without_comments.splitlines()
        if re.search(r"#[0-9a-fA-F]{3,8}\b", line)
    ]
    assert offenders == [], f"hex literals in QSS rules: {offenders}"


def test_every_colour_token_is_actually_used_somewhere():
    """A token nothing paints is a claim about the future nobody keeps.

    Engine Green sat in ``theme.py`` and DESIGN.md for years after the
    component that used it was replaced. A token counts as used when the
    stylesheet paints it *or* when Python names it — ``accent_focus`` is
    applied from ``sidebar.py`` and the Dock gradient, not from QSS, and
    checking the stylesheet alone would call that dead.
    """
    from pathlib import Path

    from app.gui.theme import TOKENS, _STYLES_DIR

    qss = (_STYLES_DIR / "base.qss").read_text(encoding="utf-8")
    python = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(Path(app_dir()).rglob("*.py"))
    )
    unused = sorted(
        name for name in TOKENS.colors
        if name not in qss and f'"{name}"' not in python and f"'{name}'" not in python
    )
    assert unused == [], f"declared but never used: {unused}"


def app_dir() -> str:
    import app
    from pathlib import Path

    return str(Path(app.__file__).parent)


def load_dark():
    from app.gui.theme import load_stylesheet

    return load_stylesheet("dark")


# --- high contrast ------------------------------------------------------


def test_is_high_contrast_is_false_off_windows(monkeypatch):
    """macOS has no forced-colours mode; Windows is the only platform
    that answers True, and every other path must be False."""
    from app.gui import theme

    monkeypatch.setattr(theme.sys, "platform", "darwin")
    assert theme.is_high_contrast() is False
    monkeypatch.setattr(theme.sys, "platform", "linux")
    assert theme.is_high_contrast() is False


def test_load_stylesheet_defers_to_the_os_in_high_contrast(monkeypatch):
    """In forced-colours mode the user has hand-picked a palette they can
    read; painting Graphite over it defeats the point, so the stylesheet
    must be empty and the window falls back to the system palette."""
    from app.gui import theme

    monkeypatch.setattr(theme, "is_high_contrast", lambda: True)
    assert theme.load_stylesheet("dark") == ""


def test_high_contrast_detection_survives_a_broken_win32_call(monkeypatch):
    """A failed probe must never break startup — worst case we paint our
    own theme over a forced-colours session."""
    from app.gui import theme

    monkeypatch.setattr(theme.sys, "platform", "win32")

    import ctypes

    def _boom(*_args, **_kwargs):
        raise OSError("no user32 here")

    # ``ctypes.windll`` only exists on Windows, so the fake has to be
    # injected rather than overwritten.
    monkeypatch.setattr(
        ctypes, "windll", type("W", (), {"user32": _boom})(), raising=False,
    )
    assert theme.is_high_contrast() is False


# --- Every text token has to clear AA on every surface it lands on ----
#
# ``text_muted`` sat at gray_245 for the life of the project: 4.47:1 on
# the window ground, 4.02:1 on a card, 3.58:1 on a raised surface. All
# three are under the 4.5:1 floor, and the token is not decoration — it
# paints model descriptions, the repository id under them, and
# DEBUG-level log messages, which is the content of the two panes people
# read.
#
# Nothing caught it, because a contrast number nobody recomputes is just
# a comment. This makes the ramp a test.


def _luminance(hex_colour: str) -> float:
    def channel(value: int) -> float:
        srgb = value / 255.0
        return (
            srgb / 12.92
            if srgb <= 0.03928
            else ((srgb + 0.055) / 1.055) ** 2.4
        )

    r, g, b = (int(hex_colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


#: Text inks, and the surfaces each one is painted on somewhere.
#:
#: ``bg_hover`` is deliberately not on any list. It is the generic
#: button hover and the scrollbar handle, and the one place muted text
#: meets a button is ``QPushButton:disabled`` — a disabled button does
#: not hover. Adding it would test a pairing no rule can produce.
_TEXT_ON_SURFACES = {
    "text_muted": ("bg_primary", "bg_secondary", "bg_elevated"),
    "text_secondary": ("bg_primary", "bg_secondary", "bg_elevated"),
    "text_primary": ("bg_primary", "bg_secondary", "bg_elevated"),
    # Sits on a *saturated* fill, where the rule is inverted: the ground
    # is the label, and the ground is the darkest ink in the palette.
    "success": ("bg_primary",),
    "danger": ("bg_primary",),
    "warning": ("bg_primary",),
    "warning_hover": ("bg_primary",),
    "accent": ("bg_primary",),
    "accent_hover": ("bg_primary",),
    # ``accent_focus`` was listed here and is not a text token. It is
    # only ever a *fill* — the selected sidebar row under keyboard focus
    # and the Dock icon's gradient stop — so "accent_focus as ink on the
    # ground" is a pairing no rule produces. The dark palette passed it
    # anyway (light2 on near-black is a comfortable ratio), which is what
    # a wrong premise looks like: green until a second palette lands and
    # the same question gets a different answer. Its real constraints —
    # the ground ink readable on top of it, and visible separation from
    # ``accent`` — are asserted in the light-palette section below.
}

#: WCAG AA for body text. 3.0:1 would be the large-text floor; the
#: smallest ink in this system is 11px at weight 600, which is not
#: large text by any reading of the spec.
_AA_BODY = 4.5


#: Both palettes, by name. These checks used to read ``TOKENS.colors`` —
#: the palette that happened to be active — which was the same thing when
#: there was only one and is a bug now: whichever other test file ran last
#: decided what "the palette" meant. A contrast assertion that changes its
#: subject depending on the test before it is not a contrast assertion.
_PALETTES = ("dark", "light")


@pytest.mark.parametrize("theme_name", _PALETTES)
@pytest.mark.parametrize("token", sorted(_TEXT_ON_SURFACES))
def test_every_text_token_clears_aa_on_every_surface(theme_name, token):
    from app.gui import theme as theme_module

    colours = theme_module._TOKEN_SETS[theme_name]
    worst = None
    for surface in _TEXT_ON_SURFACES[token]:
        ratio = _contrast(colours[token], colours[surface])
        if worst is None or ratio < worst[1]:
            worst = (surface, ratio)
        assert ratio >= _AA_BODY, (
            f"{token} {colours[token]} on {surface} "
            f"{colours[surface]} is {ratio:.2f}:1, under AA {_AA_BODY}:1"
        )
    # A token that only just scrapes by on one surface is one step from
    # failing on the next, so the floor is a warning, not a fact.
    assert worst[1] >= 4.5, f"{token} is at {worst[1]:.2f}:1 on {worst[0]}"


@pytest.mark.parametrize("theme_name", _PALETTES)
def test_the_text_ramp_stays_ordered_after_a_lift(theme_name):
    """Lifting ``text_muted`` must not collapse it into its neighbour.

    The cost of clearing AA was always a narrower gap: 4.02:1 against
    ``text_secondary``'s 6.77:1 became 5.30:1 against 6.77:1. The step
    has to stay visible or the ramp is one long gradient with no
    levels in it.

    Now checked against both palettes: inverting a palette is exactly
    the operation that can collapse an ink step without anything
    looking wrong, and the light ramp's steps are measured, not assumed.
    """
    from app.gui import theme as theme_module

    c = theme_module._TOKEN_SETS[theme_name]
    muted = _contrast(c["text_muted"], c["bg_secondary"])
    secondary = _contrast(c["text_secondary"], c["bg_secondary"])
    primary = _contrast(c["text_primary"], c["bg_secondary"])

    assert muted < secondary < primary, (
        "text_muted / text_secondary / text_primary no longer form a "
        f"strict ramp: {muted:.2f} / {secondary:.2f} / {primary:.2f}"
    )
    # And the quiet step must still be a *step*, not a rounding error.
    assert (secondary - muted) >= 1.0, (
        f"muted and secondary are only {secondary - muted:.2f} apart — "
        f"the quiet step has collapsed"
    )


# ---- The light palette ------------------------------------------------------
#
# Ratios are WCAG relative-luminance contrast, computed here rather than
# pasted in, so the test moves if a colour does. The floors are the ones
# the roles need: body text at 7:1, secondary ink and the status colours
# at 4.5:1, and non-text surfaces at whatever keeps them visible.


def _luminance(colour: str) -> float:
    def channel(value: float) -> float:
        return (
            value / 12.92
            if value <= 0.04045
            else ((value + 0.055) / 1.055) ** 2.4
        )

    h = colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _ratio(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_the_light_palette_has_the_same_tokens_as_the_dark_one():
    """A missing key is a placeholder that never gets substituted.

    It would not raise — QSS just keeps ``{{color.missing}}`` and Qt
    ignores the declaration — so the widget silently loses its colour
    and nothing anywhere complains.
    """
    from app.gui.theme import LIGHT_TOKENS, TOKENS

    assert set(LIGHT_TOKENS.colors) == set(TOKENS.colors)
    assert len(LIGHT_TOKENS.colors) == 15


_LIGHT_PAIRS = [
    ("text_primary", "bg_primary", 7.0),
    ("text_primary", "bg_secondary", 7.0),
    ("text_primary", "bg_elevated", 7.0),
    ("text_primary", "bg_hover", 7.0),
    ("text_secondary", "bg_primary", 4.5),
    ("text_secondary", "bg_secondary", 4.5),
    ("text_muted", "bg_primary", 4.5),
    ("text_muted", "bg_secondary", 4.5),
    ("text_muted", "bg_hover", 4.5),
    ("accent", "bg_primary", 4.5),
    ("success", "bg_primary", 4.5),
    ("danger", "bg_primary", 4.5),
    ("warning", "bg_primary", 4.5),
]


@pytest.mark.parametrize("fg,bg,floor", _LIGHT_PAIRS)
def test_the_light_palette_clears_its_contrast_floors(fg, bg, floor):
    from app.gui.theme import LIGHT_TOKENS

    value = _ratio(LIGHT_TOKENS.colors[fg], LIGHT_TOKENS.colors[bg])
    assert value >= floor, f"{fg} on {bg} is {value:.2f}:1, needs {floor}:1"


def test_the_light_text_roles_stay_in_order():
    """Primary, then secondary, then muted — on every surface.

    This is the part actually at risk when a palette is inverted: two
    roles can each clear their own floor while the muted one ends up
    *more* prominent than the secondary, which reads as a bug rather
    than a choice.
    """
    from app.gui.theme import LIGHT_TOKENS

    colours = LIGHT_TOKENS.colors
    for surface in ("bg_primary", "bg_secondary", "bg_elevated", "bg_hover"):
        values = [
            _ratio(colours[role], colours[surface])
            for role in ("text_primary", "text_secondary", "text_muted")
        ]
        assert values[0] > values[1] > values[2], (surface, values)


def test_the_light_surface_ladder_is_visible():
    """Cards, raised planes and hover each have to separate.

    A ladder step below ~1.1 is a plane boundary nobody can see, which
    is how a "designed" theme turns into a flat one.
    """
    from app.gui.theme import LIGHT_TOKENS

    colours = LIGHT_TOKENS.colors
    assert _ratio(colours["bg_secondary"], colours["bg_primary"]) >= 1.10
    assert _ratio(colours["bg_elevated"], colours["bg_secondary"]) >= 1.10
    # 1.24, not the dark theme's 1.271. This step is where the light
    # palette spends its budget: a stronger hover caps muted text at
    # 4.37:1 under it, and 4.55:1 is the AA floor. Written as 1.25 the
    # assertion failed on the real value of 1.2453, which is what
    # rounding the claim up would have hidden.
    assert _ratio(colours["bg_hover"], colours["bg_secondary"]) >= 1.24
    assert _ratio(colours["border"], colours["bg_secondary"]) >= 1.50


def test_the_selected_row_icon_is_readable_on_both_fills():
    """The one number the light theme cannot match, pinned anyway.

    ``sidebar.py`` paints the selected row's icon in ``bg_primary``
    because the fill is ``accent``. Inverting the theme inverts that
    relationship, so the light fill has to stay dark enough to carry a
    light icon — and that is what caps how far ``accent_focus`` can be
    separated from ``accent``. The floor here is the graphical-object
    3:1; the measured dark-theme values are 6.09 on accent and 9.56 on
    accent_focus.
    """
    from app.gui.theme import LIGHT_TOKENS

    colours = LIGHT_TOKENS.colors
    assert _ratio(colours["bg_primary"], colours["accent"]) >= 3.0
    assert _ratio(colours["bg_primary"], colours["accent_focus"]) >= 3.0


def test_switching_themes_repeatedly_does_not_erase_the_palette():
    """The aliasing bug this exists for.

    The first version held ``_DARK_TOKENS = TOKENS`` and swapped with
    ``TOKENS.colors.clear()``. That is self-erasure — it wipes the very
    dict it then copies from — and it only shows the *second* time the
    theme changes. A suite that sets each theme once never sees it.
    """
    from app.gui.theme import LIGHT_TOKENS, TOKENS

    # Compared against the dark palette by name, not against whatever was
    # active on arrival. This test used to snapshot the live tokens and
    # assert the round trip returned them — which only holds if the
    # palette on arrival *is* dark. Another test file leaves light active
    # (every one that calls ``apply_theme`` does), so the snapshot
    # depended on collection order and this failed only in a full run.
    original = dict(TOKENS.colors)
    try:
        for _ in range(3):
            for name in ("dark", "light", "system"):
                from app.gui.theme import load_stylesheet

                load_stylesheet(name)
                assert len(TOKENS.colors) == 15, name
        load_stylesheet("light")
        assert TOKENS.colors["bg_primary"] == LIGHT_TOKENS.colors["bg_primary"]
        load_stylesheet("dark")
        assert TOKENS.colors == _DARK_REFERENCE
    finally:
        TOKENS.colors.clear()
        TOKENS.colors.update(original)


# Captured at import, before any test has swapped anything, so a test
# can put the tokens in a known state without going through the code it
# is testing. Literals rather than a module attribute, for the same
# reason: ``theme._DARK_COLORS`` is exactly the dict a mutation might
# delete.
_DARK_REFERENCE = {
    "bg_primary": "#1d2021", "bg_secondary": "#282828",
    "bg_elevated": "#32302f", "bg_hover": "#3c3836",
    "accent": "#83a598", "accent_hover": "#a89984", "accent_focus": "#d5c4a1",
    "text_primary": "#fbf1c7", "text_secondary": "#bdae93", "text_muted": "#a89984",
    "border": "#504945", "success": "#b8bb26", "danger": "#fb4934",
    "warning": "#d79921", "warning_hover": "#fabd2f",
}


def test_the_returned_stylesheet_is_built_from_the_theme_it_names(monkeypatch):
    """The swap has to happen *before* the substitutions are assembled.

    ``_build_substitutions`` reads ``TOKENS.colors``, so swapping
    afterwards returns a stylesheet built from the previous theme's
    colours. The tokens on the object then read correctly while the
    window paints the other palette — which is the whole bug in one
    sentence, and it is invisible to any test that only inspects
    ``TOKENS`` afterwards.
    """
    from app.gui.theme import LIGHT_TOKENS, TOKENS, load_stylesheet

    # On ``accent`` and ``bg_secondary``, never on ``bg_primary``.
    # The light ground is #fbf1c7, and the dark palette's *text_primary*
    # is the same value — so a dark-substituted stylesheet still
    # contains the light ground, and the assertion passes either way.
    # That is not a near miss: it is the reason the first two versions
    # of this test could not kill the mutation.
    distinctive = (
        LIGHT_TOKENS.colors["accent"],
        LIGHT_TOKENS.colors["bg_secondary"],
    )
    dark_only = _DARK_REFERENCE["bg_primary"]  # #1d2021, light palette has no such token

    # Pinned to the dark palette explicitly rather than by calling
    # ``load_stylesheet("dark")`` first. Under the mutation this guards,
    # the swap moved to the end of the function — so asking it to set up
    # the starting state leaves the tokens light again, and the next
    # call then builds from light and the assertion passes. Writing the
    # colours in directly is the one way to make the starting state
    # independent of the code under test.
    dark = dict(TOKENS.colors)
    try:
        TOKENS.colors.clear()
        TOKENS.colors.update(dict(_DARK_REFERENCE))
        qss = load_stylesheet("light")
        # Comments stripped: base.qss documents the dark palette's
        # measured numbers in prose, so ``#1d2021`` is in the file
        # whatever theme is substituted, and asserting against the raw
        # text would be asserting on the documentation.
        qss = re.sub(r"/\*.*?\*/", "", qss, flags=re.S)
        for value in distinctive:
            assert value in qss, f"{value} missing — built from the wrong palette"
        assert dark_only not in qss
    finally:
        TOKENS.colors.clear()
        TOKENS.colors.update(dark)


@pytest.mark.parametrize("system_is_dark", [True, False])
def test_the_system_setting_is_what_the_os_says(monkeypatch, system_is_dark):
    """Both directions.

    Asserting only "both sides agree" is not enough: a ``resolve_theme``
    that ignored the OS and always returned dark satisfies it, because
    the comparison is made against itself. The system preference is the
    input under test here, so it is the thing that gets pinned.
    """
    import app.gui.theme as theme

    monkeypatch.setattr(
        theme, "system_prefers_dark", lambda: system_is_dark
    )

    assert theme.resolve_theme("system") == ("dark" if system_is_dark else "light")


def test_an_explicit_choice_ignores_the_system(monkeypatch):
    """Picking a theme in Settings must win over the OS.

    The one case where following the system would be actively wrong: a
    user who chose a theme because the automatic one was unreadable for
    them is exactly the user this app has to keep serving.
    """
    import app.gui.theme as theme

    monkeypatch.setattr(theme, "system_prefers_dark", lambda: True)
    assert theme.resolve_theme("light") == "light"

    monkeypatch.setattr(theme, "system_prefers_dark", lambda: False)
    assert theme.resolve_theme("dark") == "dark"
