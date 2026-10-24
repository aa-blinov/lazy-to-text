"""The Transcribe screen's methods, against stand-ins for the backend."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from app.server.events import bus
from app.server.handlers import files
from app.server.rpc import RpcError


class _Backend:
    def __init__(self, text="hello there", error=None, ready=True, gate=None):
        self.text = text
        self.error = error
        self.ready = ready
        self.gate = gate
        self.paths = []

    def health_check(self):
        return self.ready

    def transcribe_file(self, path):
        self.paths.append(path)
        if self.gate is not None:
            self.gate.wait(5)
        if self.error:
            raise RuntimeError(self.error)
        return self.text


class _State:
    def __init__(self, backend):
        self.backend = backend


def _rt(backend=None):
    return SimpleNamespace(
        state_manager=_State(backend) if backend is not None else None,
        stack_error=None,
    )


def _collect(sub, names, timeout=5.0):
    seen = []
    while True:
        item = sub.get(timeout)
        assert item is not None, f"no {names} event; saw {seen}"
        if item[0] in names:
            return item[0], json.loads(item[1])
        seen.append(item[0])


@pytest.fixture
def sub():
    s = bus.subscribe()
    yield s
    s.close()


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "memo.wav"
    path.write_bytes(b"RIFF")
    return str(path)


def test_the_formats_are_the_ones_the_qt_view_accepts():
    from app.gui.views import transcribe_view

    result = files.formats(_rt(), {})
    assert tuple(result["extensions"]) == transcribe_view._AUDIO_EXTS


def test_a_run_reports_the_path_and_the_text(sub, audio):
    backend = _Backend("some words")
    result = files.transcribe(_rt(backend), {"path": audio})

    assert result == {"started": True, "path": audio, "size": 4}
    name, data = _collect(sub, {"file.done", "file.failed"})
    assert name == "file.done"
    assert data["path"] == audio
    assert data["text"] == "some words"
    assert data["elapsed"] >= 0
    assert backend.paths == [audio]


def test_a_backend_failure_arrives_as_an_event_with_its_reason(sub, audio):
    files.transcribe(_rt(_Backend(error="decoder exploded")), {"path": audio})

    name, data = _collect(sub, {"file.done", "file.failed"})
    assert name == "file.failed"
    assert data == {"path": audio, "message": "decoder exploded"}


def test_an_empty_recognition_is_done_with_no_text_not_a_failure(sub, audio):
    files.transcribe(_rt(_Backend(text="")), {"path": audio})

    name, data = _collect(sub, {"file.done", "file.failed"})
    assert (name, data["text"]) == ("file.done", "")


def test_progress_is_announced_for_the_running_file(sub, audio):
    gate = threading.Event()
    files.transcribe(_rt(_Backend(gate=gate)), {"path": audio})
    try:
        name, data = _collect(sub, {"file.progress"})
        assert data["path"] == audio
    finally:
        gate.set()


@pytest.mark.parametrize("backend, code", [
    (None, "no_stack"),
    (_Backend(ready=False), "not_ready"),
])
def test_a_run_that_cannot_start_says_why(audio, backend, code):
    with pytest.raises(RpcError) as err:
        files.transcribe(_rt(backend), {"path": audio})
    assert err.value.code == code


def test_a_missing_file_is_refused_before_anything_starts(tmp_path):
    backend = _Backend()
    with pytest.raises(RpcError) as err:
        files.transcribe(_rt(backend), {"path": str(tmp_path / "gone.wav")})
    assert err.value.code == "not_found"
    assert err.value.message == "That file is no longer there."
    assert backend.paths == []


def test_the_extension_guard_applies_only_when_asked(tmp_path, sub):
    odd = tmp_path / "notes.txt"
    odd.write_text("x")
    rt = _rt(_Backend())

    with pytest.raises(RpcError) as err:
        files.transcribe(rt, {"path": str(odd), "strict": True})
    assert err.value.code == "bad_extension"

    # Browse and OS opens name any existing file.
    assert files.transcribe(rt, {"path": str(odd)})["started"] is True
    _collect(sub, {"file.done", "file.failed"})


def test_a_backend_without_file_support_is_named():
    backend = SimpleNamespace(health_check=lambda: True)
    rt = SimpleNamespace(state_manager=SimpleNamespace(backend=backend),
                         stack_error=None)
    with pytest.raises(RpcError) as err:
        files._ready_backend(rt)
    assert err.value.code == "unsupported"


def test_save_text_writes_utf8_and_reports_a_failure(tmp_path):
    target = tmp_path / "out.txt"
    assert files.save_text(None, {"path": str(target), "text": "privet мир"}) == {
        "saved": str(target)}
    assert target.read_text(encoding="utf-8") == "privet мир"

    with pytest.raises(RpcError) as err:
        files.save_text(None, {"path": str(tmp_path / "no" / "dir.txt"), "text": "x"})
    assert err.value.code == "write_failed"
