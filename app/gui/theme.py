"""Design tokens and QSS loader for the Qt UI.

Tokens live in Python so widgets can reference them directly. The QSS files
use ``{{group.key}}`` placeholders that are substituted at load time.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFontDatabase, QPainter
from PySide6.QtWidgets import QApplication


_STYLES_DIR = Path(__file__).parent / "styles"

# Bounds for the user-facing text scale. 1.0 is the design baseline and
# reproduces the shipped rendering byte-for-byte. The floor keeps 11px
# labels legible; the ceiling stops the four-size scale from colliding
# with the 8/12/16/20px radius steps and clipping card interiors.
TEXT_SCALE_MIN = 0.85
TEXT_SCALE_MAX = 1.75
TEXT_SCALE_STEPS = (1.0, 1.15, 1.3, 1.5)

# Module-level multiplier applied to every ``font.size_*`` substitution.
# Set once at startup from ``config.yaml`` (``ui.text_scale``) and again
# whenever the user changes it in Settings. Kept here rather than on
# ``TOKENS`` so the frozen token values stay the 100% design baseline —
# DESIGN.md's "Four Sizes Rule" describes the ratios, not the absolute
# pixels, and a scaled build is still the same four sizes.
_TEXT_SCALE = 1.0


@dataclass(frozen=True)
class _Tokens:
    colors: Dict[str, str] = field(default_factory=dict)
    spacing: Dict[str, int] = field(default_factory=dict)
    radius: Dict[str, int] = field(default_factory=dict)
    fonts: Dict[str, object] = field(default_factory=dict)


TOKENS = _Tokens(
    colors={
        # ---- Gruvbox, dimmed ---------------------------------------------
        # The four-step surface ladder is the palette's own dark ramp:
        # dark0_hard → dark0 → dark0_soft → dark1, ascending, with
        # dark2 as the hairline. Measured steps between neighbours come
        # out 1.11 / 1.12 / 1.13 — even, which is what a ladder is for.
        # A steeper ramp looked more "designed" and cost the ability to
        # see where one plane ended and the next began.
        "bg_primary": "#1d2021",   # dark0_hard — the window ground
        "bg_secondary": "#282828",   # dark0 — cards, inputs, the sidebar
        "bg_elevated": "#32302f",   # dark0_soft — raised, chips, hover
        "bg_hover": "#3c3836",   # dark1
        "accent": "#83a598",   # bright_blue
        # Gruvbox has no second step inside a single hue — its ramp is
        # faded → neutral → bright, and bright is already the top. Every
        # lighter value the palette owns is warm, and this accent is cool,
        # so "the accent, one step up" is not a colour that exists. That
        # is why the step splits in two: a pointer hover and a keyboard
        # focus want opposite things from the same job.
        #
        # Hover stays near the accent: gray_244 measures 5.90:1 under the
        # ground ink and sits 1.03× its luminance, so a sage button turns
        # into a slightly warmer sage and nothing else. The louder,
        # warmer ramp was measured against it and rejected — on a filled
        # primary button it does not read as a brighter button, it reads
        # as a different button.
        "accent_hover": "#a89984",   # gray_244
        # Focus is the loud one and is allowed to leave the hue. It has
        # to: a keyboard user has to know at a glance that the arrow keys
        # are now somewhere, and a 3% luminance step does not say that.
        # light2 is the strongest value in the palette that still carries
        # the ground ink at 9.56:1, so the focused row reads as paper
        # against the near-black ground and as nothing else on screen.
        "accent_focus": "#d5c4a1",   # light2
        "text_primary": "#fbf1c7",   # light0
        "text_secondary": "#bdae93",   # light3
        # gray_244, not gray_245. Measured: gray_245 gives 4.47:1 on the
        # window ground, 4.02:1 on a card and 3.58:1 on a raised surface
        # — under the 4.5:1 AA floor everywhere, and this token is not
        # decoration. It paints model descriptions, the repository id
        # under them, and DEBUG-level log messages, which is the content
        # of the two panes people actually read.
        #
        # gray_244 clears it on all three: 5.90 / 5.30 / 4.72. The cost
        # is that the whole quiet layer of the app lifts with it, and
        # the token now shares a value with ``accent_hover`` — which is
        # why the two labels that were borrowing ``accent_hover`` for
        # *text* were repointed at the time: a section header is chrome
        # and belongs on this token, and a progress message is emphasis
        # rather than a hue. See base.qss.
        "text_muted": "#a89984",   # gray_244
        "border": "#504945",   # dark2
        "success": "#b8bb26",   # bright_green
        "danger": "#fb4934",   # bright_red
        "warning": "#d79921",   # neutral_yellow
        "warning_hover": "#fabd2f",   # bright_yellow — one step lighter,
        # same hue. The warning banner's button is a filled amber chip
        # and its hover has to be visible against it.
        #
    },
    spacing={
        "xs": 4,
        "sm": 8,
        "md": 12,
        "lg": 16,
        "xl": 24,
    },
    radius={
        # Plumper rounded corners read as more modern. Cards float at
        # ``lg``, primary surfaces at ``md``, badges and pills at ``sm``.
        "sm": 8,
        "md": 12,
        "lg": 16,
        "xl": 20,
    },
    fonts={
        # ``Inter Variable`` is the family name our bundled
        # ``InterVariable.ttf`` registers under (Qt's
        # ``addApplicationFont`` reads it from the font's name table
        # — variable fonts get a single family with axis variations
        # rolled in). ``Inter`` is the static-cut fallback for
        # systems where the user has installed Rasmus's classic
        # release; ``Segoe UI Variable`` / ``Segoe UI`` cover
        # Windows 11 / older Windows; ``Helvetica Neue`` is the
        # preferred macOS system face when nothing else matches.
        # The whole stack is emitted into QSS verbatim, which Qt's
        # font matcher honours left-to-right.
        "family": '"Inter Variable", "Inter", "Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial, sans-serif',
        # Second family, for the two places where a proportional face
        # is simply the wrong tool: log lines, and hotkey chips. Log
        # rows are scanned vertically and compared against each other;
        # in a proportional face the columns never line up, so a
        # timestamp or a level prefix reads as noise. Nothing is
        # bundled for this -- it is a system-font stack, and Qt falls
        # through it left to right (``monospace`` is the generic
        # keyword Qt resolves last).
        "mono": 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Cascadia Mono", "DejaVu Sans Mono", monospace',
        "size_title": 22,
        "size_heading": 17,
        "size_body": 13,
        "size_small": 11,
        # Deliberate fifth size, and the only one: the transcribe
        # output is the single place the user reads *someone else's*
        # long text, so it gets more size than the app's own copy.
        # It was hard-coded as 14px in two QSS rules before, which
        # meant it also escaped the text scale — now it is a token
        # like every other size.
        "size_transcript": 14,
    },
)


# The second palette, and the only structural difference between the two
# themes: a colour. ``base.qss`` is entirely ``{{token}}``-driven — three
# literal hex values, all of which are token values duplicated in one
# place — so switching themes is swapping fifteen colours, not maintaining
# two stylesheets that have to be kept from drifting apart.
#
# Every value below is a measured one. The ladder steps sit near the dark
# theme's measured 1.112 / 1.123 / 1.271 (light: 1.209 / 1.251 / 1.270)
# and the three text roles clear their floors on all four surfaces —
# text_muted measures 5.32:1 under a hover, where the shipped dark theme
# manages 4.17:1.
LIGHT_TOKENS = _Tokens(
    colors={
        # ---- Gruvbox, light -----------------------------------------------
        # Thirteen of the fifteen below are canonical swatches under their
        # own names. This is gruvbox's own light variant: the same sixteen
        # colours, roles swapped — the dark ramp becomes ink, the
        # foreground ramp becomes ground.
        #
        # Getting here took a search rather than a decision. A first pass
        # measured a hand-written strict palette and gave up on four
        # floors; then a brute-force search over every assignment of the
        # sixteen swatches found solutions — in which accent, success,
        # danger and warning were all the same near-black. They clear
        # every floor and the palette is grey. "Passes contrast" is not
        # "is a colour", so the state tokens were required to be chromatic
        # and to differ from each other in hue by at least 20°, and with
        # that in place the search returns **zero** assignments.
        #
        # The reason is narrow and worth knowing: only five chromatic
        # swatches clear 4.5:1 as ink on the cream ground — faded_red,
        # faded_purple, faded_blue, faded_orange, neutral_red — and there
        # is no green and no yellow among them. So ``success`` and
        # ``warning`` below are the two measured values, and they are the
        # only two.
        "bg_primary": "#fbf1c7",   # fg1 — the window ground
        "bg_secondary": "#ebdbb2",   # fg — cards, inputs, the sidebar
        "bg_elevated": "#d5c4a1",   # fg2 — raised, chips
        # The dark palette's hover step is 1.27:1 and this one is 1.59:1 —
        # larger, not smaller, because the whole light ladder sits on the
        # foreground ramp and four steps out of six swatches leaves no
        # room to make the last one subtle. Muted text stays at 5.32:1
        # under it, which is the constraint that used to force a derived
        # value here.
        "bg_hover": "#bdae93",   # fg3 — hover
        # Warm, and that is the whole of it. The value this replaces was
        # ``bright_blue``: not low-contrast — the icon sits on this at
        # 5.40:1, and the fill separates from the rail it sits on by
        # 4.46:1 — but cold, and a saturated cold placed on a warm
        # desaturated ground reads as a foreign object rather than as
        # part of the palette. Measured on the rendered sidebar, not
        # reasoned about from the hex.
        #
        # Saturation was *not* the lever, and an earlier version of this
        # note claimed it was: this colour is 0.98, against the blue's
        # 0.94. In an inverted theme the icon-on-fill ratio and the
        # fill-on-rail ratio are the same number, so there is no lightness
        # or chroma to spend without taking the icon under AA.
        "accent": "#af3a03",   # faded_orange
        # Borrowed, the way the dark theme borrows ``fg4`` for its own
        # hover: Gruvbox has no second step inside a single hue. Of what
        # is left, the state colours are spoken for, so this is ``bg3`` —
        # a warm neutral, 5.74:1 as ink and 1.06:1 off the accent, which
        # is a hover nudge rather than a move, and matches the dark
        # theme's 1.03.
        "accent_hover": "#665c54",   # bg3
        # Downward, not brighter. ``sidebar.py`` paints the selected row's
        # icon in ``bg_primary``, so in an inverted theme the focus fill
        # has to be dark to carry it. This used to be recorded as a
        # structural 1.32:1 ceiling — a search that only looked up. Two
        # dark colours separate by going down exactly as a light one
        # separates by going up: 2.41:1, against the dark theme's 1.57:1.
        "accent_focus": "#282828",   # bg0
        # The dark ramp, ascending. ``bg0_hard`` rather than ``bg0``
        # because the primary ink has to clear 7:1 on the *hover* plane
        # too, and on ``fg3`` the two are 6.77 and 7.53.
        "text_primary": "#1d2021",   # bg0_hard
        "text_secondary": "#32302f",   # bg0_soft
        "text_muted": "#3c3836",   # bg1
        "border": "#928374",   # gray
        # The two values Gruvbox cannot supply. Its only dark green
        # (``faded_green`` #79740e) measures 4.29:1 on the cream ground
        # and its only dark yellow (``faded_yellow`` #b57614) measures
        # 3.33:1; the brights the dark theme uses are 2.45 and 2.19. Both
        # are pushed down from those to clear 4.5:1, and both are
        # asserted like every other floor in ``test_theme.py``.
        "success": "#61600c",   # derived — darkened from faded_green
        "danger": "#9d0006",   # faded_red
        "warning": "#8f5c10",   # derived — darkened from faded_yellow
        # Red rather than a darker yellow, and that is the only honest
        # answer left: no yellow in the palette clears 4.5:1 as ink on
        # cream. ``faded_red`` sits 1.52:1 from ``warning`` — a stronger
        # step than the dark palette's 1.46 — so the hover is visible
        # and it escalates rather than fading out.
        "warning_hover": "#9d0006",   # faded_red
    },
    spacing=TOKENS.spacing,
    radius=TOKENS.radius,
    fonts=TOKENS.fonts,
)

#: What a user may choose. ``system`` follows the OS appearance, which is
#: the default on both platforms it ships to: a user who never expressed
#: a preference should not have to.
THEMES = ("system", "light", "dark")
DEFAULT_THEME = "system"

_DARK_COLORS = dict(TOKENS.colors)
_TOKEN_SETS = {"light": LIGHT_TOKENS.colors, "dark": _DARK_COLORS}
_ACTIVE_THEME = "dark"


def _swap_active_tokens(theme: str) -> None:
    """Point ``TOKENS`` at *theme*'s colours, in place.

    In place rather than rebound, because ``TOKENS`` is imported by name
    across the widget tree (``from app.gui.theme import TOKENS``) and
    several modules hold the object itself. Rebinding ``TOKENS`` would
    leave every one of them pointing at the dark palette forever, and the
    light theme would then paint half the window dark. The dataclass is
    frozen but ``colors`` is a plain dict, so the contents can be
    replaced without touching the identity anything is holding.

    The source is a *copy*. Holding ``_DARK_TOKENS = TOKENS`` and then
    doing ``TOKENS.colors.clear()`` erases the very dict being copied
    from — self-erasure, and it only shows the second time the theme
    changes, which is why it looks like a passing test in a suite that
    sets each theme once.
    """
    global _ACTIVE_THEME
    _ACTIVE_THEME = theme
    source = _TOKEN_SETS[theme]
    TOKENS.colors.clear()
    TOKENS.colors.update(source)


def active_theme() -> str:
    """The concrete theme in force — ``"light"`` or ``"dark"``.

    Never ``"system"``: a caller asking what is painted gets an answer it
    can compare against a colour.
    """
    return _ACTIVE_THEME


def system_prefers_dark() -> bool:
    """What the OS is asking for, as a plain boolean.

    ``Unknown`` is read as light. An unrecognised hint is not evidence
    that the user wants a dark app, and the dark theme is the one this
    app has always shipped — so guessing the other way would change the
    appearance of every machine whose Qt cannot answer.
    """
    try:
        from PySide6.QtGui import QGuiApplication

        hints = QGuiApplication.styleHints()
        if hints is None:
            return False
        return hints.colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # pragma: no cover — Qt without a GUI
        return False


def resolve_theme(theme: str) -> str:
    """Turn a user's choice into the theme actually painted."""
    name = normalise_theme(theme)
    if name != "system":
        return name
    return "dark" if system_prefers_dark() else "light"


def normalise_theme(value) -> str:
    """Coerce anything to one of the three names a user may choose.

    Separate from ``resolve_theme`` because this is the *stored* value —
    what goes in the config and what the Settings combo shows — while
    resolution is the painted one. Keeping them apart means a config
    saying ``system`` round-trips as ``system`` rather than being frozen
    to whichever theme it happened to resolve to on the day it was
    written: the user asked to follow the system, not to be pinned.

    An unrecognised value falls back to the default rather than raising.
    A config file is a thing people edit, and refusing to start over a
    typo in a cosmetic setting is the wrong trade.
    """
    name = str(value or "").strip().lower()
    return name if name in THEMES else DEFAULT_THEME


def text_scale() -> float:
    """Current text-scale multiplier applied to ``font.size_*`` tokens."""
    return _TEXT_SCALE


def set_text_scale(value: float) -> float:
    """Set the text-scale multiplier, clamped to the supported band.

    Returns the value actually stored, so callers can write the clamped
    number back to ``config.yaml`` instead of the rejected one.  ``1.0``
    reproduces the shipped rendering exactly — every size token is used
    as its frozen baseline value.
    """
    global _TEXT_SCALE
    try:
        scale = float(value)
    except (TypeError, ValueError):
        scale = 1.0
    if scale != scale:  # NaN
        scale = 1.0
    _TEXT_SCALE = max(TEXT_SCALE_MIN, min(TEXT_SCALE_MAX, scale))
    return _TEXT_SCALE


def apply_text_scale(app: Optional[QApplication], value: float) -> float:
    """Set the text scale and re-resolve the stylesheet.

    ``app`` may be ``None`` — headless callers and tests only need the
    multiplier to be in effect for the next ``load_stylesheet``. The
    clamp is applied before the stylesheet is rebuilt so a rejected
    value never renders once at the wrong size.
    """
    scale = set_text_scale(value)
    if app is not None:
        # The active theme, not a hardcoded "dark": re-scaling text is a
        # thing people do in both themes, and rebuilding in dark would
        # silently repaint a light window on every step of the scale.
        app.setStyleSheet(load_stylesheet(_ACTIVE_THEME))
    return scale


def is_high_contrast() -> bool:
    """True when the OS is in a forced-colours / high-contrast mode.

    Windows is the only platform that exposes a user-facing
    high-contrast mode, and it is reached through
    ``SystemParametersInfoW(SPI_GETHIGHCONTRAST)`` — Qt 6.11's
    ``QStyleHints.colorScheme`` only reports ``Dark`` / ``Light`` /
    ``Unknown`` and never flags forced colours.  Everything else
    returns ``False``, including macOS, which has no equivalent knob
    and where the app's own palette is already the user's only
    available choice.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class HIGHCONTRASTW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("lpszDefaultScheme", wintypes.LPWSTR),
            ]

        SPI_GETHIGHCONTRAST = 0x0042
        HCF_HIGHCONTRASTON = 0x00000001

        info = HIGHCONTRASTW()
        info.cbSize = ctypes.sizeof(HIGHCONTRASTW)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETHIGHCONTRAST, info.cbSize, ctypes.byref(info), 0
        )
        return bool(ok) and bool(info.dwFlags & HCF_HIGHCONTRASTON)
    except Exception:
        # Never let a detection failure break startup — worst case we
        # paint our own theme over a forced-colours session.
        return False


def _build_substitutions() -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key, value in TOKENS.colors.items():
        result[f"color.{key}"] = value
    for key, value in TOKENS.spacing.items():
        result[f"space.{key}"] = f"{value}px"
    for key, value in TOKENS.radius.items():
        result[f"radius.{key}"] = f"{value}px"
    for key, value in TOKENS.fonts.items():
        if isinstance(value, int):
            # Only the type scale is user-scalable. Radii and spacing
            # stay put so a larger text size grows the reading surface
            # without breaking the four-step layout rhythm.
            result[f"font.{key}"] = f"{max(1, round(value * _TEXT_SCALE))}px"
        else:
            result[f"font.{key}"] = str(value)
    # Forward-slash absolute path so QSS ``url(...)`` rules can
    # reference bundled SVG icons (checkbox indicator etc.). QSS
    # treats backslashes as escape characters, so always use
    # ``as_posix``.
    result["path.styles_dir"] = _STYLES_DIR.resolve().as_posix()
    # The combo's chevron is the one icon QSS paints, and ``image:
    # url(...)`` accepts a path and nothing else — there is no way to
    # hand it a token at paint time. So it gets a resolved copy on
    # disk, written under the app's cache. If that write fails the
    # stylesheet falls back to the raw file, which is a legible chevron
    # in the previous palette's grey rather than a broken combo.
    chevron = resolved_icon_file("chevron-down.svg", "text_secondary")
    if chevron is not None:
        result["path.chevron_icon"] = chevron
    else:
        result["path.chevron_icon"] = (
            _STYLES_DIR.resolve() / "icons" / "chevron-down.svg"
        ).as_posix()
    return result


def load_stylesheet(theme: str = "system") -> str:
    """Build the QSS for *theme*.

    ``theme`` is what the user chose, so ``"system"`` arrives here and is
    resolved here. The token swap happens before the substitutions are
    built rather than after, because ``_build_substitutions`` reads
    ``TOKENS.colors`` — swapping afterwards would paint a stylesheet
    assembled from the previous theme's colours, which is the exact bug a
    "the whole window went dark except the text" report looks like.
    """
    resolved = resolve_theme(theme)
    _swap_active_tokens(resolved)

    if is_high_contrast():
        # Forced colours means the user has hand-picked a palette they
        # can actually read, usually for a low-vision or sunlight
        # reason. Painting our Graphite ground over it defeats the
        # entire point, so we hand the window back to the OS palette
        # and let Qt's own forced-colour handling take over.
        return ""

    # One stylesheet for both themes. It was ``dark.qss`` when there was
    # only a dark theme, which was an honest name then and a lie once
    # there were two — a file called ``dark.qss`` serving the light theme
    # is the sort of thing that costs someone an afternoon.
    path = _STYLES_DIR / "base.qss"
    if not path.exists():
        raise ValueError(f"Missing stylesheet: {path}")

    qss = path.read_text(encoding="utf-8")
    for token, value in _build_substitutions().items():
        qss = qss.replace(f"{{{{{token}}}}}", value)
    return qss


def icon_path(filename: str) -> Optional[str]:
    """Resolve a bundled icon (SVG/PNG) under ``styles/icons/``.

    Returns the absolute path string, or ``None`` if the file is
    missing — callers should ``Path(...).is_file()`` to be safe in
    PyInstaller-frozen builds where icons might not have been
    bundled.
    """
    candidate = _STYLES_DIR / "icons" / filename
    return str(candidate) if candidate.exists() else None


# --- token-driven icon colour -------------------------------------------
#
# The sidebar icons used to carry a baked stroke — ``stroke="#f5f6f8"``
# from the palette that shipped before Gruvbox — and nothing in the
# system could change it. QSS ``color`` never reaches a QIcon's pixels,
# and the QSS ``::item`` colour rules that darken a selected row's label
# left its icon sitting at the old near-white: a cream pill carrying a
# white glyph, at 1.51:1. The icons were the one place in the app with
# no route to a token, and they read as "washed out" for exactly that
# reason.
#
# So the stroke in the file is a placeholder like any other, and these
# three helpers resolve it from TOKENS at the moment of use. The
# parameter is always a *token name*, never a hex: a literal here would
# reintroduce the exact second source of truth this removes.

def resolve_icon_svg(filename: str, stroke_token: Optional[str] = None) -> Optional[str]:
    """Return a bundled SVG with its token placeholders substituted.

    ``stroke_token`` overrides whatever stroke the file declares, which
    is how one icon file serves three different sidebar states.
    """
    path = icon_path(filename)
    if path is None:
        return None
    try:
        svg = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    if stroke_token is not None:
        if stroke_token not in TOKENS.colors:
            raise KeyError(
                f"{stroke_token!r} is not a colour token; pass a token "
                f"name, not a hex"
            )
        svg = re.sub(
            r'stroke="[^"]*"', f'stroke="{TOKENS.colors[stroke_token]}"', svg, count=1
        )
    # Only the colour tokens, deliberately: the full substitution map
    # resolves the combo chevron, which resolves an icon, which lands
    # back here. An icon never carries a radius or a font size.
    for key, value in TOKENS.colors.items():
        svg = svg.replace(f"{{{{color.{key}}}}}", value)
    return svg


def _screen_dpr() -> float:
    """The device pixel ratio to rasterise icons for.

    ``primaryScreen()`` is None before the QApplication exists and in a
    few headless setups, and a 0.0 ratio would make every ``QPixmap`` a
    zero-sized one. 1.0 is the honest floor: it is what those setups run
    at anyway.
    """
    from PySide6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def icon_pixmap(filename: str, stroke_token: str, size: int):
    """Rasterise a bundled SVG in one of the palette's colours.

    Returns a transparent ``QPixmap``, or ``None`` if the file is
    missing or the SVG will not parse — callers treat that the same way
    they treat a missing asset, by degrading rather than raising.

    **Rendered oversized, not at ``size``.** A 20 px sidebar icon on the
    built-in Retina display occupies 40 physical pixels, and a 20x20
    raster put into that slot has to be resampled 2x on the way out —
    which is what the nav icons looked like: soft, with the 1.6 px
    Heroicons strokes the worst affected. Measured on this machine, the
    shipped 20x20 raster leaves 384 mid-tone pixels in the icon column
    where the oversized one leaves 132 — 2.91x fewer, same glyph, same
    size on screen.

    Two things this deliberately does *not* do:

    - **It does not tag the pixmap with ``setDevicePixelRatio``.** That
      is the obvious move and it renders wrong: measured, a tagged 40x40
      dpr-2 pixmap comes back from ``QIcon::pixmap(iconSize)`` at
      40x40 tagged dpr 2.0, and the list delegate then draws it into the
      20 px slot at full device size — every glyph clipped to its
      top-left corner. Qt's item delegate does not honour the tag on the
      whole-pixmap draw path.
    - **It does not hand ``QIcon`` an SVG file.** ``addFile`` on the
      resolved SVG does render natively per-dpr, but it needs the SVG
      written to the cache first, and it came out byte-identical to
      simply oversizing the pixmap — Qt's downscale of the oversized
      render reproduces the native per-dpr raster exactly. So the cache
      write buys nothing and a frozen bundle would be asking for it.

    Left untagged, the oversized pixmap reports 40x40 as its icon size,
    Qt scales it down into the 20 px slot, and nothing anywhere has to
    agree on what a device pixel means.
    """
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QPixmap
    from PySide6.QtSvg import QSvgRenderer

    svg = resolve_icon_svg(filename, stroke_token)
    if svg is None:
        return None
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return None
    dpr = _screen_dpr()
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return pm


def resolved_icon_file(filename: str, stroke_token: str) -> Optional[str]:
    """Write a token-resolved icon into the cache and return its path.

    QSS ``image: url(...)`` is the one consumer that cannot be given
    runtime colour — it takes a file path and nothing else — so the
    combo's chevron needs the substituted SVG to exist on disk. It is
    written under the app's cache directory rather than next to the
    originals, because a frozen bundle is read-only and the source tree
    is not ours to mutate.
    """
    svg = resolve_icon_svg(filename, stroke_token)
    if svg is None:
        return None
    from platformdirs import user_cache_dir

    out_dir = Path(user_cache_dir("LazyToText", appauthor=False)) / "icons"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{Path(filename).stem}-{stroke_token}.svg"
        out.write_text(svg, encoding="utf-8")
    except OSError:
        return None
    return out.as_posix()


_FONTS_LOADED = False


def load_bundled_fonts() -> None:
    """Register every ``.ttf`` shipped under ``styles/fonts/`` with
    Qt's font database.

    Idempotent — if called twice (e.g. tests vs main), the same file
    is just re-registered and Qt deduplicates internally. We bundle
    Inter Variable so the UI looks identical on machines where the
    user hasn't pre-installed it; the font-family stack in
    ``TOKENS.fonts['family']`` references it by name.

    Should be called as early as possible after ``QApplication`` is
    constructed — Qt builds its font-alias cache lazily on the first
    ``QFont`` resolution, and any reference to "Inter" before this
    runs triggers a ``qt.qpa.fonts: Replace uses of missing font
    family "Inter"`` warning. Calling here from ``apply_theme`` is
    too late if widgets / icons / message boxes were created before
    the stylesheet is applied.
    """
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return
    fonts_dir = _STYLES_DIR / "fonts"
    if not fonts_dir.exists():
        _FONTS_LOADED = True
        return
    for path in fonts_dir.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(path))
    _FONTS_LOADED = True


def apply_theme(app: QApplication, theme: str = "system") -> None:
    load_bundled_fonts()
    app.setStyleSheet(load_stylesheet(theme))
    _watch_high_contrast(app, theme)


# --- Runtime high-contrast watcher ------------------------------------------
#
# Windows lets the user flip forced colours at any time, and it does not
# hand Qt a notification we can hook: ``QStyleHints.colorSchemeChanged``
# fires for light/dark but not for a forced-colours toggle, and a raw
# ``WM_SETTINGCHANGE`` never reaches the Qt event loop. So we poll.
# ``SystemParametersInfoW(SPI_GETHIGHCONTRAST)`` is a single cheap call
# into user32 with no allocation, once a second, on a thread-free
# callback — cheaper than the repaint a missed toggle would cost, and it
# means the window fixes itself the moment the user flips the switch
# instead of demanding a restart.

_HC_WATCHER: Optional[QTimer] = None
_HC_WATCHER_STATE: Optional[bool] = None


def _watch_high_contrast(app: QApplication, theme: str) -> None:
    """Keep the stylesheet in sync with the OS forced-colours state.

    No-op on every platform except Windows, and a no-op when the caller
    is running headless in tests (no primary screen means the poller has
    nothing to repaint anyway).
    """
    global _HC_WATCHER, _HC_WATCHER_STATE

    if sys.platform != "win32":
        return
    if _HC_WATCHER is not None:
        return

    _HC_WATCHER_STATE = is_high_contrast()
    timer = QTimer(app)
    timer.setInterval(1000)

    def _poll() -> None:
        global _HC_WATCHER_STATE
        current = is_high_contrast()
        if current == _HC_WATCHER_STATE:
            return
        _HC_WATCHER_STATE = current
        # ``setStyleSheet`` re-resolves every widget, so this both swaps
        # the palette and re-renders in one pass. Fonts are already
        # registered, and Qt re-resolves the family from the same stack.
        app.setStyleSheet(load_stylesheet(resolve_theme(theme)))

    timer.timeout.connect(_poll)
    timer.start()
    _HC_WATCHER = timer
