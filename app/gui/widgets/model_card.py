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
    # Emitted after every async cache check lands. Args:
    # ``(alias, cached)``. The card already needs to know this to label
    # its own button; publishing it means a second consumer — the
    # first-run screen, which has to decide whether a download landed —
    # does not have to re-walk the filesystem on the Qt thread to ask
    # the same question.
    cache_state_changed = Signal(str, bool)
    # Emitted when the card's family chip is pressed. Arg is the family
    # name; the view owns the filter and decides whether this press
    # narrows to the family or clears it, because only the view knows
    # the current filter. The card never filters itself.
    family_filter_toggled = Signal(str)

    def __init__(
        self,
        info: ModelInfo,
        parent: Optional[QWidget] = None,
        *,
        show_pitch: bool = False,
    ) -> None:
        super().__init__(parent)
        self._info = info
        self._show_pitch = show_pitch
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
        # The card is a tab stop only while it is the *active* card —
        # see ``set_active``. An inactive card is a group whose actions
        # are its own children, so a stop on it lands on something that
        # does nothing.
        #
        # It used to be a stop unconditionally, which cost nine
        # dead stops in the Models view: four Tab presses per card to
        # reach two real controls, and 37 to reach the Download button
        # on the last one. The justification was focus landing when the
        # button hides — but that only happens on the active card, so
        # the other eight were paying for a case that cannot arise.
        #
        # The second half of the old claim — that the card gives a
        # screen reader one node per model — does *not* depend on the
        # tab chain. Verified against QAccessible: with ``NoFocus`` the
        # interface is identical (same node, same accessible name, same
        # eleven children); focus policy moves the keyboard cursor, not
        # the accessibility tree. So the node survives this change.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(self._info.display_name)
        self.setAccessibleDescription(
            f"{self._info.family}. {self._info.description}"
        )
        # Variable vertical size — the title, subtitle and description
        # each wrap onto their own lines on a narrow window, so the card
        # has to grow to fit them.
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

        # The family heads this row as a chip, and the chip is a
        # *control*: it filters the view to that family, and clicking it
        # again clears the filter.
        #
        # This chip used to be a dead label — a coloured pill that
        # repeated the card's own title in all nine shipped models, and
        # repeated it in a second ink weight at that — and removing it
        # was right. What was missing is that removing it also removed
        # the only *per-card* handle on filtering, leaving a row of
        # chips parked above the list doing the one job the card could
        # do better: the filter is reachable from the thing it filters.
        #
        # A dead label that repeats the title is furniture. A live
        # control that filters to what the card already is, is not —
        # and it takes the 8-chip filter row out of the chrome, which
        # was 48px of fixed height above the list, wrapping to 755px of
        # chips at text scale 1.75.
        #
        # Styled as ``filter-chip``, the same component the toolbar row
        # used, so it is visibly the same control in a new home. It
        # stays neutral: a family colour would be a family hue, and the
        # app has none.
        self._family_chip = QPushButton(info.family, self)
        self._family_chip.setObjectName("CardFamilyChip")
        self._family_chip.setProperty("role", "filter-chip")
        self._family_chip.setCheckable(True)
        self._family_chip.setCursor(Qt.PointingHandCursor)
        self._family_chip.setToolTip(
            f"Show only {info.family} models"
        )
        # The visible word is the title again, so the name has to say
        # what pressing it does — and say it in the same breath, because
        # the chip is a toggle and "Filter to Whisper" alone would not
        # say how to get back.
        self._family_chip.setAccessibleName(
            f"Filter to {info.family} models. Activate again to show all."
        )
        self._family_chip.clicked.connect(
            lambda: self.family_filter_toggled.emit(info.family)
        )
        header.addWidget(self._family_chip)

        title = ElidedLabel(info.display_name, self)
        title.setProperty("role", "heading")
        header.addWidget(title, 1)

        # "Recommended" is a durable claim about where to start, not a
        # transient state, so it sits on the card everywhere rather than
        # only on the first-run screen — a returning user who walked
        # past the first run still gets told which card the app measured
        # its way to. It is the one card of the sixteen whose heading
        # someone would otherwise have to read to find.
        #
        # Next to ``Active``, never in place of it: one says "this is
        # what we suggest", the other says "this is what is loaded".
        self._recommended_pill = QLabel("Recommended", self)
        self._recommended_pill.setProperty("role", "pill-recommended")
        self._recommended_pill.setAlignment(Qt.AlignCenter)
        self._recommended_pill.setVisible(info.recommended)
        header.addWidget(self._recommended_pill)

        self._active_pill = QLabel("Active", self)
        self._active_pill.setProperty("role", "pill-active")
        self._active_pill.setProperty("state", "ready")
        self._active_pill.setAlignment(Qt.AlignCenter)
        self._active_pill.setVisible(False)
        header.addWidget(self._active_pill)

        root.addLayout(header)

        # Subtitle line: alias, canonical, external-link affordance —
        # separated by space rather than by a middot, for the same
        # reason the spec line is.
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
        # The gap between the two ids is whitespace, not a middot — and
        # it has to be a *non-breaking* space to survive. Measured: with
        # nothing between them the line is 90px; two em spaces, two en
        # spaces and six thin spaces all render at 94px, because Qt's
        # rich-text engine treats them as collapsible whitespace and
        # collapses the run to a single space. Four NBSPs render at
        # 105px, a real 15px gap, and because an NBSP is a font
        # advance the gap grows with the text scale instead of
        # drifting away from the text it divides.
        #
        # The spec line below does not need this trick — its facts are
        # separate labels and the layout spaces them.
        _gap = "\u00a0" * 4
        subtitle = QLabel(
            f'<span style="color:{_c["accent_hover"]}">{info.alias}</span>'
            f'{_gap}'
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
        # card is already ``heightForWidth``, and the description below
        # already wraps), and the explicit zero minimum stops the layout
        # from
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
        # With a pitch, the measured case is off by default on this
        # surface. Both are true, but they answer different questions and
        # only one of them fits above the fold: "why this one" and "how
        # does it compare to the other fifteen". The first-run screen
        # asks the first; the catalogue asks the second.
        description.setVisible(not show_pitch)
        root.addWidget(description)

        if show_pitch and info.pitch:
            pitch = QLabel(info.pitch, self)
            pitch.setObjectName("CardPitch")
            pitch.setProperty("role", "pitch")
            pitch.setWordWrap(True)
            root.addWidget(pitch)


        # ---- Spec line ---------------------------------------------------
        # Three facts, three labels, and the gap comes from the layout.
        #
        # It was one rich-text label with em spaces between the facts,
        # which looked right in the source and wrong on screen: measured,
        # Qt's rich-text engine collapses whitespace runs, so one em, two
        # ems and six ems all rendered at 215px — identical. Whitespace
        # cannot express a gap in a QLabel. A layout can, so each fact is
        # its own label and the spacing is a real, measurable 16px that
        # survives a text scale and cannot drift out of step with the
        # items it divides.
        #
        # No middot, no dash, no separator glyph to keep in sync — which
        # was the point: three ``·`` between three numbers is
        # punctuation standing in for a gap. A test fails if one comes
        # back.
        spec_row = QHBoxLayout()
        spec_row.setContentsMargins(0, 0, 0, 0)
        spec_row.setSpacing(16)
        self._spec_facts = []
        for fact in (
            f"{_format_size(info.size_mb)} download",
            f"{info.vram_gb:.1f} GB VRAM",
        ):
            part = QLabel(fact, self)
            part.setProperty("role", "muted")
            spec_row.addWidget(part)
            self._spec_facts.append(part)

        # Only the verdict is coloured. "1.6 GB" is a number; "fast" is
        # an opinion about a value, and that is the only thing in the
        # app that earns colour on a card. Set inline from TOKENS for
        # the same reason the sidebar's focus fill is: the stylesheet
        # cannot style rich text, and a hex written out here would be a
        # token that does not exist.
        speed_part = QLabel(info.speed, self)
        speed_part.setProperty("role", "muted")
        if info.speed == "fast":
            speed_part.setStyleSheet(
                f"color: {TOKENS.colors['success']};"
            )
        spec_row.addWidget(speed_part)
        self._spec_facts.append(speed_part)
        # The speed word on its own is a fragment out of context, so it
        # says what it is in its own accessible name.
        speed_part.setAccessibleName(
            f"Speed: {info.speed}."
        )
        spec_row.addStretch(1)
        root.addLayout(spec_row)

        # The card is one focus stop, so the whole spec is spoken with
        # the card rather than as three unlabelled fragments.
        self.setAccessibleDescription(
            f"{self._info.family}. {self._info.description} "
            f"{_format_size(info.size_mb)} to download, "
            f"{info.vram_gb:.1f} gigabytes of video memory, "
            f"{info.speed}."
        )

        # ---- Inline inference settings -----------------------------------

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

    def set_family_filter_active(self, active: bool) -> None:
        """Reflect the view's family filter on this card's chip.

        The card does not own the filter, so it cannot decide what a
        press means — the view can, because it knows the current state.
        This is only the mirror: a checked chip is the one you would
        press again to get back to everything.
        """
        new_active = bool(active)
        if new_active == self._family_chip.isChecked():
            return
        self._family_chip.setChecked(new_active)
        self._family_chip.setToolTip(
            "Show all models"
            if new_active
            else f"Show only {self._info.family} models"
        )

    def _leave_tab_chain(self) -> None:
        """Give up the tab stop without stranding keyboard focus.

        The mirror of what :meth:`set_active` sets up, and it has to
        happen in the opposite order. ``release_focus_before`` is no use
        here — that helper protects a widget *leaving* focus, and here
        the card is the one losing it while its button is still hidden.

        So the button is the one that has to come back first: put it
        back, hand it the focus the card was holding, and only then
        drop the card out of the chain. Reverse that and Qt picks some
        other card's Download button, then scrolls the whole list to
        reach it — the exact failure ``focus.py`` exists to prevent.
        """
        if self.hasFocus():
            self._select_btn.setVisible(True)
            self._select_btn.setEnabled(not self._locked)
            self._select_btn.setFocus(Qt.FocusReason.OtherFocusReason)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_active(self, active: bool) -> None:
        new_active = bool(active)
        if new_active == self._active:
            return  # no state change — skip widget updates and style recalc
        self._active = new_active
        self.setProperty("active", self._active)
        self._active_pill.setVisible(self._active)
        if self._active:
            # The card becomes a tab stop exactly while it is active:
            # its Download button is the reason a card ever needs one,
            # and that button is about to disappear — so the card
            # takes over as the only thing here that can hold focus.
            # Policy first, because ``release_focus_before`` refuses a
            # fallback that is not focusable.
            self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            # Hand focus off before the button disappears, or Qt picks
            # the next card's Download button and scrolls the whole list
            # to it. The card itself is the right neighbour: it is
            # where the user's eyes already are, and it stays in the
            # tab chain.
            release_focus_before(self._select_btn, self)
        else:
            self._leave_tab_chain()
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
        self.cache_state_changed.emit(self._info.alias, cached)

    def is_cached(self) -> bool:
        """The last known cache state — no filesystem access."""
        return self._cached

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
