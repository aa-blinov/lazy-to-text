"""Models browser view — scrollable grid of ModelCards."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.smooth_scroll import apply_smooth_scroll
from app.gui.widgets.model_card import ModelCard
from app.gui.widgets.page_header import PageHeader

from app.inference_settings import InferenceSettings
from app.model_mapping import MODELS, ModelInfo


_FILTER_ALL = "All"
SEARCH_DEBOUNCE_MS = 200  # ms to wait after last keystroke before filtering


class ModelsView(QWidget):
    model_selected = Signal(str)
    # Re-emitted from whichever card the user clicked Delete on. The
    # controller is responsible for confirming with the user before
    # actually wiping the cache.
    model_delete_requested = Signal(str)
    # Re-emitted from whichever card had its inline panel touched —
    # ``(alias, InferenceSettings)``.
    inference_settings_changed = Signal(str, InferenceSettings)

    def __init__(
        self,
        models: Optional[Sequence[ModelInfo]] = None,
        search_debounce_ms: int = SEARCH_DEBOUNCE_MS,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ModelsView")
        resolved: Sequence[ModelInfo] = tuple(models) if models is not None else MODELS

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(14)

        self._header = PageHeader(
            "Models",
            "Pick what the app listens with. Bigger is more accurate and "
            "slower to load.",
            self,
        )
        root.addWidget(self._header)

        # ---- Search ------------------------------------------------------
        # Search only. The filter chips used to live here as a row of
        # eight — "All" plus every family — and they are now on the
        # cards, where the filter is actually reachable from the thing
        # it filters. That row was 48px of fixed chrome above the list,
        # and at text scale 1.75 its chips wanted 755px in a 644px
        # column.
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self._search_edit = QLineEdit(self)
        self._search_edit.setObjectName("ModelsSearchEdit")
        self._search_edit.setPlaceholderText(
            "Search models by name, alias, language…"
        )
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._on_search_changed)
        # A fixed 400px, not a stretch. Two reasons, both measured: at
        # 844px it was the widest, heaviest thing on the screen holding a
        # two-word query, and a bare QLineEdit's sizeHint is only 145px,
        # so dropping the stretch collapsed it to a stub. Fixed width
        # keeps it a proportioned tool flush with the page margin — the
        # one edge this view is built on. It must stay wide enough for
        # its own placeholder at every text scale Settings offers;
        # ``test_models_search_field_is_bounded_not_stretched`` fails the
        # day it does not.
        self._search_edit.setFixedWidth(400)
        # No stretch factor on the field, and a trailing stretch after
        # it. Giving the field the stretch instead lets the layout
        # centre it once the 400px cap leaves slack on both sides.
        toolbar.addWidget(self._search_edit)
        toolbar.addStretch(1)

        root.addLayout(toolbar)

        # ---- Cards (stacked behind a "no matches" empty state) ----------
        self._stack = QStackedWidget(self)

        scroll = QScrollArea(self._stack)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        apply_smooth_scroll(scroll)

        content = QWidget(scroll)
        content.setObjectName("ModelsScrollContent")
        cards_layout = QVBoxLayout(content)
        # Outer padding so the drop shadow on each card has room to
        # breathe instead of getting clipped at the scroll-area edge.
        cards_layout.setContentsMargins(4, 4, 4, 4)
        cards_layout.setSpacing(16)

        self._cards: Dict[str, ModelCard] = {}
        for info in resolved:
            card = ModelCard(info, parent=content)
            card.select_requested.connect(self.model_selected.emit)
            card.delete_requested.connect(self.model_delete_requested.emit)
            card.inference_settings_changed.connect(
                self.inference_settings_changed.emit
            )
            card.family_filter_toggled.connect(
                self._on_family_chip_clicked
            )
            cards_layout.addWidget(card)
            self._cards[info.alias] = card

        cards_layout.addStretch(1)
        scroll.setWidget(content)
        self._stack.addWidget(scroll)

        # Empty-state placeholder — same look as the History view's
        # "no entries yet" panel.
        empty = QWidget(self._stack)
        empty.setObjectName("ModelsEmptyState")
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(40, 60, 40, 60)
        empty_layout.setSpacing(8)
        empty_layout.addStretch(1)
        title = QLabel("No models match your filters", empty)
        title.setProperty("role", "empty-title")
        title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(title)
        hint = QLabel(
            "Clear the search box or pick a different family chip.",
            empty,
        )
        hint.setProperty("role", "empty-hint")
        hint.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(hint)
        empty_layout.addStretch(2)
        self._empty_state = empty
        self._stack.addWidget(empty)
        self._scroll = scroll

        root.addWidget(self._stack, 1)

        self._active_alias: Optional[str] = None
        self._locked = False
        self._search_query: str = ""
        self._pending_search: str = ""
        self._family_filter: str = _FILTER_ALL

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(search_debounce_ms)
        self._search_timer.timeout.connect(self._apply_search)

        self._apply_filter()

    def active_alias(self) -> Optional[str]:
        return self._active_alias

    def set_active(self, alias: Optional[str]) -> None:
        """Mark a card as the currently active one. ``None`` clears
        the active state on every card — the rollback hook used by
        the cancel-load flow when the user backs out of a
        just-clicked model before its load finishes.

        Only updates the old and new active cards to avoid O(n) work on
        the UI thread.
        """
        if alias is not None and alias not in self._cards:
            raise KeyError(alias)

        self.setUpdatesEnabled(False)
        try:
            # Deactivate the old card if any
            if self._active_alias and self._active_alias in self._cards:
                self._cards[self._active_alias].set_active(False)

            # Activate the new card
            self._active_alias = alias
            if self._active_alias:
                self._cards[self._active_alias].set_active(True)
        finally:
            self.setUpdatesEnabled(True)

    def is_locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool) -> None:
        new_locked = bool(locked)
        if new_locked == self._locked:
            return
        self._locked = new_locked
        self.setUpdatesEnabled(False)
        try:
            for card in self._cards.values():
                card.set_locked(self._locked)
        finally:
            self.setUpdatesEnabled(True)

    def set_loading(self, loading: bool) -> None:
        """Mark the currently active card as loading — its pill swaps from
        'Active' to 'Loading…' until the backend reports ready.

        Only updates the active card to avoid O(n) style recalculations
        that would otherwise block the UI thread on heavy lists.
        """
        card = self._cards.get(self._active_alias)
        if card is not None:
            card.set_loading(loading)

    def set_delete_busy(self, alias: str, busy: bool) -> None:
        card = self._cards.get(alias)
        if card is not None:
            card.set_delete_busy(busy)

    def set_loading_progress(self, current: int, total: int) -> None:
        """Forward backend download progress to the active card only.

        tqdm fires this many times per second during a download; routing
        it to every card via a loop wasted O(n) Python call overhead on
        each tick even though n-1 of those calls were immediate no-ops
        inside the card (``if not self._loading: return``).
        """
        card = self._cards.get(self._active_alias)
        if card is not None:
            card.set_loading_progress(current, total)

    def set_loading_elapsed(self, seconds: int) -> None:
        """Forward the elapsed-seconds tick to the active card only.

        The controller fires this once per second throughout a model load;
        routing it through all cards was O(n) work for one repaint.
        """
        card = self._cards.get(self._active_alias)
        if card is not None:
            card.set_loading_elapsed(seconds)

    def set_inference_settings(
        self, alias: str, settings: InferenceSettings
    ) -> None:
        """Push controller-loaded overrides onto a specific card's
        inline panel (no signal round-trip — the panel suppresses
        emission during programmatic updates)."""
        card = self._cards.get(alias)
        if card is not None:
            card.set_inference_settings(settings)

    def refresh_hf_token_state(self) -> None:
        """Recompute the HF-token warning visibility on every card.
        Called by the controller after the user pastes a token in
        Settings — Whisper cards no-op (no warning widget), GigaAM
        cards hide / show their warning based on the env vars."""
        for card in self._cards.values():
            card.refresh_hf_token_state()

    def refresh_cache_state(self) -> None:
        """Re-check the on-disk cache for every card. Called after a model
        finishes downloading so the freshly-downloaded card switches its
        button from "Download" to "Select"."""
        for card in self._cards.values():
            card.refresh_cache_state()

    # ---- Filter / search ---------------------------------------------------

    def visible_aliases(self) -> List[str]:
        """Aliases of the cards currently visible after the filter +
        search has been applied. Used in tests.

        ``isHidden`` is the canonical "did anyone call ``setVisible
        (False)``" check — ``isVisible`` only returns True once a
        top-level ancestor has been shown, which trips up tests that
        never call ``view.show()``.
        """
        return [
            alias
            for alias, card in self._cards.items()
            if not card.isHidden()
        ]

    def _on_search_changed(self, text: str) -> None:
        self._pending_search = text.lower().strip()
        self._search_timer.start()  # resets countdown on each keystroke

    def _apply_search(self) -> None:
        self._search_query = self._pending_search
        self._apply_filter()

    def _on_family_chip_clicked(self, family: str) -> None:
        """Toggle the family filter from a card's own chip.

        A toggle, not a radio. The row of eight chips is gone, so
        "All" is no longer a chip you can press — it is what you get
        when you press the active family's chip again. Keeping it a
        no-op instead would strand anyone who filtered by accident,
        with no visible way back.

        The pressed chip stays checked so the filter is readable at a
        glance: the one you would press again is the one you pressed.
        """
        if self._family_filter == family:
            self._family_filter = _FILTER_ALL
        else:
            self._family_filter = family
        for alias, card in self._cards.items():
            card.set_family_filter_active(
                self._family_filter != _FILTER_ALL
                and card.info().family == self._family_filter
            )
        self._apply_filter()

    def _card_matches(self, info: ModelInfo) -> bool:
        if (
            self._family_filter != _FILTER_ALL
            and info.family != self._family_filter
        ):
            return False
        if not self._search_query:
            return True
        haystack = " ".join(
            (
                info.alias,
                info.canonical,
                info.display_name,
                info.description,
                info.languages,
                info.family,
            )
        ).lower()
        return self._search_query in haystack

    def _apply_filter(self) -> None:
        any_visible = False
        for alias, card in self._cards.items():
            visible = self._card_matches(card.info())
            card.setVisible(visible)
            any_visible = any_visible or visible
        # Stack swaps between the scroll viewport and the empty-state
        # placeholder so the user gets a clear "nothing matches"
        # message instead of an empty grey rectangle.
        if any_visible:
            self._stack.setCurrentWidget(self._scroll)
        else:
            self._stack.setCurrentWidget(self._empty_state)
