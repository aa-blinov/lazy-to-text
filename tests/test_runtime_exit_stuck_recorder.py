"""The app has to be able to quit, even with a wedged microphone.

A recording thread that could not be stopped is parked inside PortAudio's
stop path. It holds the GIL and the microphone, and ``Pa_Terminate``
deadlocks on the way out of the interpreter. The process then stays alive
with no window while still owning the single-instance lock, so the next
launch is refused and the app looks launched but broken.

The patched PortAudio in the bundle makes the stop path safe, but the exit
path must not depend on it: ``Runtime.stuck()`` says whether a model load or
a recording thread would block exit, and ``app/server/__main__.py`` leaves the
process with ``os._exit`` when it does.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.server.runtime import Runtime

_MAIN = Path(__file__).resolve().parents[1] / "app" / "server" / "__main__.py"


class _Recorder:
    def __init__(self, stuck):
        self._stuck = stuck

    def has_stuck_recording_thread(self):
        if isinstance(self._stuck, Exception):
            raise self._stuck
        return self._stuck


class _State:
    def __init__(self, recorder):
        self.audio_recorder = recorder


class _Backend:
    def __init__(self, loading):
        self._loading = loading

    def load_in_flight(self):
        return self._loading


def _runtime(*, recorder=None, loading=False, backend=True):
    runtime = Runtime(config=object())
    runtime.backend = _Backend(loading) if backend else None
    runtime.state_manager = _State(recorder)
    return runtime


def test_nothing_stuck_when_nothing_was_built():
    assert Runtime(config=object()).stuck() is False


def test_a_healthy_recorder_is_not_stuck():
    assert _runtime(recorder=_Recorder(False)).stuck() is False


def test_a_wedged_microphone_is_stuck():
    assert _runtime(recorder=_Recorder(True)).stuck() is True


def test_a_model_load_in_flight_is_stuck():
    assert _runtime(recorder=_Recorder(False), loading=True).stuck() is True


def test_a_probe_that_raises_does_not_take_the_exit_down():
    assert _runtime(recorder=_Recorder(RuntimeError("probe exploded"))).stuck() is False


def test_a_recorder_without_the_probe_is_not_stuck():
    assert _runtime(recorder=object()).stuck() is False


def test_the_exit_path_actually_asks():
    """``stuck()`` is only useful if ``main`` consults it and then leaves hard."""
    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))
    main_func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    attrs = [n.func.attr for n in ast.walk(main_func)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert "stuck" in attrs, "main() no longer consults Runtime.stuck()"
    assert "_exit" in attrs, "main() no longer leaves with os._exit"
