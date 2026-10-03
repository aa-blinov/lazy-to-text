"""Focus management helpers for transient widget state changes.

Every ``NoFocus`` in this codebase was added to work around the same Qt
behaviour: when the widget holding keyboard focus is hidden or disabled,
Qt hands focus to whatever comes next in the tab chain on its own. The
three places this bit us each have their own flavour of the bug —

* the mic-test button, disabled for three seconds, dropped the cursor
  into the Start-hotkey ``QLineEdit``;
* the Download button, hidden the instant a card turns Active, sent
  focus to the *next card's* Download button, and the enclosing
  ``QScrollArea`` dutifully scrolled down to it;
* the storage row, disabled as a unit, dropped focus somewhere
  arbitrary.

The workarounds were ``setFocusPolicy(Qt.NoFocus)``, which keeps the
mouse working but takes the control out of the tab order entirely — so
twelve of the app's actions, including the only way to delete a cached
model, could not be reached from the keyboard at all.

The correct fix is to decide where focus goes *before* the widget
leaves, and then leave the widget focusable. ``release_focus_before``
does that. Keeping the controls in the tab chain costs nothing here:
this app is driven by a global hotkey and a keyboard, so an action
that is mouse-only is a hole in the primary interaction path, not a
polish item.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget


def _is_focusable(widget: QWidget) -> bool:
    return (
        widget.isVisible()
        and widget.isEnabled()
        and widget.focusPolicy() != Qt.FocusPolicy.NoFocus
    )


def _first_focusable_in_window(widget: QWidget) -> Optional[QWidget]:
    """Left-most focusable control in the widget's window.

    Used as the fallback when the caller has no better idea. Scanning in
    creation order rather than geometric order keeps the result stable
    across resizes, which matters because the Models view builds its
    cards in alias order and re-orders them when filters change.
    """
    window = widget.window()
    for candidate in window.findChildren(QWidget):
        if candidate is widget:
            continue
        if _is_focusable(candidate):
            return candidate
    return None


def release_focus_before(
    widget: QWidget,
    fallback: Optional[QWidget] = None,
) -> bool:
    """Move focus off *widget* before it is hidden or disabled.

    Call this immediately **before** ``setVisible(False)`` or
    ``setEnabled(False)`` on *widget*. If *widget* does not currently
    hold focus this is a no-op and returns ``False``.

    *fallback* is where focus goes. When omitted, focus lands on the
    first focusable control in the same window, which is a visible,
    predictable neighbour rather than Qt's choice. A fallback that is
    itself hidden, disabled, or focus-less is skipped.

    Returns ``True`` when focus was actually moved, so callers can tell
    "handled" from "nothing to do" without re-querying.
    """
    app = QApplication.instance()
    if app is None or not widget.hasFocus():
        return False

    target: Optional[QWidget] = None
    if fallback is not None and _is_focusable(fallback):
        target = fallback
    else:
        target = _first_focusable_in_window(widget)

    if target is None:
        # Nothing sensible to focus. Clearing it is still better than
        # letting Qt pick: `OtherFocusReason` does not make the view
        # scroll, and the next Tab resumes from the top of the chain.
        widget.clearFocus()
        return True

    target.setFocus(Qt.FocusReason.OtherFocusReason)
    return True


def install_tab_order(*widgets: Optional[QWidget]) -> None:
    """Make the tab chain run through *widgets* in the order given.

    Qt's default order is widget-creation order, which happens to track
    the visual layout here but drifts the moment a view re-orders rows
    (the Models view does, on every filter change) or a card is rebuilt.
    Stating it explicitly costs one line per view and removes the whole
    class of problem. ``None`` entries are skipped, so a caller can pass
    an optional widget without branching.

    Note there is deliberately no attempt to "anchor the head" of the
    chain. ``setTabOrder(first, second)`` means only *after ``first``
    comes ``second``*; calling it a second time with the same ``first``
    overwrites that link rather than adding one, so a closing
    ``setTabOrder(first, last)`` would break the very sequence this
    function exists to establish.
    """
    present = [w for w in widgets if w is not None]
    if len(present) < 2:
        return
    for previous, current in zip(present, present[1:]):
        QWidget.setTabOrder(previous, current)
