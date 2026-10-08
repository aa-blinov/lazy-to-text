"""First run: choose a model, download it once, learn the key.

Between "installed" and "dictating" there used to be a catalogue of
sixteen cards in a scrolling list, ordered alphabetically — which put
Whisper Large v3 Turbo first, a 1.6 GB model at 25x the transcription
time of the default, above the 260 MB model the app actually measures
out as the right one. The header even said "bigger is more accurate and
slower to load" directly above a list sorted so that the biggest thing
was first. Nothing was broken; a newcomer simply had no way to tell
which of sixteen equally-formatted cards was the app's own answer.

So the first run is its own screen, and it has three steps and one job
each:

1. **Choose.** One card, the recommended one, with the download button
   on the card itself. There is no second button competing with it —
   two controls that do the same thing on one screen is how a user
   ends up pressing the wrong one and concluding the app is broken.
2. **Download.** Real bytes, real percentage, a cancel. The card is not
   on screen: it would say the same thing in a smaller font.
3. **The key.** The configured hotkey as a key cap. Not a sentence
   telling the user to press a key — the sentence is the easiest line
   on screen to skim past, because it looks like every other sentence.

Three steps, and every one of them ends in a decision the user already
had to make anyway. No welcome screen, because a screen with no
decision in it is a screen between the user and the decision.

**It comes back until a model is ready.** The flag is set by a model
reaching ``ready`` and by nothing else — not by dismissing this screen.
"If there is no model there is nothing to dictate with" is the whole
condition, so re-asking when it is still true is a fact rather than
nagging, and there is no separate dismissed state to get wrong. The
escape hatch out of step 1 is the catalogue: choose another model
there and this screen is in the background, not in the way.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.widgets.empty_state import hotkey_cap
from app.gui.widgets.model_card import ModelCard
from app.gui.widgets.page_header import PageHeader
from app.model_mapping import ModelInfo, display_order


# Recommended first, then by size — the same order the catalogue uses,
# via ``model_mapping.display_order``. This module deliberately does not
# have its own copy: two orders that agree today and drift tomorrow is
# how the first-run card stops matching the catalogue card it claims to
# be the recommendation for.
def first_run_candidates() -> list[ModelInfo]:
    return display_order()


class FirstRunView(QWidget):
    """Three pages: pick one model, watch it arrive, learn the key."""

    # ``(alias)`` — the user picked the card on screen 1. Routed
    # through the same signal the catalogue uses so the download, the
    # card's own state and the model switch are one implementation.
    model_chosen = Signal(str)
    # The user wants the full catalogue instead of the one card.
    catalogue_requested = Signal()
    # A model is loaded and working. First run is over, for good.
    completed = Signal()

    _DOWNLOAD_TICK_MS = 200

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("FirstRunView")

        self._info: ModelInfo = first_run_candidates()[0]
        self._finished = False
        self._elapsed_seconds = 0
        # True between "the backend stopped loading" and "the card's
        # disk check came back". The next cache result is the verdict
        # on whether the download landed.
        self._settling = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(16)

        self._header = PageHeader("", "", parent=self)
        outer.addWidget(self._header)

        self._pages = QStackedWidget(self)
        self._build_choose_page()
        self._build_download_page()
        self._build_hotkey_page()
        outer.addWidget(self._pages, 1)

        outer.addLayout(self._build_footer())

        # A countdown needs a reason to exist and a reason to stop.
        # Elapsed time answers "is this thing stuck?", which is the one
        # question a bare percentage bar cannot, and it stops the
        # instant the download does.
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(self._DOWNLOAD_TICK_MS)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self.show_step("choose")

    # ---- step 1: choose ----------------------------------------------------

    def _build_choose_page(self) -> None:
        page = QFrame(self._pages)
        page.setObjectName("FirstRunChoosePage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Optical centre, not mathematical. With a single card in a tall
        # window, a block centred on the vertical midpoint reads as a
        # header for the empty space below it; a 1:2 split above and
        # below sits it where the eye actually looks. Without this the
        # card hugged the top and the bottom two thirds of the window
        # was a void with one link in it.
        layout.addStretch(1)

        # The real ModelCard, not a lookalike. It owns the download
        # button, the progress pill, the cache check and the delete
        # affordance, and a second copy of any of those here would be
        # a second implementation to keep in step with the first.
        #
        # ``show_pitch`` swaps the measured case for the one-sentence
        # answer: on this screen the question is "why this one", not
        # "how does it compare to the other fifteen".
        self._card = ModelCard(self._info, page, show_pitch=True)
        self._card.select_requested.connect(self._on_card_selected)
        self._card.cache_state_changed.connect(self._on_card_cache_state)
        layout.addWidget(self._card)

        catalogue = QPushButton("See all models instead", page)
        catalogue.setObjectName("FirstRunCatalogueButton")
        catalogue.setProperty("role", "link")
        catalogue.setCursor(Qt.PointingHandCursor)
        catalogue.setToolTip(
            "Open the full model catalogue and pick one yourself"
        )
        catalogue.clicked.connect(self.catalogue_requested)
        layout.addWidget(catalogue, 0, Qt.AlignLeft)

        layout.addStretch(2)
        self._pages.addWidget(page)
        self._choose_page = page

    def _on_card_selected(self, alias: str) -> None:
        if alias != self._info.alias:
            # A card that is not the one this screen is about asked to
            # be selected. The catalogue is the place for that.
            self.catalogue_requested.emit()
            return
        self._settling = False
        self.show_step("download")
        self.set_download_started(self._info)
        self.model_chosen.emit(alias)

    def begin_settle_check(self) -> None:
        """The backend stopped loading — go and find out whether that
        means the weights arrived.

        Called by the controller on the transition into ``idle``. It
        cannot answer the question itself: the state machine reports
        that loading *stopped*, which is what a failed download looks
        like too, and a first-run screen that advanced to "press the
        key" after a failed fetch would be a lie the user only finds
        out when nothing transcribes.
        """
        if self.step() != "download":
            return
        self._settling = True
        self._card.refresh_cache_state()

    def _on_card_cache_state(self, alias: str, cached: bool) -> None:
        if alias != self._info.alias or not self._settling:
            return
        self._settling = False
        self._elapsed_timer.stop()
        if cached:
            self._progress.setRange(0, 100)
            self._progress.setValue(100)
            self.show_step("hotkey")
        else:
            self.set_download_failed(
                "The download did not finish."
            )

    # ---- step 2: download --------------------------------------------------

    def _build_download_page(self) -> None:
        page = QFrame(self._pages)
        page.setObjectName("FirstRunDownloadPage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addStretch(1)

        self._progress = QProgressBar(page)
        self._progress.setObjectName("FirstRunProgress")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setAccessibleName("Model download progress")
        layout.addWidget(self._progress)

        self._detail = QLabel("", page)
        self._detail.setProperty("role", "muted")
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

        self._hint = QLabel("", page)
        self._hint.setProperty("role", "muted")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        layout.addStretch(1)
        layout.addStretch(2)
        self._pages.addWidget(page)
        self._download_page = page

    def set_download_progress(self, current: int, total: int) -> None:
        """Real bytes, not a timer pretending to be progress.

        ``total`` of 0 means the download has not reported a size yet —
        Hugging Face streams the content-length header late — and a bar
        that sits at 0% until it does is telling the truth. Guessing a
        total here is how a progress bar ends up stuck at 137%.
        """
        self._download_started()
        if total > 0:
            pct = max(0, min(100, round(current * 100 / total)))
            self._progress.setRange(0, 100)
            self._progress.setValue(pct)
            self._detail.setText(
                f"{pct}%  ·  {_mb(current)} of {_mb(total)}"
            )
        else:
            self._progress.setRange(0, 0)  # indeterminate
            self._detail.setText(f"Downloading… {_mb(current)}")
        self._progress.setAccessibleDescription(
            self._detail.text() or "Downloading"
        )

    def _download_started(self) -> None:
        if not self._elapsed_timer.isActive():
            self._elapsed_seconds = 0
            self._elapsed_timer.start()
            self._hint.setText(
                "This happens once. The app works offline from here on."
            )

    def _tick_elapsed(self) -> None:
        """Elapsed seconds, appended to the size line.

        The answer to "is this thing stuck?" is the only thing a bar
        cannot say: a download sitting at 40% looks identical whether it
        is thirty seconds from done or has died. The registry reports a
        260 MB fetch in tens of seconds, so anything past a minute is
        the user looking at a reason to go and check the Logs.
        """
        self._elapsed_seconds += 1
        head = self._detail.text().split("  ·  ")[0]
        self._detail.setText(f"{head}  ·  {self._elapsed_seconds}s")

    def set_download_started(self, info: ModelInfo) -> None:
        """Called the moment the model switch is accepted."""
        self._info = info
        self._progress.setRange(0, 0)
        self._detail.setText("Starting…")
        self._download_started()

    def set_download_failed(self, reason: str) -> None:
        self._elapsed_timer.stop()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._detail.setText(reason)
        self._hint.setText(
            "Nothing was saved. Press the key on the card to try again."
        )

    # ---- step 3: the key ---------------------------------------------------

    def _build_hotkey_page(self) -> None:
        page = QFrame(self._pages)
        page.setObjectName("FirstRunHotkeyPage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addStretch(1)

        cap_row = QHBoxLayout()
        cap_row.setContentsMargins(0, 0, 0, 0)
        self._cap_slot = QHBoxLayout()
        cap_row.addStretch(1)
        cap_row.addLayout(self._cap_slot)
        cap_row.addStretch(1)
        layout.addLayout(cap_row)

        self._key_body = QLabel("", page)
        self._key_body.setProperty("role", "muted")
        self._key_body.setWordWrap(True)
        self._key_body.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._key_body)

        layout.addStretch(1)
        layout.addStretch(2)
        self._pages.addWidget(page)
        self._hotkey_page = page

    def set_hotkey(self, value: str, stop_value: str = "") -> None:
        """The key as a key cap, built from the configured binding.

        Not a literal: the shipped default differs per platform and the
        user can rebind it, so a hardcoded "Ctrl+F2" would be a lie on
        one platform and a lie again for anyone who changed it. An
        unbound value renders no cap at all — there is nothing true to
        print.
        """
        while self._cap_slot.count():
            item = self._cap_slot.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        cap = hotkey_cap(value, self)
        if cap is not None:
            self._cap_slot.addWidget(cap)

        stop = hotkey_cap(stop_value, self)
        if stop is not None:
            between = QLabel("to stop", self)
            between.setProperty("role", "muted")
            self._cap_slot.addWidget(between)
            self._cap_slot.addWidget(stop)

        self._key_body.setText(
            "Press it, say a sentence, press stop. The text appears "
            "wherever you were typing."
        )

    # ---- chrome ------------------------------------------------------------

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._back_btn = QPushButton("Back", self)
        self._back_btn.setProperty("role", "default")
        self._back_btn.clicked.connect(lambda: self.show_step("choose"))
        row.addWidget(self._back_btn)

        self._defer_btn = QPushButton("Set up later", self)
        self._defer_btn.setObjectName("FirstRunDeferButton")
        self._defer_btn.setProperty("role", "link")
        self._defer_btn.setCursor(Qt.PointingHandCursor)
        self._defer_btn.setToolTip(
            "Skip this and open the app. With no model downloaded there "
            "is nothing to dictate yet."
        )
        row.addWidget(self._defer_btn)
        row.addStretch(1)

        self._next_btn = QPushButton("Done", self)
        self._next_btn.setProperty("role", "primary")
        self._next_btn.clicked.connect(self._on_done)
        row.addWidget(self._next_btn)
        return row

    def _on_done(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._elapsed_timer.stop()
        self.completed.emit()

    # ---- state -------------------------------------------------------------

    def show_step(self, step: str) -> None:
        """``choose`` / ``download`` / ``hotkey``.

        Every header is rewritten from here rather than living on the
        pages, because the page that says what is happening is the one
        that is visible and the three titles are three lines of state
        that would otherwise be three places to forget to update.
        """
        index = {"choose": 0, "download": 1, "hotkey": 2}.get(step, 0)
        self._pages.setCurrentIndex(index)
        self._elapsed_timer.stop()

        if step == "choose":
            name = self._info.display_name
            self._header.set_title("Start dictating")
            self._header.set_subtitle(
                f"One download, then a hotkey puts what you say into "
                f"whatever window you are typing in. No account, no "
                f"cloud — {name} is the one this app measures out as "
                f"the right starting point."
            )
            self._back_btn.setVisible(False)
            self._next_btn.setVisible(False)
            self._defer_btn.setVisible(True)
        elif step == "download":
            self._header.set_title(f"Downloading {self._info.display_name}")
            self._header.set_subtitle(
                f"{self._info.size_mb} MB, once. Then it works offline."
            )
            self._back_btn.setVisible(False)
            self._next_btn.setVisible(False)
            self._defer_btn.setVisible(True)
        else:
            self._header.set_title("That is the whole setup")
            self._header.set_subtitle(
                "The key is the product. Everything else is "
                "configuration you will not touch again."
            )
            self._back_btn.setVisible(False)
            self._next_btn.setVisible(True)
            self._next_btn.setText("Start dictating")
            self._defer_btn.setVisible(False)

    def step(self) -> str:
        return ("choose", "download", "hotkey")[self._pages.currentIndex()]

    def model_info(self) -> ModelInfo:
        return self._info

    def stop_timers(self) -> None:
        self._elapsed_timer.stop()

    @property
    def card(self) -> ModelCard:
        return self._card


def _mb(value: int) -> str:
    """A byte count as something a person can read at a glance.

    The first progress callback of a Hugging Face download is routinely
    a few kilobytes of headers, so the sub-megabyte branch exists and is
    not dead code. Rounding 12 kB to "0.0 MB" would make the bar look
    stalled for the first second of every download.
    """
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    return f"{max(1, round(value / 1024))} KB"