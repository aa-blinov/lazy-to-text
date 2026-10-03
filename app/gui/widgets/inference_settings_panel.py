"""Inline 'Inference settings' panel for the active model card.

Five controls — language / VAD filter / beam size / temperature /
initial prompt — laid out as two compact rows. Emits a single
``settings_changed`` signal whenever any field commits a change so
the controller can persist + push to the live backend in one shot.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class _MultilinePromptEdit(QPlainTextEdit):
    """``QPlainTextEdit`` that mimics ``QLineEdit.editingFinished``.

    Whisper's ``initial_prompt`` is a free-form string — sometimes
    just a comma-list of names, sometimes a paragraph of context.
    A single-line field punishes the latter, so use a 3-row text
    area and emit ``editing_finished`` when focus leaves so the
    controller can persist the change without reacting on every
    keystroke.
    """

    editing_finished = Signal()

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.editing_finished.emit()

from app.inference_settings import InferenceSettings


# Curated subset of the ~99 languages Whisper supports — top
# spoken languages first, ``Auto`` is the default. The dropdown
# shows the human label; the ``data`` field carries the ISO code
# (or ``None`` for auto-detect) that's plumbed into ``transcribe``.
_LANGUAGES: tuple[tuple[str, Optional[str]], ...] = (
    ("Auto-detect", None),
    ("Russian", "ru"),
    ("English", "en"),
    ("Spanish", "es"),
    ("French", "fr"),
    ("German", "de"),
    ("Chinese", "zh"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
    ("Arabic", "ar"),
    ("Hindi", "hi"),
    ("Portuguese", "pt"),
    ("Italian", "it"),
    ("Polish", "pl"),
    ("Dutch", "nl"),
    ("Turkish", "tr"),
    ("Ukrainian", "uk"),
)


class InferenceSettingsPanel(QFrame):
    settings_changed = Signal(InferenceSettings)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("InferenceSettingsPanel")
        self.setProperty("role", "inference-panel")
        self.setFrameShape(QFrame.NoFrame)

        # Programmatic updates suppress the signal so we don't
        # round-trip a save when the controller pre-fills the panel.
        self._suspend_emit = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(8)

        title = QLabel("Inference settings", self)
        title.setProperty("role", "section-header")
        outer.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self._grid = grid
        self._compact = False
        self._language_label = QLabel("Language", self)
        self._beam_label = QLabel("Beam size", self)
        self._temperature_label = QLabel("Temperature", self)
        self._prompt_label = QLabel("Initial prompt", self)

        # Row 0: Language | VAD
        grid.addWidget(self._language_label, 0, 0)
        self._language = QComboBox(self)
        self._language.setObjectName("LanguageCombo")
        for label, code in _LANGUAGES:
            self._language.addItem(label, code)
        self._language.currentIndexChanged.connect(self._on_changed)
        grid.addWidget(self._language, 0, 1)

        self._vad = QCheckBox("VAD filter (skip silence)", self)
        self._vad.setObjectName("VadFilterCheckbox")
        self._vad.toggled.connect(self._on_changed)
        grid.addWidget(self._vad, 0, 2, 1, 2)

        # Row 1: Beam size | Temperature.
        # Strip the up/down arrow buttons from both spinboxes — Qt's
        # QSS support for the spinbox sub-controls is patchy (custom
        # styles disable the native arrows but require a hand-rolled
        # image, otherwise the arrows render as weird stacked
        # widgets). Users still get keyboard ↑/↓ and mouse-wheel
        # scrolling, plus direct typing — all the natural ways to
        # adjust the value.
        grid.addWidget(self._beam_label, 1, 0)
        self._beam = QSpinBox(self)
        self._beam.setObjectName("BeamSizeSpin")
        self._beam.setRange(1, 20)
        self._beam.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._beam.setAlignment(Qt.AlignCenter)
        self._beam.valueChanged.connect(self._on_changed)
        grid.addWidget(self._beam, 1, 1)

        grid.addWidget(self._temperature_label, 1, 2)
        self._temperature = QDoubleSpinBox(self)
        self._temperature.setObjectName("TemperatureSpin")
        self._temperature.setRange(0.0, 1.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setDecimals(1)
        self._temperature.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._temperature.setAlignment(Qt.AlignCenter)
        self._temperature.valueChanged.connect(self._on_changed)
        grid.addWidget(self._temperature, 1, 3)

        # Row 2: Initial prompt — full-width multiline so structured
        # context (term lists, names, paragraph descriptions) doesn't
        # fight a single-line field.
        prompt_label = self._prompt_label
        # Top-align the label so it sits flush with the first line of
        # the multiline edit instead of vertically centring against
        # its 3-row height.
        prompt_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        grid.addWidget(prompt_label, 2, 0)
        self._prompt = _MultilinePromptEdit(self)
        self._prompt.setObjectName("InitialPromptEdit")
        self._prompt.setPlaceholderText(
            "Names / terms / context Whisper should recognise — "
            "e.g. \"Anthropic, Claude, ctranslate2. Speakers: Алексей.\""
        )
        # Keep the widget compact — three visible lines is plenty for
        # a few sentences without dominating the card. The height is
        # derived from the font, so it is recomputed on a font change
        # rather than frozen at construction: the app's text scale is
        # applied by re-resolving the stylesheet, and a fixed pixel
        # height would have clipped lines two and three at 175%.
        self._resize_prompt()
        self._prompt.editing_finished.connect(self._on_changed)
        grid.addWidget(self._prompt, 2, 1, 1, 3)

        outer.addLayout(grid)
        self._place(False)

    # ---- responsive structure ------------------------------------------------

    def _place(self, compact: bool) -> None:
        """Put the controls in the two-column or the one-column grid.

        The paired grid is the better layout and is the default, but it
        has a hard floor: at the 900px window minimum with the type scale
        at 175%, the four field labels plus the VAD sentence
        ("VAD filter (skip silence)" — 269px on its own) need more width
        than the card can hand out, and the card — which cannot shrink
        below its content — pushed the whole Models view 19px into a
        horizontal overflow.

        So the structure is chosen from the panel's own available width,
        never from a device or window-size list. One column costs
        vertical space, which this panel can spare: it lives at the
        bottom of a card in a vertical scroll area.
        """
        if compact == self._compact:
            return
        self._compact = compact
        grid = self._grid
        widgets = (
            self._language_label, self._language, self._vad,
            self._beam_label, self._beam,
            self._temperature_label, self._temperature,
            self._prompt_label, self._prompt,
        )
        for widget in widgets:
            grid.removeWidget(widget)

        if compact:
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(3, 0)
            grid.addWidget(self._language_label, 0, 0)
            grid.addWidget(self._language, 0, 1)
            grid.addWidget(self._vad, 1, 0, 1, 2)
            grid.addWidget(self._beam_label, 2, 0)
            grid.addWidget(self._beam, 2, 1)
            grid.addWidget(self._temperature_label, 3, 0)
            grid.addWidget(self._temperature, 3, 1)
            grid.addWidget(self._prompt_label, 4, 0)
            grid.addWidget(self._prompt, 4, 1, 1, 2)
        else:
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(3, 1)
            grid.addWidget(self._language_label, 0, 0)
            grid.addWidget(self._language, 0, 1)
            grid.addWidget(self._vad, 0, 2, 1, 2)
            grid.addWidget(self._beam_label, 1, 0)
            grid.addWidget(self._beam, 1, 1)
            grid.addWidget(self._temperature_label, 1, 2)
            grid.addWidget(self._temperature, 1, 3)
            grid.addWidget(self._prompt_label, 2, 0)
            grid.addWidget(self._prompt, 2, 1, 1, 3)

    def _two_column_floor(self) -> int:
        """Width below which the paired grid cannot lay itself out.

        The sum of the two widest label+control pairs, plus the VAD
        sentence that has to sit on one line, plus the grid's own
        spacing. Measured from the widgets rather than hard-coded, so it
        follows the type scale instead of assuming one.
        """
        margins = self._grid.contentsMargins()
        h_gap = self._grid.horizontalSpacing()
        v_gap = self._grid.verticalSpacing()
        left = (
            self._beam_label.sizeHint().width()
            + h_gap
            + self._beam.sizeHint().width()
        )
        right = (
            self._temperature_label.sizeHint().width()
            + h_gap
            + self._temperature.sizeHint().width()
        )
        widest_pair = max(left, right)
        return (
            margins.left()
            + widest_pair
            + h_gap
            + right
            + max(self._vad.sizeHint().width(), self._language.sizeHint().width())
            + margins.right()
            + v_gap  # room for the rows themselves
        )

    def _resize_prompt(self) -> None:
        """Three text lines plus breathing room, at the current font."""
        line_spacing = self._prompt.fontMetrics().lineSpacing()
        self._prompt.setFixedHeight(int(line_spacing * 3 + 16))

    def _recompute_structure(self) -> None:
        self._resize_prompt()
        margins = self._grid.contentsMargins()
        available = self.width() - margins.left() - margins.right()
        if available <= 0:
            return  # pre-layout: nothing to decide yet
        self._place(available < self._two_column_floor())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._recompute_structure()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().changeEvent(event)
        # Re-resolving the stylesheet (which is how the text scale is
        # applied) arrives as a font change, not a resize.
        if event.type() == QEvent.Type.FontChange:
            self._recompute_structure()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        # A panel revealed for the first time can reach its final width
        # without a resize ever being delivered, so decide once here too.
        self._recompute_structure()

    # ---- public API ---------------------------------------------------------

    def set_settings(self, settings: InferenceSettings) -> None:
        """Mirror ``settings`` onto the controls without firing the
        ``settings_changed`` signal — used by the controller when it
        pre-fills the panel from config."""
        self._suspend_emit = True
        try:
            target = settings.language
            for i in range(self._language.count()):
                if self._language.itemData(i) == target:
                    self._language.setCurrentIndex(i)
                    break
            else:
                # Unknown code (e.g. ``"sw"``); fall back to Auto.
                self._language.setCurrentIndex(0)
            self._vad.setChecked(bool(settings.vad_filter))
            self._beam.setValue(int(settings.beam_size))
            self._temperature.setValue(float(settings.temperature))
            self._prompt.setPlainText(settings.initial_prompt or "")
        finally:
            self._suspend_emit = False

    def set_enabled_for_engine(self, enabled: bool, reason: str = "") -> None:
        """Greys out every control — used for engines (GigaAM) that
        don't accept any of these knobs at inference time. Optional
        ``reason`` becomes the panel's tooltip so the user knows why."""
        for widget in (
            self._language,
            self._vad,
            self._beam,
            self._temperature,
            self._prompt,
        ):
            widget.setEnabled(bool(enabled))
        if reason:
            self.setToolTip(reason)
        else:
            self.setToolTip("")

    def values(self) -> InferenceSettings:
        return InferenceSettings(
            language=self._language.currentData(),
            vad_filter=self._vad.isChecked(),
            initial_prompt=(self._prompt.toPlainText().strip() or None),
            beam_size=int(self._beam.value()),
            temperature=float(self._temperature.value()),
        )

    # ---- internal -----------------------------------------------------------

    def _on_changed(self, *_args) -> None:
        if self._suspend_emit:
            return
        self.settings_changed.emit(self.values())
