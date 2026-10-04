"""Tests for the ModelCard widget."""

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


def _make_info():
    from app.model_mapping import ModelInfo

    return ModelInfo(
        alias="whisper-large-v3",
        canonical="onnx-community/whisper-large-v3",
        display_name="Whisper Large v3",
        size_mb=3000,
        vram_gb=6.0,
        speed="slow",
        quality="excellent",
        languages="multilingual",
        description="OpenAI Whisper Large v3 ONNX export.",
        compute_type="float16",
        backend_kind="onnx_asr",
        family="Whisper",
        onnx_family="whisper",
    )


def test_model_card_exposes_alias_and_info(qtbot):
    from app.gui.widgets.model_card import ModelCard

    info = _make_info()
    card = ModelCard(info)
    qtbot.addWidget(card)
    assert card.alias() == "whisper-large-v3"
    assert card.info() is info


def test_model_card_renders_display_name(qtbot):
    from app.gui.widgets.model_card import ModelCard

    info = _make_info()
    card = ModelCard(info)
    qtbot.addWidget(card)

    from PySide6.QtWidgets import QLabel

    labels = card.findChildren(QLabel)
    texts = [label.text() for label in labels]
    assert any("Whisper Large v3" == text for text in texts)


def test_model_card_renders_description(qtbot):
    from app.gui.widgets.model_card import ModelCard

    info = _make_info()
    card = ModelCard(info)
    qtbot.addWidget(card)

    from PySide6.QtWidgets import QLabel

    texts = [label.text() for label in card.findChildren(QLabel)]
    assert any(info.description in text for text in texts)


def test_model_card_shows_a_spec_line_not_pills(qtbot):
    """The card's metadata is one quiet line, not a row of pills.

    Four pills were a table that had lost its alignment: four
    key-value pairs, same shape, same weight. A pill is a state or a
    tag; a specification is text. What survives the repetition test
    against the nine shipped models is size and VRAM — 100x and 12x
    spreads, and in no description — plus the one speed adjective worth
    a glance.
    """
    from PySide6.QtWidgets import QLabel
    from app.gui.widgets.model_card import ModelCard

    info = _make_info()
    card = ModelCard(info)
    qtbot.addWidget(card)

    # No pill survives anywhere on the card.
    assert [l for l in card.findChildren(QLabel)
            if l.property("role") == "badge"] == []
    # The Active pill is a state, not metadata, and stays.
    assert [l for l in card.findChildren(QLabel)
            if l.property("role") == "pill-active"]

    spec = next(
        l for l in card.findChildren(QLabel)
        if l.textFormat().name == "RichText"
        and "VRAM" in l.text()
    )
    assert info.speed in spec.text()
    assert "GB VRAM" in spec.text()
    assert f"{info.size_mb}" not in spec.text()  # formatted, not raw MB


def test_model_card_defaults_to_inactive(qtbot):
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    assert card.is_active() is False


def test_model_card_set_active_reflects_state(qtbot):
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)

    card.set_active(True)
    assert card.is_active() is True
    assert card.property("active") is True

    card.set_active(False)
    assert card.is_active() is False
    assert card.property("active") is False


def test_model_card_hides_select_button_when_active(qtbot):
    """Active model should not offer a Select button."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)

    card.set_active(True)
    select_btn = next(
        b for b in card.findChildren(QPushButton) if b.objectName() == "SelectButton"
    )
    assert not select_btn.isVisible() or not select_btn.isEnabled()


def test_model_card_default_loading_state_is_off(qtbot):
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    assert card.is_loading() is False


def test_model_card_active_loading_swaps_pill_text(qtbot):
    """While loading, the Active pill must say 'Loading…' so it stops
    contradicting the topbar status pill."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.set_active(True)

    # Default: pill says Active
    assert card._active_pill.text() == "Active"

    card.set_loading(True)
    assert card.is_loading() is True
    assert "loading" in card._active_pill.text().lower()
    assert card._active_pill.property("state") == "loading"

    card.set_loading(False)
    assert card.is_loading() is False
    assert card._active_pill.text() == "Active"
    assert card._active_pill.property("state") == "ready"


def test_model_card_does_not_rerender_the_family_chip(qtbot):
    """The family chip used to head the card as its own coloured pill.

    It is gone because it repeated the model name in all nine shipped
    models — "WHISPER TURBO" beside "Whisper Large v3 Turbo" — and a
    badge that repeats the thing it labels is furniture. This test is
    the fence: re-adding a family pill fails here rather than quietly
    restoring the seventh pill on every card.
    """
    from PySide6.QtWidgets import QLabel
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)

    chips = [
        lbl for lbl in card.findChildren(QLabel)
        if lbl.property("role") == "family-chip"
        or lbl.objectName() == "FamilyChip"
    ]
    assert chips == [], (
        "the family chip is back — it duplicated the title in 9/9 models"
    )

    # The information is not lost: it is the card's accessible
    # description, and a sighted reader gets it from the title.
    assert card.accessibleDescription().startswith(card._info.family)


def test_model_card_spec_line_carries_numbers_the_description_omits(qtbot):
    """Size and VRAM are the two facts that earned the spec line.

    Measured across the nine shipped models: VRAM spans 0.5-6.0 GB and
    download size spans 30 MB to 3.1 GB, and neither number appears in
    any model's description. They are the trade a reader is choosing
    on, so the line has to carry the model's own values, not constants.
    """
    from PySide6.QtWidgets import QLabel
    from app.gui.widgets.model_card import ModelCard
    from app.model_mapping import MODELS

    vrams = {m.vram_gb for m in MODELS}
    assert len(vrams) > 1
    assert min(vrams) < 1.0 < max(vrams)

    for info in MODELS:
        card = ModelCard(info)
        qtbot.addWidget(card)
        spec = next(
            l for l in card.findChildren(QLabel) if "VRAM" in l.text()
        )
        assert f"{info.vram_gb:.1f} GB VRAM" in spec.text()
        card.deleteLater()


def test_model_card_spec_line_drops_what_the_description_says(qtbot):
    """``quality`` and ``speed`` are not on the card any more.

    ``quality`` read "excellent" on eight of the nine — a badge that
    says the same thing everywhere is furniture, and the description
    says more useful things ("Quality dips on accented speech").
    ``speed`` is not far behind: six of nine descriptions already carry
    "6x speed", "Fastest multilingual ASR", "ultra-lightweight" or
    "Best speed/size/quality balance".

    The speed word stays on the line as plain text, because the reader's
    first question is "is it quick" and the number itself is not in the
    description. The quality word is gone entirely — there is nothing
    left for it to say.
    """
    from PySide6.QtWidgets import QLabel
    from app.gui.widgets.model_card import ModelCard
    from app.model_mapping import MODELS

    qualities = [m.quality for m in MODELS]
    assert qualities.count("excellent") >= 8, (
        "the quality badge was cut because 8/9 read identical — if the "
        "registry changed, revisit the decision rather than trusting it"
    )

    for info in MODELS:
        card = ModelCard(info)
        qtbot.addWidget(card)
        labels = [l.text() for l in card.findChildren(QLabel)]
        joined = " ".join(labels)
        assert info.quality not in joined, (
            f"{info.display_name}: quality is back on the card"
        )
        assert info.speed in joined, (
            f"{info.display_name}: the speed word must stay as text"
        )
        card.deleteLater()


def test_model_card_subtitle_contains_alias_canonical_and_link(qtbot):
    """The subtitle line surfaces the registry alias, the full
    canonical id, and a clickable link to the model's home page."""
    from PySide6.QtWidgets import QLabel
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)

    subtitle = next(
        lbl for lbl in card.findChildren(QLabel)
        if lbl.objectName() == "ModelSubtitle"
    )
    text = subtitle.text()
    assert "whisper-large-v3" in text
    assert "onnx-community/whisper-large-v3" in text
    assert "huggingface.co" in text
    assert subtitle.openExternalLinks() is True


# ---------------------------------------------------------------------------
# Async cache check tests
# ---------------------------------------------------------------------------

def test_refresh_cache_state_not_called_on_main_thread(qtbot, monkeypatch):
    """is_cached_for_info must run in a thread-pool thread, not the main thread."""
    import threading
    from app.gui.widgets.model_card import ModelCard

    main_id = threading.get_ident()
    worker_thread_ids: list[int] = []

    def mock_cached(info):
        worker_thread_ids.append(threading.get_ident())
        return False

    monkeypatch.setattr("app.utils.is_cached_for_info", mock_cached)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    # Wait for the __init__ worker to deliver its result, then reset.
    qtbot.waitUntil(lambda: card._cached is not None, timeout=2000)
    worker_thread_ids.clear()
    card._cached = None  # reset so waitUntil can detect the next result

    card.refresh_cache_state()
    qtbot.waitUntil(lambda: card._cached is not None, timeout=2000)

    assert len(worker_thread_ids) == 1
    assert worker_thread_ids[0] != main_id, "is_cached_for_info ran on the Qt main thread"


def test_refresh_cache_state_calls_is_cached_exactly_once(qtbot, monkeypatch):
    """Each refresh_cache_state() triggers exactly one disk check, not two."""
    from app.gui.widgets.model_card import ModelCard

    call_count: list[int] = []

    monkeypatch.setattr(
        "app.utils.is_cached_for_info",
        lambda info: call_count.append(1) or False,
    )

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    qtbot.waitUntil(lambda: card._cached is not None, timeout=2000)
    call_count.clear()
    card._cached = None

    card.refresh_cache_state()
    qtbot.waitUntil(lambda: card._cached is not None, timeout=2000)

    assert len(call_count) == 1, f"Expected 1 disk check, got {len(call_count)}"


def test_stale_cache_result_is_ignored(qtbot, monkeypatch):
    """A result arriving from an older worker must not overwrite a result
    that has already been applied from the latest worker.

    Simulates the race: two rapid refresh_cache_state() calls issued while
    the first worker is still in flight.  The stale result (from request N-1)
    must be discarded when the current request counter is already at N.
    """
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: False)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    qtbot.waitUntil(lambda: card._cached is not None, timeout=2000)

    # Advance the counter to simulate a newer request having landed.
    card._cache_request_id = 5
    card._cached = False  # newest result: not cached

    # Inject a stale result from an older request (id=3).
    card._apply_cache_result(True, 3)

    select_btn = next(
        b for b in card.findChildren(QPushButton) if b.objectName() == "SelectButton"
    )
    assert card._cached is False, "stale result must not update _cached"
    assert select_btn.text() == "Download", "stale result must not flip the button"


def test_refresh_cache_state_updates_button_to_select_when_cached(qtbot, monkeypatch):
    """When the async worker reports the model is on disk, button shows 'Select'."""
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: True)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)

    select_btn = next(
        b for b in card.findChildren(QPushButton) if b.objectName() == "SelectButton"
    )
    qtbot.waitUntil(lambda: select_btn.text() == "Select", timeout=2000)


def test_refresh_cache_state_updates_button_to_download_when_not_cached(qtbot, monkeypatch):
    """When the async worker reports the model is absent, button shows 'Download'."""
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: False)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)

    select_btn = next(
        b for b in card.findChildren(QPushButton) if b.objectName() == "SelectButton"
    )
    qtbot.waitUntil(lambda: select_btn.text() == "Download", timeout=2000)


def test_set_active_does_not_hit_disk(qtbot, monkeypatch):
    """set_active() must reuse the last known cache result — no disk I/O."""
    from app.gui.widgets.model_card import ModelCard

    call_count: list[int] = []

    monkeypatch.setattr(
        "app.utils.is_cached_for_info",
        lambda info: call_count.append(1) or True,
    )

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    # Wait for the __init__ worker to deliver its result before asserting.
    qtbot.waitUntil(lambda: card._cached is not None, timeout=2000)
    call_count.clear()

    card.set_active(True)
    card.set_active(False)
    qtbot.wait(100)  # short fixed wait: confirming no I/O fires

    assert len(call_count) == 0, "set_active() triggered unexpected disk I/O"


def test_set_loading_does_not_hit_disk(qtbot, monkeypatch):
    """set_loading() must reuse the last known cache result — no disk I/O."""
    from app.gui.widgets.model_card import ModelCard

    call_count: list[int] = []

    monkeypatch.setattr(
        "app.utils.is_cached_for_info",
        lambda info: call_count.append(1) or True,
    )

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.set_active(True)
    # Wait for the __init__ worker to deliver its result before asserting.
    qtbot.waitUntil(lambda: card._cached is not None, timeout=2000)
    call_count.clear()

    card.set_loading(True)
    card.set_loading(False)
    qtbot.wait(100)  # short fixed wait: confirming no I/O fires

    assert len(call_count) == 0, "set_loading() triggered unexpected disk I/O"


# ---- Style-recalculation guard (no-op when state unchanged) ----------------


def test_set_active_same_value_is_noop(qtbot, monkeypatch):
    """set_active() called with the same value must leave visible state
    unchanged — no pill toggle, no widget flicker."""
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: False)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)

    # Initially inactive — calling set_active(False) again must be a no-op.
    assert card.is_active() is False
    card.set_active(False)
    assert card.is_active() is False
    # Use isHidden(): isVisible() requires all ancestors to be shown, but
    # isHidden() reflects only whether *this* widget was explicitly hidden.
    assert card._active_pill.isHidden(), "pill must stay hidden"

    # Activate, then call again — must not double-toggle.
    card.set_active(True)
    assert card.is_active() is True
    card.set_active(True)
    assert card.is_active() is True
    assert not card._active_pill.isHidden(), "pill must stay visible"


def test_set_loading_same_value_preserves_progress_text(qtbot, monkeypatch):
    """set_loading(True) on an already-loading card must not reset the
    progress text that was already rendered on the pill.

    ModelsView.set_loading loops all cards; without the no-op guard each
    card resets its pill text on every call — the user would see the
    progress percentage blink back to 'Loading…' on the next loop pass.
    """
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: False)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.set_active(True)
    card.set_loading(True)

    # Simulate 50 % download progress.
    card.set_loading_progress(50, 100)
    assert "50%" in card._active_pill.text()

    # Calling set_loading(True) again must NOT reset the progress text.
    card.set_loading(True)
    assert "50%" in card._active_pill.text(), (
        "repeated set_loading(True) must not wipe the progress text"
    )


def test_model_card_select_button_is_reachable_and_does_not_chase_focus(qtbot):
    """The Download/Select action must be keyboard-reachable, and hiding
    it must not move focus somewhere else.

    The card hides the Select button the instant the model turns active.
    If the button held focus, Qt picks the next widget in the tab chain
    (the Download button on the *next* card) and the enclosing
    QScrollArea scrolls down to it — so clicking Download on the first
    card used to jump the whole list. An earlier version of this test
    asserted ``Qt.NoFocus`` on the button, which silenced the chase by
    taking every card's primary action out of the tab chain entirely.

    The fix is to hand focus to the card itself before hiding the
    button, so both halves are asserted here: the button is Tab-
    reachable, and activating the card parks focus on the card rather
    than letting Qt's chase run.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.show()
    # Offscreen Qt only grants focus to an *active* window; without this
    # ``setFocus`` is silently a no-op and the assertions below would be
    # testing nothing.
    card.activateWindow()
    QApplication.processEvents()

    select_btn = next(
        b for b in card.findChildren(QPushButton) if b.objectName() == "SelectButton"
    )
    # Reachable: the whole point of dropping the old NoFocus guard.
    assert select_btn.focusPolicy() != Qt.NoFocus
    # The card is the deliberate landing spot.
    assert card.focusPolicy() != Qt.NoFocus

    select_btn.setFocus()
    assert select_btn.hasFocus()

    card.set_active(True)

    assert not select_btn.isVisible()
    assert card.hasFocus(), (
        "focus must land on the card, not be chased to another card's button"
    )


def test_model_card_loading_progress_updates_pill_text(qtbot):
    """While loading, the active pill should show download progress as a
    percentage so the user can see the model fetch advancing."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.set_active(True)
    card.set_loading(True)

    # Default loading pill before any progress
    assert card._active_pill.text() == "Loading\u2026"

    card.set_loading_progress(50, 100)
    assert "50%" in card._active_pill.text()

    card.set_loading_progress(35, 100)
    assert "35%" in card._active_pill.text()


def test_model_card_set_loading_elapsed_does_not_change_pill_text(qtbot):
    """Cached model loads (CTranslate2 deserialisation) take ~15 seconds
    without ever firing a tqdm progress event. Without an elapsed
    counter the pill just sits at 'Loading…' and looks frozen — show
    seconds instead so the user can see the wait advancing."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.set_active(True)
    card.set_loading(True)

    initial = card._active_pill.text()

    card.set_loading_elapsed(5)
    # Pill text doesn't change on elapsed ticks — topbar pill owns
    # the seconds display so the same number doesn't appear twice.
    assert card._active_pill.text() == initial
    assert card._loading_elapsed_s == 5

    card.set_loading_elapsed(12)
    assert card._active_pill.text() == initial
    assert card._loading_elapsed_s == 12


def test_model_card_loading_progress_takes_priority_over_elapsed(qtbot):
    """Once download bytes start arriving, the percentage is more
    informative than elapsed seconds — the pill should show '%' even
    if the elapsed counter is also being pushed."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.set_active(True)
    card.set_loading(True)

    card.set_loading_elapsed(7)
    card.set_loading_progress(50, 100)
    assert "50%" in card._active_pill.text()
    assert "7" not in card._active_pill.text()


def test_model_card_set_loading_false_clears_elapsed(qtbot):
    """Returning to ready state must wipe both progress and elapsed
    state, not just the progress text."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.set_active(True)
    card.set_loading(True)
    card.set_loading_elapsed(7)

    card.set_loading(False)
    assert card._active_pill.text() == "Active"

    card.set_loading(True)
    # Re-entering loading must not resurrect the stale elapsed text.
    assert card._active_pill.text() == "Loading\u2026"


def test_model_card_loading_progress_falls_back_to_size(qtbot):
    """When the total file size is unknown (Hugging Face streaming bars
    sometimes have total=0), fall back to a byte counter so the user
    still sees movement instead of a stuck 'Loading…'."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.set_active(True)
    card.set_loading(True)

    card.set_loading_progress(2_500_000, 0)
    text = card._active_pill.text()
    assert "MB" in text or "KB" in text or "GB" in text


def test_model_card_loading_progress_ignored_when_not_loading(qtbot):
    """Stale progress events arriving after the model finished must not
    repaint the green Active pill with download bytes."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.set_active(True)
    # Not in loading state.

    card.set_loading_progress(50, 100)
    assert card._active_pill.text() == "Active"


def test_model_card_set_loading_false_resets_pill_text(qtbot):
    """Returning to ready state must wipe any leftover progress text."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.set_active(True)
    card.set_loading(True)
    card.set_loading_progress(50, 100)

    card.set_loading(False)
    assert card._active_pill.text() == "Active"


def test_model_card_inactive_card_ignores_loading(qtbot):
    """Loading should only affect the currently-active card's pill, not
    the inactive ones."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    # No set_active(True) — card is inactive.

    card.set_loading(True)
    # Inactive cards: pill is hidden, no visible text changes needed.
    assert not card._active_pill.isVisibleTo(card)


def test_model_card_button_says_download_when_not_cached(qtbot, monkeypatch):
    """Uncached models advertise the action as 'Download' so the user knows
    the click will fetch weights from the network."""
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: False)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)

    select_btn = next(
        b for b in card.findChildren(QPushButton) if b.objectName() == "SelectButton"
    )
    qtbot.waitUntil(lambda: select_btn.text() == "Download", timeout=2000)


def test_model_card_button_says_select_when_cached(qtbot, monkeypatch):
    """Once weights are on disk, the action button switches to 'Select'."""
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: True)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)

    select_btn = next(
        b for b in card.findChildren(QPushButton) if b.objectName() == "SelectButton"
    )
    qtbot.waitUntil(lambda: select_btn.text() == "Select", timeout=2000)


def test_model_card_refresh_cache_state_picks_up_new_state(qtbot, monkeypatch):
    """After a download finishes, calling refresh_cache_state should flip
    the button label without needing to rebuild the card."""
    from app.gui.widgets.model_card import ModelCard

    cache_status = {"cached": False}
    monkeypatch.setattr(
        "app.utils.is_cached_for_info",
        lambda info: cache_status["cached"],
    )

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    select_btn = next(
        b for b in card.findChildren(QPushButton) if b.objectName() == "SelectButton"
    )
    qtbot.waitUntil(lambda: select_btn.text() == "Download", timeout=2000)

    cache_status["cached"] = True
    card.refresh_cache_state()
    qtbot.waitUntil(lambda: select_btn.text() == "Select", timeout=2000)


def test_model_card_emits_select_signal_with_alias(qtbot):
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.show()  # buttons must be visible for qtbot.mouseClick
    qtbot.waitExposed(card)

    select_btn = next(
        b for b in card.findChildren(QPushButton) if b.objectName() == "SelectButton"
    )

    with qtbot.waitSignal(card.select_requested, timeout=1000) as blocker:
        qtbot.mouseClick(select_btn, Qt.LeftButton)

    assert blocker.args == ["whisper-large-v3"]


# ---- Delete button ---------------------------------------------------------


def _delete_btn(card) -> QPushButton:
    return next(
        b for b in card.findChildren(QPushButton)
        if b.objectName() == "DeleteButton"
    )


def test_model_card_has_a_delete_button(qtbot):
    """Every card carries a Delete affordance — cached state controls
    its visibility, but the widget is always present."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    btns = [b.objectName() for b in card.findChildren(QPushButton)]
    assert "DeleteButton" in btns


def test_model_card_delete_button_hidden_when_not_cached(qtbot, monkeypatch):
    """Nothing to delete → no button. Otherwise the user gets an
    enabled control that does nothing (or worse, fires a confirm
    dialog over an empty cache)."""
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: False)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    qtbot.waitUntil(lambda: card._cached is not None, timeout=2000)
    assert not _delete_btn(card).isVisible()


def test_model_card_delete_button_visible_when_cached_and_inactive(qtbot, monkeypatch):
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: True)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)
    qtbot.waitUntil(lambda: _delete_btn(card).isVisible(), timeout=2000)


def test_model_card_delete_button_hidden_when_active(qtbot, monkeypatch):
    """Deleting the loaded model would crash the running backend —
    hide the button until the user picks a different active card."""
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: True)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)
    # Wait for cache check to complete so _cached = True
    qtbot.waitUntil(lambda: card._cached is True, timeout=2000)
    card.set_active(True)
    assert not _delete_btn(card).isVisible()


def test_model_card_delete_button_hidden_when_loading(qtbot, monkeypatch):
    """Mid-download / mid-deserialise the cache state is undefined —
    hiding Delete avoids confusing the user with a button that might
    succeed or fail depending on timing."""
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: True)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)
    card.set_active(True)
    # Wait for cache check to complete so _cached = True
    qtbot.waitUntil(lambda: card._cached is True, timeout=2000)
    card.set_loading(True)
    assert not _delete_btn(card).isVisible()


def test_model_card_delete_button_emits_signal_with_alias(qtbot, monkeypatch):
    from app.gui.widgets.model_card import ModelCard

    monkeypatch.setattr("app.utils.is_cached_for_info", lambda info: True)

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)
    # Wait until the delete button becomes visible (async cache result arrived)
    qtbot.waitUntil(lambda: _delete_btn(card).isVisible(), timeout=2000)

    with qtbot.waitSignal(card.delete_requested, timeout=1000) as blocker:
        qtbot.mouseClick(_delete_btn(card), Qt.LeftButton)

    assert blocker.args == ["whisper-large-v3"]


def test_model_card_refresh_cache_state_toggles_delete_visibility(qtbot, monkeypatch):
    """After a Download or Delete completes, the controller calls
    ``refresh_cache_state`` — Delete's visibility must follow."""
    from app.gui.widgets.model_card import ModelCard

    cache_status = {"cached": True}
    monkeypatch.setattr(
        "app.utils.is_cached_for_info",
        lambda info: cache_status["cached"],
    )

    card = ModelCard(_make_info())
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)
    qtbot.waitUntil(lambda: _delete_btn(card).isVisible(), timeout=2000)

    cache_status["cached"] = False
    card.refresh_cache_state()
    qtbot.waitUntil(lambda: not _delete_btn(card).isVisible(), timeout=2000)


# ---- HF token warning (GigaAM only) ----------------------------------------


def _make_gigaam_info():
    from app.model_mapping import ModelInfo

    return ModelInfo(
        alias="gigaam-v3-ctc",
        canonical="istupakov/gigaam-v3-onnx",
        display_name="GigaAM v3 CTC (Russian, punctuated)",
        size_mb=260,
        vram_gb=2.0,
        speed="fast",
        quality="excellent",
        languages="Russian (only)",
        description="Sber GigaAM v3 with CTC decoder.",
        compute_type="float16",
        backend_kind="onnx_asr",
        family="GigaAM",
        onnx_family="gigaam",
    )


# HF-token warning / pyannote dependency was removed when GigaAM
# switched to its ONNX path — no token gating, no warning.  The
# legacy ``test_gigaam_card_*_token_*`` suite is gone with the feature.


# ---- Backend-specific inference panel dispatch -----------------------------


def _make_parakeet_info():
    from app.model_mapping import ModelInfo

    return ModelInfo(
        alias="parakeet-tdt-v3",
        canonical="istupakov/parakeet-tdt-0.6b-v3-onnx",
        display_name="Parakeet TDT v3",
        size_mb=1200,
        vram_gb=2.0,
        speed="fast",
        quality="excellent",
        languages="25 langs incl. Russian, Ukrainian",
        description="NVIDIA Parakeet TDT 0.6B v3 — 25 European languages.",
        compute_type="float32",
        backend_kind="onnx_asr",
        family="Parakeet",
        onnx_family="parakeet",
    )


def test_whisper_card_uses_whisper_inference_panel(qtbot):
    """Whisper-backed cards get the full 5-knob panel
    (language / VAD / beam / temperature / prompt)."""
    from app.gui.widgets.inference_settings_panel import InferenceSettingsPanel
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_info())  # _make_info() builds a Whisper card
    qtbot.addWidget(card)
    assert isinstance(card._settings_panel, InferenceSettingsPanel)


def test_parakeet_card_uses_nemo_inference_panel(qtbot):
    """Parakeet cards get the minimal panel — onnx-asr only exposes
    the ``timestamps`` toggle for the TDT family."""
    from app.gui.widgets.model_card import ModelCard
    from app.gui.widgets.parakeet_inference_settings_panel import (
        ParakeetInferenceSettingsPanel,
    )

    card = ModelCard(_make_parakeet_info())
    qtbot.addWidget(card)
    assert isinstance(card._settings_panel, ParakeetInferenceSettingsPanel)


def test_gigaam_card_has_no_inference_panel(qtbot):
    """GigaAM is end-to-end with no transcribe-time tunables — the
    panel is omitted entirely so a disabled control group doesn't
    look like a rendering bug."""
    from app.gui.widgets.model_card import ModelCard

    card = ModelCard(_make_gigaam_info())
    qtbot.addWidget(card)
    assert card._settings_panel is None


def test_parakeet_card_panel_emits_through_card_signal(qtbot):
    """The card forwards each panel's ``settings_changed`` to its
    own ``inference_settings_changed`` so the controller listens at
    a single point regardless of backend family."""
    from app.gui.widgets.model_card import ModelCard
    from app.inference_settings import ParakeetInferenceSettings

    card = ModelCard(_make_parakeet_info())
    qtbot.addWidget(card)

    with qtbot.waitSignal(card.inference_settings_changed, timeout=1000) as blocker:
        card._settings_panel.settings_changed.emit(
            ParakeetInferenceSettings(timestamps=True)
        )

    alias, settings = blocker.args
    assert alias == "parakeet-tdt-v3"
    assert isinstance(settings, ParakeetInferenceSettings)
    assert settings.timestamps is True


def test_model_card_colours_fast_and_only_fast(qtbot):
    """The spec line's one colour has to stay, and stay narrow.

    It is the only chromatic voice on the card, it is a *state* token
    (``success`` — "this one is quick" is a verdict about a value), and
    it appears on exactly the models whose speed is the desirable one.
    Nothing else on the line is coloured: size and VRAM are facts, not
    verdicts, and the description above already carries the nuance.
    """
    from PySide6.QtWidgets import QLabel
    from app.gui.theme import TOKENS
    from app.gui.widgets.model_card import ModelCard
    from app.model_mapping import MODELS

    success = TOKENS.colors["success"]
    coloured = 0
    for info in MODELS:
        card = ModelCard(info)
        qtbot.addWidget(card)
        spec = next(
            l for l in card.findChildren(QLabel) if "VRAM" in l.text()
        )
        markup = spec.text()
        if info.speed == "fast":
            assert f'color:{success}' in markup, (
                f"{info.display_name}: fast lost its colour"
            )
            coloured += 1
        else:
            assert f'color:{success}' not in markup, (
                f"{info.display_name}: {info.speed!r} should not be "
                f"coloured — only the desirable value is"
            )
        # Exactly one coloured span, never more.
        assert markup.count("color:") == (1 if info.speed == "fast" else 0)
        card.deleteLater()

    # And it has to be a minority verdict, or colouring it says nothing.
    assert 0 < coloured < len(MODELS)
