"""Design tokens and QSS loader for the Qt UI.

Tokens live in Python so widgets can reference them directly. The QSS files
use ``{{group.key}}`` placeholders that are substituted at load time.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
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
        # Slightly bluer, more saturated dark base — gives the surface
        # a "designed" feel instead of pure neutral gray.
        "bg_primary": "#0f1115",
        "bg_secondary": "#1a1d24",
        "bg_elevated": "#252932",
        "bg_hover": "#2d323d",
        "accent": "#5b8cff",
        "accent_hover": "#7aa2ff",
        "text_primary": "#f5f6f8",
        "text_secondary": "#b8bcc6",
        "text_muted": "#7d828d",
        "border": "#2d3140",
        "success": "#4ade80",
        "danger": "#ef4444",
        "warning": "#f59e0b",
        # The warning banner's button is a filled amber chip, and its
        # hover has to be a lighter step — which is the same value the
        # turbo family uses for its ink. One value, one name.
        "warning_hover": "#fbbf24",
        # Family pairs — surface, ink, and a one-step-lighter border of
        # the same hue. These were QSS literals for the life of the
        # project while DESIGN.md documented them as tokens; a literal
        # that is also a documented token is drift, and a value that a
        # Python widget cannot reach is a token that is not a token.
        "family_whisper_surface": "#1d2746",
        "family_whisper_ink": "#93b5ff",
        "family_whisper_border": "#2d3f6c",
        "family_turbo_surface": "#3d2a0a",
        "family_turbo_ink": "#fbbf24",
        "family_turbo_border": "#5a3f17",
        "family_distil_surface": "#1c3a28",
        "family_distil_ink": "#86efac",
        "family_distil_border": "#2c5a3e",
        "family_ru_surface": "#4a1c1c",
        "family_ru_ink": "#fca5a5",
        "family_ru_border": "#6c2929",
        "family_gigaam_surface": "#3a1c4a",
        "family_gigaam_ink": "#d8b4fe",
        "family_gigaam_border": "#5a2c6c",
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
        app.setStyleSheet(load_stylesheet("dark"))
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
    return result


def load_stylesheet(theme: str = "dark") -> str:
    if is_high_contrast():
        # Forced colours means the user has hand-picked a palette they
        # can actually read, usually for a low-vision or sunlight
        # reason. Painting our Graphite ground over it defeats the
        # entire point, so we hand the window back to the OS palette
        # and let Qt's own forced-colour handling take over.
        return ""

    path = _STYLES_DIR / f"{theme}.qss"
    if not path.exists():
        raise ValueError(f"Unknown theme: {theme!r} (looked for {path})")

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


def apply_theme(app: QApplication, theme: str = "dark") -> None:
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
        app.setStyleSheet(load_stylesheet(theme))

    timer.timeout.connect(_poll)
    timer.start()
    _HC_WATCHER = timer
