"""Native window-chrome fixes that a Qt stylesheet cannot reach.

The app paints its own title-bar-adjacent surfaces, but the Windows
title bar is drawn by DWM and follows the *system* theme. On Windows 11
with a light system theme that produces a pale strip sitting on top of
a dark window — a seam the user cannot fix from inside the app, because
the setting lives in Settings → Personalisation, not here.

The request is made for the theme the app is actually painting, so the
same seam does not reappear inverted once the light palette exists. A
light app asking DWM for a dark title bar is the same defect with the
colours swapped, and it would only show on Windows.

This module asks DWM for the dark title bar explicitly. Everything is
guarded three ways: the platform, the DWM attribute version, and the
call itself, so a Windows build without the API (or a Wine prefix)
falls through silently instead of raising during startup.

macOS is already correct: the unified toolbar takes its appearance
from the app's own material, and Qt's Cocoa plugin follows
``NSApp``'s effective appearance. Nothing to do there.
"""

from __future__ import annotations

import sys
from typing import Optional


def _dwm_dark_mode_attributes() -> tuple[int, ...]:
    """DWM attribute ids for the immersive dark title bar, newest first.

    ``20`` is Windows 11 22H2 and Windows 10 21H2+; ``19`` is the
    original 1809 preview id. Windows 10 rejects ``20``, Windows 11
    before 22H2 rejects ``19``, and returning ``False`` from
    ``DwmSetWindowAttribute`` is the documented "not supported" signal
    rather than an error — so we simply try both and stop at the first
    that sticks.
    """
    return (20, 19)


def apply_dark_title_bar(widget: Optional[object], dark: Optional[bool] = None) -> bool:
    """Draw *widget*'s title bar in the same mode the app is painting.

    ``dark`` defaults to the theme actually in force, read from
    ``theme.active_theme()``. Resolved here rather than at the call site
    so a theme the user switches at runtime cannot leave the title bar
    behind; the import is local so this module keeps no dependency on
    the palette.

    Returns ``True`` when DWM accepted the request. A no-op returning
    ``False`` on every non-Windows platform, which is what callers
    should assume rather than branching on ``sys.platform`` themselves.
    """
    if sys.platform != "win32" or widget is None:
        return False

    if dark is None:
        try:
            from app.gui.theme import active_theme

            dark = active_theme() == "dark"
        except Exception:  # pragma: no cover — never block startup
            dark = True
    return _set_dark_mode(widget, dark)


def _set_dark_mode(widget: Optional[object], enabled: bool) -> bool:
    """The DWM call itself, for either mode.

    Split out from ``apply_dark_title_bar`` so releasing the immersive
    dark title bar goes through exactly the same attribute probing as
    setting it. Doing nothing instead would be the obvious version and
    is wrong: a window that was handed a dark title bar earlier in the
    process keeps it, which is the seam this module exists to remove,
    now in the other direction.
    """
    try:
        import ctypes
        from ctypes import wintypes

        # ``winId()`` materialises the native handle; a widget that has
        # never been shown may not have one yet, hence the show() call
        # that the caller has already made by this point.
        hwnd = wintypes.HWND(int(widget.winId()))  # type: ignore[attr-defined]
        if not hwnd:
            return False

        dwm = ctypes.windll.dwmapi
        flag = wintypes.BOOL(bool(enabled))

        for attribute in _dwm_dark_mode_attributes():
            hr = dwm.DwmSetWindowAttribute(
                hwnd,
                wintypes.DWORD(attribute),
                ctypes.byref(flag),
                ctypes.sizeof(flag),
            )
            # S_OK == 0. Anything else means this build does not know
            # the attribute, so fall through to the next id.
            if hr == 0:
                return bool(enabled)

        # Pre-1809 builds (and some Wine prefixes) do not implement the
        # DWM attribute at all. The undocumented "DarkMode_Explorer"
        # window theme is the long-standing fallback and costs one
        # call, so try it before giving up. A light theme asks for the
        # ordinary explorer theme, which is the documented way to undo
        # an earlier "DarkMode_Explorer".
        uxtheme = ctypes.windll.uxtheme
        uxtheme.SetWindowTheme(
            hwnd, "DarkMode_Explorer" if enabled else "Explorer", None,
        )
        return False
    except Exception:
        # Never let window-chrome polish break startup. A light title
        # bar is cosmetic; a raised exception here is a blank app.
        return False
