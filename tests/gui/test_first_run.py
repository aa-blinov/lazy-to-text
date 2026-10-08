"""First run: who gets the setup screen, and does it ever lie.

Three things had to be true for this screen to be worth building, and
each of them is a thing that can quietly stop being true later:

* the card the screen opens on is the one the rest of the app already
  calls the default — two "recommendations" is one too many;
* a first run is shown to someone with nothing downloaded and to no one
  else, which is the same condition as "can this person dictate";
* it never says the download worked when it did not.
"""

import sys
from unittest.mock import MagicMock

import pytest

from app.gui.views.first_run_view import first_run_candidates


def _config(complete):
    """The one config section first run reads, and nothing else.

    Mirrors the real shape — ``get_setting(section, key)`` over nested
    dicts — rather than answering from a flat bag, so a renamed section
    fails here instead of silently reading ``None``.
    """
    sections = {"onboarding": {"complete": complete}}
    config = MagicMock()
    config.get_setting.side_effect = lambda section, key: sections.get(
        section, {}
    ).get(key)
    return config


# ---- the recommendation is one, and it is the default ----------------------


def test_exactly_one_model_is_recommended():
    """A second recommended card turns a decision back into a choice."""
    from app.model_mapping import MODELS

    marked = [m for m in MODELS if m.recommended]
    assert len(marked) == 1, [m.alias for m in marked]


def test_the_recommended_model_is_the_shipped_default():
    """The first-run screen opening on a card the rest of the app does
    not call the default is how two truths get into one codebase."""
    from app.config_manager import DEFAULT_CONFIG
    from app.model_mapping import get_model

    info = get_model(DEFAULT_CONFIG["whisper"]["model"])
    assert info.recommended is True, (
        "the default model is not the recommended one: "
        f"{DEFAULT_CONFIG['whisper']['model']}"
    )


def test_the_first_card_is_the_recommended_one():
    ranked = first_run_candidates()
    assert ranked[0].recommended is True
    assert ranked[0].alias == first_run_candidates()[0].alias


def test_the_recommended_pitch_is_a_sentence_and_not_a_benchmark_table():
    """The card's ``description`` is the measured case for the model and
    is right to be dense. The pitch is the other thing, and it is what a
    first-time user can act on."""
    from app.model_mapping import get_model

    info = get_model("gigaam-v3-ctc")
    assert info.pitch, "the recommended card has no pitch"
    assert "WER" not in info.pitch
    assert len(info.pitch) < 160, info.pitch


def test_a_model_without_a_pitch_still_has_a_description():
    """The field is optional, so anything reading it has to cope with
    the empty case rather than assuming it is populated."""
    from app.model_mapping import MODELS

    without = [m for m in MODELS if not m.pitch]
    assert without, "no card is without a pitch — the fallback is untested"
    assert all(m.description for m in without)


# ---- who gets the screen ---------------------------------------------------


def test_a_fresh_install_gets_the_setup_screen():
    from app.gui.app import _should_show_first_run

    assert _should_show_first_run(_config(False), False)


def test_someone_who_already_downloaded_a_model_never_sees_it_again():
    """The case that decides whether this ships: every existing install
    reads ``complete: False`` out of the defaults because its config
    predates the section, and all of them have weights on disk."""
    from app.gui.app import _should_show_first_run

    assert _should_show_first_run(
        _config(False), True
    ) is False


def test_a_finished_first_run_is_not_shown_again():
    from app.gui.app import _should_show_first_run

    assert _should_show_first_run(
        _config(True), False
    ) is False


def test_an_unreadable_config_does_not_wall_the_app_off():
    """A screen the user cannot finish is worse than no screen."""
    from app.gui.app import _should_show_first_run

    config = MagicMock()
    config.get_setting.side_effect = RuntimeError("no such file")
    assert _should_show_first_run(config, False) is False


def test_startup_says_so_when_there_is_nothing_to_load():
    """This log line was unreachable — it sat inside the fallback loop
    after its own ``return``, so the one case a first-run user is in
    wrote nothing at all."""
    import logging

    from app.gui.app import _autoload_persisted_model

    backend = MagicMock()
    backend.current_model.return_value = "gigaam-v3-ctc"
    with pytest.MonkeyPatch.context() as mp:
        import app.gui.app as module

        mp.setattr(module, "is_cached_for_info", lambda info: False)
        mp.setattr(module, "is_model_cached", lambda name: False)
        with __import__("tempfile").TemporaryDirectory() as tmp:
            mp.setenv("LAZY_TO_TEXT_MODELS_DIR", tmp)
            with __import__("io").StringIO() as buf:
                handler = logging.StreamHandler(buf)
                logger = logging.getLogger("app.gui.app")
                logger.setLevel(logging.INFO)
                logger.addHandler(handler)
                try:
                    found = _autoload_persisted_model(backend, None)
                    # Read inside the block: a StringIO is closed on the
                    # way out, and reading it afterwards is a ValueError
                    # that has nothing to do with what is under test.
                    logged = buf.getvalue()
                finally:
                    logger.removeHandler(handler)
    assert found is False
    assert backend.load.call_count == 0
    # The line itself. It was unreachable for its whole life — it sat
    # inside the fallback loop after its own ``return`` — so the one
    # case a first-run user is in wrote nothing at all, and a test that
    # only checks the return value would have passed against the dead
    # version just as happily.
    assert "skipping auto-load" in logged, logged


# ---- the screen itself -----------------------------------------------------


def test_the_screen_starts_on_the_choose_step(qtbot):
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)

    assert view.step() == "choose"
    assert view._card.info().recommended is True
    assert view._header.title_label.text() == "Start dictating"


def test_picking_the_card_moves_to_the_download_step(qtbot):
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)
    chosen = []
    view.model_chosen.connect(chosen.append)

    view._card.select_requested.emit(view._card.alias())

    assert view.step() == "download"
    assert chosen == [view._card.alias()]
    assert "MB" in view._header.subtitle_label.text()


def test_the_card_is_the_only_way_to_pick_on_that_screen(qtbot):
    """Two controls that do the same thing on one screen is how someone
    presses the wrong one and concludes the app is broken."""
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)

    primaries = [
        b for b in view.findChildren(type(view._card._select_btn))
        if b.property("role") == "primary" and not b.isHidden()
    ]
    assert len(primaries) == 1, [b.text() for b in primaries]
    assert primaries[0].text() in ("Download", "Select")


def test_progress_is_reported_in_real_bytes_not_a_fake_percentage(qtbot):
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)
    view.set_download_started(view.model_info())

    view.set_download_progress(65 * 1024 * 1024, 260 * 1024 * 1024)

    assert view._progress.value() == 25
    assert "25%" in view._detail.text()
    assert "65.0 MB" in view._detail.text()


def test_an_unknown_total_is_indeterminate_rather_than_a_guess(qtbot):
    """Hugging Face streams ``content-length`` late. A bar that invents a
    denominator ends up stuck at 137%."""
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)

    view.set_download_progress(4096, 0)

    assert view._progress.maximum() == 0
    assert "4 KB" in view._detail.text()


def test_elapsed_time_appears_because_a_bar_cannot_say_it(qtbot):
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)
    view.set_download_started(view.model_info())
    view.set_download_progress(1024 * 1024, 260 * 1024 * 1024)

    view._tick_elapsed()
    view._tick_elapsed()

    assert "2s" in view._detail.text()


def test_a_landed_download_advances_to_the_key(qtbot):
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)
    view._card.select_requested.emit(view._card.alias())

    view.begin_settle_check()
    # Through the card's own result path, not by emitting the signal by
    # hand — emitting it by hand passes even if the card stopped
    # publishing entirely, which is the thing worth catching.
    view._card._cache_request_id = view._card._cache_request_id
    view._card._apply_cache_result(True, view._card._cache_request_id)

    assert view.step() == "hotkey"


def test_a_download_that_did_not_land_never_claims_it_did(qtbot):
    """``idle`` is what a failed fetch looks like too. Advancing to
    "press the key" after one would be a lie the user only finds out
    when nothing transcribes."""
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)
    view._card.select_requested.emit(view._card.alias())

    view.begin_settle_check()
    view._card._apply_cache_result(False, view._card._cache_request_id)

    assert view.step() == "download"
    assert "did not finish" in view._detail.text()
    assert "retry" in view._hint.text().lower() or "again" in (
        view._hint.text().lower()
    )


def test_the_settle_check_is_ignored_outside_the_download_step(qtbot):
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)

    view.begin_settle_check()
    view._card._apply_cache_result(True, view._card._cache_request_id)

    assert view.step() == "choose"


def test_the_key_is_shown_as_a_cap_built_from_the_configured_binding(qtbot):
    """A literal would be wrong on one platform and wrong again for
    anyone who rebinds it."""
    from app.gui.widgets.empty_state import format_hotkey
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)

    view.set_hotkey("ctrl+f8", "ctrl+f9")

    labels = [
        w.text() for w in view.findChildren(
            type(view._header.title_label)
        ) if w.property("role") == "kbd"
    ]
    assert format_hotkey("ctrl+f8") in labels
    assert format_hotkey("ctrl+f9") in labels


def test_an_unbound_key_renders_no_cap_at_all(qtbot):
    """There is nothing true to print, and a blank square is worse than
    an absent one."""
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)

    view.set_hotkey("", "")

    labels = [
        w.text() for w in view.findChildren(
            type(view._header.title_label)
        ) if w.property("role") == "kbd"
    ]
    assert labels == []


# ---- the window ------------------------------------------------------------


def test_first_run_hides_the_navigation(qtbot):
    """Five tabs into views that need a working model is the catalogue
    the screen was built to replace."""
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)

    window.set_first_run(True)

    assert window.is_first_run()
    assert window.sidebar.isHidden()
    assert window.topbar.isHidden()
    assert window.stack.currentWidget() is window.first_run_view


def test_leaving_first_run_gives_the_navigation_back(qtbot):
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.set_first_run(True)

    window.set_first_run(False)

    assert not window.is_first_run()
    assert not window.sidebar.isHidden()
    assert not window.topbar.isHidden()
    assert window.stack.currentWidget() is not window.first_run_view


def test_set_first_run_reports_whether_anything_changed(qtbot):
    """``idle`` arrives more than once per session and the controller
    writes config off the back of this."""
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.set_first_run(True) is True
    assert window.set_first_run(True) is False
    assert window.set_first_run(False) is True
    assert window.set_first_run(False) is False


def test_a_keyboard_nav_keystroke_cannot_skip_the_setup_screen(qtbot):
    """Ctrl+1..5 are application shortcuts and do not care whether a
    widget is visible."""
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.set_first_run(True)
    window._views["logs"].show()

    window.sidebar.set_active("logs")

    assert window.stack.currentWidget() is window.first_run_view

# ---- the pill, as rendered -------------------------------------------------


@pytest.fixture
def themed(qtbot):
    """The real stylesheet, restored afterwards.

    Without it every colour rule below is satisfied by Qt's default
    palette, which is why ``palette()`` is not the witness and rendered
    pixels are.
    """
    from PySide6.QtWidgets import QApplication
    from app.gui.theme import load_stylesheet

    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(load_stylesheet("dark"))
    try:
        yield app
    finally:
        app.setStyleSheet(previous)


def test_the_recommended_pill_is_drawn_from_a_token(qtbot, themed):
    """Outlined in accent, not filled in success.

    Success is what "Active" paints, and a user who has deliberately
    loaded a different model should see both pills at once and not read
    them as the same answer twice. Painted as pixels because the rule
    can sit in the stylesheet for months without ever firing.
    """
    from app.gui.theme import TOKENS
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)
    view.show()

    pill = view._card._recommended_pill
    assert pill.isVisibleTo(view)
    QApplication_process_events()
    image = pill.grab().toImage()
    # Row 0 is the border; row 1 is already the padding inside it. The
    # middle is the transparent fill, because the pill is an outline —
    # sampling there would have found black and proved nothing either
    # way.
    border = image.pixelColor(image.width() // 2, 0)
    centre = image.pixelColor(
        image.width() // 2, image.height() // 2
    )
    accent = TOKENS.colors["accent"].lower()
    assert border.name().lower() == accent, border.name()
    assert centre.name().lower() != accent, "the pill filled up after all"


def QApplication_process_events():
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()


def test_the_live_stylesheet_carries_no_colour_literals(qtbot):
    """Tokens are the only place a colour is written down.

    Checked on the *template*, and only outside comments: the comments
    legitimately quote hex values, because they explain measured
    contrast ratios and a ratio is meaningless without the two colours
    it is between. What is forbidden is a hex in a declaration.
    """
    import re

    from app.gui.theme import _STYLES_DIR

    template = (_STYLES_DIR / "dark.qss").read_text(encoding="utf-8")
    # Strip whole comment blocks, not lines that happen to start with a
    # marker: the header banner is a /* ... */ block whose middle lines
    # quote hex contrast pairs, and those are prose about measured
    # ratios rather than styling.
    declarations = re.sub(r"/\*.*?\*/", "", template, flags=re.S)
    literals = re.findall(r"#[0-9a-fA-F]{3,8}\b", declarations)
    assert literals == [], f"colour literals in dark.qss: {literals[:5]}"


def test_the_recommended_pill_is_not_shown_on_another_card(qtbot):
    from app.gui.views.first_run_view import FirstRunView
    from app.gui.widgets.model_card import ModelCard
    from app.model_mapping import get_model

    view = FirstRunView()
    qtbot.addWidget(view)
    other = ModelCard(get_model("canary-1b-v2"))
    qtbot.addWidget(other)

    assert view._card._recommended_pill.isVisibleTo(view)
    assert not other._recommended_pill.isVisibleTo(other)


def test_the_screen_stops_its_timer_when_first_run_ends(qtbot):
    """The elapsed-seconds counter runs off a QTimer.

    Leaving first run for the catalogue would otherwise leave a timer
    ticking against a page nobody is looking at, for as long as the app
    stays open.
    """
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.set_first_run(True)
    view = window.first_run_view
    view.set_download_started(view.model_info())
    assert view._elapsed_timer.isActive()

    window.set_first_run(False)

    assert not view._elapsed_timer.isActive()


# ---- one order, shared -----------------------------------------------------


def test_the_catalogue_and_the_first_run_screen_show_the_same_order():
    """Two orderings that agree today and drift tomorrow is how the
    first-run card stops being the card the catalogue points at."""
    from app.gui.views.models_view import ModelsView
    from app.model_mapping import display_order

    view = ModelsView()
    shown = [view._cards[a].info().alias for a in view._cards]

    assert shown == [m.alias for m in display_order()]
    assert first_run_candidates() == display_order()


def test_the_recommended_card_comes_before_the_big_slow_ones():
    """The complaint the order exists to answer: Whisper Large v3 Turbo
    used to be the first card, under a header saying bigger is slower."""
    from app.model_mapping import display_order, get_model

    ordered = display_order()
    assert get_model("whisper-large-v3-turbo") in ordered
    assert ordered.index(get_model("gigaam-v3-ctc")) < ordered.index(
        get_model("whisper-large-v3-turbo")
    )


def test_the_first_run_card_leads_with_the_pitch_and_hides_the_benchmarks(qtbot):
    """Both are true, but they answer different questions and only one
    of them fits on this screen: "why this one", not "how does it
    compare to the other fifteen"."""
    from app.gui.views.first_run_view import FirstRunView

    view = FirstRunView()
    qtbot.addWidget(view)
    from PySide6.QtWidgets import QLabel

    pitches = [
        w for w in view._card.findChildren(QLabel)
        if w.property("role") == "pitch"
    ]
    # Matched by content, not by length: the canonical-id line is also a
    # long muted label and it is supposed to stay.
    described = [
        w for w in view._card.findChildren(QLabel)
        if w.text() == view.model_info().description
    ]

    assert len(pitches) == 1, [p.text() for p in pitches]
    assert pitches[0].text() == view.model_info().pitch
    assert described, "the measured case is not on the card at all"
    assert not described[0].isVisibleTo(view._card)


def test_the_catalogue_card_still_shows_the_measured_case(qtbot):
    """``show_pitch`` is a first-run decision. The catalogue is where
    someone compares, and the comparison data has to still be there."""
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    card = view._cards["gigaam-v3-ctc"]

    assert card._show_pitch is False
    from PySide6.QtWidgets import QLabel

    described = [
        w for w in card.findChildren(QLabel)
        if w.text() == card.info().description
    ]
    pitched = [
        w for w in card.findChildren(QLabel)
        if w.property("role") == "pitch"
    ]
    assert described, "the catalogue card lost its description"
    assert all(d.isVisibleTo(card) for d in described)
    assert pitched == [], "the catalogue card grew a pitch line"
