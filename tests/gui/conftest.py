"""Shared fixtures for the Qt GUI test tree.

Top-level ``conftest.py`` already pins the offscreen Qt platform.
This file adds an ``autouse`` fixture that stubs the modal-dialog
helpers (``confirm`` / ``confirm_three_way`` / ``notify``) at every
callsite where the production code imports them.

Why an autouse stub
-------------------
``QMessageBox.exec()`` is a blocking modal — pytest can't dismiss
it, so any test that triggers a code path which shows a dialog
hangs forever. The previous code monkey-patched
``QMessageBox.question`` / ``information`` static methods directly;
those are still the names tests historically used, but the
production code now goes through ``app.gui.widgets.dialogs.confirm``
/ ``notify`` which build a ``QMessageBox`` instance. Stubbing the
helpers here keeps those tests passing without each one needing
its own monkey-patch boilerplate.

Tests that want to assert a particular dialog answer (e.g.
"Cancel doesn't delete") simply override the relevant attribute
with their own ``monkeypatch.setattr(...)`` — pytest applies
overrides on top of fixtures.
"""

from __future__ import annotations

import pytest


# --- Width diagnostics -----------------------------------------------------
#
# A layout overflow is a *number*, and a number is not a bug report.
# "needs 2px more width" names a size and nothing about the cause, which
# is useless when the overflow only appears on a platform you cannot
# reproduce it on — the Settings page overflows by 2px on Windows CI at
# text scale 1.75 and by 0px on a Mac with the same bundled font, the
# same stylesheet and the same test.
#
# So every overflow assertion here reports a ladder instead: the widget
# that sets the minimum, then the row inside it, then the widget inside
# that row. The next CI run answers "which of these grew on Windows"
# with a measurement rather than a guess.

def _safe_width(widget) -> int:
    """Minimum width of a widget, or 0 if it cannot answer any more.

    ``minimumSizeHint()`` raises ``RuntimeError`` on a widget whose C++
    half is already gone — Qt deletes children on window close, and
    ``findChildren`` happily hands back the ones it is about to.
    """
    try:
        return widget.minimumSizeHint().width()
    except (AttributeError, RuntimeError):
        return 0


def _named(widget, width: int) -> str:
    """Identify a widget by name, else by the text it shows.

    The text fallback is what makes a ladder readable when the widgets
    have no ``objectName``: three unlabelled ``QPushButton``s all print
    as "QPushButton", which names a class rather than a thing you can go
    and look at.
    """
    label = widget.objectName()
    if not label:
        text = getattr(widget, "text", None)
        if callable(text):
            try:
                label = widget.text()
            except (AttributeError, RuntimeError):
                label = ""
        label = label or type(widget).__name__
    return f"{label} ({type(widget).__name__}, {width}px)"


def _why(widget) -> str:
    """The one level below ``widget``, if it has an explainable inside."""
    from PySide6.QtWidgets import QFormLayout, QLayout

    form = widget.findChild(QFormLayout)
    if form is None:
        return ""
    # TRAP: ``itemAt(row, role)`` wants the enum, not the bare int, and
    # the int is a silent no-op in PySide6.
    parts = []
    for row in range(form.rowCount()):
        label = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
        field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
        if label is None and field is None:
            continue
        text = label.widget().text() if label and label.widget() else ""
        lw = _safe_width(label.widget()) if label and label.widget() else 0
        fw = field.minimumSize().width() if field is not None else 0
        if not lw and not fw:
            continue
        # Name what is inside the field too: a form row's width is
        # "label + field", so "row 1" alone still leaves the reader
        # guessing which of the two grew. TRAP: the field item is a
        # ``QLayoutItem`` when the row holds a nested layout and a
        # ``QWidgetItem`` when it holds a bare widget — only the first
        # has ``count()``, and reaching for it on the second is an
        # ``AttributeError`` in the middle of a failure message.
        inside = ""
        if isinstance(field, QLayout):
            inner = max(
                (field.itemAt(i).minimumSize().width()
                 for i in range(field.count())
                 if field.itemAt(i) is not None),
                default=0,
            )
            for i in range(field.count()):
                sub = field.itemAt(i)
                if sub is not None and sub.minimumSize().width() == inner:
                    w = sub.widget()
                    if w is not None:
                        inside = f" [{_named(w, inner)}]"
                    break
        elif field is not None and field.widget() is not None:
            # The bare-widget shape has no layout to walk, but it still
            # deserves a name — "field 175px" alone does not say what
            # is 175px wide.
            inside = f" [{_named(field.widget(), fw)}]"
        parts.append(f"row {row}: {text!r} {lw}px + field {fw}px{inside}")
    return " <- " + "; ".join(parts) if parts else ""


def _explain(container) -> str:
    """Name the widest descendant and, one level down, why it is that wide."""
    widest, who = 0, None
    for child in container.findChildren(object):
        width = _safe_width(child)
        if width > widest:
            widest, who = width, child
    if who is None:
        return "?"
    return _named(who, widest) + _why(who)


@pytest.fixture(scope="session")
def explain_width():
    """Report what sets a container's minimum width, level by level.

    Pass the scroll area's content widget; get back something a person
    can act on::

        assert over == 0, explain_width(sa.widget())
    """
    return _explain


_HELPER_TARGETS = (
    # Each entry: ``module.attr`` and a default-stub return value.
    # Stubs accept ``*a, **kw`` so the helpers' optional
    # ``yes_label`` / ``default_yes`` etc. don't trip them up.
    ("app.gui.controllers._history_mixin.confirm", True),
    ("app.gui.controllers._history_mixin.notify", None),
    ("app.gui.controllers._storage_mixin.notify", None),
    ("app.gui.controllers._storage_mixin.confirm_three_way", "no"),
    ("app.gui.controllers.app_controller.confirm", True),
    # The dialogs module itself, in case a future caller imports
    # the helper at module load and the per-callsite patches above
    # don't catch it.
    ("app.gui.views.logs_view.confirm", True),
    ("app.gui.widgets.dialogs.confirm", True),
    ("app.gui.widgets.dialogs.confirm_three_way", "no"),
    ("app.gui.widgets.dialogs.notify", None),
)


@pytest.fixture(autouse=True)
def stub_modal_dialogs(monkeypatch: pytest.MonkeyPatch):
    """Replace every modal-dialog helper with a non-blocking stub
    so tests don't hang on ``QMessageBox.exec()``.

    The default for ``confirm_three_way`` is ``"no"`` (leave-as-is)
    rather than ``"yes"`` because most code paths gate destructive
    work behind ``"yes"`` and a default of "yes" would silently
    perform actions tests didn't ask for. Tests that need a
    specific answer override this fixture's stub:

    .. code-block:: python

        monkeypatch.setattr(
            "app.gui.controllers._storage_mixin.confirm_three_way",
            lambda *a, **kw: "yes",
        )
    """
    for target, default in _HELPER_TARGETS:
        monkeypatch.setattr(
            target,
            lambda *_a, _default=default, **_kw: _default,
            raising=False,
        )
    yield
