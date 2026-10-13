"""Dock icon follows the main window and the recording overlay.

The AppKit call itself only runs on the cocoa platform, which the suite
never uses, so these tests pin the rule and the wiring. What the rule
*does* on a real Mac has to be checked on the machine itself.
"""

from __future__ import annotations

import pytest

from app.gui.dock_presence import apply_dock_presence, wants_dock_icon


@pytest.mark.parametrize(
    ("main_visible", "overlay_visible", "expected"),
    [
        (True, False, True),    # window open, idle: Dock icon
        (True, True, False),    # dictating over another app: accessory
        (False, True, False),   # window in the tray, dictating
        (False, False, False),  # window in the tray, idle: no Dock icon
    ],
)
def test_the_rule_puts_the_dock_icon_only_with_the_window_and_no_dictation(
    main_visible, overlay_visible, expected
):
    assert wants_dock_icon(main_visible, overlay_visible) is expected


def test_apply_is_a_no_op_on_the_offscreen_platform():
    # Offscreen there is no NSApplication to change. The call must return
    # without reaching AppKit, and AppKit is not importable on the CI legs
    # that run this, so a silent return is what the test can check.
    assert apply_dock_presence(main_visible=True, overlay_visible=False) is None


@pytest.mark.parametrize(
    ("window_visible", "overlay_visible", "expected"),
    [(True, False, True), (True, True, False), (False, True, False)],
)
def test_the_main_window_passes_both_visibilities_to_the_policy(
    monkeypatch, window_visible, overlay_visible, expected
):
    # Called on a stand-in rather than a built MainWindow: constructing one
    # starts thumbnail runnables that outlive it and crash whichever test
    # the worker runs next. The signal wiring is one line in __init__.
    from types import SimpleNamespace

    from app.gui import main_window as mw_module
    from app.gui.main_window import MainWindow

    seen = []
    monkeypatch.setattr(
        mw_module, "apply_dock_presence",
        lambda main_visible, overlay_visible: seen.append(
            (main_visible, overlay_visible)),
    )
    stand_in = SimpleNamespace(
        isVisible=lambda: window_visible,
        recording_overlay=SimpleNamespace(isVisible=lambda: overlay_visible),
    )

    MainWindow._sync_dock_presence(stand_in)

    assert seen == [(window_visible, overlay_visible)]
    assert wants_dock_icon(window_visible, overlay_visible) is expected
