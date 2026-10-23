"""The overlay's native window on macOS.

The recording overlay — and with it the delivery confirmation — is a
floating panel that has to be on screen while the user is in another
app.  Two macOS behaviours decide whether it is:

- a window of a **hidden** application is not on screen, even when it
  is ordered front, so the app has to wake up before the panel is
  ordered;
- a window that is **not on the active space** is on screen and
  invisible at the same time.

The native calls cannot be exercised off the cocoa platform — the
offscreen suite skips them — so what is asserted here is the contract:
the function does nothing at all elsewhere, and it is called on every
appearance rather than once.
"""

import ast
import inspect
from pathlib import Path

import pytest

from app.gui.mac_window import float_over_full_screen


def test_off_cocoa_the_native_window_is_left_alone():
    """Nothing to adjust without a native window."""
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() == "cocoa":
        pytest.skip("on cocoa the native path is taken")
    assert float_over_full_screen(object()) is False


def test_the_overlay_adjusts_its_window_on_every_appearance():
    """Once per process is not enough.

    The overlay disappears without an error and without a trace, so the
    state at the moment it was shown is the only evidence there is. The
    log line has to be written every time the window is shown, not once
    at startup.
    """
    source = inspect.getsource(float_over_full_screen)
    assert "log.info(" in source
    assert "on_active_space" in source


def test_the_overlay_wakes_the_app_before_ordering_itself_front():
    """A window of a hidden application is not on screen.

    ``orderFrontRegardless`` orders the window; it does not wake the
    application. The app spends most of its life hidden — its main
    window sits in the tray — so the wake-up has to be explicit.
    """
    source = inspect.getsource(float_over_full_screen)
    assert "isHidden()" in source
    assert "unhideWithoutActivation" in source

    # The wake-up comes before the window is ordered front. Compared on
    # the call sites themselves: the name also appears in a comment
    # above them, and a text search would find that one first.
    import app.gui.mac_window as module

    tree = ast.parse(Path(module.__file__).read_text())
    func = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "float_over_full_screen"
    )
    calls = {
        node.func.attr: node.lineno
        for node in ast.walk(func)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls["unhideWithoutActivation"] < calls["orderFrontRegardless"]


def test_the_overlay_reorders_itself_onto_the_active_space():
    """A window on another space is on screen and invisible at once."""
    source = inspect.getsource(float_over_full_screen)
    assert "isOnActiveSpace" in source


def test_the_call_sites_do_not_skip_the_adjustment():
    """Every appearance has to adjust the window.

    The overlay is shown for three states in a row — recording,
    processing, delivery — and each of them is a separate appearance.
    A guard that only adjusted the first one would leave the panel
    behind whatever was in front of it.
    """
    from app.gui.widgets import recording_overlay

    tree = ast.parse(Path(recording_overlay.__file__).read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_apply_mac_window_behaviors"
    ]
    assert calls, "the overlay never adjusts its native window"
