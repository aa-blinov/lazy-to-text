"""Files run in a second worker, never in the one the dictation uses."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from app.backends.background_runner import (
    BackgroundTranscriber,
    BackgroundUnavailable,
    FileCancelled,
)


class _Worker:
    """Stands in for a ``SubprocessBackend`` started with ``background=True``."""

    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.gate = None
        self.state = "stopped"
        self.fail_load = False
        self.shut = False
        self.aborted = False
        _Worker.instances.append(self)

    def update_inference_settings(self, settings):
        self.calls.append(("settings", settings))

    def set_vad_enabled(self, enabled):
        self.calls.append(("vad", enabled))

    def load(self):
        self.calls.append(("load",))
        if self.fail_load:
            raise RuntimeError("no model")
        self.state = "ready"

    def status(self):
        return self.state

    def transcribe_file(self, path, diarize=False, speaker_label="Speaker", timeout=None):
        self.calls.append(("file", path, diarize, speaker_label, timeout))
        if self.gate is not None:
            self.gate.wait(5)
            if self.aborted:
                raise RuntimeError("Subprocess error: cancelled")
        return f"text of {path}"

    def abort(self):
        self.aborted = True
        if self.gate is not None:
            self.gate.set()

    def shutdown(self):
        self.shut = True


@pytest.fixture(autouse=True)
def _fresh():
    _Worker.instances = []


def _main(**over):
    base = dict(
        _init_kwargs={"model": "gigaam-v3-ctc", "device": "auto"},
        _last_inference_settings=None,
        _vad_wanted=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _runner(main=None, idle=60.0):
    return BackgroundTranscriber(main or _main(), factory=_Worker, idle_seconds=idle)


def test_a_backend_without_a_worker_to_copy_is_not_supported():
    assert BackgroundTranscriber.supported(_main()) is True
    assert BackgroundTranscriber.supported(SimpleNamespace()) is False


def test_the_file_runs_in_a_background_copy_of_the_dictation_worker():
    runner = _runner(_main(_last_inference_settings="S", _vad_wanted=True))

    assert runner.transcribe_file("/a.wav", diarize=True, speaker_label="Voice") == "text of /a.wav"

    (worker,) = _Worker.instances
    assert worker.kwargs["background"] is True
    assert worker.kwargs["model"] == "gigaam-v3-ctc"
    assert ("settings", "S") in worker.calls and ("vad", True) in worker.calls
    assert ("load",) in worker.calls
    assert worker.calls[-1][:4] == ("file", "/a.wav", True, "Voice")
    assert worker.calls[-1][4] > 3600, "a long file at low priority must not hit the short cap"


def test_the_worker_is_reused_for_the_next_file():
    runner = _runner()

    runner.transcribe_file("/a.wav")
    runner.transcribe_file("/b.wav")

    assert len(_Worker.instances) == 1


def test_the_worker_is_sent_away_after_the_idle_time():
    runner = _runner(idle=0.05)
    runner.transcribe_file("/a.wav")
    (worker,) = _Worker.instances

    deadline = time.monotonic() + 2
    while not worker.shut and time.monotonic() < deadline:
        time.sleep(0.02)

    assert worker.shut is True
    runner.transcribe_file("/b.wav")
    assert len(_Worker.instances) == 2


def test_a_changed_model_gets_a_new_worker_for_the_next_file():
    main = _main()
    runner = _runner(main)
    runner.transcribe_file("/a.wav")

    main._init_kwargs = {"model": "whisper-base", "device": "auto"}
    runner.transcribe_file("/b.wav")

    first, second = _Worker.instances
    assert first.shut is True
    assert second.kwargs["model"] == "whisper-base"


def test_a_run_in_progress_keeps_its_worker_when_the_model_changes():
    main = _main()
    runner = _runner(main)
    first_run = threading.Event()
    gate = threading.Event()

    def long_run():
        runner.transcribe_file("/a.wav")
        first_run.set()

    # Hold the first worker inside its file until the model has changed.
    original = _Worker.transcribe_file

    def held(self, *a, **k):
        gate.wait(5)
        return original(self, *a, **k)

    _Worker.transcribe_file = held
    try:
        thread = threading.Thread(target=long_run)
        thread.start()
        time.sleep(0.2)
        main._init_kwargs = {"model": "whisper-base", "device": "auto"}
        runner.transcribe_file("/b.wav")
        gate.set()
        thread.join(5)
    finally:
        _Worker.transcribe_file = original

    assert len(_Worker.instances) == 1


def test_cancel_ends_the_run_and_reports_it_as_cancelled():
    runner = _runner()
    gate = threading.Event()
    result = {}

    original = _Worker.__init__

    def init(self, **kw):
        original(self, **kw)
        self.gate = gate

    _Worker.__init__ = init
    try:
        def run():
            try:
                runner.transcribe_file("/a.wav")
            except BaseException as exc:
                result["error"] = exc

        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 2
        while not _Worker.instances and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.2)

        assert runner.cancel() is True
        thread.join(5)
    finally:
        _Worker.__init__ = original

    assert isinstance(result["error"], FileCancelled)
    assert _Worker.instances[0].aborted is True


def test_cancel_with_nothing_running_says_so():
    assert _runner().cancel() is False


def test_a_model_that_does_not_load_in_the_background_falls_back_to_the_caller():
    def broken(**kw):
        worker = _Worker(**kw)
        worker.fail_load = True
        return worker

    runner = BackgroundTranscriber(_main(), factory=broken, idle_seconds=60)

    with pytest.raises(BackgroundUnavailable):
        runner.transcribe_file("/a.wav")


def test_a_worker_that_reports_an_error_is_unavailable():
    def failing(**kw):
        worker = _Worker(**kw)
        worker.load = lambda: setattr(worker, "state", "error")
        return worker

    runner = BackgroundTranscriber(_main(), factory=failing, idle_seconds=60)

    with pytest.raises(BackgroundUnavailable):
        runner.transcribe_file("/a.wav")
