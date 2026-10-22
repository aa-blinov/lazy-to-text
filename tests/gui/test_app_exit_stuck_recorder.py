"""The app has to be able to quit, even with a wedged microphone.

A recording thread that could not be stopped is parked inside
PortAudio's stop path. It holds the GIL and the microphone, and
``Pa_Terminate`` deadlocks on the way out of the interpreter. The
process then stays alive with no window while still owning the
single-instance lock — so the next launch is refused and the app looks
launched but broken. That is exactly what the field report was.

The patched PortAudio in the bundle makes the stop path safe, but the
exit path must not depend on it: this is the part that turns a bad
moment into an app the user cannot use.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


_APP_PY = Path(__file__).resolve().parents[2] / "app" / "gui" / "app.py"


class _Controller:
    """The shape ``RecordingController`` exposes to the exit path."""

    def __init__(self, stuck: bool):
        self._stuck = stuck

    def recording_thread_stuck(self) -> bool:
        return self._stuck


def test_no_controller_means_nothing_is_stuck():
    from app.gui.app import _recording_thread_stuck

    assert _recording_thread_stuck(None) is False


def test_a_healthy_recorder_is_not_stuck():
    from app.gui.app import _recording_thread_stuck

    assert _recording_thread_stuck(_Controller(False)) is False


def test_a_wedged_microphone_is_stuck():
    from app.gui.app import _recording_thread_stuck

    assert _recording_thread_stuck(_Controller(True)) is True


def test_a_probe_that_raises_does_not_take_the_exit_down():
    """Defensive: a broken probe must not stop the app from quitting."""

    class _Broken:
        def recording_thread_stuck(self):
            raise RuntimeError("probe exploded")

    from app.gui.app import _recording_thread_stuck

    assert _recording_thread_stuck(_Broken()) is False


def test_a_controller_without_the_probe_is_not_stuck():
    from app.gui.app import _recording_thread_stuck

    assert _recording_thread_stuck(object()) is False


def test_the_exit_path_actually_asks():
    """The helper is only useful if ``main`` consults it.

    Asserted on the AST rather than on the text: the call has to be
    inside ``main``'s body, not merely mentioned in the file.
    """
    tree = ast.parse(_APP_PY.read_text())
    main_func = next(
        (node for node in tree.body
         if isinstance(node, ast.FunctionDef) and node.name == "main"),
        None,
    )
    assert main_func is not None, "app/gui/app.py has no main()"

    called = {
        node.func.id
        for node in ast.walk(main_func)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_recording_thread_stuck" in called, (
        "main() no longer consults the recorder's stuck thread — an app "
        "with a wedged microphone would hang on exit again"
    )


@pytest.mark.parametrize("module", ["app.gui.app"])
def test_importing_the_helper_does_not_need_a_running_app(module):
    """The helper is importable on its own, so the test says what it says."""
    import importlib

    assert hasattr(importlib.import_module(module), "_recording_thread_stuck")
