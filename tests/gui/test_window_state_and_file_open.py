"""Window position memory, and files the OS asks the app to open.

Two features, one file, because both are about the same thing: the
window's relationship to the desktop around it. Where it was, and what
the OS hands it.

The file-open half carries the load-bearing detail. ``QFileOpenEvent``
is documented to return a ``QStringList`` and this binding returns a
``str`` — measured, not assumed — so the idiomatic loop emits one
single-character "path" per character of the real filename. That test
is the reason the normalisation helper exists, and it is the first
thing to break if someone simplifies it away.
"""

import os
from typing import Any, Dict, List, Optional, Tuple

import pytest
from PySide6.QtCore import QEvent, QUrl
from PySide6.QtGui import QCloseEvent, QFileOpenEvent
from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow


class FakeConfig:
    """Minimal ``ConfigManager`` stand-in, as in ``test_app_controller``."""

    def __init__(self, initial: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._data: Dict[str, Dict[str, Any]] = {
            section: dict(values) for section, values in (initial or {}).items()
        }
        self.writes: List[Tuple[str, str, Any]] = []

    def get_setting(self, section: str, key: str) -> Any:
        return self._data.get(section, {}).get(key)

    def get_section(self, section: str) -> Dict[str, Any]:
        return dict(self._data.get(section, {}))

    def update_user_setting(self, section: str, key: str, value: Any) -> None:
        self._data.setdefault(section, {})[key] = value
        self.writes.append((section, key, value))


@pytest.fixture(autouse=True)
def _assume_cached(monkeypatch):
    monkeypatch.setattr(
        "app.gui.controllers.app_controller.is_cached_for_info",
        lambda info: True,
    )


def _make_window(qtbot) -> MainWindow:
    window = MainWindow()
    qtbot.addWidget(window)
    return window


def _save_geometry(window: MainWindow) -> str:
    return bytes(window.saveGeometry().toBase64()).decode("ascii")


# ---- The QFileOpenEvent payload --------------------------------------------


def test_a_file_open_event_becomes_one_file_open_request(qtbot):
    """The whole feature in one step.

    Handed the event the way Cocoa hands it — notified to the window,
    which is where a post-and-notify measured it arriving — the window
    announces the path once.
    """
    window = _make_window(qtbot)
    seen: List[str] = []
    window.file_open_requested.connect(seen.append)

    accepted = QApplication.instance().notify(
        window, QFileOpenEvent("/tmp/interview.wav")
    )
    window.hide()

    assert accepted is True
    # ``abspath`` rather than the literal: the window normalises every
    # path to absolute, which on Windows turns "/tmp/…" into "D:\tmp\…".
    # The normalisation is the feature — a path the OS handed us is
    # resolved against the drive it was meant for.
    assert seen == [os.path.abspath("/tmp/interview.wav")]


def test_the_path_is_not_walked_character_by_character(qtbot):
    """The trap this file exists for.

    ``QFileOpenEvent.file()`` returns a ``QStringList`` in C++ and a
    ``str`` on this binding. Looping over it directly emits ``"/"``,
    ``"t"``, ``"m"``, ``"p"``… — one request per character, each one a
    path that does not exist. Nothing raises, and every request would be
    reported to the user as a missing file.

    So the assertion is on the *count*, not just on the content: a
    30-character name must produce one announcement, not thirty.
    """
    window = _make_window(qtbot)
    seen: List[str] = []
    window.file_open_requested.connect(seen.append)

    long_path = "/Users/someone/Movies/dictation-2026-03-11.wav"
    assert len(long_path) > 20, "the fixture must be long enough to prove it"

    QApplication.instance().notify(window, QFileOpenEvent(long_path))
    window.hide()

    assert seen == [os.path.abspath(long_path)]
    assert len(seen) == 1, "one announcement, not one per character"


def test_a_file_url_is_turned_into_a_local_path(qtbot):
    """Constructed from a URL, ``file()`` hands back the URL itself.

    ``file:///tmp/a.wav`` is not a file anything can open, and it is what
    the binding returns for that constructor — so it is converted rather
    than forwarded to the backend as though it were a path.
    """
    window = _make_window(qtbot)
    seen: List[str] = []
    window.file_open_requested.connect(seen.append)

    # Driven through the normaliser rather than a QFileOpenEvent: the
    # QUrl constructor already hands back a decoded path on this binding
    # (measured), so posting one would never reach the ``file:`` branch
    # and the test would pass whether the conversion existed or not.
    assert window._paths_from_file_open("file:///tmp/from-url.wav") == [
        os.path.abspath("/tmp/from-url.wav")
    ]

    url = QUrl.fromLocalFile("/tmp/from-url.wav")
    QApplication.instance().notify(window, QFileOpenEvent(url))
    window.hide()

    assert seen == [os.path.abspath("/tmp/from-url.wav")]


def test_a_url_that_is_not_a_local_file_is_dropped(qtbot):
    """``toLocalFile`` returns empty for one of these.

    Dropping it is right and forwarding it is not: an http URL is not a
    transcription input, and the alternative is a backend error about a
    file that never claimed to be one.
    """
    window = _make_window(qtbot)
    seen: List[str] = []
    window.file_open_requested.connect(seen.append)

    QApplication.instance().notify(
        window, QFileOpenEvent(QUrl("https://example.com/a.wav"))
    )
    window.hide()

    assert seen == []


def test_several_files_in_one_request_all_get_announced(qtbot):
    """Multi-select in Finder sends one event naming several files.

    The binding collapses that to a string in practice, so this pins the
    normaliser's list handling separately — the loop that consumes the
    result has to be able to see more than one.
    """
    window = _make_window(qtbot)
    seen: List[str] = []
    window.file_open_requested.connect(seen.append)

    paths = window._paths_from_file_open(["/tmp/one.wav", "/tmp/two.wav"])

    assert paths == [os.path.abspath("/tmp/one.wav"), os.path.abspath("/tmp/two.wav")]


def test_paths_are_normalised_to_absolute(qtbot):
    """Relative in, absolute out.

    The app has no business guessing a working directory later, when a
    file the user picked in Finder is being opened from a request that
    arrived before the process had settled anywhere.
    """
    window = _make_window(qtbot)

    result = window._paths_from_file_open("relative-clip.wav")

    assert result == [os.path.abspath("relative-clip.wav")]


def test_an_empty_payload_produces_no_request(qtbot):
    """A file-open event that names nothing is not an error.

    It just must not produce a request, and must not be consumed either —
    ``event()`` returns False for it, which is what lets the base handler
    see an empty event.
    """
    window = _make_window(qtbot)
    seen: List[str] = []
    window.file_open_requested.connect(seen.append)

    assert window._paths_from_file_open("") == []
    assert window._paths_from_file_open(None) == []
    assert window._paths_from_file_open("   ") == []
    assert seen == []


# ---- Launch arguments -------------------------------------------------------


def test_launch_arguments_yield_the_files_that_exist(qtbot, tmp_path):
    window = _make_window(qtbot)

    real = tmp_path / "interview.wav"
    real.write_bytes(b"RIFF")
    missing = tmp_path / "gone.wav"

    found = window.open_paths_from_argv([str(real), str(missing)])

    assert found == [str(real)]


def test_switch_like_arguments_are_not_treated_as_files(qtbot):
    """``-psn_0_12345`` is how macOS launches an app from Finder.

    It arrives in ``sys.argv``, it is not a file, and any argument that
    opens with a dash has to be left alone rather than probed as a path.
    """
    window = _make_window(qtbot)

    assert window.open_paths_from_argv(["-psn_0_12345", "--verbose"]) == []
    assert window.open_paths_from_argv([]) == []
    assert window.open_paths_from_argv(None) == []


def test_the_dash_check_only_ever_bites_on_a_relative_path(qtbot, tmp_path, monkeypatch):
    """What the dash check actually does, measured rather than assumed.

    ``-psn_0_12345`` is filtered out by ``os.path.exists`` whether or not
    the dash check exists, so the obvious test passes either way. And a
    dash-named file handed over the way Finder sends files — as an
    absolute path — must be opened, because the dash is nowhere in it.

    The only shape both checks disagree on is a *relative* dash-named
    file in the working directory. That is what this pins, and it is why
    the guard exists at all: launcher noise arrives relative and real
    paths from the OS arrive absolute.
    """
    window = _make_window(qtbot)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "-weird.wav").write_bytes(b"RIFF")

    assert window.open_paths_from_argv(["-weird.wav"]) == []
    # The same file, spelled the way the OS spells it, is not skipped.
    assert window.open_paths_from_argv([str(tmp_path / "-weird.wav")]) == [
        str(tmp_path / "-weird.wav")
    ]


def test_a_directory_is_not_a_file_to_open(qtbot, tmp_path):
    window = _make_window(qtbot)

    assert window.open_paths_from_argv([str(tmp_path)]) == []


# ---- Bringing the window forward -------------------------------------------


def test_show_window_if_hidden_unminimises_before_showing(qtbot):
    """A minimised window is visible and not there at the same time.

    Someone who asked for the window back should not also have to guess
    how to get it out of the Dock.
    """
    window = _make_window(qtbot)
    window.show()
    window.showMinimized()
    assert window.isMinimized()

    window.show_window_if_hidden()

    assert not window.isMinimized()
    assert window.isVisible()


def test_show_window_if_hidden_on_a_visible_window_is_harmless(qtbot):
    window = _make_window(qtbot)
    window.show()

    window.show_window_if_hidden()

    assert window.isVisible()


# ---- The controller's half --------------------------------------------------


def test_a_file_the_os_opened_is_transcribed(qtbot, tmp_path):
    from app.gui.controllers.app_controller import AppController

    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"RIFF")

    window = _make_window(qtbot)
    transcribed: List[str] = []
    window.transcribe_view.file_dropped.connect(transcribed.append)

    controller = AppController(config=FakeConfig(), window=window)
    # ``_on_transcribe_file_picked`` is the mixin's; the OS path must reach
    # the same handler a drag does, not a second pipeline.
    controller._on_transcribe_file_picked = transcribed.append
    controller._recording = None

    window.file_open_requested.emit(str(audio))
    window.hide()

    assert transcribed == [str(audio)]


def test_a_missing_file_the_os_opened_says_so_on_the_view(qtbot, tmp_path):
    """Checked before dispatch, so the diagnosis is ours and not the
    backend's — and so it needs no model to reach."""
    from app.gui.controllers.app_controller import AppController

    window = _make_window(qtbot)
    messages: List[str] = []
    window.transcribe_view.set_error = messages.append

    controller = AppController(config=FakeConfig(), window=window)
    called: List[str] = []
    controller._on_transcribe_file_picked = called.append

    window.file_open_requested.emit(str(tmp_path / "gone.wav"))
    window.hide()

    assert called == [], "a missing file must not reach the pipeline"
    assert messages and "no longer there" in messages[0]


def test_the_os_file_open_is_logged(qtbot, tmp_path, caplog):
    """The only trace of a double-click that did nothing.

    This path is the one part of the app the desktop starts rather than
    the user. If Finder hands over a file and the app drops it, there is
    no window message, no popup and no history entry — the log line is
    what separates "macOS never delivered it" from "we got it and threw
    it away", which are the same symptom and opposite bugs.
    """
    import logging

    from app.gui.controllers.app_controller import AppController

    audio = tmp_path / "logged.wav"
    audio.write_bytes(b"RIFF")

    window = _make_window(qtbot)
    controller = AppController(config=FakeConfig(), window=window)
    controller._on_transcribe_file_picked = lambda p: None

    with caplog.at_level(logging.INFO):
        window.file_open_requested.emit(str(audio))
    window.hide()

    assert any(
        str(audio) in record.getMessage() for record in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_a_missing_os_file_is_logged_as_a_warning(qtbot, tmp_path, caplog):
    """Loudly, because the user sees an error and the cause is not theirs."""
    import logging

    from app.gui.controllers.app_controller import AppController

    window = _make_window(qtbot)
    window.transcribe_view.set_error = lambda m: None
    controller = AppController(config=FakeConfig(), window=window)
    controller._on_transcribe_file_picked = lambda p: None

    with caplog.at_level(logging.WARNING):
        window.file_open_requested.emit(str(tmp_path / "gone.wav"))
    window.hide()

    assert any(
        "gone.wav" in record.getMessage() and record.levelno >= logging.WARNING
        for record in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_an_os_opened_file_brings_the_window_forward(qtbot, tmp_path):
    """The work must not happen invisibly behind a tray icon."""
    from app.gui.controllers.app_controller import AppController

    audio = tmp_path / "late.wav"
    audio.write_bytes(b"RIFF")

    window = _make_window(qtbot)
    shown: List[bool] = []
    window.show_window_if_hidden = lambda: shown.append(True)

    controller = AppController(config=FakeConfig(), window=window)
    controller._on_transcribe_file_picked = lambda p: None

    window.file_open_requested.emit(str(audio))
    window.hide()

    assert shown == [True]


# ---- Remembering where the window was --------------------------------------


def test_closing_the_window_reports_where_it_was(qtbot):
    window = _make_window(qtbot)
    window.show()
    window.resize(720, 540)
    qtbot.waitExposed(window)

    seen: List[Tuple[str, str]] = []
    window.window_state_changed.connect(lambda g, s: seen.append((g, s)))

    window.closeEvent(QCloseEvent())

    assert len(seen) == 1
    geometry, screen = seen[0]
    assert geometry, "an empty blob would restore nothing"
    assert len(geometry) > 32


def test_hiding_to_the_tray_also_remembers_the_position(qtbot):
    """Closing to the tray is the last event before the app runs for
    hours — the window the user finds later is the one they expect
    back exactly where they left it."""
    window = _make_window(qtbot)
    window.show()
    window.set_close_to_tray(True)
    qtbot.waitExposed(window)

    seen: List[str] = []
    window.window_state_changed.connect(lambda g, s: seen.append(g))

    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted(), "close-to-tray must ignore the close"

    assert len(seen) == 1
    assert seen[0]


def test_a_minimised_window_does_not_overwrite_the_remembered_position(qtbot):
    """A minimised window's frame is not where it will pop up to.

    Saving it would move the window somewhere the user never put it, and
    the damage only shows on the *next* launch, long after anyone can
    connect it to the click they made here.
    """
    window = _make_window(qtbot)
    window.show()
    window.set_close_to_tray(True)
    qtbot.waitExposed(window)
    window.showMinimized()
    assert window.isMinimized()

    seen: List[str] = []
    window.window_state_changed.connect(lambda g, s: seen.append(g))

    window.closeEvent(QCloseEvent())

    assert seen == []


def test_a_saved_geometry_comes_back(qtbot):
    window = _make_window(qtbot)
    window.show()
    window.resize(760, 560)
    qtbot.waitExposed(window)
    saved = _save_geometry(window)

    other = _make_window(qtbot)
    assert other.restore_window_state(saved, "") is True


def test_an_empty_config_entry_restores_nothing(qtbot):
    """A first launch has no geometry, and that is not a failure."""
    window = _make_window(qtbot)

    assert window.restore_window_state("", "") is False
    assert window.restore_window_state("   ", "") is False


def test_a_short_blob_is_refused_rather_than_half_restored(qtbot):
    """Four bytes is Qt's own decode floor; anything decodes past it.

    A real blob is a version header plus several rectangles, well over a
    hundred bytes. A short one is a hand-edited config, and accepting it
    would report success while quietly handing back a default Qt picked
    — which looks to the user like the app forgot.
    """
    import base64

    window = _make_window(qtbot)

    # Valid base64 of 10 real bytes — decodes cleanly, so the only thing
    # that can reject it is the length check. Handing the method raw
    # bytes as an ASCII string (the first attempt at this fixture) made it
    # fail at *decoding*, which is a different rejection and survived a
    # mutation of the threshold untouched.
    tiny = base64.b64encode(bytes(10)).decode("ascii")
    assert len(base64.b64decode(tiny)) == 10
    assert len(tiny) < 32
    assert window.restore_window_state(tiny, "") is False


def test_a_geometry_from_a_screen_that_is_gone_is_centred_instead(qtbot):
    """Saved on a second monitor, restored after it was unplugged.

    Restoring it verbatim puts the window at coordinates nobody can
    reach — worse than forgetting the position, because the user cannot
    get it back. The size is kept and the window is centred.
    """
    window = _make_window(qtbot)
    window.show()
    window.resize(700, 500)
    qtbot.waitExposed(window)
    saved = _save_geometry(window)

    window.resize(400, 300)
    before = window.frameGeometry()

    restored = window.restore_window_state(saved, "A-SCREEN-THAT-WAS-UNPLUGGED")

    assert restored is False, "an off-screen restore is not a restore"
    assert window.frameGeometry() != before, "the window must have moved"

    # Centred, not contained. ``MainWindow.minimumSize`` is 900x620, so on
    # the 800x800 offscreen screen this window genuinely cannot fit — Qt
    # restores its own floor and no amount of clamping changes that. What
    # is assertable is that the overflow is split evenly instead of the
    # window hanging off one edge, which is the difference between the two
    # candidate answers measured on this screen: -102 (flush left, only
    # the right edge out of reach) versus -52 (centred).
    frame = window.frameGeometry()
    area = QApplication.primaryScreen().availableGeometry()
    assert abs(frame.center().x() - area.center().x()) <= 1
    assert abs(frame.center().y() - area.center().y()) <= 1


def test_a_geometry_from_a_screen_that_is_present_is_restored(qtbot):
    window = _make_window(qtbot)
    window.show()
    window.resize(700, 500)
    qtbot.waitExposed(window)
    saved = _save_geometry(window)
    name = QApplication.primaryScreen().name()

    other = _make_window(qtbot)
    assert other.restore_window_state(saved, name) is True


def test_the_controller_persists_the_window_state(qtbot):
    from app.gui.controllers.app_controller import AppController

    window = _make_window(qtbot)
    config = FakeConfig()
    AppController(config=config, window=window)

    window.window_state_changed.emit("QUFB", "screen-one")

    assert ("window", "geometry", "QUFB") in config.writes
    assert ("window", "screen", "screen-one") in config.writes


def test_the_controller_restores_the_remembered_geometry_at_startup(qtbot):
    """Read back, not only written: this is the one piece of window state
    that has to be pushed *into* the window at startup."""
    from app.gui.controllers.app_controller import AppController

    source = _make_window(qtbot)
    source.show()
    source.resize(812, 604)
    qtbot.waitExposed(source)
    saved = _save_geometry(source)

    target = _make_window(qtbot)

    # Spied on rather than measured afterwards. The first version of this
    # asserted ``target.size() == before or target.restoreGeometry is not
    # None`` — the right half is always true, so it passed whether the
    # restore ran or not. A test that cannot fail is not a test.
    calls: List[Tuple[str, str]] = []
    target.restore_window_state = lambda g, s="": calls.append((g, s))

    config = FakeConfig({"window": {"geometry": saved, "screen": "screen-x"}})
    AppController(config=config, window=target)

    assert calls == [(saved, "screen-x")]


def test_a_window_without_the_state_signals_still_starts(qtbot):
    """Duck-typed like every other optional window capability here.

    A stub window that predates both signals — a screenshot generator, a
    test double — has to keep working; a missing attribute is not a
    reason to refuse to start.

    Driven through ``_wire_window`` rather than the constructor because
    ``AppController`` is a ``QObject`` and its ``__init__`` needs a real
    ``QObject`` for a parent. Swapping ``_window`` afterwards puts the
    stub in front of the very code path the constructor uses.
    """
    from app.gui.controllers.app_controller import AppController

    real = _make_window(qtbot)
    controller = AppController(config=FakeConfig(), window=real)

    class OldWindow:
        """A window from before window state existed.

        Only the two attributes the new wiring looks for, and neither of
        them being a signal — which is the case a bare ``getattr(..., None)``
        guard exists for.
        """

    controller._window = OldWindow()
    try:
        controller._wire_window()  # must not raise
    finally:
        # Background probes (storage size, history) still fire against
        # ``_window`` after this test, and a stub has none of the views.
        controller._window = real


def test_a_window_with_one_signal_and_not_the_other_still_starts(qtbot):
    """The two are wired separately, so one can be missing alone.

    ``file_open_requested`` returning early without connecting either
    would be a shorter way to write this and would silently drop window
    state on any window that has one signal.
    """
    from PySide6.QtCore import QObject, Signal

    from app.gui.controllers.app_controller import AppController

    real = _make_window(qtbot)
    controller = AppController(config=FakeConfig(), window=real)

    class HalfView:
        errors: List[str] = []

        def set_error(self, message: str) -> None:
            self.errors.append(message)

    class HalfWindow(QObject):
        """Has the file signal but not the state signal.

        Carries the couple of methods the file handler touches so the emit
        below runs the real handler rather than tripping over the stub —
        the assertion is that the signal is wired, and it is only wired
        if a live emit arrives.
        """

        file_open_requested = Signal(str)
        transcribe_view = HalfView()

        def show_window_if_hidden(self) -> None:
            return None

    half = HalfWindow()
    seen: List[str] = []
    half.file_open_requested.connect(seen.append)

    controller._window = half
    try:
        controller._wire_window()
        half.file_open_requested.emit("/tmp/does-not-exist.wav")
    finally:
        controller._window = real

    assert seen == ["/tmp/does-not-exist.wav"]
    # No window-state signal on this one, so nothing about geometry was
    # touched — and the file path still went through to a verdict.
    assert HalfView.errors, "the handler should have run and complained"


def test_the_file_open_signal_is_connected_exactly_once(qtbot, tmp_path):
    """Two connections on one signal transcribes twice.

    The first version of this wired the file-open signal from inside
    ``_wire_shortcuts`` and then again from the window wiring, which is
    not a bug that raises — it is a bug that opens the file twice.
    """
    from app.gui.controllers.app_controller import AppController

    audio = tmp_path / "twice.wav"
    audio.write_bytes(b"RIFF")

    window = _make_window(qtbot)
    controller = AppController(config=FakeConfig(), window=window)
    picked: List[str] = []
    controller._on_transcribe_file_picked = picked.append

    window.file_open_requested.emit(str(audio))
    window.hide()

    assert picked == [str(audio)], "the OS path must fire exactly once"


def test_a_geometry_config_section_exists_by_default():
    """The keys have to be in ``DEFAULT_CONFIG``.

    A missing key reads as ``None`` rather than ``""``, and the app
    rewrites the file from these defaults on first launch — so a section
    added only in code would be gone the next time the config is saved.
    """
    from app.config_manager import DEFAULT_CONFIG

    assert "window" in DEFAULT_CONFIG
    assert set(DEFAULT_CONFIG["window"]) == {"geometry", "screen"}
    assert DEFAULT_CONFIG["window"]["geometry"] == ""