"""File-transcription view — drag-and-drop or browse for audio files,
get text back.

Single-file workflow for v1: pick one audio file, get a transcript,
edit it if the model heard it wrong, copy or save it.  Diarization,
batch processing and per-segment timestamps are out of scope until the
underlying backend grows support for them.

The screen is a stage with two acts, and the layout is built so only
one of them is ever asking for attention.  Empty, it is an invitation:
a drop zone and nothing else competing.  Loaded, the zone collapses
into a one-line identity of the file — name, size, how long it took,
how many words came back — and the transcript gets the screen.  A
drop target that never yields is a drop target that permanently
outshouts the thing you came here to read.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QMimeData, Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.audio_formats import AUDIO_EXTS, looks_like_audio
from app.config_manager import default_start_hotkey
from app.gui.widgets.empty_state import EmptyState
from app.gui.widgets.page_header import PageHeader
from app.language import bind, tr_count, tr_format, tr_text


# The list lives in a Qt-free module so the headless runtime validates
# against the same names this view's drop guard does.
_AUDIO_EXTS = AUDIO_EXTS

# How long a courtesy message ("Copied to clipboard.") stays up before
# the identity line is left alone again.  Long enough to register,
# short enough that it is not the last thing you read.
_STATUS_FLUSH_MS = 4000

# The names printed under the drop prompt.  Kept as a literal rather
# than sliced out of ``_AUDIO_EXTS`` on purpose: the set of *common*
# formats is an editorial choice, not the first five entries of a
# decoder's capability list, and deriving it would quietly repaint the
# copy whenever the decoder's order changed.
#
# Every entry is pinned against ``_AUDIO_EXTS`` by
# ``test_every_format_named_in_the_drop_hint_is_really_accepted``, so
# narrowing support cannot leave the hint promising a file that then
# gets rejected.
_DROP_FORMAT_EXAMPLES: tuple[str, ...] = ("MP3", "WAV", "M4A", "MP4", "MKV")


_looks_like_audio = looks_like_audio


def _format_size(num_bytes: int) -> str:
    """File size the way a person would say it out loud."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 ** 2:
        return f"{num_bytes / 1024:.0f} KB"
    if num_bytes < 1024 ** 3:
        return f"{num_bytes / 1024 ** 2:.1f} MB"
    return f"{num_bytes / 1024 ** 3:.1f} GB"


def _format_elapsed(seconds: float) -> str:
    """Processing time, kept short enough to sit inline with a filename."""
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes)}:{secs:04.1f}"


class TranscribeView(QWidget):
    """Drag-and-drop / browse zone wired to a single transcription
    pipeline.

    Emits one signal up to the controller:

    - ``file_dropped(path)`` — user picked a file (browse button or
      drag-drop).  The controller is expected to dispatch this to a
      worker thread and call back via ``set_result`` / ``set_error``.

    Convenience signals for telemetry / Logs view:

    - ``copy_requested()`` — user clicked Copy.
    - ``save_requested(path)`` — user clicked Save and confirmed a path.
    """

    file_dropped = Signal(str)
    copy_requested = Signal()
    save_requested = Signal(str)
    # Which profile a dictation should run. ``preset_override_changed``
    # fires with an id to pin for the next one, or "" to fall back to
    # the active profile.
    #
    # This screen used not to touch post-processing at all, and that was
    # a decision rather than an oversight: the LLM step belonged to the
    # dictation path, and putting a model picker here made a screen that
    # transcribes files look like it edits your dictation settings. It
    # now carries one control because choosing a profile at the moment
    # you use it is the whole reason profiles exist.
    preset_override_changed = Signal(str)

    def _build_profile_strip(self) -> QWidget:
        """The preset picker and its "use this one instead" checkbox.

        Two controls and no more. The dropdown says which preset; the
        checkbox says whether that choice applies here or is just what
        the picker is showing. Merging them — a dropdown whose first
        entry is "the default" — was the alternative, and it puts the
        decision inside a list the user has to read to find out which
        item is running.

        "Use this one instead" rather than "For this one": the first
        reads as a sentence about what will happen, the second as a
        flag whose effect you have to already know.
        """
        strip = QWidget(self)
        strip.setObjectName("TranscribePresetStrip")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # The checkbox sits in a plain, unstyled holder, and that is the
        # whole fix for the combo sitting on its text. A layout applies its
        # spacing to a QCheckBox and then places the next widget *one pixel
        # before* where the checkbox ended: measured, the combo lands at
        # x=152 with the checkbox's cell ending at 153, so the layout's own
        # 8 px never appears and the combo's border touches the label. The
        # same host with a QLabel or a QPushButton in the checkbox's place
        # measures a clean 8 px, so the stylesheet-styled checkbox is what
        # defeats it — not the width, not the theme, not the window size:
        # it is -1 px at 1200 and at 360, dark and light.
        #
        # Moving the checkbox's 10 px from the widget's ``spacing`` to the
        # indicator's ``margin-right`` changes nothing (also -1 px), and so
        # does raising the layout's spacing — that only widens the cell the
        # checkbox gets, and the combo moves with it. A plain widget in a
        # layout does get the spacing, so the checkbox gets one.
        holder = QWidget(strip)
        holder.setObjectName("TranscribePresetCheckHolder")
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(0)

        self._preset_override_check = QCheckBox(holder)
        bind(self._preset_override_check, "setText", "TranscribeView", "Preset for this file")
        self._preset_override_check.setObjectName("TranscribePresetOverrideCheck")
        bind(
            self._preset_override_check,
            "setToolTip",
            "TranscribeView",
            "Use the chosen preset for the next dictation only, without changing the default.",
        )
        self._preset_override_check.toggled.connect(self._on_profile_override_toggled)
        holder_layout.addWidget(self._preset_override_check)
        layout.addWidget(holder)

        self._preset_combo = QComboBox(strip)
        self._preset_combo.setObjectName("TranscribePresetCombo")
        self._preset_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._preset_combo.currentIndexChanged.connect(
            self._on_preset_combo_changed
        )
        layout.addWidget(self._preset_combo)

        layout.addStretch(1)
        return strip

    def set_profiles(
        self,
        names: List[Tuple[str, str]],
        active_id: str = "",
        override_id: str = "",
    ) -> None:
        """Fill the picker.

        *names* is ``(id, label)`` pairs rather than profile objects,
        because this screen displays names and must not grow a second
        opinion about what a profile is — the registry in
        ``app.llm.profiles`` is the only thing that decides.
        """
        self._suspend_preset_emit = True
        try:
            self._preset_combo.clear()
            for profile_id, label in names:
                self._preset_combo.addItem(label, userData=profile_id)

            live_ids = {pid for pid, _ in names}
            # An override that no longer exists must fall back to the
            # active profile, not to whichever row happens to be first.
            # Measured: with a stale override the combo landed on
            # "Work" while the default was "Letters" — the picker
            # contradicting the thing it is meant to show.
            pinned = bool(override_id) and override_id in live_ids
            wanted = override_id if pinned else active_id
            index = self._preset_combo.findData(wanted)
            self._preset_combo.setCurrentIndex(max(index, 0))

            self._preset_override_check.blockSignals(True)
            self._preset_override_check.setChecked(pinned)
            self._preset_override_check.setEnabled(bool(names))
            self._preset_override_check.blockSignals(False)
            self._preset_combo.setEnabled(bool(names))
            # With one configuration there is nothing to choose between, so the
            # strip stays out of the way.
            several = len(names) > 1
            self._preset_override_check.setVisible(several)
            self._preset_combo.setVisible(several)
        finally:
            self._suspend_preset_emit = False

    def _on_profile_override_toggled(self, checked: bool) -> None:
        if self._suspend_preset_emit:
            return
        if checked:
            current = self._preset_combo.currentData()
            if current:
                self.preset_override_changed.emit(current)
        else:
            self.preset_override_changed.emit("")

    def _on_preset_combo_changed(self, index: int) -> None:
        if self._suspend_preset_emit or index < 0:
            return
        # Choosing a row while the box is unticked is a question about
        # *this* dictation, so it ticks the box rather than quietly
        # doing nothing. The alternative is a dropdown that looks
        # broken: the user picks a row and nothing observable happens.
        if not self._preset_override_check.isChecked():
            self._preset_override_check.setChecked(True)
            return
        current = self._preset_combo.currentData()
        if current:
            self.preset_override_changed.emit(current)

    # ---- States ----
    _STATE_IDLE = "idle"
    _STATE_BUSY = "busy"
    _STATE_DONE = "done"
    _STATE_ERROR = "error"

    def __init__(
        self,
        start_hotkey: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TranscribeView")
        # Set while ``set_profiles`` rewrites the picker, so filling it
        # is not read as the user changing their mind.
        self._suspend_preset_emit = False
        # Top-level layout: header, source zone, identity + actions,
        # status, transcript. 28/22, the frame every other view uses.
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(16)

        self._header = PageHeader("", "", self)
        bind(self._header, "set_title", "TranscribeView", "Transcribe")
        bind(
            self._header,
            "set_subtitle",
            "TranscribeView",
            "Turn an audio or video file into text you can edit.",
        )
        root.addWidget(self._header)

        # The drop zone is a QFrame (so the dashed border applies to
        # the whole region) wrapping a two-page stack: an invitation
        # while nothing is loaded, a one-line identity of the file once
        # something is.  Same widget, same dashed border, same drag
        # behaviour — it just stops shouting once it has done its job.
        self._drop_zone = QFrame(self)
        self._drop_zone.setObjectName("TranscribeDropZone")
        self._drop_zone.setProperty("dropState", "idle")
        drop_layout = QVBoxLayout(self._drop_zone)
        drop_layout.setContentsMargins(24, 18, 24, 18)
        drop_layout.setSpacing(8)
        self._source_stack = QStackedWidget(self._drop_zone)
        self._source_stack.setObjectName("TranscribeSourceStack")
        drop_layout.addWidget(self._source_stack)

        # Page 0 — the invitation.
        invite = QWidget(self._source_stack)
        invite.setObjectName("TranscribeSourcePage")
        invite_layout = QVBoxLayout(invite)
        invite_layout.setContentsMargins(0, 0, 0, 0)
        invite_layout.setSpacing(8)
        invite_layout.addStretch(1)
        prompt = QLabel("", invite)
        bind(prompt, "setText", "TranscribeView", "Drop an audio or video file here")
        prompt.setObjectName("TranscribeDropPrompt")
        prompt.setAlignment(Qt.AlignCenter)
        invite_layout.addWidget(prompt)
        formats_hint = QLabel(
            # Concrete names, not a count and not a taxonomy.
            #
            # It first carried "— 24 of them", which answered a question
            # nobody asked: the user has one file in mind and is not
            # choosing between 24 formats. Dropping the count left
            # "Audio, lossless and video containers", which was worse —
            # it restated the prompt one line above it, and did not
            # describe the three buckets it appeared to name. "lossless"
            # is not a container, and .wav / .flac / .aiff are already
            # audio, so the list was muddy as well as redundant.
            #
            # What the line is actually for is the question people bring
            # to a drop zone: "will *my* file work?"  A count cannot
            # answer that; five real names can. The full list stays one
            # hover away on the tooltip below.
            ", ".join(_DROP_FORMAT_EXAMPLES),
            invite,
        )
        formats_hint.setObjectName("TranscribeDropFormats")
        formats_hint.setAlignment(Qt.AlignCenter)
        invite_layout.addWidget(formats_hint)
        invite_layout.addStretch(1)
        # The full extension list is still reachable, but it no longer
        # costs a permanent line of screen to advertise itself.  It was
        # sixteen names wrapped across two rows, sitting above the thing
        # you actually came to read.
        formats = ", ".join(ext.lstrip(".").upper() for ext in _AUDIO_EXTS)
        bind(prompt, "setToolTip", "TranscribeView", "Supported: %1", formats)
        bind(formats_hint, "setToolTip", "TranscribeView", "Supported: %1", formats)
        self._source_stack.addWidget(invite)

        # Page 1 — the file, named.
        loaded = QWidget(self._source_stack)
        loaded.setObjectName("TranscribeSourcePage")
        loaded_layout = QVBoxLayout(loaded)
        loaded_layout.setContentsMargins(0, 0, 0, 0)
        self._file_name_label = QLabel("", loaded)
        self._file_name_label.setObjectName("TranscribeFileName")
        loaded_layout.addWidget(self._file_name_label)
        self._file_meta_label = QLabel("", loaded)
        self._file_meta_label.setObjectName("TranscribeFileMeta")
        loaded_layout.addWidget(self._file_meta_label)
        self._source_stack.addWidget(loaded)

        # AcceptDrops on the parent widget; the QFrame is just a
        # visual cue (it doesn't have its own dragEnterEvent).
        self.setAcceptDrops(True)

        # One identity surface, not two. The collapsed zone names the
        # file and the stats under it; a separate line repeating the
        # name 20px below it was the same fact twice, which reads as a
        # mistake even when both copies are correct. The row beneath
        # holds only the actions, which act on the transcript.
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addStretch(1)

        # Browse is this view's one primary action while it is empty.
        self._browse_btn = QPushButton(self)
        bind(self._browse_btn, "setText", "TranscribeView", "Browse…")
        self._browse_btn.setObjectName("TranscribeBrowseButton")
        self._browse_btn.setProperty("role", "primary")
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        self._header.set_action(self._browse_btn)

        # Copy takes over as primary once there is text: the whole job
        # of this screen is to hand you the text, so when the text
        # exists that button is the one worth looking at.  Save stays
        # secondary — it is the rarer intent.
        self._copy_btn = QPushButton(self)
        bind(self._copy_btn, "setText", "TranscribeView", "Copy")
        self._copy_btn.setObjectName("TranscribeCopyButton")
        self._copy_btn.setProperty("role", "primary")
        self._copy_btn.setVisible(False)
        self._copy_btn.clicked.connect(self._on_copy_clicked)

        self._save_btn = QPushButton(self)
        bind(self._save_btn, "setText", "TranscribeView", "Save .txt")
        self._save_btn.setObjectName("TranscribeSaveButton")
        self._save_btn.setVisible(False)
        self._save_btn.clicked.connect(self._on_save_clicked)

        bar.addWidget(self._copy_btn)
        bar.addWidget(self._save_btn)
        bar.addWidget(self._build_profile_strip())
        root.addWidget(self._drop_zone)
        root.addLayout(bar)

        # A separate, transient line for anything that is not the
        # identity: failures, an empty result, and the courtesy note
        # after Copy.  It used to be the same label the identity lived
        # in, so saying "Copied" overwrote the only record of which
        # file you were looking at.
        self._status_label = QLabel("", self)
        self._status_label.setObjectName("TranscribeStatus")
        self._status_label.setVisible(False)
        self._status_flush = QTimer(self)
        self._status_flush.setSingleShot(True)
        self._status_flush.setInterval(_STATUS_FLUSH_MS)
        self._status_flush.timeout.connect(self._dismiss_status)

        self._transcript = QPlainTextEdit(self)
        self._transcript.setObjectName("TranscribeOutput")
        # Editable, and editable on purpose.  This app's entire premise
        # is that the text ends up in someone else's document; making
        # them leave to fix a single misheard word costs the feature its
        # point.  ``_baseline`` is what the model actually returned, so
        # "edited" is a fact we can show rather than guess at.
        self._baseline = ""
        self._transcript.setReadOnly(True)
        self._transcript.textChanged.connect(self._on_text_changed)

        # Per-pixel scrolling and a sane wheel step — no animation, the
        # platform drives the wheel.
        from app.gui.smooth_scroll import apply_smooth_scroll
        apply_smooth_scroll(self._transcript)

        # The transcript is a surface that is empty most of the time, so
        # its empty state is not a placeholder string painted into a
        # text box — that told the user nothing they could act on. This
        # says what is missing, how to get it, and carries the hotkey
        # as a key cap rather than as another sentence.
        self._transcript_stack = QStackedWidget(self)
        self._transcript_stack.addWidget(self._transcript)

        self._transcript_empty = EmptyState(
            "",
            "",
            parent=self._transcript_stack,
        )
        bind(self._transcript_empty.title_label, "setText", "TranscribeView", "No transcript yet")
        bind(
            self._transcript_empty.hint_label,
            "setText",
            "TranscribeView",
            "The text appears here once you drop a file, ready to edit.",
        )
        self._transcript_empty.hint_label.setVisible(True)
        # No hotkey cap on this screen, and that is the change.
        #
        # The cap answered "which key?" and the sentence around it had
        # to explain where the key's text goes, because this view is fed
        # by file drops alone — ``set_result`` is only reached through
        # the ``current_file() == path`` guard in ``_TranscribeMixin``.
        # Dictated words go to the focused app, the clipboard and
        # History; they never appear in this box.
        #
        # So the pair was defending a key that has no business on a
        # file-transcription screen: the honest answer to "no transcript
        # yet" here is a file, not a hotkey. It used to read "press the
        # start hotkey and speak", promising that the words would show
        # up sixty pixels under a drop zone saying something else. The
        # repair was to admit where dictation goes; the better repair is
        # to stop mentioning it. The History view keeps its cap, because
        # a dictation *is* what lands there.
        #
        # ``start_hotkey`` is still accepted and still stored — Settings
        # owns the binding, and ``set_start_hotkey`` keeps working — it
        # simply has nothing to paint on this view.
        self._start_hotkey = start_hotkey or default_start_hotkey()
        self._kbd_cap = None
        self._transcript_stack.addWidget(self._transcript_empty)
        self._transcript_stack.setCurrentWidget(self._transcript_empty)

        root.addWidget(self._status_label)
        root.addWidget(self._transcript_stack, 1)

        self._current_path: Optional[str] = None
        self._started_at: float = 0.0
        self._set_state(self._STATE_IDLE)
        self._show_source("invite")

    # ---- public API ----------------------------------------------------------

    def current_file(self) -> Optional[str]:
        return self._current_path

    def transcript(self) -> str:
        return self._transcript.toPlainText()

    def _show_transcript(self, has_content: bool) -> None:
        """Swap between the reading surface and its empty state.

        Driven by whether there is anything to read, not by the
        processing state: mid-transcription the box is still empty but
        the status line is already explaining why, so the empty state's
        "press the hotkey" would be answering a question nobody asked.
        """
        self._transcript_stack.setCurrentWidget(
            self._transcript if has_content else self._transcript_empty
        )

    # ---- status / identity ---------------------------------------------------

    def _set_status(
        self,
        text: str,
        kind: str = "info",
        *,
        sticky: bool = False,
    ) -> None:
        """Write the transient status line — and actually let the colour
        change.

        A dynamic property does not restyle a widget by itself; Qt needs
        the unpolish/polish pair.  Without it this label rendered every
        state in the same muted grey, which is why an error looked like
        a caption: four rules in the QSS ([status="busy"/"done"/
        "warning"/"error"]) and not one of them had ever fired.  The
        drop zone below already knew this trick — see
        ``_reapply_drop_style``.
        """
        self._status_flush.stop()
        if not text:
            self._dismiss_status()
            return
        self._status_label.setText(text)
        self._status_label.setProperty("status", kind)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)
        self._status_label.setVisible(True)
        if not sticky:
            self._status_flush.start()

    def _dismiss_status(self) -> None:
        """Take the transient line away — and clear the state it wore.

        Hiding the label alone left ``property("status")`` claiming the
        last kind it was given, so after a successful transcription the
        property said ``busy`` while the view's own state was ``done``
        and nothing was on screen. Invisible, so nothing painted wrong —
        but ``test_each_status_kind_is_a_distinct_property`` reads that
        property, and anything else reading it was being told a state
        that was not true. ``_set_status`` re-sets and re-polishes the
        property on every show, so no polish pair is needed here.
        """
        self._status_label.setVisible(False)
        self._status_label.setProperty("status", None)

    def _show_source(self, page: str) -> None:
        """Invite while empty, file identity once loaded.

        The zone keeps its dashed border and its drag surface in both
        states — it is still where you drop the next file — it just
        stops reserving 120px of screen for a prompt that has already
        been answered.
        """
        idx = 0 if page == "invite" else 1
        self._source_stack.setCurrentIndex(idx)
        if idx == 0:
            self._drop_zone.setMinimumHeight(120)
        else:
            # Let the strip size to its own two lines. A fixed minimum
            # here is what kept the zone from ever yielding the screen.
            self._drop_zone.setMinimumHeight(0)
            self._drop_zone.setMaximumHeight(
                self._source_stack.sizeHint().height()
                + self._drop_zone.layout().contentsMargins().top()
                + self._drop_zone.layout().contentsMargins().bottom()
            )

    def _set_actions(self, visible: bool) -> None:
        """Copy and Save appear with the text instead of sitting greyed
        out before it.  A disabled control is a promise about a future
        state; a hidden one is honest about the present."""
        self._copy_btn.setVisible(visible)
        self._save_btn.setVisible(visible)
        # Only one accent-filled control at a time. Browse owns the
        # header while there is nothing to take away; Copy is the more
        # useful of the two once there is.
        self._browse_btn.setProperty("role", "secondary" if visible else "primary")
        self._browse_btn.style().unpolish(self._browse_btn)
        self._browse_btn.style().polish(self._browse_btn)

    def _set_file_line(self, detail: str) -> None:
        """Write the second line of the collapsed zone.

        The filename is on the line above it; this carries the facts
        that make it worth knowing which file you are looking at.
        """
        self._file_meta_label.setText(detail)

    def _describe_file(self) -> str:
        """``34 KB · 1.2 s · 218 words`` — size, how long it took, and
        how much came back.  Audio duration is deliberately absent: the
        decode happens on the worker thread and the backend's contract
        is a string back, so any number here would be a guess.  File
        size and elapsed time are measured, and the word count is
        counted.
        """
        if not self._current_path:
            return ""
        parts = []
        try:
            parts.append(_format_size(Path(self._current_path).stat().st_size))
        except OSError:
            pass
        if self._started_at:
            parts.append(_format_elapsed(time.monotonic() - self._started_at))
        words = len(self._transcript.toPlainText().split())
        if words:
            # A 1-word transcript is a real case here: a dropped clip that
            # only caught a stray syllable.
            parts.append(
                tr_count(
                    "TranscribeView",
                    words,
                    one="%1 word",
                    few="%1 words (few)",
                    many="%1 words",
                )
            )
        if self._is_edited():
            # The field is editable on purpose, so this is the honest
            # note: what you are reading is no longer exactly what the
            # model returned.
            parts.append(tr_text("TranscribeView", "Edited"))
        return "  ·  ".join(parts)

    def _is_edited(self) -> bool:
        return self._transcript.toPlainText() != self._baseline

    def _refresh_file_line(self) -> None:
        """Recompute the zone's detail line from current state."""
        if self._current_path:
            self._file_name_label.setText(Path(self._current_path).name)
        self._set_file_line(self._describe_file())

    def _on_text_changed(self) -> None:
        """Keep the identity honest while the user edits.

        The word count has to move with the caret or the line starts
        lying, and "Edited" has to appear the moment they touch
        anything.
        """
        if self._state == self._STATE_DONE and self._current_path:
            self._refresh_file_line()

    def set_busy(self, file_path: str) -> None:
        """Controller calls this when transcription starts."""
        self._current_path = file_path
        self._started_at = time.monotonic()
        self._baseline = ""
        self._transcript.setReadOnly(True)
        self._transcript.clear()
        self._set_actions(False)
        self._browse_btn.setEnabled(False)
        self._show_source("loaded")
        self._file_name_label.setText(Path(file_path).name)
        size = ""
        try:
            size = _format_size(Path(file_path).stat().st_size)
        except OSError:
            pass
        self._set_file_line(
            "  ·  ".join(p for p in (tr_text("TranscribeView", "Transcribing…"), size) if p)
        )
        self._set_status(tr_text("TranscribeView", "Working. The window stays usable."), "busy")
        self._set_state(self._STATE_BUSY)

    def set_start_hotkey(self, value: str) -> None:
        """Record the user's binding. Nothing on this view paints it.

        Still called on build and again whenever Settings saves or resets
        the hotkeys, so the view's copy of the binding cannot drift out
        of step with the one the rest of the app uses.

        It used to point a key cap at that binding. The cap is gone —
        this screen is about files, and dictation has nothing to say
        here — so there is no widget to update, and no branch guarding
        one: a condition that cannot be false is not a guard.
        """
        value = str(value or "").strip() or default_start_hotkey()
        if value == self._start_hotkey:
            return
        self._start_hotkey = value

    def set_result(self, text: str) -> None:
        """Controller calls this when transcription succeeds."""
        self._baseline = text or ""
        self._transcript.setReadOnly(False)
        self._transcript.setPlainText(text or "")
        has_text = bool(text and text.strip())
        self._show_transcript(True)
        self._set_actions(has_text)
        self._browse_btn.setEnabled(True)
        self._refresh_file_line()
        if has_text:
            self._set_status("")
        else:
            self._set_file_line(tr_text("TranscribeView", "No speech recognised in that file."))
            self._set_status(
                tr_text(
                    "TranscribeView",
                    "The model heard nothing. If the file has audio, try another model. A smaller one often helps.",
                ),
                "warning",
                sticky=True,
            )
        self._set_state(self._STATE_DONE)

    def set_error(self, message: str) -> None:
        """Controller calls this when transcription fails."""
        self._baseline = ""
        self._transcript.setReadOnly(True)
        self._transcript.clear()
        self._show_transcript(False)
        self._set_actions(False)
        self._browse_btn.setEnabled(True)
        if self._current_path:
            self._file_name_label.setText(Path(self._current_path).name)
            self._set_file_line(tr_text("TranscribeView", "Failed"))
        self._set_status(
            tr_format("TranscribeView", "Error: %1", message), "error", sticky=True
        )
        self._set_state(self._STATE_ERROR)

    # ---- Qt drag-drop --------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._state == self._STATE_BUSY:
            event.ignore()
            return
        mime: QMimeData = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        # Accept if at least one local URL is an audio file by extension.
        for url in mime.urls():
            if url.isLocalFile() and _looks_like_audio(url.toLocalFile()):
                event.acceptProposedAction()
                self._drop_zone.setProperty("dropState", "active")
                self._reapply_drop_style()
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drop_zone.setProperty("dropState", "idle")
        self._reapply_drop_style()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._drop_zone.setProperty("dropState", "idle")
        self._reapply_drop_style()
        if self._state == self._STATE_BUSY:
            event.ignore()
            return
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if _looks_like_audio(path):
                event.acceptProposedAction()
                self.file_dropped.emit(path)
                return
        event.ignore()

    # ---- internal ------------------------------------------------------------

    def _reapply_drop_style(self) -> None:
        """Force a stylesheet recalculation for the drop zone after a
        property change.  Without this Qt won't notice the
        ``dropState`` flip during drag-enter/leave events."""
        self._drop_zone.style().unpolish(self._drop_zone)
        self._drop_zone.style().polish(self._drop_zone)
        self._drop_zone.update()

    def _on_browse_clicked(self) -> None:
        if self._state == self._STATE_BUSY:
            return
        # Build a filter string from the recognised extensions.
        glob = " ".join(f"*{ext}" for ext in _AUDIO_EXTS)
        path, _selected = QFileDialog.getOpenFileName(
            self,
            tr_text("TranscribeView", "Choose an audio or video file"),
            "",
            tr_format("TranscribeView", "Audio / video (%1);;All files (*.*)", glob),
        )
        if path:
            self.file_dropped.emit(path)

    def _on_copy_clicked(self) -> None:
        from PySide6.QtWidgets import QApplication

        text = self.transcript()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.copy_requested.emit()
        self._set_status(tr_text("TranscribeView", "Copied to clipboard."), "done")

    def _on_save_clicked(self) -> None:
        text = self.transcript()
        if not text:
            return
        suggested_dir = ""
        suggested_name = "transcript.txt"
        if self._current_path:
            stem = Path(self._current_path).stem
            suggested_name = f"{stem}.txt"
            suggested_dir = str(Path(self._current_path).parent)
        suggested = (
            os.path.join(suggested_dir, suggested_name)
            if suggested_dir
            else suggested_name
        )
        path, _selected = QFileDialog.getSaveFileName(
            self,
            tr_text("TranscribeView", "Save transcript"),
            suggested,
            tr_text("TranscribeView", "Text (*.txt);;All files (*.*)"),
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as exc:
            self._set_status(
                tr_format("TranscribeView", "Save failed: %1", exc), "error", sticky=True
            )
            return
        self.save_requested.emit(path)
        self._set_status(tr_format("TranscribeView", "Saved: %1", path), "done")

    def _set_state(self, state: str) -> None:
        self._state = state
