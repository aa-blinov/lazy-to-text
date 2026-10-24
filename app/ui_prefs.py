"""The look-and-language preferences and their allowed values, with no UI imports.

The runtime reads ``ui.theme``, ``ui.language`` and ``ui.text_scale`` from
the one ``config.yaml`` and has to say what a hand-edited value means,
so the bounds and the fallbacks are written once, here.
"""

from __future__ import annotations

# Bounds for the user-facing text scale. 1.0 is the design baseline. The
# floor keeps small labels legible; the ceiling stops the type scale from
# colliding with the fixed radius steps and clipping card interiors.
TEXT_SCALE_MIN = 0.85
TEXT_SCALE_MAX = 1.75
#: The presets a screen offers. A stored value between them is snapped.
TEXT_SCALE_PRESETS = (1.0, 1.15, 1.3, 1.5, 1.75)

THEMES = ("system", "light", "dark")
DEFAULT_THEME = "system"

#: The six palettes of the @monos/ui kit; the first is the default.
PALETTES = ("gruvbox", "github", "dracula", "nord", "solarized", "catppuccin")
DEFAULT_PALETTE = PALETTES[0]

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "ru")
#: Names as they are written in each language, so a user who has landed on
#: the wrong one can still find their own in the list.
NATIVE_NAMES: dict[str, str] = {"en": "English", "ru": "Русский"}


def normalise_theme(value: object) -> str:
    """One of the three names a user may choose; anything else is the default.

    This is the *stored* value, so ``system`` stays ``system`` instead of
    being frozen to whichever theme it resolved to on the day it was written.
    A config file is a thing people edit, and refusing to start over a typo
    in a cosmetic setting is the wrong trade.
    """
    name = str(value or "").strip().lower()
    return name if name in THEMES else DEFAULT_THEME


def normalise_palette(value: object) -> str:
    name = str(value or "").strip().lower()
    return name if name in PALETTES else DEFAULT_PALETTE


def normalise_language(value: object) -> str:
    """Unknown or empty values fall back to English, never raise."""
    code = str(value or "").strip().lower()
    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def clamp_text_scale(value: object) -> float:
    """A usable multiplier for any stored value, NaN and junk included."""
    try:
        candidate = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    if candidate != candidate:  # NaN
        return 1.0
    return max(TEXT_SCALE_MIN, min(TEXT_SCALE_MAX, candidate))
