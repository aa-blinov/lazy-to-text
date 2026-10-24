"""A failed transcription keeps its type across the worker pipe.

QA-JOURNEYS-11 / QA-RUNTIME-3: the worker replies ``"TranscriptionError:
<text>"`` and the parent used to raise ``RuntimeError("Subprocess error:
TranscriptionError: <text>")``, so the pipeline's ``except
TranscriptionError`` never matched and the plumbing prefix reached the
user's screen.
"""

from __future__ import annotations

import time

import pytest

from app.backends.base import TranscriptionError, user_reason
from tests.backends.test_subprocess_backend import (  # noqa: F401 - fixtures
    _drive_worker,
    patched_subprocess,
)


def test_a_worker_side_transcription_error_is_rebuilt_as_one(patched_subprocess):
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]
    conn.script_next("error", "TranscriptionError: The model failed while transcribing: boom")

    with pytest.raises(TranscriptionError) as caught:
        backend.transcribe_file("/tmp/x.wav")

    assert str(caught.value) == "The model failed while transcribing: boom"
    assert "Subprocess" not in str(caught.value)


def test_any_other_worker_error_stays_a_runtime_error(patched_subprocess):
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]
    conn.script_next("error", "ValueError: nope")

    with pytest.raises(RuntimeError) as caught:
        backend.transcribe_file("/tmp/x.wav")

    assert not isinstance(caught.value, TranscriptionError)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Subprocess error: TranscriptionError: Could not read audio from a.wav",
         "Could not read audio from a.wav"),
        ("TranscriptionError: plain", "plain"),
        ("first line\n  Traceback: noise", "first line"),
    ],
)
def test_user_reason_strips_the_plumbing(raw, expected):
    assert user_reason(RuntimeError(raw)) == expected


def test_user_reason_caps_a_huge_onnx_message():
    assert len(user_reason(RuntimeError("x" * 5000))) <= 240


def test_a_model_change_reads_as_loading_before_the_worker_has_pushed(patched_subprocess):
    """``status()`` is a cache filled by pushes that arrive later than the
    command. Read right after ``change_model`` it said ``ready`` (the old
    model's), the watcher declared the new model loaded, and Cancel had
    nothing left to cancel (QA-RUNTIME-7)."""
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]
    conn.push(("status_change", "ready"))
    deadline = time.monotonic() + 2
    while backend.status() != "ready" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert backend.status() == "ready"

    backend.change_model("other/model")

    assert backend.status() == "loading"
    backend.shutdown()


def test_a_failed_change_model_command_restores_the_cached_status(patched_subprocess):
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend(model="x")
    conn = patched_subprocess["conn_holder"]["conn"]
    conn.push(("status_change", "ready"))
    deadline = time.monotonic() + 2
    while backend.status() != "ready" and time.monotonic() < deadline:
        time.sleep(0.01)
    conn.script_next("error", "RuntimeError: refused")

    with pytest.raises(RuntimeError):
        backend.change_model("other/model")

    assert backend.status() == "ready"
    backend.shutdown()


def test_the_worker_pushes_its_status_ahead_of_the_reply_to_a_load():
    """A load that finishes between two broadcaster polls is never seen as
    ``loading``; the push before the reply is what stops the parent
    waiting for a transition that already happened."""
    import multiprocessing
    import threading
    from unittest.mock import MagicMock

    import app.backends.subprocess_worker as worker_mod

    fake = MagicMock()
    fake.status.return_value = "ready"

    class _Backend:
        def __new__(cls, **_kw):
            return fake

    original = worker_mod._RegistryBackend
    worker_mod._RegistryBackend = _Backend
    parent, child = multiprocessing.Pipe(duplex=True)
    thread = threading.Thread(target=worker_mod._worker_main, args=(child,), daemon=True)
    thread.start()
    try:
        parent.send(("init", {"model": "x"}))
        assert parent.recv() == ("ok", None)
        parent.send(("cmd", 1, "change_model", "m", None))
        seen = []
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if parent.poll(0.05):
                msg = parent.recv()
                seen.append(msg)
                if msg[0] == "resp":
                    break
        kinds = [m[0] for m in seen]
        assert "resp" in kinds
        pushes = [i for i, m in enumerate(seen) if m[0] == "status_change"]
        assert pushes and pushes[0] < kinds.index("resp"), seen
    finally:
        parent.send(("shutdown_worker",))
        thread.join(timeout=2)
        worker_mod._RegistryBackend = original
