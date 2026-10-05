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
from typing import Optional

from PySide6.QtCore import QMimeData, Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
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

from app.config_manager import default_start_hotkey
from app.gui.widgets.empty_state import EmptyState, format_hotkey, hotkey_cap
from app.gui.widgets.page_header import PageHeader


# Audio / video extensions our two-tier decoder can handle.
# ``soundfile`` covers the lossless / OGG family; ``imageio-ffmpeg``
# (the bundled static ffmpeg) covers everything else.  We accept
# common video container extensions too — the audio track is what
# the model cares about, not the codec.
_AUDIO_EXTS: tuple[str, ...] = (
    # libsndfile native
    ".wav", ".flac", ".ogg", ".oga", ".opus", ".aiff", ".aif",
    # ffmpeg fallback — audio
    ".mp3", ".m4a", ".aac", ".wma", ".amr", ".ac3", ".alac",
    # ffmpeg fallback — video containers (we extract the audio track)
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".flv", ".3gp", ".m4v",
    ".wmv", ".ts",
)

# How long a courtesy message ("Copied to clipboard.") stays up before
# the identity line is left alone again.  Long enough to register,
# short enough that it is not the last thing you read.
_STATUS_FLUSH_MS = 4000


def _looks_like_audio(path: str) -> bool:
    return path.lower().endswith(_AUDIO_EXTS)


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


def _plural_words(count: int) -> str:
    """``1 word`` / ``4 words``, because a 1-word transcript is a real
    case here — a dropped clip that only caught a stray syllable."""
    return "word" if count == 1 else "words"


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
        # Top-level layout: header, source zone, identity + actions,
        # status, transcript. 28/22, the frame every other view uses.
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(16)

        self._header = PageHeader(
            "Transcribe",
            "Drop a recording, or press the start hotkey to dictate.",
            self,
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
        prompt = QLabel(
            "Drop an audio or video file here — or click Browse",
            invite,
        )
        prompt.setObjectName("TranscribeDropPrompt")
        prompt.setAlignment(Qt.AlignCenter)
        invite_layout.addWidget(prompt)
        formats_hint = QLabel(
            "Audio, lossless and video containers — 24 of them",
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
        prompt.setToolTip(
            "Supported: "
            + ", ".join(ext.lstrip(".").upper() for ext in _AUDIO_EXTS)
        )
        formats_hint.setToolTip(prompt.toolTip())
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
        self._browse_btn = QPushButton("Browse…", self)
        self._browse_btn.setObjectName("TranscribeBrowseButton")
        self._browse_btn.setProperty("role", "primary")
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        self._header.set_action(self._browse_btn)

        # Copy takes over as primary once there is text: the whole job
        # of this screen is to hand you the text, so when the text
        # exists that button is the one worth looking at.  Save stays
        # secondary — it is the rarer intent.
        self._copy_btn = QPushButton("Copy", self)
        self._copy_btn.setObjectName("TranscribeCopyButton")
        self._copy_btn.setProperty("role", "primary")
        self._copy_btn.setVisible(False)
        self._copy_btn.clicked.connect(self._on_copy_clicked)

        self._save_btn = QPushButton("Save .txt", self)
        self._save_btn.setObjectName("TranscribeSaveButton")
        self._save_btn.setVisible(False)
        self._save_btn.clicked.connect(self._on_save_clicked)

        bar.addWidget(self._copy_btn)
        bar.addWidget(self._save_btn)
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

        # Same cosine-eased wheel animation the other scrollable views
        # use, refresh-aware (60 / 144 / 240 Hz).
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
            "No transcript yet",
            "Drop a file above, or press the start hotkey and speak.",
            parent=self._transcript_stack,
        )
        # The cap names the configured hotkey, not a literal — the
        # shipped default is ``Ctrl+F8`` on macOS, and the user can
        # rebind it in Settings.
        self._start_hotkey = start_hotkey or default_start_hotkey()
        self._kbd_cap = hotkey_cap(self._start_hotkey, self._transcript_empty)
        if self._kbd_cap is not None:
            self._transcript_empty.set_footer(self._kbd_cap)
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
            self._status_label.setVisible(False)
            return
        self._status_label.setText(text)
        self._status_label.setProperty("status", kind)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)
        self._status_label.setVisible(True)
        if not sticky:
            self._status_flush.start()

    def _dismiss_status(self) -> None:
        self._status_label.setVisible(False)

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
            parts.append(f"{words} {_plural_words(words)}")
        if self._is_edited():
            # The field is editable on purpose, so this is the honest
            # note: what you are reading is no longer exactly what the
            # model returned.
            parts.append("Edited")
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
        self._set_file_line("  ·  ".join(p for p in ("Transcribing…", size) if p))
        self._set_status("Working — the window stays usable.", "busy")
        self._set_state(self._STATE_BUSY)

    def set_start_hotkey(self, value: str) -> None:
        """Point the empty state's key cap at the user's actual binding.

        Called when the view is built and again whenever Settings saves
        or resets the hotkeys, so the cap cannot drift into naming a
        shortcut the user no longer holds.
        """
        value = str(value or "").strip() or default_start_hotkey()
        if value == self._start_hotkey:
            return
        self._start_hotkey = value
        if self._kbd_cap is not None:
            self._kbd_cap.setText(format_hotkey(value))

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
            self._set_file_line("No speech recognised in that file.")
            self._set_status(
                "The model heard nothing. If the file has audio in it, "
                "try a different model — a smaller one often helps.",
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
            self._set_file_line("Failed")
        self._set_status(f"Error: {message}", "error", sticky=True)
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
            "Choose an audio or video file",
            "",
            f"Audio / video ({glob});;All files (*.*)",
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
        self._set_status("Copied to clipboard.", "done")

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
            "Save transcript",
            suggested,
            "Text (*.txt);;All files (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as exc:
            self._set_status(f"Save failed: {exc}", "error", sticky=True)
            return
        self.save_requested.emit(path)
        self._set_status(f"Saved: {path}", "done")

    def _set_state(self, state: str) -> None:
        self._state = state
