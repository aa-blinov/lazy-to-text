"""Tests for the ModelsView."""

import pytest


def test_models_view_creates_one_card_per_registry_entry(qtbot):
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard
    from app.model_mapping import MODELS

    view = ModelsView()
    qtbot.addWidget(view)

    cards = view.findChildren(ModelCard)
    assert {c.alias() for c in cards} == {m.alias for m in MODELS}


def test_models_view_custom_registry(qtbot):
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard
    from app.model_mapping import get_model

    subset = (get_model("whisper-large-v3-turbo"), get_model("whisper-large-v3"))
    view = ModelsView(models=subset)
    qtbot.addWidget(view)

    cards = view.findChildren(ModelCard)
    assert [c.alias() for c in cards] == ["whisper-large-v3-turbo", "whisper-large-v3"]


def test_models_view_set_active_marks_correct_card(qtbot):
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard

    view = ModelsView()
    qtbot.addWidget(view)

    view.set_active("whisper-large-v3")
    assert view.active_alias() == "whisper-large-v3"

    cards = {c.alias(): c for c in view.findChildren(ModelCard)}
    assert cards["whisper-large-v3"].is_active() is True
    for alias, card in cards.items():
        if alias != "whisper-large-v3":
            assert card.is_active() is False


def test_models_view_set_active_switches_cleanly(qtbot):
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard

    view = ModelsView()
    qtbot.addWidget(view)

    view.set_active("whisper-large-v3-turbo")
    view.set_active("whisper-large-v3")

    cards = {c.alias(): c for c in view.findChildren(ModelCard)}
    assert cards["whisper-large-v3-turbo"].is_active() is False
    assert cards["whisper-large-v3"].is_active() is True


def test_models_view_set_active_rejects_unknown(qtbot):
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    with pytest.raises(KeyError):
        view.set_active("does-not-exist")


def test_models_view_set_active_none_clears_all(qtbot):
    """``set_active(None)`` is the rollback hook used by the
    cancel-load flow: when the user clicks Cancel before a
    just-picked card finishes loading, the controller has to
    un-mark it. Passing None means 'no card is Active'."""
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard

    view = ModelsView()
    qtbot.addWidget(view)

    view.set_active("whisper-large-v3")
    view.set_active(None)

    assert view.active_alias() is None
    cards = {c.alias(): c for c in view.findChildren(ModelCard)}
    for card in cards.values():
        assert card.is_active() is False


def test_models_view_emits_model_selected_when_card_emits(qtbot):
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard

    view = ModelsView()
    qtbot.addWidget(view)

    card = next(c for c in view.findChildren(ModelCard) if c.alias() == "vosk-ru-small")

    with qtbot.waitSignal(view.model_selected, timeout=1000) as blocker:
        card.select_requested.emit(card.alias())

    assert blocker.args == ["vosk-ru-small"]


def test_models_view_emits_model_delete_requested_when_card_emits(qtbot):
    """Cards bubble their delete_requested up through the view so the
    controller only has to listen to one signal source."""
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard

    view = ModelsView()
    qtbot.addWidget(view)

    card = next(c for c in view.findChildren(ModelCard) if c.alias() == "vosk-ru-small")

    with qtbot.waitSignal(view.model_delete_requested, timeout=1000) as blocker:
        card.delete_requested.emit(card.alias())

    assert blocker.args == ["vosk-ru-small"]


def test_models_view_starts_with_no_active(qtbot):
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    assert view.active_alias() is None


# ---- Lock state ------------------------------------------------------------


def test_models_view_starts_unlocked(qtbot):
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    assert view.is_locked() is False


def test_set_locked_disables_all_select_buttons(qtbot):
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard

    view = ModelsView()
    qtbot.addWidget(view)

    view.set_locked(True)
    assert view.is_locked() is True

    for card in view.findChildren(ModelCard):
        select_btn = next(
            b for b in card.findChildren(__import__('PySide6.QtWidgets', fromlist=['QPushButton']).QPushButton)
            if b.objectName() == "SelectButton"
        )
        assert not select_btn.isEnabled()


def test_models_view_set_loading_elapsed_records_value_on_active_card(qtbot):
    """Elapsed-seconds ticks reach the active card and update its
    internal counter, but the card's pill text intentionally doesn't
    render the number — the topbar pill owns that display.  So the
    behaviour is: ``set_loading_elapsed(N)`` propagates to the active
    card's ``_loading_elapsed_s`` attribute, but the pill text stays
    the same.
    """
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard

    view = ModelsView()
    qtbot.addWidget(view)
    view.set_active("whisper-large-v3-turbo")
    view.set_loading(True)

    view.set_loading_elapsed(5)

    cards = {c.alias(): c for c in view.findChildren(ModelCard)}
    active = cards["whisper-large-v3-turbo"]
    assert active._loading_elapsed_s == 5
    # Pill text is unchanged — no "5" anywhere in it.
    assert "5" not in active._active_pill.text()


def test_models_view_set_loading_progress_propagates_to_active_card(qtbot):
    """Download progress events arriving from the backend should bubble
    down to whichever card is currently flagged as loading, so the
    user sees percentage advance on the model they just clicked."""
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard

    view = ModelsView()
    qtbot.addWidget(view)
    view.set_active("whisper-large-v3-turbo")
    view.set_loading(True)

    view.set_loading_progress(50, 100)

    cards = {c.alias(): c for c in view.findChildren(ModelCard)}
    assert "50%" in cards["whisper-large-v3-turbo"]._active_pill.text()
    # Inactive cards' pills are hidden — text doesn't matter to the
    # user, but we don't want to crash trying to update them either.


def test_models_view_refresh_cache_state_propagates_to_all_cards(qtbot, monkeypatch):
    """When the cache state for any model changes (e.g. a download just
    finished), the view's refresh_cache_state must update every card so
    freshly-downloaded models flip from 'Download' to 'Select'."""
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard
    from PySide6.QtWidgets import QPushButton

    cache_status = {"cached": False}
    # Cache check runs in a QThreadPool worker — patch at the source module.
    monkeypatch.setattr(
        "app.utils.is_cached_for_info",
        lambda info: cache_status["cached"],
    )

    view = ModelsView()
    qtbot.addWidget(view)

    def _select_btn(card):
        return next(
            b for b in card.findChildren(QPushButton) if b.objectName() == "SelectButton"
        )

    # Wait for the initial async workers to settle — all cards → Download.
    cards = view.findChildren(ModelCard)
    qtbot.waitUntil(
        lambda: all(_select_btn(c).text() == "Download" for c in cards),
        timeout=3000,
    )

    cache_status["cached"] = True
    view.refresh_cache_state()

    # After refresh, all cards should flip to Select asynchronously.
    qtbot.waitUntil(
        lambda: all(_select_btn(c).text() == "Select" for c in cards),
        timeout=3000,
    )


def test_set_locked_false_re_enables_buttons_for_inactive_cards(qtbot):
    from app.gui.views.models_view import ModelsView
    from app.gui.widgets.model_card import ModelCard

    view = ModelsView()
    qtbot.addWidget(view)
    view.set_active("whisper-large-v3")

    view.set_locked(True)
    view.set_locked(False)

    cards = {c.alias(): c for c in view.findChildren(ModelCard)}
    # Active card's Select stays hidden/disabled (active state).
    assert cards["whisper-large-v3"].is_active() is True
    # Inactive cards must be clickable again.
    select_btn = next(
        b for b in cards["whisper-large-v3-turbo"].findChildren(__import__('PySide6.QtWidgets', fromlist=['QPushButton']).QPushButton)
        if b.objectName() == "SelectButton"
    )
    assert select_btn.isEnabled()


def test_models_view_uses_pixel_scroll_step(qtbot):
    """The models scroll area should use a small wheel step so the
    list scrolls pixel-by-pixel instead of jumping a whole card per
    notch — matches the rest of the UI."""
    from PySide6.QtWidgets import QScrollArea
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    scroll = view.findChild(QScrollArea)
    assert scroll is not None
    assert scroll.verticalScrollBar().singleStep() <= 20


def test_models_view_search_filters_by_substring(qtbot):
    """Typing in the search box should hide cards whose
    metadata doesn't contain the query (case-insensitive)."""
    from PySide6.QtWidgets import QLineEdit
    from app.gui.views.models_view import ModelsView

    view = ModelsView(search_debounce_ms=0)
    qtbot.addWidget(view)

    search = view.findChild(QLineEdit, "ModelsSearchEdit")
    search.setText("turbo")
    qtbot.wait(50)  # let debounce timer fire

    aliases = set(view.visible_aliases())
    # 'turbo' substring matches the Whisper Turbo card (alias and family)
    # but not the plain Whisper / GigaAM / Parakeet cards.
    assert "whisper-large-v3-turbo" in aliases
    assert "gigaam-v3-rnnt" not in aliases
    assert "parakeet-tdt-v3" not in aliases


def test_models_view_search_matches_canonical_and_language(qtbot):
    """The haystack covers alias, canonical, display name,
    description, language, family — so 'russian' surfaces every card
    that mentions Russian anywhere in those."""
    from PySide6.QtWidgets import QLineEdit
    from app.gui.views.models_view import ModelsView

    view = ModelsView(search_debounce_ms=0)
    qtbot.addWidget(view)

    search = view.findChild(QLineEdit, "ModelsSearchEdit")
    search.setText("russian")
    qtbot.wait(50)

    aliases = set(view.visible_aliases())
    # GigaAM is Russian-only, Vosk is Russian-only, Parakeet/Canary say
    # "incl. Russian" — all surface.
    assert "gigaam-v3-rnnt" in aliases
    assert "gigaam-v3-ctc" in aliases
    assert "vosk-ru-small" in aliases

    # Both Whisper cards match, and this used to be an assertion in the
    # other direction. It held only because the word "Russian" happened
    # not to appear in their prose — the haystack has always included
    # the description, so prose counted by design. Both cards now say
    # outright that they are the wrong pick for Russian, which is a
    # warning worth surfacing from the search rather than hiding from
    # it. Pinned here so the next person does not read it as a
    # regression.
    assert "whisper-large-v3-turbo" in aliases
    assert "whisper-large-v3" in aliases


def _card_chip(view, family):
    """The family chip on any card of that family."""
    from PySide6.QtWidgets import QPushButton
    for button in view.findChildren(QPushButton):
        if button.objectName() == "CardFamilyChip" and button.text() == family:
            return button
    raise AssertionError(f"no card carries a {family!r} chip")


def test_models_view_family_chip_filters_by_family(qtbot):
    """The GigaAM chip on a card should leave only GigaAM cards visible.

    The filter used to be a row of eight chips above the list. It now
    lives on the cards, so the filter is reachable from the thing it
    filters and the row's 48px of fixed chrome is gone.
    """
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)

    _card_chip(view, "GigaAM").click()

    aliases = set(view.visible_aliases())
    assert all(a.startswith("gigaam") for a in aliases)
    assert aliases  # at least one model survived


def test_models_view_family_chip_toggles_back_to_everything(qtbot):
    """Press the active chip again and the filter clears.

    The row is gone, so "All" is not a chip you can press — it is what
    you get by pressing the active family again. If this ever goes back
    to being a no-op, anyone who filtered by accident is stranded with
    no visible way out.
    """
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    everything = set(view.visible_aliases())

    chip = _card_chip(view, "Vosk")
    chip.click()
    filtered = set(view.visible_aliases())
    assert filtered < everything
    assert chip.isChecked() is True, (
        "the pressed chip has to stay checked, or the filter is unreadable"
    )

    chip.click()
    assert set(view.visible_aliases()) == everything
    assert chip.isChecked() is False


def test_models_view_family_chip_marks_exactly_the_visible_family(qtbot):
    """Only the filtered family's cards show a pressed chip, and a
    hidden card's chip must not be left lit behind a filter."""
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    _card_chip(view, "GigaAM").click()

    for alias, card in view._cards.items():
        expect = card.info().family == "GigaAM"
        assert card._family_chip.isChecked() is expect, alias

    # And a family the filter is not on is untouched.
    assert _card_chip(view, "Vosk").isChecked() is False


def test_models_view_has_no_filter_chip_row(qtbot):
    """The row above the list is gone, and only the cards carry chips.

    Kept as a test because "put the chips back in a row" is a
    one-line change someone will try when the list is long.
    """
    from PySide6.QtWidgets import QPushButton
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    names = {b.objectName() for b in view.findChildren(QPushButton)}
    assert "ModelsFilterChip" not in names
    assert "CardFamilyChip" in names


def test_models_view_no_match_shows_empty_state(qtbot):
    """A search that matches nothing should swap the scroll for the
    empty-state placeholder."""
    from PySide6.QtWidgets import QLineEdit
    from app.gui.views.models_view import ModelsView

    view = ModelsView(search_debounce_ms=0)
    qtbot.addWidget(view)

    search = view.findChild(QLineEdit, "ModelsSearchEdit")
    search.setText("definitely-no-such-model")
    qtbot.wait(50)

    assert view.visible_aliases() == []
    assert view._stack.currentWidget() is view._empty_state


def test_models_view_clearing_search_restores_all_cards(qtbot):
    from PySide6.QtWidgets import QLineEdit
    from app.gui.views.models_view import ModelsView
    from app.model_mapping import MODELS

    view = ModelsView(search_debounce_ms=0)
    qtbot.addWidget(view)

    search = view.findChild(QLineEdit, "ModelsSearchEdit")
    search.setText("whisper-large-v3-turbo")
    search.setText("")  # both coalesced by debounce — only "" fires
    qtbot.wait(50)

    assert set(view.visible_aliases()) == {m.alias for m in MODELS}


# ---- Search debounce --------------------------------------------------------


def test_models_view_search_debounce_does_not_filter_immediately(qtbot):
    """Typing must not hide cards until the debounce timer fires —
    without this, every keystroke rebuilds card visibility for all models."""
    from app.gui.views.models_view import ModelsView

    DEBOUNCE_MS = 120
    view = ModelsView(search_debounce_ms=DEBOUNCE_MS)
    qtbot.addWidget(view)

    all_aliases = set(view.visible_aliases())
    assert len(all_aliases) > 1  # sanity — multiple cards visible

    # Keystroke without waiting.
    view._on_search_changed("whisper-large-v3-turbo")

    # Immediately after: all cards still visible (filter not yet applied).
    assert set(view.visible_aliases()) == all_aliases, (
        "_apply_filter must not fire synchronously on each keystroke"
    )

    # After debounce fires: only turbo cards survive.
    qtbot.wait(DEBOUNCE_MS + 60)
    aliases_after = set(view.visible_aliases())
    assert "whisper-large-v3-turbo" in aliases_after
    assert "whisper-large-v3" not in aliases_after


def test_models_view_search_debounce_rapid_keystrokes_single_filter(qtbot):
    """Five rapid keystrokes must coalesce into one _apply_filter call."""
    from app.gui.views.models_view import ModelsView

    DEBOUNCE_MS = 120
    view = ModelsView(search_debounce_ms=DEBOUNCE_MS)
    qtbot.addWidget(view)

    all_count = len(view.visible_aliases())

    for prefix in ("t", "tu", "tur", "turb", "whisper-large-v3-turbo"):
        view._on_search_changed(prefix)

    # Still unfiltered (timer keeps restarting).
    assert len(view.visible_aliases()) == all_count

    qtbot.wait(DEBOUNCE_MS + 60)
    # "whisper-large-v3-turbo" query matches only turbo cards.
    assert len(view.visible_aliases()) < all_count


def test_models_view_search_debounce_timer_is_single_shot(qtbot):
    """Debounce timer must be single-shot so filtering stops after one pass."""
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    assert view._search_timer.isSingleShot()


# ---- Loading-event dispatch (O(1) not O(n)) --------------------------------


def test_set_loading_progress_dispatches_only_to_active_card(qtbot):
    """set_loading_progress must reach only the active card, not every card.

    During a model download tqdm fires dozens of times per second.
    Fanning the event out to all ~15 cards burns O(n) Python call overhead
    on each tick even though 14 of the calls are immediately no-ops inside
    the card.  The view must dispatch directly to the active card.
    """
    from app.model_mapping import get_model
    from app.gui.views.models_view import ModelsView

    subset = (get_model("whisper-large-v3-turbo"), get_model("whisper-large-v3"))
    view = ModelsView(models=subset)
    qtbot.addWidget(view)
    view.set_active("whisper-large-v3-turbo")
    view.set_loading(True)

    received: dict[str, list] = {"whisper-large-v3-turbo": [], "whisper-large-v3": []}
    for alias, card in view._cards.items():
        orig = card.set_loading_progress
        def _spy(c, t, _alias=alias, _orig=orig):
            received[_alias].append((c, t))
            _orig(c, t)
        card.set_loading_progress = _spy

    view.set_loading_progress(50_000_000, 100_000_000)

    assert received["whisper-large-v3-turbo"] == [(50_000_000, 100_000_000)], "active card must get progress"
    assert received["whisper-large-v3"] == [], "inactive card must not be called at all"


def test_set_loading_elapsed_dispatches_only_to_active_card(qtbot):
    """set_loading_elapsed must reach only the active card.

    The elapsed-seconds timer fires every second throughout a model load.
    Looping all cards on each tick wastes O(n) calls for no gain.
    """
    from app.model_mapping import get_model
    from app.gui.views.models_view import ModelsView

    subset = (get_model("whisper-large-v3-turbo"), get_model("whisper-large-v3"))
    view = ModelsView(models=subset)
    qtbot.addWidget(view)
    view.set_active("whisper-large-v3-turbo")
    view.set_loading(True)

    received: dict[str, list] = {"whisper-large-v3-turbo": [], "whisper-large-v3": []}
    for alias, card in view._cards.items():
        orig = card.set_loading_elapsed
        def _spy(s, _alias=alias, _orig=orig):
            received[_alias].append(s)
            _orig(s)
        card.set_loading_elapsed = _spy

    view.set_loading_elapsed(5)

    assert received["whisper-large-v3-turbo"] == [5], "active card must get elapsed tick"
    assert received["whisper-large-v3"] == [], "inactive card must not be called at all"


def test_set_loading_progress_noop_when_no_active_card(qtbot):
    """set_loading_progress with no active card must not raise."""
    from app.model_mapping import get_model
    from app.gui.views.models_view import ModelsView

    view = ModelsView(models=(get_model("whisper-large-v3-turbo"),))
    qtbot.addWidget(view)
    # No set_active call — _active_alias is None
    view.set_loading_progress(50, 100)  # must not raise


def test_set_loading_elapsed_noop_when_no_active_card(qtbot):
    """set_loading_elapsed with no active card must not raise."""
    from app.model_mapping import get_model
    from app.gui.views.models_view import ModelsView

    view = ModelsView(models=(get_model("whisper-large-v3-turbo"),))
    qtbot.addWidget(view)
    view.set_loading_elapsed(3)  # must not raise


def test_models_search_field_is_bounded_not_stretched(qtbot):
    """The search field must not fill the row.

    It used to stretch to the full content width — 844px in a 1100px
    window — to hold a query that is never more than two words, which
    made the widest, heaviest element on the screen the one carrying
    the least information. Bounded, the row reads as a column.
    """
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    view.resize(1100, 780)
    view.show()
    for _ in range(8):
        qtbot.wait(10)

    search = view._search_edit
    assert search.width() == 400, (
        f"search field is {search.width()}px — the fixed width is not holding"
    )
    assert search.minimumWidth() == 400
    assert search.width() <= 400, (
        f"search field is {search.width()}px wide — the bound is not holding"
    )
    # And it must still be wide enough for its own hint at every text
    # scale Settings offers, so the placeholder never elides.
    from PySide6.QtGui import QFontMetrics
    needed = QFontMetrics(search.font()).horizontalAdvance(
        search.placeholderText()
    ) + 48  # frame + clear button + breathing room
    assert search.width() >= needed, (
        f"search field {search.width()}px elides a {needed}px placeholder"
    )


def test_models_card_family_chip_is_keyboard_reachable(qtbot):
    """The chip is a control, so it has to be focusable and named.

    It used to be a dead label, and the fix was to make it live — which
    means it now answers for itself: its accessible name has to say
    what pressing it does, because the word on it is just the family,
    which the title beside it already says.
    """
    from PySide6.QtWidgets import QPushButton
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    chip = _card_chip(view, "Whisper Turbo")

    assert chip.focusPolicy() != chip.focusPolicy().NoFocus
    assert "Filter to Whisper Turbo" in chip.accessibleName()
    # …and it has to say how to get back, since there is no All chip.
    assert "again" in chip.accessibleName().lower()
    assert chip.toolTip()


# ---- Tab order and keyboard scrolling --------------------------------------


def _models_view_shown(qtbot, width=1100, height=620):
    from app.gui.views.models_view import ModelsView

    view = ModelsView()
    qtbot.addWidget(view)
    view.resize(width, height)
    view.show()
    qtbot.wait(10)
    return view


def test_the_scroll_area_is_not_a_tab_stop(qtbot):
    """A QScrollArea is a tab stop by default, which put it second in the
    chain — ahead of nine cards of content and, visually, after all of
    them.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea

    view = _models_view_shown(qtbot)
    scroll = view.findChild(QScrollArea)

    assert not scroll.focusPolicy() & Qt.FocusPolicy.TabFocus
    # …and it is not NoFocus either, because a click still has to park
    # focus there: that is what lets the arrow keys scroll the list.
    assert scroll.focusPolicy() & Qt.FocusPolicy.ClickFocus


def test_tab_from_the_search_lands_on_a_card_not_the_scroll_area(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QScrollArea

    view = _models_view_shown(qtbot)
    search = view.findChild(QLineEdit, "ModelsSearchEdit")
    scroll = view.findChild(QScrollArea)
    search.setFocus()
    qtbot.wait(10)

    QTest.keyClick(view, Qt.Key_Tab)
    qtbot.wait(10)

    landed = scroll.window().focusWidget()
    assert landed is not None
    assert landed is not scroll, "Tab still stops on the scroll area"
    assert landed is not view, "Tab left the card list entirely"


def test_tabbing_through_the_cards_scrolls_the_list(qtbot):
    """Tab has to do the scrolling itself once the scroll area is out of
    the chain.

    QScrollArea does not follow focus into a child widget: measured over
    30 Tabs, the content never moved off y=0 while eight of the nine
    cards sat below the fold. Without this the keyboard walks models the
    user cannot see.

    The tab budget is derived from the catalog size on purpose. It used to
    be a hardcoded 30, which was enough for the nine cards this test was
    written against; at twelve cards the list needs 36 presses to reach
    its own bottom, so the budget stopped mid-scroll and the test failed
    on a correct implementation. A 30-tab run reaching only 82% of the
    range proves nothing either way, so what this asserts is the whole
    walk, with the budget as patience rather than as the mechanism.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QScrollArea

    view = _models_view_shown(qtbot, height=500)
    scroll = view.findChild(QScrollArea)
    content = scroll.widget()
    reachable = scroll.verticalScrollBar().maximum()
    assert reachable > 0, "the list does not overflow, so this proves nothing"

    view.findChild(QLineEdit, "ModelsSearchEdit").setFocus()
    qtbot.wait(10)
    offsets = []
    # Generous: 6 stops per card, ~1s total. Reaching the bottom exits
    # early; the cap only bounds a regression that never scrolls at all.
    for _ in range(6 * len(view._cards)):
        QTest.keyClick(view, Qt.Key_Tab)
        qtbot.wait(5)  # the smooth-scroll animation lands
        offsets.append(content.y())
        if content.y() <= -reachable:
            break

    assert min(offsets) < 0, f"the list never moved (stuck at {offsets[0]})"
    assert min(offsets) <= -reachable * 0.9, (
        f"only reached {abs(min(offsets))}px of {reachable}px"
    )
