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

    def transcribe_file(self, path, diarize=False, speaker_label="Speaker", speakers=None):
        self.paths.append(path)
        self.speakers = speakers
        self.diarized = (diarize, speaker_label) if diarize else None
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


def test_the_formats_are_the_shared_list():
    from app.audio_formats import AUDIO_EXTS

    result = files.formats(_rt(), {})
    assert tuple(result["extensions"]) == AUDIO_EXTS


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
    assert data["path"] == audio
    assert data["message"] == "decoder exploded"
    assert data["code"] == "failed"


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
    assert err.value.code == "bad_path"


# ---- results survive a window that was not listening (QA-RUNTIME-8) ------------


@pytest.fixture(autouse=True)
def _fresh_results():
    with files._results_lock:
        files._results.clear()
    yield


def _settled(path, timeout=5.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entry = files.result(None, {"path": path})["result"]
        if entry and entry["status"] != "running":
            return entry
        time.sleep(0.01)
    raise AssertionError("the run never settled")


def test_a_finished_run_can_be_read_back_with_no_subscriber(audio):
    files.transcribe(_rt(_Backend("kept words")), {"path": audio})

    entry = _settled(audio)

    assert entry["status"] == "done" and entry["text"] == "kept words"
    assert entry["path"] == audio and "run" not in entry
    assert files.results(None, {})["results"][0]["path"] == audio


def test_a_failed_run_is_remembered_with_a_friendly_reason(audio):
    files.transcribe(_rt(_Backend(error="decoder exploded")), {"path": audio})

    entry = _settled(audio)

    assert entry["status"] == "failed"
    assert entry["message"] == "decoder exploded" and entry["code"] == "failed"


def test_a_run_in_flight_is_listed_as_running(audio):
    gate = threading.Event()
    files.transcribe(_rt(_Backend(gate=gate)), {"path": audio})
    try:
        assert files.result(None, {"path": audio})["result"]["status"] == "running"
    finally:
        gate.set()
    _settled(audio)


def test_dismissing_forgets_the_run_and_unknown_paths_are_null(audio):
    files.transcribe(_rt(_Backend()), {"path": audio})
    _settled(audio)

    assert files.dismiss(None, {"path": audio}) == {"dismissed": True}
    assert files.result(None, {"path": audio}) == {"result": None}
    assert files.dismiss(None, {"path": audio}) == {"dismissed": False}


def test_only_the_most_recent_runs_are_kept(tmp_path):
    rt = _rt(_Backend())
    paths = []
    for index in range(files._MAX_RESULTS + 4):
        path = tmp_path / f"f{index}.wav"
        path.write_bytes(b"RIFF")
        paths.append(str(path))
        files.transcribe(rt, {"path": str(path)})
        _settled(str(path))

    kept = [r["path"] for r in files.results(None, {})["results"]]
    assert len(kept) == files._MAX_RESULTS
    assert kept[0] == paths[-1] and paths[0] not in kept


def test_a_second_run_of_the_same_file_replaces_the_first(audio):
    rt = _rt(_Backend("first"))
    files.transcribe(rt, {"path": audio})
    _settled(audio)
    rt = _rt(_Backend("second"))
    files.transcribe(rt, {"path": audio})
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        entry = files.result(None, {"path": audio})["result"]
        if entry["status"] == "done" and entry["text"] == "second":
            break
        time.sleep(0.01)
    assert entry["text"] == "second"
    assert len(files.results(None, {})["results"]) == 1


# ---- the reason is words, not plumbing (QA-JOURNEYS-11, QA-RUNTIME-15) ----------


@pytest.mark.parametrize("raw, code, expect, absent", [
    ("Subprocess error: TranscriptionError: Could not read audio from fake.wav "
     "- neither libsndfile nor ffmpeg could decode it", "unreadable",
     "Could not read audio from fake.wav", "Subprocess"),
    ("Subprocess error: TranscriptionError: The model failed while transcribing: "
     "[ONNXRuntimeError] : 1 : FAIL : Non-zero status code returned while running "
     "Reshape node '/encoder/encoders.0/layers.0'", "model_failed",
     "The model could not process this audio", "ONNX"),
    ("Subprocess error: OSError: [Errno 5] failed reading /Users/me/build/x/y.bin",
     "failed", "failed reading y.bin", "/Users/"),
])
def test_failure_reasons_lose_their_plumbing(raw, code, expect, absent):
    out = files.explain_failure(RuntimeError(raw), "/tmp/some/fake.wav")

    assert out["code"] == code
    assert expect in out["message"]
    assert absent not in out["message"]
    assert "TranscriptionError" not in out["message"]


def test_the_failed_event_carries_the_friendly_message_and_code(sub, audio):
    err = "Subprocess error: TranscriptionError: Could not read audio from memo.wav - x"
    files.transcribe(_rt(_Backend(error=err)), {"path": audio})

    name, data = _collect(sub, {"file.done", "file.failed"})

    assert name == "file.failed" and data["code"] == "unreadable"
    assert "Subprocess" not in data["message"]


# ---- diarization -------------------------------------------------------------


@pytest.fixture
def diar_on(monkeypatch):
    from app import diarization_models

    state = SimpleNamespace(cached=True)
    monkeypatch.setattr(diarization_models, "is_cached", lambda: state.cached)
    return state


def test_a_diarized_run_passes_the_flag_and_the_label_to_the_backend(sub, audio, diar_on):
    backend = _Backend("Спикер 1: hi\n\nСпикер 2: yo")
    files.transcribe(_rt(backend), {"path": audio, "diarize": True, "speaker_label": "Спикер"})

    name, data = _collect(sub, {"file.done", "file.failed"})
    assert name == "file.done" and data["text"].startswith("Спикер 1:")
    assert backend.diarized == (True, "Спикер")


def test_the_number_of_speakers_reaches_the_backend_when_given(sub, audio, diar_on):
    backend = _Backend("Спикер 1: hi\n\nСпикер 2: yo")
    files.transcribe(_rt(backend), {"path": audio, "diarize": True, "speakers": 3})

    _collect(sub, {"file.done", "file.failed"})
    assert backend.speakers == 3


def test_without_a_count_the_backend_is_left_to_find_the_speakers(sub, audio, diar_on):
    backend = _Backend("Спикер 1: hi\n\nСпикер 2: yo")
    files.transcribe(_rt(backend), {"path": audio, "diarize": True})

    _collect(sub, {"file.done", "file.failed"})
    assert backend.speakers is None


def test_a_plain_run_never_mentions_diarization_to_the_backend(sub, audio, diar_on):
    class Old:
        """A backend from before the option: ``transcribe_file(path)`` only."""
        def health_check(self):
            return True

        def transcribe_file(self, path):
            return "plain"

    files.transcribe(_rt(Old()), {"path": audio})

    assert _collect(sub, {"file.done", "file.failed"})[1]["text"] == "plain"


def test_a_diarized_run_without_the_model_is_refused_before_it_starts(audio, diar_on):
    diar_on.cached = False
    backend = _Backend()

    with pytest.raises(RpcError) as err:
        files.transcribe(_rt(backend), {"path": audio, "diarize": True})

    assert err.value.code == "diarization_missing" and backend.paths == []


@pytest.mark.parametrize("params", [
    {"diarize": "yes"},
    {"diarize": True, "speaker_label": ""},
    {"diarize": True, "speaker_label": 3},
    {"diarize": True, "speaker_label": "x" * 41},
    {"diarize": True, "speakers": 0},
    {"diarize": True, "speakers": 21},
    {"diarize": True, "speakers": "3"},
    {"diarize": True, "speakers": 2.5},
    {"diarize": True, "speakers": True},
])
def test_diarization_parameters_are_checked(audio, diar_on, params):
    with pytest.raises(RpcError) as err:
        files.transcribe(_rt(_Backend()), {"path": audio, **params})

    assert err.value.code == "bad_params"


# ---- files run in the background worker -------------------------------------


class _Runner:
    def __init__(self, text="from the background", error=None):
        self.text = text
        self.error = error
        self.calls = []
        self.cancelled = False

    def transcribe_file(self, path, diarize=False, speaker_label="Speaker", speakers=None):
        self.calls.append((path, diarize, speaker_label))
        if self.error:
            raise self.error
        return self.text

    def cancel(self):
        self.cancelled = True
        return True


def _rt_with_runner(backend, runner):
    rt = _rt(backend)
    rt.file_runner = runner
    return rt


def test_a_file_runs_in_the_background_worker_not_in_the_dictation_one(sub, audio):
    backend = _Backend(text="from the dictation worker")
    runner = _Runner()

    files.transcribe(_rt_with_runner(backend, runner), {"path": audio})

    name, data = _collect(sub, {"file.done", "file.failed"})
    assert (name, data["text"]) == ("file.done", "from the background")
    assert backend.paths == [], "the dictation worker must not see the file"
    assert runner.calls == [(audio, False, "Speaker")]


def test_a_file_falls_back_to_the_main_worker_when_the_background_one_is_unavailable(sub, audio):
    from app.backends.background_runner import BackgroundUnavailable

    backend = _Backend(text="from the dictation worker")
    runner = _Runner(error=BackgroundUnavailable("no model"))

    files.transcribe(_rt_with_runner(backend, runner), {"path": audio})

    name, data = _collect(sub, {"file.done", "file.failed"})
    assert (name, data["text"]) == ("file.done", "from the dictation worker")


def test_a_cancelled_run_is_announced_and_remembered_as_cancelled(sub, audio):
    from app.backends.background_runner import FileCancelled

    runner = _Runner(error=FileCancelled("cancelled"))

    files.transcribe(_rt_with_runner(_Backend(), runner), {"path": audio})

    name, data = _collect(sub, {"file.cancelled", "file.done", "file.failed"})
    assert name == "file.cancelled"
    assert data["path"] == audio
    assert files.result(None, {"path": audio})["result"]["status"] == "cancelled"


def test_cancel_reaches_the_runner_and_says_whether_anything_was_running():
    runner = _Runner()

    assert files.cancel(_rt_with_runner(_Backend(), runner), {}) == {"cancelled": True}
    assert runner.cancelled is True
    assert files.cancel(_rt(_Backend()), {}) == {"cancelled": False}
