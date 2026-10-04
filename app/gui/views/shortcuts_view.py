"""Settings view — global hotkeys, microphone, and auto-paste toggle.

Three independent cards (Audio input / Hotkeys / Clipboard) make the
panel easier to scan than a single flat form. Edits persist
immediately on commit (``editingFinished`` for line edits,
``currentIndexChanged`` for the combo, ``toggled`` for the checkbox);
there is no Save button. A Reset button restores defaults.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.gui.focus import release_focus_before
from app.gui.theme import TOKENS, apply_text_scale
from app.gui.smooth_scroll import apply_smooth_scroll
from app.gui.views._accessibility_check import (
    is_accessibility_trusted,
    is_post_event_access_trusted,
    open_accessibility_settings,
    request_accessibility_access,
    request_post_event_access,
)
from app.gui.views._hotkey_validation import (
    is_push_to_talk_solo_key,
    validate_all,
)
from app.gui.views._microphone_check import (
    microphone_authorization_status,
    open_microphone_settings,
    request_microphone_access,
)
from app.gui.widgets.page_header import PageHeader

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# Text-size presets. The first entry is the design baseline and
# reproduces the shipped rendering exactly; each step is a jump the eye
# can read at a glance, not a 5% nudge.
_TEXT_SCALE_CHOICES: Tuple[Tuple[str, float], ...] = (
    ("100% (default)", 1.0),
    ("115%", 1.15),
    ("130%", 1.3),
    ("150%", 1.5),
    ("175%", 1.75),
)


def _slug(title: str) -> str:
    """"Audio input" -> "AudioInput", for an object name."""
    return "".join(ch for ch in title.title() if ch.isalnum())


def _make_section_card(title: str, parent: QWidget) -> tuple[QFrame, QFormLayout]:
    """Build a card-styled QFrame with a section title and an empty
    QFormLayout ready for rows.

    Returns ``(card, form)`` so the caller can keep adding rows. The
    title sits inside the card, above the form, with consistent
    padding.
    """
    card = QFrame(parent)
    card.setProperty("role", "card")
    # Named after the section it holds. The overflow tests report which
    # widget is setting this view's minimum width, and an unnamed
    # ``QFrame`` is not a thing anyone can go and look at — the two
    # cards that already set their own names are the only two the
    # failure message could name.
    card.setObjectName(_slug(title) + "Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(12)

    header = QLabel(title, card)
    header.setProperty("role", "section-header")
    layout.addWidget(header)

    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    form.setLabelAlignment(form.labelAlignment())  # default left
    form.setFormAlignment(form.formAlignment())
    form.setRowWrapPolicy(QFormLayout.DontWrapRows)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    layout.addLayout(form)
    return card, form


class _PermissionBanner(QFrame):
    """A permission warning: one paragraph plus the verb that fixes it.

    The button is capped at half the row because a permission banner is
    a sentence with an action attached, and the action must never
    outgrow the sentence. Measured at text scale 1.75 in a 900px window
    the microphone banner gave its button 53% of the row — 313px of
    "Open Microphone settings" against 239px for the message, which
    wrapped into eight lines and made the banner 246px tall.

    A ``QHBoxLayout`` will not do this on its own: it hands the leftover
    space to the stretch item, but nothing stops a wide ``sizeHint``
    from winning the row outright, and this button's hint grows faster
    than the label's minimum shrinks. The cap is applied in
    ``resizeEvent`` so it holds at any scale and any window width
    without anyone having to re-measure the copy by hand.

    Copy length is the other half of the fix, and it is why the button
    labels are "Grant access" / "Open Settings": the message names the
    exact System Settings pane, so repeating the pane in the button is
    words the paragraph already spent.
    """

    #: The button may claim at most this fraction of the banner width.
    #: Half leaves the paragraph at least as much room as the verb.
    _BUTTON_SHARE = 0.5

    def __init__(
        self,
        object_name: str,
        button_object_name: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setProperty("role", "warning-banner")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)

        self.text = QLabel("", self)
        self.text.setWordWrap(True)
        self.text.setProperty("role", "warning-banner-text")
        # A wrapping label already reports a small minimum width, but
        # the explicit zero stops the layout from reserving room for
        # the longest unbreakable run in a System Settings path.
        self.text.setMinimumWidth(0)
        row.addWidget(self.text, 1)

        self.button = QPushButton("", self)
        self.button.setObjectName(button_object_name)
        self.button.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Fixed,
        )
        row.addWidget(self.button, 0)

    def set_message(self, text: str, action: str) -> None:
        """Restate the banner. ``action`` is the button's label."""
        self.text.setText(text)
        self.button.setText(action)
        self._clamp_button_width()

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().resizeEvent(event)
        self._clamp_button_width()

    def _clamp_button_width(self) -> None:
        """Hold the button to its share of the row.

        Called on every resize rather than at construction because the
        banner's width is not known until the form lays it out, and it
        changes with the window and the text scale.

        The cap is a backstop, not the mechanism: with the shipped
        labels ("Grant access", "Open Settings") the button's own
        ``sizeHint`` stays well inside the share, so nothing gets
        elided. What the cap buys is that the *next* person to write a
        long button label cannot silently starve the paragraph. If the
        cap ever does bind, the button elides — ``test_banner_button_
        never_elides`` is what catches that.
        """
        width = self.width()
        if width <= 0:
            # Pre-layout: a zero-width banner would clamp the button
            # to nothing and flash it collapsed.
            return
        self.button.setMaximumWidth(int(width * self._BUTTON_SHARE))


class _DeviceCombo(QComboBox):
    """Combo whose popup widens on open instead of in the layout.

    Long device names ("Микрофон (Razer BlackShark V2 Pro 2.4 …)")
    need a wider popup than the combo itself, or they are cut off. The
    obvious way to get one is a static ``420px`` minimum on
    ``view()``.

    TRAP: ``view()`` is a *child* widget of the combo, reparented into a
    popup only at show time — so a width constraint left on it also
    counts against the combo's own geometry, and walks up through the
    form row, the card and finally forces a horizontal scrollbar on the
    page. That is not hypothetical: measured, the 420px static minimum
    made the Settings view overflow by 15px at text scale 1.75, which
    is precisely what the comment that used to sit here predicted
    ("a larger text scale could turn it into a real overflow").

    So the width is set in ``showPopup``, when the widget really is a
    popup and really is on screen. The page never reserves the space,
    so the card's minimum goes back to being its own content.
    """

    #: Wide enough for the longest device name we have seen.
    _POPUP_WIDTH = 420

    def showPopup(self) -> None:  # noqa: N802 — Qt naming
        self.view().setMinimumWidth(self._POPUP_WIDTH)
        super().showPopup()


class ShortcutsView(QWidget):
    save_requested = Signal(dict)
    test_mic_requested = Signal()
    # Per-card reset signals — granular replacements for the old
    # single ``reset_requested`` footer button. Each card now owns
    # its own affordance so the user can revert one section without
    # nuking unrelated state.
    hotkeys_reset_requested = Signal()
    hf_token_reset_requested = Signal()
    # Storage card — view delegates path-picking to the controller so
    # QFileDialog stays out of the widget code (cleaner tests).
    storage_path_change_requested = Signal()
    storage_reset_requested = Signal()
    # 'Open folder' shortcut — the controller spawns Explorer
    # (subprocess + path stays out of the view).
    storage_open_requested = Signal()
    # Hugging Face card — fired on focus loss after the user edits
    # the token field. Controller persists + applies to env.
    hf_token_changed = Signal(str)
    # macOS-only — a permission changed in a way that may require
    # lightweight runtime refresh (e.g. re-enumerate microphones or
    # rebuild the hotkey monitor), but not a full app restart.
    mac_permissions_changed = Signal()
    # macOS-only — bridges the asynchronous AVFoundation microphone
    # permission callback back onto the GUI thread. Emitting a Qt
    # signal from the background completion handler is reliable;
    # trying to schedule a raw callable with QTimer from that thread
    # can miss the main event loop and leave the banner stale.
    _mic_request_result = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ShortcutsView")
        self._mic_request_result.connect(
            self._apply_mic_request_completed,
        )

        # Suppresses save_requested emission while we are populating fields
        # programmatically (e.g. controller prefilling from config).
        self._suspend_emit = False
        self._storage_is_default = True
        self._storage_busy = False

        # Snapshot of the user's Stop hotkey taken just before we
        # mirror the Start value over it on toggle-mode entry, so
        # un-ticking can restore exactly what was there before.
        # Only set on user-driven toggle (``_on_toggle_mode_changed``)
        # — ``set_values`` skips it because the values come from
        # config and don't need a "previous" copy.
        self._previous_stop_hotkey: Optional[str] = None
        self._last_accessibility_trusted = is_accessibility_trusted()
        self._last_mic_status = microphone_authorization_status()
        self._last_post_event_trusted = is_post_event_access_trusted()

        # Outer layout = top hint pinned + scrollable card stack.
        # Without the scroll area Qt tried to fit every card into
        # whatever vertical space the window had; once we pushed
        # past 4-5 cards Qt started squishing form rows below
        # their min-height and labels rendered on top of inputs.
        # Mirrors the Models view's pattern exactly.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        hint_wrapper = QWidget(self)
        hint_wrapper_layout = QVBoxLayout(hint_wrapper)
        # Bottom margin separates the description from the first card
        # so the text doesn't kiss the card border on scroll — without
        # this the muted hint visually merged with the dark card frame.
        hint_wrapper_layout.setContentsMargins(28, 22, 28, 14)
        hint_wrapper_layout.setSpacing(4)

        # Settings was the one view that already had a purpose line, and
        # it was floating as muted body text with no title above it. It
        # is now the same header every other view uses, which is what
        # makes the five screens read as five sections of one app.
        self._header = PageHeader(
            "Settings",
            "Microphone, global hotkeys, paste behaviour. "
            "Changes save automatically.",
            hint_wrapper,
        )
        hint_wrapper_layout.addWidget(self._header)
        outer.addWidget(hint_wrapper)

        scroll = QScrollArea(self)
        scroll.setObjectName("ShortcutsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        apply_smooth_scroll(scroll)
        outer.addWidget(scroll, 1)

        scroll_content = QWidget(scroll)
        scroll_content.setObjectName("ShortcutsScrollContent")
        scroll.setWidget(scroll_content)
        root = QVBoxLayout(scroll_content)
        root.setContentsMargins(28, 14, 28, 22)
        root.setSpacing(14)

        # ---- Audio input card -------------------------------------------
        audio_card, audio_form = _make_section_card("Audio input", self)

        # macOS-only: similar story to the Accessibility banner —
        # if the user hasn't granted Microphone access via TCC,
        # ``sounddevice.InputStream.start`` returns silence with no
        # exception, so recording "works" but every transcription
        # comes back empty. Surface the state explicitly with a
        # banner that walks the user through grant.
        self._mic_banner = _PermissionBanner(
            "MicrophoneWarningBanner", "MicrophoneActionButton", audio_card,
        )
        # Both permission banners carry the same short visible label —
        # "Grant access" — because the banner text above it already says
        # which permission, and the button is capped at half the banner
        # width. That is fine for eyes and useless for a screen reader,
        # which would meet two buttons both announced as "Grant access,
        # button" and could not tell the microphone from Accessibility.
        # The accessible name adds back what the visible label leaves
        # to the surrounding text.
        self._mic_banner.button.setAccessibleName("Grant microphone access")
        self._mic_banner.button.setAccessibleDescription(
            "Opens the system settings page for microphone access."
        )
        self._mic_banner_text = self._mic_banner.text
        self._mic_banner_button = self._mic_banner.button
        self._mic_banner_button.clicked.connect(
            self._on_mic_banner_clicked,
        )
        self._mic_banner.setVisible(False)
        # State machine: ``"not_determined"`` (Grant access) /
        # ``"denied"`` (Open Settings) / ``"hidden"``.
        self._mic_state = "hidden"
        audio_form.addRow(self._mic_banner)
        self._refresh_mic_banner()

        # Long device names ("Микрофон (Razer BlackShark V2 Pro 2.4 …)") need
        # a wider popup than the combo box itself, otherwise they're cut off.
        # TRAP: ``view()`` is a *child* widget of the combo, reparented into a
        # popup only at show time — so any width constraint left on it also
        # counts against this combo's own geometry and can walk up through
        # the form row, the card and finally force a horizontal scrollbar on
        # the page. Measured 2026-10: the combo's minimumSizeHint stays 76px
        # with the 420 below, and the settings view overflows by 0px at
        # 900/1100/1280/1920/2560 — so it is currently safe, but anything
        # that grows this card's content (a longer hint, a wider label, a
        # larger text scale) could turn it into a real overflow. If it ever
        # needs to move, size the view inside ``showPopup()`` instead.
        self._device_combo = _DeviceCombo(audio_card)
        self._device_combo.setObjectName("MicrophoneCombo")
        self._device_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        # No QSS ``min-width`` here: it applied to the same child widget
        # and carried the same overflow into the page. ``_DeviceCombo``
        # sets the width when the popup actually opens.
        # Populated later via set_devices(); placeholder until then.
        self._device_combo.addItem("System default", None)
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)

        # Microphone row: dropdown + Test button inline. Same trick
        # as the HF card — kills the empty space a button-on-its-
        # own-row left next to the dropdown.
        from app.gui.widgets.vu_meter import VUMeter

        mic_input_row = QHBoxLayout()
        mic_input_row.setSpacing(10)
        mic_input_row.addWidget(self._device_combo, 1)
        self._test_mic_btn = QPushButton("Test microphone", audio_card)
        self._test_mic_btn.setObjectName("TestMicrophoneButton")
        # Focusable on purpose. This used to carry ``Qt.NoFocus``:
        # clicking the button focused it, and disabling it for the
        # 3-second test made Qt chase focus to the next focusable
        # widget — the Start-hotkey QLineEdit — dropping the cursor
        # inside it. The real fix is to hand focus off deliberately
        # before disabling (see ``_on_test_mic_clicked``), not to take
        # the control out of the tab chain.
        self._test_mic_btn.clicked.connect(self.test_mic_requested.emit)
        mic_input_row.addWidget(self._test_mic_btn)
        audio_form.addRow("Microphone", mic_input_row)

        # Result row: live VU meter (visible only during / after a
        # test) + the textual result. Sits below the input row —
        # collapses to a thin empty strip when nothing is running,
        # blooms into a meter + verdict line during / after a test.
        mic_result_row = QHBoxLayout()
        mic_result_row.setSpacing(10)
        self._test_mic_meter = VUMeter(audio_card)
        self._test_mic_meter.setObjectName("MicrophoneTestMeter")
        self._test_mic_meter.setVisible(False)
        mic_result_row.addWidget(self._test_mic_meter)

        self._test_mic_label = QLabel("", audio_card)
        self._test_mic_label.setObjectName("MicrophoneTestResult")
        self._test_mic_label.setProperty("role", "muted")
        self._test_mic_label.setWordWrap(True)
        mic_result_row.addWidget(self._test_mic_label, 1)
        audio_form.addRow("", mic_result_row)
        root.addWidget(audio_card)

        # ---- Hotkeys card -----------------------------------------------
        hotkeys_card, hotkeys_form = _make_section_card("Hotkeys", self)

        # macOS-only: warn the user when the process hasn't been
        # added to System Settings → Privacy & Security →
        # Accessibility. Without that, ``pynput``'s CGEventTap
        # silently returns no events at all and hotkeys "don't
        # work" with no on-screen explanation.
        #
        # The banner has two states.  At startup the process is
        # either trusted (banner hidden) or untrusted (banner
        # shows the "grant access" text + "Open Accessibility
        # settings" button).  After the user grants access the
        # ``AXIsProcessTrusted()`` call starts returning True, but
        # ``pynput``'s already-installed event tap was attached
        # under the old untrusted state and won't pick up new
        # events without a relaunch — so we flip the banner to a
        # now allow us to rebuild the listener live, so the banner
        # can simply disappear once permission is granted.
        self._accessibility_banner = _PermissionBanner(
            "AccessibilityWarningBanner",
            "AccessibilityActionButton",
            hotkeys_card,
        )
        self._accessibility_banner.button.setAccessibleName(
            "Grant accessibility access"
        )
        self._accessibility_banner.button.setAccessibleDescription(
            "Opens the system settings page for accessibility access."
        )
        self._accessibility_banner_text = self._accessibility_banner.text
        self._accessibility_banner_button = self._accessibility_banner.button
        # Click handler swaps based on banner state — set in
        # ``_refresh_accessibility_banner``.
        self._accessibility_banner_button.clicked.connect(
            self._on_accessibility_banner_clicked,
        )
        self._accessibility_banner.setVisible(False)
        # The form's row spans both columns — the banner runs full
        # card width, not nested under the field column.
        hotkeys_form.addRow(self._accessibility_banner)
        # State machine: ``"untrusted"`` (request/open settings) /
        # ``"hidden"``.
        self._accessibility_state = "hidden"
        self._refresh_accessibility_banner()

        # Recording mode picker.  Three options:
        #
        #   - "Two keys"     — separate Start and Stop bindings
        #                      (the historical default; Cancel is
        #                      independent).
        #   - "One key (toggle)" — single Start hotkey flips between
        #                      idle ↔ recording; Stop field is muted.
        #   - "Push to talk"   — hold a single key (default
        #                      ``right_cmd`` on Mac, ``right_alt``
        #                      elsewhere) to record, release to
        #                      transcribe; Stop field is muted, the
        #                      PTT key field becomes the active one.
        #
        # A QComboBox is more compact than a 3-way radio cluster
        # and the "select-from-discrete-set" semantic matches what
        # the user is doing.  ``setCurrentData`` keeps the on-disk
        # config value (``"two_keys"`` / ``"toggle"`` / ``"push_to_talk"``)
        # decoupled from the user-facing label.
        self._mode_combo = QComboBox(hotkeys_card)
        self._mode_combo.setObjectName("RecordingModeCombo")
        self._mode_combo.addItem(
            "Two keys (Start + Stop)", userData="two_keys",
        )
        self._mode_combo.addItem(
            "One key — press to toggle", userData="toggle",
        )
        self._mode_combo.addItem(
            "Push to talk — hold to record", userData="push_to_talk",
        )
        self._mode_combo.setToolTip(
            "Two keys: classic start + stop bindings.\n"
            "Toggle: one hotkey flips between idle and recording.\n"
            "Push-to-talk: hold a single key (e.g. right Cmd) to "
            "record, release to transcribe — best for short dictation."
        )
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        hotkeys_form.addRow("Recording mode", self._mode_combo)

        self._start_edit = QLineEdit(hotkeys_card)
        self._start_edit.setObjectName("StartHotkeyEdit")
        self._start_edit.setPlaceholderText("e.g. ctrl+f2")
        self._start_edit.editingFinished.connect(self._emit_save)
        # While toggle-mode is on, the Stop field mirrors Start —
        # listen for live edits to keep them in sync visually.
        self._start_edit.textChanged.connect(self._mirror_start_into_stop)
        hotkeys_form.addRow("Start recording", self._start_edit)

        self._stop_edit = QLineEdit(hotkeys_card)
        self._stop_edit.setObjectName("StopHotkeyEdit")
        self._stop_edit.setPlaceholderText("e.g. ctrl+f3")
        self._stop_edit.editingFinished.connect(self._emit_save)
        hotkeys_form.addRow("Stop recording", self._stop_edit)

        # Push-to-talk key — only meaningful in PTT mode, but the
        # row stays in the form so the field's vertical position
        # matches the others when it appears.  Hidden via
        # ``setVisible(False)`` from ``_apply_mode`` when the mode
        # isn't ``"push_to_talk"``.
        self._ptt_edit = QLineEdit(hotkeys_card)
        self._ptt_edit.setObjectName("PushToTalkEdit")
        self._ptt_edit.setPlaceholderText(
            "e.g. right_cmd, right_alt, fn — solo modifier OK in PTT mode"
        )
        self._ptt_edit.editingFinished.connect(self._emit_save)
        hotkeys_form.addRow("Push-to-talk key", self._ptt_edit)
        self._ptt_label_widget = hotkeys_form.labelForField(self._ptt_edit)

        # "Discard buffer without transcribing" — the runtime has
        # always supported this (StateManager.cancel_active_recording)
        # but the hotkey was never exposed. Optional — empty value
        # means no global key, the feature simply isn't bound.
        self._cancel_edit = QLineEdit(hotkeys_card)
        self._cancel_edit.setObjectName("CancelHotkeyEdit")
        self._cancel_edit.setPlaceholderText("e.g. ctrl+f6 — leave empty to disable")
        self._cancel_edit.editingFinished.connect(self._emit_save)
        hotkeys_form.addRow("Cancel recording", self._cancel_edit)

        # "Reset to defaults" lives inside the card now (next to its
        # owned content) instead of a footer at the bottom of the
        # whole tab — matches the Storage card's button placement
        # and means each card's reset only touches its own settings.
        hotkeys_btn_row = QHBoxLayout()
        hotkeys_btn_row.setSpacing(10)
        hotkeys_btn_row.addStretch(1)
        self._reset_hotkeys_btn = QPushButton("Reset to defaults", hotkeys_card)
        self._reset_hotkeys_btn.setAccessibleName("Reset hotkeys to defaults")
        self._reset_hotkeys_btn.setObjectName("ResetHotkeysButton")
        self._reset_hotkeys_btn.clicked.connect(
            self.hotkeys_reset_requested.emit
        )
        hotkeys_btn_row.addWidget(self._reset_hotkeys_btn)
        hotkeys_card.layout().addLayout(hotkeys_btn_row)

        # Hint goes into the card's OUTER VBox, not the form — adding
        # it as a labelless form-row would offset it to the field
        # column (under the inputs), inconsistent with the Storage
        # card's hint which sits flush-left across the full card.
        hotkeys_hint = QLabel(
            "Cancel discards the current buffer instead of transcribing.",
            hotkeys_card,
        )
        hotkeys_hint.setObjectName("HotkeysHint")
        hotkeys_hint.setProperty("role", "muted")
        hotkeys_hint.setWordWrap(True)
        hotkeys_card.layout().addWidget(hotkeys_hint)
        root.addWidget(hotkeys_card)

        # ---- Clipboard card ---------------------------------------------
        clipboard_card, clipboard_form = _make_section_card("Clipboard", self)

        # macOS 14+ can gate synthetic key posting separately from
        # global hotkey listening. Surface that state next to the
        # auto-paste toggle so the user sees why text is copied but
        # not inserted into the focused app.
        self._post_event_banner = QFrame(clipboard_card)
        self._post_event_banner.setObjectName("PostEventWarningBanner")
        self._post_event_banner.setProperty("role", "warning-banner")
        post_event_layout = QHBoxLayout(self._post_event_banner)
        post_event_layout.setContentsMargins(12, 10, 12, 10)
        post_event_layout.setSpacing(12)
        self._post_event_banner_text = QLabel("", self._post_event_banner)
        self._post_event_banner_text.setWordWrap(True)
        self._post_event_banner_text.setProperty("role", "warning-banner-text")
        post_event_layout.addWidget(self._post_event_banner_text, 1)
        self._post_event_banner_button = QPushButton("", self._post_event_banner)
        self._post_event_banner_button.setObjectName("PostEventActionButton")
        self._post_event_banner_button.clicked.connect(
            self._on_post_event_banner_clicked,
        )
        post_event_layout.addWidget(self._post_event_banner_button, 0)
        self._post_event_banner.setVisible(False)
        self._post_event_state = "hidden"
        clipboard_form.addRow(self._post_event_banner)

        self._auto_paste_cb = QCheckBox(
            "Auto-paste transcription into the focused window",
            clipboard_card,
        )
        self._auto_paste_cb.setObjectName("AutoPasteCheckbox")
        self._auto_paste_cb.toggled.connect(self._on_auto_paste_toggled)
        # Single full-width row — no left label needed for a checkbox
        # whose own text already describes it.
        clipboard_form.addRow(self._auto_paste_cb)
        self._refresh_post_event_banner()
        root.addWidget(clipboard_card)

        # ---- Appearance card ---------------------------------------------
        # Text scale is the one accessibility control that has to live
        # in the app: Qt expresses font sizes in device-independent
        # pixels, so the OS-level text-size preference is a widget-scale
        # setting here, not something a stylesheet inherits. Sizes are
        # the five ``font.size_*`` tokens multiplied by this factor, so
        # the type scale keeps its ratios at every step — the four-size
        # rule in DESIGN.md describes the ratios, not the pixels.
        appearance_card, appearance_form = _make_section_card(
            "Appearance", self,
        )
        self._text_scale_combo = QComboBox(appearance_card)
        self._text_scale_combo.setObjectName("TextScaleCombo")
        self._text_scale_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        for label, value in _TEXT_SCALE_CHOICES:
            self._text_scale_combo.addItem(label, value)
        self._text_scale_combo.setToolTip(
            "Scales every text size in the app. 100% is the default."
        )
        self._text_scale_combo.setAccessibleName("Text size")
        self._text_scale_combo.currentIndexChanged.connect(
            self._on_text_scale_changed
        )
        appearance_form.addRow("Text size", self._text_scale_combo)

        appearance_hint = QLabel(
            "Applies immediately. Radii and spacing keep their size so "
            "the layout rhythm holds at any text scale.",
            appearance_card,
        )
        appearance_hint.setProperty("role", "muted")
        appearance_hint.setWordWrap(True)
        appearance_card.layout().addWidget(appearance_hint)
        root.addWidget(appearance_card)

        # ---- Storage card -----------------------------------------------
        # User-pickable models directory — both Whisper (HF hub) and
        # GigaAM weights live under this root. Empty config value =
        # use the default ``<project>/models`` (or ``<exe>/models``
        # when frozen).
        #
        # Built by hand instead of via ``_make_section_card`` because
        # this card mixes a label-row with a button-row and a hint
        # paragraph; QFormLayout's spanning-row layout shrinks rows
        # whose label column is empty, squashing the buttons. A
        # straight QVBoxLayout sidesteps that entirely.
        storage_card = QFrame(self)
        storage_card.setObjectName("StorageCard")
        storage_card.setProperty("role", "card")
        storage_v = QVBoxLayout(storage_card)
        storage_v.setContentsMargins(20, 16, 20, 16)
        storage_v.setSpacing(10)

        storage_header = QLabel("Storage", storage_card)
        storage_header.setProperty("role", "section-header")
        storage_v.addWidget(storage_header)

        # Path row — leading caption + selectable label, all on one line.
        storage_path_row = QHBoxLayout()
        storage_path_row.setSpacing(16)
        storage_caption = QLabel("Models folder", storage_card)
        storage_path_row.addWidget(storage_caption)

        self._storage_path_label = QLabel("(loading…)", storage_card)
        self._storage_path_label.setObjectName("StoragePathLabel")
        self._storage_path_label.setProperty("role", "muted")
        self._storage_path_label.setWordWrap(True)
        self._storage_path_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        storage_path_row.addWidget(self._storage_path_label, 1)
        storage_v.addLayout(storage_path_row)

        # Used-space row: tells the user how much disk the cache eats
        # so they can decide whether to move it to a bigger drive.
        # The controller computes this asynchronously (cached_models_size
        # walks the entire HF hub subtree).
        storage_size_row = QHBoxLayout()
        storage_size_row.setSpacing(16)
        storage_size_caption = QLabel("Used", storage_card)
        storage_size_row.addWidget(storage_size_caption)
        self._storage_size_label = QLabel("…", storage_card)
        self._storage_size_label.setObjectName("StorageSizeLabel")
        self._storage_size_label.setProperty("role", "muted")
        self._storage_size_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        storage_size_row.addWidget(self._storage_size_label, 1)
        storage_v.addLayout(storage_size_row)

        # Button row — flush left, stretch on the right. Wrapped in a
        # QWidget rather than added as a bare QHBoxLayout because the
        # outer VBox doesn't reliably pick up the layout's sizeHint
        # in this nesting (hint label was rendering on top of the
        # button row's bottom edge).
        storage_btn_widget = QWidget(storage_card)
        storage_btn_widget.setObjectName("StorageButtonRow")
        storage_btn_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # Without this the global ``QWidget { background-color:
        # bg_primary }`` rule paints a dark slab around the buttons
        # that's visibly different from the card's elevated bg —
        # makes the row look like its own button-coloured strip.
        storage_btn_widget.setStyleSheet("background: transparent;")
        storage_btn_row = QHBoxLayout(storage_btn_widget)
        storage_btn_row.setContentsMargins(0, 0, 0, 0)
        storage_btn_row.setSpacing(10)
        self._change_storage_btn = QPushButton("Change…", storage_btn_widget)
        self._change_storage_btn.setObjectName("ChangeStorageButton")
        # "Change…" names the gesture and nothing else. The card titles
        # it, so eyes are covered; a screen reader gets the two words the
        # label leaves out.
        self._change_storage_btn.setAccessibleName("Change storage folder")
        self._change_storage_btn.clicked.connect(
            self.storage_path_change_requested.emit
        )
        storage_btn_row.addWidget(self._change_storage_btn)

        self._reset_storage_btn = QPushButton(
            # Matched the Hotkeys card's button. The two were "Reset to
            # default" and "Reset to defaults" on the same screen for
            # the same kind of action, and nothing distinguished them
            # but a plural — which reads as a typo rather than a rule.
            "Reset to defaults", storage_btn_widget,
        )
        self._reset_storage_btn.setObjectName("ResetStorageButton")
        self._reset_storage_btn.setAccessibleName("Reset storage folder")
        # Disabled until a custom path is set — see ``set_storage_path``.
        self._reset_storage_btn.setEnabled(False)
        self._reset_storage_btn.clicked.connect(
            self.storage_reset_requested.emit
        )
        storage_btn_row.addWidget(self._reset_storage_btn)

        # Open-folder shortcut — once the user knows the size, the
        # natural next step is "show me what's inside" (delete stale
        # downloads, free up space, copy weights to a backup, …).
        # Cheaper than implementing a built-in cache browser.
        self._open_storage_btn = QPushButton(
            "Open folder", storage_btn_widget,
        )
        self._open_storage_btn.setObjectName("OpenStorageButton")
        self._open_storage_btn.setAccessibleName("Open storage folder")
        self._open_storage_btn.clicked.connect(
            self.storage_open_requested.emit
        )
        storage_btn_row.addWidget(self._open_storage_btn)
        storage_btn_row.addStretch(1)
        # Match the wrapper's height to the buttons' sizeHint so the
        # outer VBox can't squish it below the button height.
        storage_btn_widget.setMinimumHeight(
            self._change_storage_btn.sizeHint().height(),
        )
        storage_v.addWidget(storage_btn_widget)

        storage_hint = QLabel(
            "New downloads land here immediately. Already-downloaded "
            "weights stay in their current folder unless you choose "
            "to move them.",
            storage_card,
        )
        storage_hint.setObjectName("StorageHint")
        storage_hint.setProperty("role", "muted")
        storage_hint.setWordWrap(True)
        storage_v.addWidget(storage_hint)
        root.addWidget(storage_card)

        # ---- Hugging Face card ------------------------------------------
        # Optional API token, only relevant for GigaAM long-form
        # audio (>25 s) which routes through pyannote VAD —
        # ``pyannote/segmentation-3.0`` is gated and needs an HF
        # account that's accepted the model card. Built by hand
        # rather than via ``_make_section_card`` for the same
        # reason as the Storage card (form-row layout + helper
        # widgets clash on spanning rows).
        hf_card = QFrame(self)
        hf_card.setObjectName("HfCard")
        hf_card.setProperty("role", "card")
        hf_v = QVBoxLayout(hf_card)
        hf_v.setContentsMargins(20, 16, 20, 16)
        hf_v.setSpacing(10)

        hf_header = QLabel("Hugging Face", hf_card)
        hf_header.setProperty("role", "section-header")
        hf_v.addWidget(hf_header)

        # Token field + Clear on a single row to avoid the wide
        # empty rectangle a stretch-aligned button row used to
        # leave next to the input. Scope is field-level (just the
        # token), so inline placement is clear without the extra
        # vertical real estate.
        hf_row = QHBoxLayout()
        hf_row.setSpacing(10)
        hf_caption = QLabel("API token", hf_card)
        hf_row.addWidget(hf_caption)
        self._hf_token_edit = QLineEdit(hf_card)
        self._hf_token_edit.setObjectName("HfTokenEdit")
        self._hf_token_edit.setEchoMode(QLineEdit.Password)
        self._hf_token_edit.setPlaceholderText("hf_…")
        self._hf_token_edit.setClearButtonEnabled(True)
        # The card's caption is a plain QLabel, not a buddy, so Qt hands
        # the screen reader no name at all — and the placeholder is not a
        # name either: "hf_…" says what the value looks like, never what
        # the field is for. A sighted user reads the caption above;
        # without this they get "edit, hf_…" and stop there.
        self._hf_token_edit.setAccessibleName("Hugging Face API token")
        self._hf_token_edit.setAccessibleDescription(
            "Optional. Only needed to download gated models."
        )
        self._hf_token_edit.editingFinished.connect(self._on_hf_token_finished)
        hf_row.addWidget(self._hf_token_edit, 1)
        self._clear_hf_token_btn = QPushButton("Clear token", hf_card)
        self._clear_hf_token_btn.setObjectName("ClearHfTokenButton")
        # Discards a stored credential. Painted like the neutral controls
        # around it, one click removed the user's Hugging Face token.
        self._clear_hf_token_btn.setProperty("role", "danger")
        self._clear_hf_token_btn.clicked.connect(
            self.hf_token_reset_requested.emit
        )
        hf_row.addWidget(self._clear_hf_token_btn)
        hf_v.addLayout(hf_row)

        hf_hint = QLabel(
            "Optional. Used when downloading gated or private "
            "Hugging Face models — the app passes it to "
            "<code>huggingface_hub</code> on every fetch.<br>"
            "Get one at "
            '<a href="https://huggingface.co/settings/tokens" '
            f'style="color:{TOKENS.colors["accent_hover"]};'
            'text-decoration:none">'
            "huggingface.co/settings/tokens</a>.",
            hf_card,
        )
        hf_hint.setObjectName("HfHint")
        hf_hint.setProperty("role", "muted")
        hf_hint.setWordWrap(True)
        hf_hint.setTextFormat(Qt.RichText)
        hf_hint.setOpenExternalLinks(True)
        hf_hint.setTextInteractionFlags(Qt.TextBrowserInteraction)
        hf_v.addWidget(hf_hint)
        root.addWidget(hf_card)

        # Footer reset button retired — each card now owns its own
        # 'Reset' / 'Clear' affordance. The previous global button
        # was misleading: it advertised 'Reset to defaults' but
        # only touched hotkeys + auto_paste, leaving Storage / HF
        # untouched. Per-card buttons make the scope explicit.
        root.addStretch(1)

    # ---- public API ---------------------------------------------------------

    def set_values(
        self,
        start_hotkey: str,
        stop_hotkey: str,
        auto_paste: bool,
        cancel_hotkey: str = "",
        mode: str = "two_keys",
        push_to_talk_key: str = "",
    ) -> None:
        # Programmatic update — must not feed back into save_requested.
        # ``cancel_hotkey`` / ``mode`` / ``push_to_talk_key`` are
        # keyword-only with defaults so callers written before the
        # fields existed keep working unchanged.
        self._suspend_emit = True
        try:
            self._start_edit.setText(start_hotkey)
            self._stop_edit.setText(stop_hotkey)
            self._auto_paste_cb.setChecked(bool(auto_paste))
            self._cancel_edit.setText(cancel_hotkey or "")
            self._ptt_edit.setText(push_to_talk_key or "")

            # Migration path: legacy configs (pre-mode-field) implicitly
            # encoded toggle mode by setting Start == Stop.  Honour
            # that when the explicit ``mode`` field is missing or set
            # to the default but Start == Stop happens to match.
            resolved_mode = mode if mode in {"two_keys", "toggle", "push_to_talk"} else "two_keys"
            same = bool(
                start_hotkey
                and start_hotkey.strip().lower() == stop_hotkey.strip().lower()
            )
            if resolved_mode == "two_keys" and same:
                resolved_mode = "toggle"

            # Find and select the combo entry whose userData matches
            # the resolved mode.  ``setCurrentIndex`` would fire
            # ``currentIndexChanged`` and through it ``_on_mode_changed``,
            # but ``_suspend_emit`` is up so the save-cycle stays
            # quiet.
            for i in range(self._mode_combo.count()):
                if self._mode_combo.itemData(i) == resolved_mode:
                    self._mode_combo.setCurrentIndex(i)
                    break
            self._apply_mode(resolved_mode)
        finally:
            self._suspend_emit = False
        # Run validation once the suspend flag is back down so the
        # invalid-border / tooltip state matches the freshly-loaded
        # values.  Doing it inside the suspend block would skip the
        # repaint triggered by the property change.
        self._refresh_hotkey_validation()
        self._refresh_accessibility_banner()
        self._refresh_post_event_banner()

    def set_devices(
        self,
        devices: List[Tuple[int, str]],
        current: Optional[int] = None,
    ) -> None:
        """Populate the microphone dropdown. ``devices`` is a list of
        ``(index, name)`` tuples. ``current`` is the index to preselect, or
        ``None`` for system default."""
        self._suspend_emit = True
        try:
            self._device_combo.clear()
            self._device_combo.addItem("System default", None)
            for idx, name in devices:
                self._device_combo.addItem(f"[{idx}] {name}", idx)

            if current is not None:
                for i in range(self._device_combo.count()):
                    if self._device_combo.itemData(i) == current:
                        self._device_combo.setCurrentIndex(i)
                        break
        finally:
            self._suspend_emit = False

    def start_hotkey(self) -> str:
        return self._start_edit.text().strip()

    def stop_hotkey(self) -> str:
        mode = self._current_mode()
        # Toggle mode: the stop combo is the start combo (the
        # HotkeyListener checks equality to decide on a single
        # toggle handler).  PTT mode: Stop is unused, but we still
        # write the user's previous stop value to disk so a
        # later switch back to two_keys restores it.
        if mode == "toggle":
            return self._start_edit.text().strip()
        return self._stop_edit.text().strip()

    def cancel_hotkey(self) -> str:
        mode = self._current_mode()
        # Toggle / PTT modes both disable Cancel — the user picked a
        # streamlined "one key for everything recording" flow.
        # Returning an empty string propagates through ``values()`` /
        # ``save_requested`` so the persisted config drops the
        # binding and HotkeyListener stops registering it.  The
        # field text itself is preserved on screen so a later
        # mode-switch back to two_keys restores the previous value
        # transparently.
        if mode in {"toggle", "push_to_talk"}:
            return ""
        return self._cancel_edit.text().strip()

    def recording_mode(self) -> str:
        """Active recording mode — ``"two_keys"`` / ``"toggle"`` /
        ``"push_to_talk"``.  Forwarded to the controller's save
        bundle so ``HotkeyListener`` rebuilds with the right path."""
        return self._current_mode()

    def push_to_talk_key(self) -> str:
        """Push-to-talk binding (e.g. ``"right_cmd"``).  Honoured by
        the controller only when ``recording_mode() == "push_to_talk"``.
        """
        return self._ptt_edit.text().strip()

    def auto_paste(self) -> bool:
        return self._auto_paste_cb.isChecked()

    def device_index(self) -> Optional[int]:
        return self._device_combo.currentData()

    def set_hf_token(self, token: str) -> None:
        """Programmatic prefill of the HF token field — used by the
        controller on init. Won't echo a ``hf_token_changed`` signal
        back so we don't re-save what we just loaded."""
        self._suspend_emit = True
        try:
            self._hf_token_edit.setText(token or "")
        finally:
            self._suspend_emit = False

    def hf_token(self) -> str:
        return self._hf_token_edit.text().strip()

    def _on_hf_token_finished(self) -> None:
        if self._suspend_emit:
            return
        self.hf_token_changed.emit(self.hf_token())

    def set_storage_path(self, path: str, is_default: bool) -> None:
        """Update the Storage card's path display.

        ``path`` is the *resolved* absolute path — not the raw config
        value. ``is_default`` toggles a ``(default)`` marker and
        disables the Reset button (no point resetting when we're
        already on the default).
        """
        self._storage_is_default = bool(is_default)
        if is_default:
            self._storage_path_label.setText(f"{path}  (default)")
            if not self._storage_busy:
                release_focus_before(
                    self._reset_storage_btn, self._change_storage_btn
                )
                self._reset_storage_btn.setEnabled(False)
        else:
            self._storage_path_label.setText(path)
            if not self._storage_busy:
                self._reset_storage_btn.setEnabled(True)

    def set_storage_size(self, text: str) -> None:
        """Render the human-readable used-space string in the Storage card.

        The controller does the formatting (bytes → ``"3.4 GB"``) so
        this view stays free of locale rules and unit thresholds.
        ``""`` blanks the label (used while the worker is computing).
        """
        self._storage_size_label.setText(text or "…")

    def set_storage_busy(
        self, busy: bool, status_text: Optional[str] = None
    ) -> None:
        """Temporarily disable the Storage card actions while a long-running
        filesystem operation is in progress."""
        self._storage_busy = bool(busy)
        if self._storage_busy:
            # All three storage actions go dead together, so there is
            # no in-row fallback — ``release_focus_before`` falls back
            # to the window's first focusable control. Do it before
            # any of the three is disabled, otherwise Qt chases.
            for button in (
                self._change_storage_btn,
                self._open_storage_btn,
                self._reset_storage_btn,
            ):
                release_focus_before(button)
        self._change_storage_btn.setEnabled(not self._storage_busy)
        self._open_storage_btn.setEnabled(not self._storage_busy)
        self._reset_storage_btn.setEnabled(
            (not self._storage_busy) and (not self._storage_is_default)
        )
        if status_text is not None:
            self.set_storage_size(status_text)

    # ---- Text scale --------------------------------------------------------

    def set_text_scale(self, scale: float) -> None:
        """Reflect a stored text scale in the combo without re-emitting.

        Called once at startup from ``config.yaml``. Uses the same
        ``_suspend_emit`` guard as ``set_values`` so loading a config
        cannot bounce back out as a user edit.
        """
        self._suspend_emit = True
        try:
            index = self._text_scale_combo.findData(float(scale))
            if index < 0:
                # A hand-edited or clamped config value outside the
                # preset list snaps to the nearest preset rather than
                # silently showing 100% for a stored 1.2.
                index = min(
                    range(len(_TEXT_SCALE_CHOICES)),
                    key=lambda i: abs(
                        _TEXT_SCALE_CHOICES[i][1] - float(scale)
                    ),
                )
            self._text_scale_combo.setCurrentIndex(index)
        finally:
            self._suspend_emit = False

    def text_scale(self) -> float:
        data = self._text_scale_combo.currentData()
        try:
            return float(data)
        except (TypeError, ValueError):
            return 1.0

    def _on_text_scale_changed(self, _index: int) -> None:
        if self._suspend_emit:
            return
        # Re-resolve the stylesheet against the new factor and repaint
        # every widget. Radii and spacing tokens are untouched, so only
        # the type scale moves.
        apply_text_scale(QApplication.instance(), self.text_scale())
        self.save_requested.emit(self.values())

    def values(self) -> Dict[str, Any]:
        return {
            "start_hotkey": self.start_hotkey(),
            "stop_hotkey": self.stop_hotkey(),
            "cancel_hotkey": self.cancel_hotkey(),
            "auto_paste": self.auto_paste(),
            "device": self.device_index(),
            "mode": self.recording_mode(),
            "push_to_talk_key": self.push_to_talk_key(),
            "text_scale": self.text_scale(),
        }

    # ---- internal -----------------------------------------------------------

    def _emit_save(self) -> None:
        if self._suspend_emit:
            return
        # Run validation alongside every save so red-border / tooltip
        # state stays in sync with whatever's currently typed.  We
        # still emit ``save_requested`` even when fields are invalid
        # — backend writes a warning to the Logs view, the UI
        # carries the visual feedback, and the user can keep typing
        # to fix it without the controller getting stuck on a
        # partial edit.
        self._refresh_hotkey_validation()
        self._refresh_accessibility_banner()
        self._refresh_post_event_banner()
        self.save_requested.emit(self.values())

    def _refresh_hotkey_validation(self) -> None:
        """Run :func:`validate_all` over the current field values
        and toggle the ``invalid`` Qt property + tooltip on each
        QLineEdit. Pure UI shuffle — no signals.

        In PTT mode, the active "start" field is actually the PTT
        key edit (not ``_start_edit``), so we feed that value into
        the validator and stamp the result on ``_ptt_edit`` instead.
        """
        mode = self._current_mode()
        if mode == "push_to_talk":
            errors = validate_all(
                start=self._ptt_edit.text(),
                stop="",
                cancel=self._cancel_edit.text(),
                mode="push_to_talk",
            )
            field_pairs = (
                ("start", self._ptt_edit),
                ("cancel", self._cancel_edit),
            )
            # Clear any stale invalid state on the muted Start /
            # Stop fields — they're not in use, validation noise
            # there is misleading.
            for edit in (self._start_edit, self._stop_edit):
                edit.setProperty("invalid", False)
                edit.setToolTip("")
                edit.style().unpolish(edit)
                edit.style().polish(edit)
        else:
            errors = validate_all(
                start=self._start_edit.text(),
                stop=self._stop_edit.text(),
                cancel=self._cancel_edit.text(),
                mode=mode,
            )
            field_pairs = (
                ("start", self._start_edit),
                ("stop", self._stop_edit),
                ("cancel", self._cancel_edit),
            )
            # Clear stale invalid state on the hidden PTT field.
            self._ptt_edit.setProperty("invalid", False)
            self._ptt_edit.setToolTip("")
            self._ptt_edit.style().unpolish(self._ptt_edit)
            self._ptt_edit.style().polish(self._ptt_edit)

        for field_name, edit in field_pairs:
            err = errors.get(field_name)
            edit.setProperty("invalid", bool(err))
            edit.setToolTip(err or "")
            # ``setProperty`` on a styled widget needs an
            # unpolish/polish cycle for Qt to repaint with the new
            # selector match.
            edit.style().unpolish(edit)
            edit.style().polish(edit)

    def _on_auto_paste_toggled(self, _checked: bool) -> None:
        self._refresh_post_event_banner()
        self._emit_save()

    def _refresh_accessibility_banner(self) -> None:
        """Update the macOS Accessibility banner based on current
        listen-event permission state.

        State transitions:

        - ``trusted is None``                                       → hidden
          (non-macOS — no permission gate to worry about)
        - ``trusted is False``                                      → "untrusted"
          ("Grant access" button)
        - ``trusted is True``                                       → hidden
        """
        trusted = is_accessibility_trusted()
        previous = self._last_accessibility_trusted
        self._last_accessibility_trusted = trusted
        if trusted is None:
            self._accessibility_state = "hidden"
            self._accessibility_banner.setVisible(False)
            return
        if self._can_current_mac_hotkey_mode_work_without_banner():
            self._accessibility_state = "hidden"
            self._accessibility_banner.setVisible(False)
            return
        if trusted is False:
            self._accessibility_state = "untrusted"
            # The paragraph names the pane, so the button does not have
            # to. "Grant access" also covers the click falling through
            # to System Settings when macOS refuses to show a prompt.
            self._accessibility_banner.set_message(
                "Global hotkeys won't fire until you allow Lazy to "
                "Text under System Settings → Privacy & Security → "
                "Accessibility.",
                "Grant access",
            )
            self._accessibility_banner.setVisible(True)
            return
        self._accessibility_state = "hidden"
        self._accessibility_banner.setVisible(False)
        if previous is False and trusted is True:
            self.mac_permissions_changed.emit()

    def _can_current_mac_hotkey_mode_work_without_banner(self) -> bool:
        """Return whether the active macOS hotkey mode is already on
        the known-working modifier-only push-to-talk path.

        ``right_cmd`` / ``right_alt`` / similar solo modifiers use
        ``flagsChanged`` rather than a normal combo ``keyDown``
        binding. In practice that path is what the user actually uses
        in push-to-talk mode, and showing the generic "global hotkeys
        won't fire" banner for it is misleading once the workflow is
        demonstrably working.
        """
        if not hasattr(self, "_mode_combo") or not hasattr(self, "_ptt_edit"):
            return False
        if self._current_mode() != "push_to_talk":
            return False
        return is_push_to_talk_solo_key(
            self.push_to_talk_key(), platform="darwin"
        )

    def _on_accessibility_banner_clicked(self) -> None:
        """Banner button dispatch for global-hotkey read access."""
        if self._accessibility_state == "untrusted":
            granted = request_accessibility_access()
            # Even when the CoreGraphics request path exists, macOS
            # can return ``False`` without surfacing a visible prompt
            # (for example after a prior denial). In that case, open
            # the Settings pane explicitly so the click never feels
            # like a no-op.
            if not granted:
                open_accessibility_settings()
            QTimer.singleShot(250, self.refresh_macos_permission_banners)

    def _refresh_mic_banner(self) -> None:
        """Show / hide / restate the macOS Microphone-permission
        banner based on the current TCC status.

        States:

        - ``status is None`` → hidden (non-macOS)
        - ``not_determined`` → "Click to grant" (system prompt
          only fires from the first ``requestAccess``; we wire
          that to the button)
        - ``denied`` / ``restricted`` → "Open Settings"
          (system won't show a fresh prompt — only the toggle in
          System Settings can flip the state)
        - ``authorized`` → hidden
        """
        status = microphone_authorization_status()
        previous = self._last_mic_status
        self._last_mic_status = status
        if status is None:
            self._mic_state = "hidden"
            self._mic_banner.setVisible(False)
            return
        if status == "not_determined":
            self._mic_state = "not_determined"
            self._mic_banner.set_message(
                "macOS hasn't asked for microphone access — recordings "
                "would silently come back empty.",
                "Grant access",
            )
            self._mic_banner.setVisible(True)
            return
        if status in ("denied", "restricted"):
            self._mic_state = "denied"
            self._mic_banner.set_message(
                "Microphone is blocked, so recordings come back empty. "
                "Enable Lazy to Text under System Settings → "
                "Privacy & Security → Microphone.",
                "Open Settings",
            )
            self._mic_banner.setVisible(True)
            return
        self._mic_state = "hidden"
        self._mic_banner.setVisible(False)
        if previous not in (None, "authorized") and status == "authorized":
            self.mac_permissions_changed.emit()

    def _on_mic_banner_clicked(self) -> None:
        """Banner button dispatch — first time fires the system
        prompt, post-deny opens System Settings."""
        if self._mic_state == "not_determined":
            request_microphone_access(
                on_result=self._on_mic_request_completed,
            )
            return
        if self._mic_state == "denied":
            open_microphone_settings()
            return

    def _on_mic_request_completed(self, granted: bool) -> None:
        """Called from a background thread once the user dismisses
        the system Microphone prompt.  Re-render the banner so it
        flips into the appropriate post-prompt state.

        The completion handler runs on a non-Qt thread; touching
        widgets from there crashes Qt. Bounce through a Qt signal so
        the slot is delivered on the GUI thread that owns the view.
        """
        self._mic_request_result.emit(bool(granted))

    def _apply_mic_request_completed(self, granted: bool) -> None:
        del granted
        self._refresh_mic_banner()

    def _refresh_post_event_banner(self) -> None:
        """Render the synthetic-keyboard-event permission banner.

        Only relevant on macOS and only while auto-paste is enabled.
        """
        if not self.auto_paste():
            self._post_event_state = "hidden"
            self._post_event_banner.setVisible(False)
            return
        granted = is_post_event_access_trusted()
        self._last_post_event_trusted = granted
        if granted is None or granted is True:
            self._post_event_state = "hidden"
            self._post_event_banner.setVisible(False)
            return
        self._post_event_state = "untrusted"
        self._post_event_banner_text.setText(
            "macOS hasn't granted keyboard-control access yet — "
            "the app can copy text to the clipboard, but auto-paste "
            "Cmd+V will not reach the focused window until you allow "
            "Lazy to Text under System Settings → Privacy & Security "
            "→ Accessibility."
        )
        self._post_event_banner_button.setText("Allow auto-paste access")
        self._post_event_banner.setVisible(True)

    def _on_post_event_banner_clicked(self) -> None:
        if self._post_event_state != "untrusted":
            return
        granted = request_post_event_access()
        if not granted:
            open_accessibility_settings()
        QTimer.singleShot(250, self.refresh_macos_permission_banners)

    def refresh_macos_permission_banners(self) -> None:
        self._refresh_accessibility_banner()
        self._refresh_mic_banner()
        self._refresh_post_event_banner()

    def showEvent(self, event):  # noqa: N802 — Qt naming
        """Re-check macOS permission banners every time the Settings
        tab becomes visible."""
        super().showEvent(event)
        self.refresh_macos_permission_banners()

    def event(self, event):  # noqa: N802 - Qt naming
        if event.type() == QEvent.WindowActivate:
            self.refresh_macos_permission_banners()
        return super().event(event)

    def _current_mode(self) -> str:
        """Read the active recording mode from the combo box.  Returns
        one of ``"two_keys"`` / ``"toggle"`` / ``"push_to_talk"``."""
        data = self._mode_combo.currentData()
        if data in {"two_keys", "toggle", "push_to_talk"}:
            return data
        return "two_keys"

    def _on_mode_changed(self, _index: int) -> None:
        """User picked a different recording mode in the combo box.

        Apply the visual shuffle (mute / unmute fields, mirror Start
        into Stop for toggle, show or hide PTT field), snapshot
        Stop's previous value when entering toggle mode so we can
        restore on switch-back, then emit save.
        """
        mode = self._current_mode()
        if mode == "toggle":
            # Capture Stop's value before we mirror Start in.
            # Skipped if we're already in toggle (re-emitting the
            # same mode change) — would snapshot a mirror of Start.
            if self._previous_stop_hotkey is None:
                self._previous_stop_hotkey = self._stop_edit.text()
        else:
            # Restore the user's previous Stop value when leaving
            # toggle.  Two_keys honours it directly; push_to_talk
            # keeps it for visual continuity (Stop field is hidden
            # but the value is preserved on disk so switching back
            # to two_keys doesn't reset to defaults).
            if self._previous_stop_hotkey is not None:
                self._stop_edit.setText(self._previous_stop_hotkey)
                self._previous_stop_hotkey = None
        self._apply_mode(mode)
        self._emit_save()

    def _apply_mode(self, mode: str) -> None:
        """Wire field visibility / muting to the active mode.  Pure
        UI shuffle — no signal emission.

        Read-only (rather than disabled) makes it obvious that the
        fields are *deactivated by the current mode*, not broken.
        The ``muted="true"`` Qt property flips the QSS to
        ``color.bg_elevated`` background + ``text_muted`` foreground
        so the visual reads as "currently inactive" rather than a
        normal editable input.

        Field map per mode:

        =================  ==========  ==========  ==========  =======
                           Start       Stop        PTT key     Cancel
        =================  ==========  ==========  ==========  =======
        two_keys           active      active      hidden      active
        toggle             active      muted       hidden      muted
        push_to_talk       muted       muted       active      muted
        =================  ==========  ==========  ==========  =======
        """
        is_toggle = mode == "toggle"
        is_ptt = mode == "push_to_talk"

        # Stop is muted in any mode that doesn't use a separate stop
        # binding — toggle mirrors Start; PTT doesn't have a stop.
        for field in (self._stop_edit, self._cancel_edit):
            muted = is_toggle or is_ptt
            field.setReadOnly(muted)
            field.setProperty("muted", muted)
            field.style().unpolish(field)
            field.style().polish(field)

        # Start is muted in PTT mode (its value isn't used by the
        # listener — the PTT key field is the active binding).
        self._start_edit.setReadOnly(is_ptt)
        self._start_edit.setProperty("muted", is_ptt)
        self._start_edit.style().unpolish(self._start_edit)
        self._start_edit.style().polish(self._start_edit)

        # PTT key field appears only in PTT mode.  Hide both the
        # input and its form-row label so the form's vertical
        # spacing collapses cleanly.
        self._ptt_edit.setVisible(is_ptt)
        if self._ptt_label_widget is not None:
            self._ptt_label_widget.setVisible(is_ptt)

        if is_toggle:
            self._stop_edit.setText(self._start_edit.text())

    def _mirror_start_into_stop(self, new_text: str) -> None:
        """Keep the Stop field synced with Start while toggle-mode
        is on.  No-op in any other mode.

        Bypasses ``_suspend_emit`` because this is a UI mirror, not
        a programmatic load — we explicitly want the user's keystroke
        in Start to ripple through and persist.
        """
        if self._current_mode() == "toggle":
            self._stop_edit.setText(new_text)

    def _on_device_changed(self, _idx: int) -> None:
        self._emit_save()

    # ---- mic test feedback --------------------------------------------------

    def show_mic_test_running(self) -> None:
        # The device combo sits immediately left of this button in the
        # same row, so it is both the nearest control and the one the
        # user's eye is already on. Move focus there before the button
        # is disabled, otherwise Qt picks the Start-hotkey field and
        # the cursor lands inside it.
        release_focus_before(self._test_mic_btn, self._device_combo)
        self._test_mic_btn.setEnabled(False)
        self._test_mic_label.setText("Listening… speak now (3 s)")
        self._test_mic_label.setProperty("role", "muted")
        self._test_mic_label.style().unpolish(self._test_mic_label)
        self._test_mic_label.style().polish(self._test_mic_label)
        # Show the live VU meter for the duration of the test.
        # Controller starts a polling timer to feed it through
        # ``set_mic_test_level`` — without that the bar would just
        # sit at zero.
        self._test_mic_meter.reset()
        self._test_mic_meter.setVisible(True)

    def set_mic_test_level(self, level: float) -> None:
        """Push a fresh amplitude reading into the mic-test VU meter.
        Called by the controller while a test is running. No-op when
        the meter is hidden so a stray late tick can't paint over a
        finished result."""
        if self._test_mic_meter.isVisible():
            self._test_mic_meter.set_level(level)

    def show_mic_test_result(self, peak: float, rms: float) -> None:
        self._test_mic_btn.setEnabled(True)
        # Keep the meter visible and frozen at the peak amplitude
        # — the bar IS the visual "how loud were you" answer, no
        # numeric % needed in the text. ``set_level`` once + no
        # follow-up calls = the peak-and-decay envelope just holds
        # the value indefinitely (decay only fires on subsequent
        # ``set_level`` calls). Reset happens on the next test.
        self._test_mic_meter.setVisible(True)
        self._test_mic_meter.set_level(max(0.0, min(1.0, peak)))

        # Plain English result: descriptive only, no jargon, no
        # mystery numbers. Power users / bug-reporters still get
        # the raw 0–1 ``peak`` and ``rms`` via the tooltip.
        if peak < 0.01:
            text = "No sound detected — check the selected microphone."
            role = "test-result-bad"
        elif peak < 0.08:
            text = (
                "Very quiet. Speak louder or raise the input "
                "level in Windows sound settings."
            )
            role = "test-result-warn"
        else:
            text = "Looks good."
            role = "test-result-good"
        self._test_mic_label.setText(text)
        self._test_mic_label.setToolTip(
            f"peak={peak:.3f}, rms={rms:.3f}\n"
            "(amplitude on a 0–1 scale; peak = loudest sample, "
            "rms = average power)"
        )
        self._test_mic_label.setProperty("role", role)
        self._test_mic_label.style().unpolish(self._test_mic_label)
        self._test_mic_label.style().polish(self._test_mic_label)

    def show_mic_test_error(self, reason: str) -> None:
        self._test_mic_btn.setEnabled(True)
        self._test_mic_meter.setVisible(False)
        self._test_mic_meter.reset()
        self._test_mic_label.setText(f"Test failed: {reason}")
        self._test_mic_label.setProperty("role", "test-result-bad")
        self._test_mic_label.style().unpolish(self._test_mic_label)
        self._test_mic_label.style().polish(self._test_mic_label)
