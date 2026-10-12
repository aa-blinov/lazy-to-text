"""The Transcribe view's two acts, and what each of them shows.

The screen used to hold one shape for its whole life: a 120px dashed
drop zone, two greyed buttons, and — after a result — the word "Done."
Four things were wrong with that and each has a test here.

The drop zone never yielded, so after a transcript arrived the input
affordance was still the second-largest thing on the page. It collapses
now, keeping its border and its drag surface.

There was no way to tell which file you were looking at, so three files
in a row meant a memory test. The zone's second line now carries size,
elapsed time, word count, and whether you have touched the text.

The transcript was read-only, which sent the user out of the app to fix
one misheard word — in a product whose entire premise is that the text
ends up in someone else's document.

And the status label set a dynamic property for four semantic colours
without the unpolish/polish pair that makes Qt re-read it, so every
state rendered in the same muted grey. An error looked like a caption.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def view(qtbot):
    from app.gui.views.transcribe_view import TranscribeView

    v = TranscribeView(start_hotkey="ctrl+f8")
    qtbot.addWidget(v)
    v.resize(1000, 640)
    v.show()
    return v


@pytest.fixture
def clip(tmp_path):
    """A file that exists, so size formatting has something real."""
    path = tmp_path / "interview-2026-10-05.m4a"
    path.write_bytes(b"\0" * 4096)
    return str(path)


SOME_TEXT = (
    "Yeah, so the move to ONNX runtime really paid off and cold start "
    "dropped from a minute and a half to about four seconds."
)


# --- the drop zone yields -------------------------------------------------


def test_the_zone_is_an_invitation_while_nothing_is_loaded(view):
    assert view._source_stack.currentIndex() == 0
    assert view._drop_zone.minimumHeight() == 120


def test_the_zone_collapses_once_a_file_is_loaded(view, clip):
    view.set_busy(clip)

    assert view._source_stack.currentIndex() == 1, (
        "the zone kept the invitation while a file was already loaded"
    )
    assert view._drop_zone.minimumHeight() == 0
    # A fixed minimum here is exactly what stopped it ever yielding.
    assert view._drop_zone.maximumHeight() < 120


def test_the_collapsed_zone_still_names_the_file(view, clip):
    view.set_busy(clip)
    view.set_result(SOME_TEXT)

    assert view._file_name_label.text() == "interview-2026-10-05.m4a"
    assert "interview-2026-10-05.m4a" not in view._status_label.text()


def test_the_zone_stays_a_drop_target_after_a_result(view, clip):
    """Collapsing it must not turn it into a dead label — the whole view
    accepts drops, and the next file usually arrives the same way the
    last one did."""
    view.set_busy(clip)
    view.set_result(SOME_TEXT)

    assert view.acceptDrops()
    assert view._drop_zone.objectName() == "TranscribeDropZone"


# --- the result is editable, and says so ---------------------------------


def test_the_transcript_is_editable_after_a_result(view, clip):
    """This is the whole change in one assertion. Read-only sent the
    user to the target app to fix a single misheard word."""
    view.set_busy(clip)
    view.set_result(SOME_TEXT)

    assert not view._transcript.isReadOnly()


def test_it_is_read_only_while_working(view, clip):
    view.set_busy(clip)
    assert view._transcript.isReadOnly()


def test_an_untouched_transcript_does_not_claim_to_be_edited(view, clip):
    view.set_busy(clip)
    view.set_result(SOME_TEXT)

    assert "Edited" not in view._file_meta_label.text()


def test_touching_the_text_marks_it_edited_and_moves_the_count(view, clip):
    view.set_busy(clip)
    view.set_result(SOME_TEXT)
    before = view._file_meta_label.text()
    before_count = _word_count(before)

    view._transcript.setPlainText(SOME_TEXT + " One more sentence typed by hand.")
    after = view._file_meta_label.text()

    assert "Edited" in after
    # The count has to move with the caret or the line starts lying.
    assert _word_count(after) == before_count + 6


def _word_count(meta_line: str) -> int:
    """Pull the ``N words`` figure out of the zone's detail line.

    Read back from what is rendered rather than hardcoded — the exact
    count of the fixture text is a number that changes every time the
    sentence is edited, and a test that breaks on its own fixture is a
    test people start ignoring.
    """
    import re

    match = re.search(r"(\d+)\s+words?", meta_line)
    assert match, f"no word count in {meta_line!r}"
    return int(match.group(1))


def test_editing_back_to_the_original_drops_the_edited_flag(view, clip):
    """Edited means "differs from the model", not "was touched" — a user
    who corrects a typo and reverts it has produced the model's text."""
    view.set_busy(clip)
    view.set_result(SOME_TEXT)
    view._transcript.setPlainText(SOME_TEXT + " stray")
    assert "Edited" in view._file_meta_label.text()

    view._transcript.setPlainText(SOME_TEXT)
    assert "Edited" not in view._file_meta_label.text()


def test_copy_takes_the_edited_text_not_the_baseline(view, clip, qtbot):
    """Otherwise the field is editable theatre: you fix the word and the
    old one still leaves the building."""
    from PySide6.QtWidgets import QApplication

    view.set_busy(clip)
    view.set_result(SOME_TEXT)
    view._transcript.setPlainText(SOME_TEXT + " Corrected by hand.")
    view._copy_btn.click()
    qtbot.wait(30)

    assert QApplication.clipboard().text().endswith("Corrected by hand.")


# --- the status colour actually changes ----------------------------------


def _status_ink(view, kind: str) -> str:
    """The hex of the text the status label actually paints.

    Sampled from a render rather than read off the widget: a dynamic
    QSS property is applied at paint time, so every widget-side
    accessor — including ``palette()``, whose ``window`` role is not
    even the one QSS's ``color:`` writes to — keeps reporting the base
    value even after the change has landed. The pixels are the only
    honest witness. An earlier version of this test used the palette
    and passed against a build with the fix removed.
    """
    from collections import Counter

    from PySide6.QtWidgets import QApplication

    from app.gui.theme import apply_theme

    apply_theme(QApplication.instance())
    view._set_status(f"sample message for {kind}", kind, sticky=True)
    view._status_label.adjustSize()

    image = view._status_label.grab().toImage()
    counts: Counter = Counter()
    for y in range(image.height()):
        for x in range(image.width()):
            counts[image.pixelColor(x, y).name()] += 1
    # The background is whatever the isolated grab put behind the text;
    # the ink is the most common colour that is not it.
    background = counts.most_common(1)[0][0]
    ink = [(n, name) for name, n in counts.items() if name != background]
    assert ink, "the label painted no text at all"
    return max(ink)[1]


def test_an_error_paints_red_not_the_base_grey(view, clip):
    """The regression this file exists for.

    A dynamic property does not restyle a widget by itself — Qt needs
    the unpolish/polish pair. Without it ``setProperty("status",
    "error")`` was a no-op and all four documented states rendered in
    the same muted grey, so an error looked like a caption. Four rules
    in the QSS and not one of them had ever fired.
    """
    view.set_busy(clip)
    view.set_error("ffmpeg is not available in this build.")
    error_ink = _status_ink(view, "error").lower()

    from app.gui.theme import TOKENS

    base = TOKENS.colors["text_secondary"].lower()
    assert error_ink != base, "the error line is painting the base muted grey"
    # And it has to be the palette's red, not merely "some other colour".
    # Read off the token rather than written as a literal, so re-theming
    # moves the expectation with the paint instead of failing here.
    assert error_ink == TOKENS.colors["danger"].lower(), (
        f"expected the danger token {TOKENS.colors['danger']}, "
        f"painted {error_ink}"
    )


def test_the_four_states_are_four_different_inks(view, clip):
    """One property value that changes nothing would satisfy every other
    test here, so the states are compared with each other as well as
    with the base."""
    from app.gui.theme import TOKENS

    inks = {
        kind: _status_ink(view, kind).lower()
        for kind in ("busy", "done", "warning", "error")
    }
    assert len(set(inks.values())) == 4, inks
    assert TOKENS.colors["text_secondary"].lower() not in inks.values(), inks


def test_the_label_is_repolished_when_the_property_changes(view, clip):
    """Why `_set_status` calls unpolish/polish at all, asserted directly.

    The rendering test above proves the outcome; this one pins the
    mechanism, so the pair cannot be quietly deleted as "redundant". It
    measured as redundant once: the view's other polish calls happen to
    cascade, the colour still came out right, and a mutation removing
    the pair passed everything. The outcome was right by luck, not by
    intent.

    Isolated proof that the pair is load-bearing on its own: the
    pre-fix file plus only these two lines renders the error red; the
    pre-fix file alone renders it the base grey.
    """
    calls: list[tuple[str, object]] = []
    style = view._status_label.style()
    real_unpolish, real_polish = style.unpolish, style.polish
    # Recorded per widget, not just counted: the style object is the
    # application-wide one, so ``_set_actions`` polishes the Browse
    # button a few lines earlier and a bare counter would be satisfied
    # by somebody else's unpolish.
    style.unpolish = lambda w: (calls.append(("unpolish", w)), real_unpolish(w))[1]
    style.polish = lambda w: (calls.append(("polish", w)), real_polish(w))[1]
    try:
        view.set_busy(clip)
        calls.clear()
        view.set_error("model is still loading")
    finally:
        style.unpolish, style.polish = real_unpolish, real_polish

    own = {name for name, widget in calls if widget is view._status_label}
    assert {"unpolish", "polish"} <= own, (
        f"the status label was not re-polished after its property "
        f"changed; its own calls were {sorted(own)}"
    )


def test_each_status_kind_is_a_distinct_property(view):
    """Four states, four values — so a state can be told apart from the
    others at the point where it is set, without rendering each one."""
    seen = set()
    for kind in ("busy", "done", "warning", "error"):
        view._set_status(f"message for {kind}", kind, sticky=True)
        assert view._status_label.property("status") == kind
        seen.add(view._status_label.text())
    assert len(seen) == 4


def test_a_dismissed_status_stops_claiming_a_state(view, clip):
    """A hidden status line must not keep wearing the last kind.

    ``_set_status("")`` used to hide the label and return, leaving
    ``property("status")`` at whatever it last was. So after a
    successful transcription the property read ``busy`` while the
    view's state was ``done`` and nothing was on screen — invisible,
    but ``test_each_status_kind_is_a_distinct_property`` reads that
    property, and so would any future test asking what the status is.

    Caught by driving the real file path: the label was hidden and the
    property still said "busy".
    """
    view.set_busy(clip)
    assert view._status_label.property("status") == "busy"

    view.set_result(SOME_TEXT)
    assert view._status_label.isHidden()
    assert view._status_label.property("status") is None, (
        "a dismissed status is still claiming a state it is not showing"
    )


def test_a_courtesy_message_disappears_on_its_own(view, clip):
    """Copy says "Copied", then gets out of the way. It used to be the
    same label the file identity lived in, so saying "Copied" overwrote
    the only record of which file you were looking at."""
    view.set_busy(clip)
    view.set_result(SOME_TEXT)
    view._set_status("Copied to clipboard.", "done")

    assert not view._status_label.isHidden()
    view._status_flush.setInterval(10)
    view._dismiss_status()
    assert view._status_label.isHidden()


def test_an_error_stays_until_something_replaces_it(view, clip):
    """The opposite contract: a failure is not a courtesy note, and a
    timer would take it away before it was read."""
    view.set_busy(clip)
    view.set_error("model is still loading")

    assert not view._status_label.isHidden()
    assert not view._status_flush.isActive()


def test_the_page_never_mentions_dictation_at_all(view):
    """This screen is fed by files. It says so, and nothing else.

    ``set_result`` is only ever reached through ``_TranscribeMixin``'s
    ``current_file() == path`` guard — dictation carries no path, so it
    goes to the focused app, the clipboard and History instead. The page
    header and the empty state both used to say otherwise, and did it
    sixty pixels apart: the header read "press the start hotkey to
    dictate" while the drop zone directly under it read "Drop an audio
    or video file here". A user reading top to bottom had two
    instructions for one screen.

    That was fixed by admitting where dictation goes — "the key below
    dictates into your focused window", plus a key cap. A stricter fix
    replaced it: the screen stopped mentioning dictation at all. There
    is no key on it, so there is nothing to explain and nothing to
    disclaim. A caveat only earns its line by being about something the
    reader can act on here.

    Asserted on the whole page rather than the one string, because the
    claim can be made in either of the two places, and on the cap being
    gone — the cap was the thing that made the sentence necessary.
    """
    from app.gui.widgets.page_header import PageHeader

    header = view.findChild(PageHeader)
    assert header is not None
    page_copy = (header._title.text() + " " + header._subtitle.text()).lower()

    empty = view._transcript_empty
    assert empty is not None
    empty_copy = empty._hint.text().lower()

    copy = page_copy + " " + empty_copy

    # The original promises, and the repair's disclaimer.
    assert "hotkey and speak" not in copy
    assert "press the start hotkey" not in copy
    assert "focused window" not in copy

    # …and the rest of the vocabulary dictation travels with. "Dictation"
    # on this screen is the signal that the wrong feature is being
    # advertised, so the word itself is the assertion.
    for word in ("dictation", "dictate", "microphone", "hotkey", "speak"):
        assert word not in copy, (
            f"{word!r} is on a file-transcription screen: {copy!r}"
        )

    # No key cap, and nothing sitting in the footer's layout to hold one.
    assert view._kbd_cap is None
    assert empty._footer_row.count() == 0

    # The binding is still owned by Settings — the view simply has
    # nothing to paint it on.
    assert view._start_hotkey == "ctrl+f8"


def test_the_page_invites_the_file_exactly_once(view):
    """One Browse, and the format count stays off the screen.

    Both of these survived a mutation check once: the copy was changed
    and nothing held it, so either could be put back without a test
    failing. The duplication they were part of — the same invitation
    three times over — is invisible to any assertion that only reads the
    header and the empty state, because it takes the whole page.

    Browse was on the header button, in the drop zone ("or click
    Browse") and again in the empty state ("or pick one with Browse").
    Three invitations to one action, on a screen whose only job is to
    offer that action.

    "24 of them" answered a question nobody asked. The user has one
    file; they are not choosing between 24 formats. The full extension
    list is still one hover away, which is where someone actually
    wondering about formats is already looking.
    """
    from PySide6.QtWidgets import QLabel, QPushButton

    browse_button = view.findChild(QPushButton, "TranscribeBrowseButton")
    assert browse_button is not None, "the page's primary action is gone"

    # Everything the page can say, as one string.
    said = " ".join(
        [w.text() for w in view.findChildren(QLabel)]
        + [b.text() for b in view.findChildren(QPushButton)]
    ).lower()

    assert said.count("browse") == 1, (
        f"Browse is offered {said.count('browse')} times on a page whose "
        f"only action is Browse: {said!r}"
    )

    # The drop hint invites a drop; the button offers a browse. Each
    # element keeps its own verb instead of listing the other's.
    prompt = view.findChild(QLabel, "TranscribeDropPrompt")
    assert prompt is not None
    assert "browse" not in prompt.text().lower(), prompt.text()

    formats = view.findChild(QLabel, "TranscribeDropFormats")
    assert formats is not None
    assert "24" not in formats.text(), formats.text()
    assert "of them" not in formats.text().lower(), formats.text()

    # …and the list it was counting is still reachable, so nothing was
    # lost with the count. (The count was correct — 24 entries — which is
    # exactly why this is a copy decision and not a bug fix: the number
    # was right and still answered a question nobody asked.)
    tip = prompt.toolTip().lower()
    assert "supported:" in tip
    for ext in ("wav", "mp3", "mp4", "mkv"):
        assert ext in tip, f"{ext} left the tooltip: {tip}"
