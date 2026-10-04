"""Card widget that displays a single model entry."""

from __future__ import annotations

import base64
import os
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.focus import release_focus_before
from app.gui.widgets.elided_label import ElidedLabel
from app.gui.theme import TOKENS, resolve_icon_svg


def _external_link_icon_data_uri() -> str:
    """``external-link`` icon as a data URI for QLabel rich text.

    A file:// URL would work too, but QLabel's QTextDocument resolves
    relative image sources against its own baseUrl, which is the process
    working directory — different in a dev checkout, a py2app bundle and
    a PyInstaller folder. Inlining the SVG removes that dependency
    entirely, and it is 310 bytes to begin with.

    The stroke is resolved from ``accent_hover`` — the same token the
    link text next to it uses — so the glyph and the label cannot drift
    apart, and so neither is left holding a colour from a palette the
    app no longer ships.
    """
    svg = resolve_icon_svg("arrow-top-right-on-square.svg", "accent_hover")
    if svg is None:
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(
        svg.encode("utf-8")
    ).decode("ascii")


def _has_hf_token() -> bool:
    """True if either ``HF_TOKEN`` or its legacy alias
    ``HUGGING_FACE_HUB_TOKEN`` is set to a non-empty value."""
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = os.environ.get(name)
        if value and value.strip():
            return True
    return False

from app.gui.widgets.flow_layout import FlowLayout
from app.gui.widgets.inference_settings_panel import InferenceSettingsPanel
from app.gui.widgets.parakeet_inference_settings_panel import (
    ParakeetInferenceSettingsPanel,
)
from app.inference_settings import InferenceSettings, ParakeetInferenceSettings
from app.model_mapping import ModelInfo, model_url


class _CacheWorkerSignals(QObject):
    """Signals carrier for ``_CacheCheckWorker``.

    ``QRunnable`` cannot itself hold signals (it doesn't inherit
    ``QObject``), so the canonical PySide6 pattern is a tiny
    ``QObject`` companion created on the main thread — Qt then
    routes the emitted signal back via a queued connection.

    The ``request_id`` int travels with the boolean result so
    ``_apply_cache_result`` can discard stale responses from workers
    that were superseded by a later ``refresh_cache_state()`` call.
    """

    result = Signal(bool, int)  # (cached, request_id)


class _CacheCheckWorker(QRunnable):
    """Run ``is_cached_for_info`` in a thread-pool thread.

    Emits ``signals.result`` with the boolean outcome and the
    originating ``request_id`` so the card can ignore results that
    arrived out-of-order (an older worker finishing after a newer one).
    """

    def __init__(self, info: ModelInfo, request_id: int) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._info = info
        self._request_id = request_id
        self.signals = _CacheWorkerSignals()

    def run(self) -> None:  # called by QThreadPool on a worker thread
        from app.utils import is_cached_for_info  # lazy — gets patched version in tests

        cached = is_cached_for_info(self._info)
        self.signals.result.emit(cached, self._request_id)


def _format_size(size_mb: int) -> str:
    if size_mb >= 1000:
        return f"{size_mb / 1000:.1f} GB"
    return f"{size_mb} MB"


def _format_bytes(num_bytes: int) -> str:
    """Compact byte counter used inside the loading pill."""
    if num_bytes <= 0:
        return ""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def _format_loading_progress(current: int, total: int) -> str:
    """Pill label for the active card while a model is downloading.

    Returns an empty string when neither bytes nor totals are known —
    the caller falls back to the default 'Loading…' marker.
    """
    if total > 0 and current >= 0:
        pct = int(min(99, max(0, current * 100 // total)))
        return f"Loading {pct}%"
    if current > 0:
        return f"Loading {_format_bytes(current)}"
    return ""


def _compute_label(compute_type: str) -> str:
    """Pretty short label for the ``compute_type`` badge."""
    return {
        "float32": "fp32",
        "float16": "fp16",
        "int8_float16": "int8 + fp16",
        "int8": "int8",
    }.get(compute_type, compute_type)


class ModelCard(QFrame):
    select_requested = Signal(str)
    # Emitted when the user clicks Delete on a cached model — arg is
    # the alias. The controller is responsible for confirming with
    # the user before actually wiping the cache, then calling
    # ``refresh_cache_state`` so the button visibility and label
    # update.
    delete_requested = Signal(str)
    # Emitted when the user changes anything in the inline inference
    # settings panel. Args: ``(alias, settings_object)``. The settings
    # object is either ``InferenceSettings`` (faster-whisper cards)
    # or ``ParakeetInferenceSettings`` (NeMo cards) — controller dispatches
    # on the alias's backend kind. Declared as ``object`` because
    # PySide signals can't express a sum type and the consumer only
    # uses duck-typed ``.to_mapping()``.
    inference_settings_changed = Signal(str, object)

    def __init__(self, info: ModelInfo, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._info = info
        self._active = False
        self._locked = False
        self._loading = False
        self._delete_busy = False
        # Pill-text inputs — both reset on every loading transition.
        # ``_loading_progress_text`` wins when present (download %),
        # ``_loading_elapsed_s`` is the fallback for cached loads.
        self._loading_progress_text: str = ""
        self._loading_elapsed_s: int = 0
        # Last result from the async cache check.  None = check not yet
        # complete; False = not cached; True = cached on disk.
        self._cached: Optional[bool] = None
        # Monotonically increasing counter: bumped on every
        # refresh_cache_state() call.  Workers embed this id at
        # dispatch time; _apply_cache_result silently drops any
        # result whose id doesn't match the current value (stale
        # worker from a superseded request).
        self._cache_request_id: int = 0

        self.setObjectName("ModelCard")
        self.setProperty("role", "card")
        self.setProperty("active", False)
        self.setFrameShape(QFrame.NoFrame)
        # The card is its own tab stop. It is where focus lands when the
        # Download button hides out from under the user (see
        # ``set_active``), and it gives a screen reader one node per
        # model instead of a loose pile of badges and buttons.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(self._info.display_name)
        self.setAccessibleDescription(
            f"{self._info.family}. {self._info.description}"
        )
        # Variable vertical size — badges wrap onto a second line on
        # narrow windows, so the card has to grow to fit them.
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

        # Soft drop shadow makes the card "float" off the dark surface
        # — Qt QSS has no box-shadow so this is the only way to add
        # depth. Keep blur generous and offset small so the effect is
        # subtle, not theatrical.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 100))
        self.setGraphicsEffect(shadow)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)

        # The family used to head this row as its own coloured pill
        # ("WHISPER TURBO" beside "Whisper Large v3 Turbo"). It is gone
        # because it repeated the title in all nine shipped models, and
        # a badge that repeats the thing it labels is furniture. The
        # card went from seven pills to four, and the header from two
        # competing ink weights to one.
        #
        # Grouping is not lost — it is the filter row's job, which
        # lists every family and is the only place the grouping can
        # actually do something. The family still reaches screen
        # readers through ``setAccessibleDescription`` above.
        #
        # Elides rather than widening the card. A plain QLabel reports
        # its full text as a minimum width, so one long display name
        # pushed the whole card — and the Download button on it — past
        # the right edge of a narrow window. The stretch that used to
        # sit here is replaced by the title's own stretch factor, so the
        # Active pill stays pinned to the right exactly as before.
        title = ElidedLabel(info.display_name, self)
        title.setProperty("role", "heading")
        header.addWidget(title, 1)

        self._active_pill = QLabel("Active", self)
        self._active_pill.setProperty("role", "pill-active")
        self._active_pill.setProperty("state", "ready")
        self._active_pill.setAlignment(Qt.AlignCenter)
        self._active_pill.setVisible(False)
        header.addWidget(self._active_pill)

        root.addLayout(header)

        # Subtitle line: alias · canonical · external-link affordance.
        # ``QLabel`` with ``openExternalLinks`` is the cheapest way to
        # get a clickable URL inside the card without a button.
        #
        # The affordance used to be a bare ``↗`` (U+2197). A Unicode
        # glyph standing in for an icon is off-system — the rest of the
        # UI is one bundled Heroicons set — and it announces as "north
        # east arrow" to a screen reader, which says nothing about the
        # action. It is a real SVG from ``styles/icons/`` now, and the
        # label carries a sentence in its accessible name.
        external_icon = _external_link_icon_data_uri()
        link_glyph = (
            f'<img src="{external_icon}" width="12" height="12"/>'
            if external_icon
            # Last-resort fallback if the SVG cannot be resolved: keep
            # the link clickable rather than dropping it.
            else "&#8599;"
        )
        # Rich text cannot be styled by the app stylesheet, so these
        # three spans carry their colour inline — resolved from TOKENS
        # rather than written out, so the subtitle cannot drift away
        # from the accent and muted inks the rest of the app uses.
        _c = TOKENS.colors
        subtitle = QLabel(
            f'<span style="color:{_c["accent_hover"]}">{info.alias}</span>'
            f'<span style="color:{_c["text_muted"]}">  ·  </span>'
            f'<span style="color:{_c["text_secondary"]}">{info.canonical}</span>'
            f'  <a href="{model_url(info)}" '
            f'style="color:{_c["accent_hover"]};text-decoration:none">'
            f"{link_glyph}</a>",
            self,
        )
        subtitle.setObjectName("ModelSubtitle")
        subtitle.setProperty("role", "muted")
        subtitle.setOpenExternalLinks(True)
        subtitle.setTextFormat(Qt.RichText)
        subtitle.setTextInteractionFlags(
            Qt.TextBrowserInteraction
        )
        # A canonical id is one unbroken token, so it needs the whole
        # card rather than a share of it. ``wordWrap`` breaks it (the
        # card is already ``heightForWidth``, and its badge row already
        # wraps), and the explicit zero minimum stops the layout from
        # reserving room for the longest unbreakable run. The link
        # stays inline in the rich text and wraps with the line.
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        subtitle.setToolTip(f"Open {model_url(info)}")
        # The whole label — alias, canonical id and the link — is one
        # accessibility node, so the name states what activating the
        # link actually does instead of leaving it to the glyph.
        subtitle.setAccessibleName(
            f"{info.alias}, {info.canonical}. "
            f"Link opens {model_url(info)} in your browser."
        )
        root.addWidget(subtitle)

        description = QLabel(info.description, self)
        description.setProperty("role", "muted")
        description.setWordWrap(True)
        root.addWidget(description)

        # FlowLayout wraps badges to a new line when the card is too
        # narrow to fit them all in one row — without this, narrow
        # windows clipped the right side of the card (and the
        # Download button) at the scroll viewport's edge.
        badges = FlowLayout(spacing=6)
        # Each badge carries a ``cat`` property (and ``value`` where
        # the value is one of a known set) so the QSS can give the two
        # categories distinct visual weights:
        #   - speed / quality → tinted (green / blue) when the value
        #     is the desirable one ("fast", "excellent")
        #   - size / vram → solid neutral pills (current default)
        #
        # Four, down from six, and the two that went were measured
        # against the nine shipped models rather than picked by taste:
        #
        # - ``lang`` repeated the model name. "GigaAM v3 CTC (Russian,
        #   punctuated)", "Parakeet TDT v3 (multilingual)" and
        #   "T-One (Russian, telephony-tuned)" already say it, and for
        #   a Russian-first product that is exactly the fact a reader
        #   is scanning the name for.
        # - ``compute`` is float16 on eight of the nine. A badge that
        #   reads the same on every card is furniture, and the one
        #   exception (Parakeet, float32) is a backend detail the
        #   inference panel already owns.
        #
        # What is left is what a choice actually turns on — how fast,
        # how accurate, how big to download, how much GPU it wants —
        # which is the same trade the view's own purpose line names.
        badge_specs = (
            ("speed", info.speed, info.speed),
            ("quality", info.quality, info.quality),
            ("size", _format_size(info.size_mb), ""),
            ("vram", f"{info.vram_gb:.1f} GB", ""),
        )
        for cat, display_value, qss_value in badge_specs:
            badge = QLabel(f"{cat}: {display_value}", self)
            badge.setProperty("role", "badge")
            badge.setProperty("cat", cat)
            if qss_value:
                badge.setProperty("value", qss_value)
            badges.addWidget(badge)
        root.addLayout(badges)

        # Inline inference settings — choice of panel keyed on
        # onnx_family:
        #   - ``whisper``: full Whisper panel (language, beam,
        #     temperature, …). Some knobs (beam) don't translate to
        #     the onnx-asr Whisper path but the panel stays useful
        #     for language selection.
        #   - ``parakeet``: minimal panel (timestamps toggle — the
        #     only inference-time tunable onnx-asr exposes for Parakeet).
        #   - ``gigaam``: no panel; e2e model with no per-call knobs.
        self._settings_panel: Optional[QWidget] = None
        onnx_family = getattr(info, "onnx_family", "auto")
        if onnx_family == "whisper":
            self._settings_panel = InferenceSettingsPanel(self)
        elif onnx_family == "parakeet":
            self._settings_panel = ParakeetInferenceSettingsPanel(self)
        if self._settings_panel is not None:
            self._settings_panel.setVisible(False)
            self._settings_panel.settings_changed.connect(
                lambda s: self.inference_settings_changed.emit(
                    self._info.alias, s
                )
            )
            root.addWidget(self._settings_panel)

        # HF-token warning is no longer needed: the legacy GigaAM-Python
        # path used pyannote VAD (gated weights) for long audio.  ONNX
        # GigaAM has its own internal segmentation, no token required.
        self._hf_warning: Optional[QLabel] = None

        footer = QHBoxLayout()
        footer.addStretch(1)
        # Delete sits to the LEFT of Select — destructive action stays
        # visually subordinate to the primary one. Hidden by default;
        # visibility is recomputed every time the cache / active /
        # loading state changes (see ``_refresh_delete_visibility``).
        self._delete_btn = QPushButton("Delete", self)
        self._delete_btn.setObjectName("DeleteButton")
        self._delete_btn.setProperty("role", "danger")
        self._delete_btn.setVisible(False)
        self._delete_btn.clicked.connect(
            lambda: self.delete_requested.emit(self._info.alias)
        )
        footer.addWidget(self._delete_btn)

        self._select_btn = QPushButton("Download", self)
        self._select_btn.setObjectName("SelectButton")
        self._select_btn.setProperty("role", "primary")
        # Stays focusable. It used to carry ``Qt.NoFocus`` because
        # clicking it focused the button, and the card immediately
        # turned Active and hid the button — Qt then chased focus to
        # the *next card's* Download button and the QScrollArea
        # scrolled down to it, jumping the whole list. The fix is not
        # to remove the button from the tab chain but to move focus off
        # it ourselves, before hiding it (see ``_set_select_button``).
        self._select_btn.clicked.connect(
            lambda: self.select_requested.emit(self._info.alias)
        )
        footer.addWidget(self._select_btn)
        root.addLayout(footer)

        # Initial Download/Select label based on whether the canonical is
        # already cached on disk. Refreshable via ``refresh_cache_state``.
        self.refresh_cache_state()

    def hasHeightForWidth(self) -> bool:  # type: ignore[override]
        return True

    def heightForWidth(self, width: int) -> int:  # type: ignore[override]
        layout = self.layout()
        if layout is None:
            return -1
        margins = self.contentsMargins()
        inner = width - margins.left() - margins.right()
        return layout.heightForWidth(inner) + margins.top() + margins.bottom()

    def alias(self) -> str:
        return self._info.alias

    def info(self) -> ModelInfo:
        return self._info

    def is_active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        new_active = bool(active)
        if new_active == self._active:
            return  # no state change — skip widget updates and style recalc
        self._active = new_active
        self.setProperty("active", self._active)
        self._active_pill.setVisible(self._active)
        # Hand focus off before the button disappears, or Qt picks the
        # next card's Download button and scrolls the whole list to it.
        # The card itself is the right neighbour: it is where the
        # user's eyes already are, and it stays in the tab chain.
        if self._active:
            release_focus_before(self._select_btn, self)
        self._select_btn.setVisible(not self._active)
        self._select_btn.setEnabled(not self._active and not self._locked)
        # Inference panel visible only on the active card (and only
        # on cards that actually have one — GigaAM doesn't).
        if self._settings_panel is not None:
            self._settings_panel.setVisible(self._active)
        self._refresh_delete_visibility()
        self.style().unpolish(self)
        self.style().polish(self)

    def set_inference_settings(self, settings) -> None:
        """Pre-fill the inline panel from the controller (called when
        the card becomes active and the controller has loaded the
        per-alias overrides out of config). No-op on engines that
        don't have a panel (GigaAM). ``settings`` is the dataclass
        appropriate for this card's backend (Whisper /
        NeMo) — caller is responsible for sending the right type."""
        if self._settings_panel is not None:
            self._settings_panel.set_settings(settings)

    def inference_settings(self):
        """Return the panel's current values (``InferenceSettings``
        for Whisper, ``ParakeetInferenceSettings`` for NeMo) or ``None``
        on cards that don't have a panel."""
        if self._settings_panel is None:
            return None
        return self._settings_panel.values()

    def set_locked(self, locked: bool) -> None:
        new_locked = bool(locked)
        if new_locked == self._locked:
            return
        self._locked = new_locked
        # Active cards keep Select hidden regardless; for inactive ones,
        # locking disables the button.
        if not self._active:
            if self._locked:
                release_focus_before(self._select_btn, self)
            self._select_btn.setEnabled(not self._locked)

    def is_loading(self) -> bool:
        return self._loading

    def refresh_hf_token_state(self) -> None:
        """Recompute warning visibility from the current process env.
        Called by the controller after the user pastes a token in
        Settings; no-op on cards that don't carry the warning
        (Whisper)."""
        if self._hf_warning is None:
            return
        self._hf_warning.setVisible(not _has_hf_token())

    def refresh_cache_state(self) -> None:
        """Schedule an async disk check for this model.

        Launches a ``_CacheCheckWorker`` on Qt's global thread pool so
        the filesystem walk never blocks the main thread.  Each call
        increments ``_cache_request_id``; workers carry that id and
        ``_apply_cache_result`` discards any result whose id is stale
        (i.e. a slower earlier worker finishing after a faster newer
        one).
        """
        self._cache_request_id += 1
        worker = _CacheCheckWorker(self._info, self._cache_request_id)
        worker.signals.result.connect(self._apply_cache_result)
        QThreadPool.globalInstance().start(worker)

    def _apply_cache_result(self, cached: bool, request_id: int) -> None:
        """Slot — called on the main thread by the queued connection
        when the thread-pool worker has finished its disk check.

        Results from superseded requests (stale workers) are silently
        dropped so they cannot overwrite a more recent cache state.
        """
        if request_id != self._cache_request_id:
            return  # stale — a newer request has already landed
        self._cached = cached
        self._select_btn.setText("Select" if cached else "Download")
        self._refresh_delete_visibility()

    def _refresh_delete_visibility(self) -> None:
        """Update Delete button visibility from the last known cache state.

        Uses ``self._cached`` — set by the async worker — so this method
        never touches the filesystem.  Called from ``_apply_cache_result``,
        ``set_active``, and ``set_loading`` to keep the button in sync
        whenever active/loading state changes.

        Delete is shown only when (a) weights are on disk, (b) the card
        isn't currently the active model, and (c) we aren't mid-load.
        """
        if self._delete_busy:
            release_focus_before(self._delete_btn, self)
            self._delete_btn.setVisible(True)
            self._delete_btn.setEnabled(False)
            self._delete_btn.setText("Deleting…")
            return
        cached = self._cached or False  # None → unknown → treat as not cached
        self._delete_btn.setText("Delete")
        self._delete_btn.setEnabled(not self._locked)
        will_show = cached and not self._active and not self._loading
        if not will_show:
            # Same chase as Select: a hidden Delete button would hand
            # focus to the next card's action and scroll there.
            release_focus_before(self._delete_btn, self)
        self._delete_btn.setVisible(will_show)

    def set_delete_busy(self, busy: bool) -> None:
        self._delete_busy = bool(busy)
        self._refresh_delete_visibility()

    def set_loading(self, loading: bool) -> None:
        """Reflect backend load state on the active pill — swap 'Active' for
        'Loading…' with a different colour while the model is loading."""
        new_loading = bool(loading)
        if new_loading == self._loading:
            return  # no state change \u2014 skip pill update and style recalc
        self._loading = new_loading
        # Reset pill-text inputs only on actual state transitions so a
        # fresh load never inherits stale numbers from a previous one, but
        # repeated set_loading(True) calls don't wipe in-progress text.
        self._loading_progress_text = ""
        self._loading_elapsed_s = 0
        if self._loading:
            self._active_pill.setText("Loading\u2026")
            self._active_pill.setProperty("state", "loading")
        else:
            self._active_pill.setText("Active")
            self._active_pill.setProperty("state", "ready")
        self._active_pill.style().unpolish(self._active_pill)
        self._active_pill.style().polish(self._active_pill)
        self._refresh_delete_visibility()

    def set_loading_progress(self, current: int, total: int) -> None:
        """Update the active pill with download progress while the card
        is in the loading state. Ignored when the card isn't loading so
        stale events arriving after the model finishes can't repaint
        the green Active pill with stale byte counts."""
        if not self._loading:
            return
        self._loading_progress_text = _format_loading_progress(
            int(current), int(total)
        )
        self._refresh_loading_pill()

    def set_loading_elapsed(self, seconds: int) -> None:
        """Update the elapsed-seconds counter shown in the loading pill
        when no byte progress is available — used for cached model
        loads where CTranslate2 deserialises weights silently."""
        if not self._loading:
            return
        self._loading_elapsed_s = max(0, int(seconds))
        # Deliberately no ``_refresh_loading_pill()`` — the pill text
        # only ever changes on real download progress, not on elapsed
        # ticks.  The elapsed counter lives on the topbar pill so the
        # same number doesn't appear in two places at once.

    def _refresh_loading_pill(self) -> None:
        """Recompute the loading pill text from progress + elapsed inputs.

        Order of precedence: download percentage / bytes win over
        elapsed seconds; both win over the static 'Loading…' marker."""
        if not self._loading:
            return
        if self._loading_progress_text:
            self._active_pill.setText(self._loading_progress_text)
        else:
            # No elapsed-seconds branch on the card \u2014 topbar pill
            # owns that display.
            self._active_pill.setText("Loading\u2026")
