"""Presets — the named bundles a dictation actually runs.

Post-processing settings are five fields that always change together:
provider, endpoint, model, credential and mode. Making somebody edit
all five to switch from a local model to a cloud one is a form, not a
setting, so this screen makes a bundle the thing you name and switch
between. The Presets screen edits the bundle; the Transcribe screen
chooses one.

**Not called "profile".** The word comes from accounts and logins, where
a profile is a person, and here there are usually two and none of them
is anybody. "Preset" says what it is: a prepared thing you switch
between. The rename cost nothing — no data moved — because the config
key is still ``llm.profiles`` and that is never shown to anyone.

Settings now shows only the switch and a line naming the preset in
use. This screen is the single place these five fields are edited,
which is what makes the word unnecessary: a user who meets two editors
for one setting needs a concept to tell them apart, and a user who
meets one does not.

The view is a pure form. It emits what the user did and the controller
writes it; nothing here touches the config file or the network, which is
what lets the whole screen be tested without a config manager.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.smooth_scroll import apply_smooth_scroll
from app.gui.views._section_card import _make_section_card
from app.gui.widgets.page_header import PageHeader

#: Shown above the prompt editor. Says what happens to a custom prompt,
#: because the alternative — that the user has to guess — is the reason
#: somebody writes a prompt promising something the app will not do.
_CUSTOM_PROMPT_HINT = (
    "Your own instruction, used instead of the mode above. Numbers are "
    "still written as digits and the language is still preserved — those "
    "two are the app's promise, not the mode's."
)


class PresetsView(QWidget):
    """A list of presets and an editor for the selected one."""

    #: Emitted when the user edits a field of the open profile. The
    #: payload is one profile's complete dict, not a partial — a
    #: profile is a value, and merging field-by-field in the controller
    #: is how a half-saved profile becomes possible.
    preset_changed = Signal(dict)
    #: Emitted when a different profile is selected.
    preset_selected = Signal(str)
    #: Emitted when the active profile changes from this screen.
    preset_activated = Signal(str)
    preset_create_requested = Signal()
    preset_delete_requested = Signal(str)
    preset_duplicate_requested = Signal(str)
    #: "Discard the key of the open preset." Its own signal rather than a
    #: field edit, so the write happens even when the user never leaves
    #: focus on the box.
    preset_key_reset_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("PresetsView")

        # While populating fields programmatically, so a load does not
        # read as the user editing.
        self._suspend_emit = False
        self._profiles: List[Dict[str, Any]] = []
        self._current_id: str = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header_wrapper = QWidget(self)
        header_layout = QVBoxLayout(header_wrapper)
        header_layout.setContentsMargins(28, 22, 28, 14)
        header_layout.setSpacing(4)
        self._header = PageHeader(
            "Presets",
            "A preset is the model, the server and the wording that "
            "dictated text goes through. Keep one for work and one for "
            "anything else — then switch on the Transcribe screen.",
            header_wrapper,
        )
        header_layout.addWidget(self._header)
        outer.addWidget(header_wrapper)

        scroll = QScrollArea(self)
        scroll.setObjectName("PresetsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        apply_smooth_scroll(scroll)

        column = QWidget(scroll)
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(28, 0, 28, 28)
        column_layout.setSpacing(16)

        column_layout.addWidget(self._build_picker_card())
        column_layout.addWidget(self._build_editor_card())

        # Empty state. In practice a fresh install never reaches this:
        # the controller materialises the existing settings as the first
        # preset on launch, because making somebody press New to start
        # using a screen that is showing them their own configuration is
        # backwards. It stays for the case where every preset was
        # deleted from the file.
        self._empty_state = QLabel(
            "No presets left. Everything is back to what post-processing "
            "uses before you make any — a local model on this machine.",
            column,
        )
        self._empty_state.setObjectName("PresetsEmptyState")
        self._empty_state.setProperty("role", "muted")
        self._empty_state.setWordWrap(True)
        column_layout.addWidget(self._empty_state)

        column_layout.addStretch(1)
        scroll.setWidget(column)
        outer.addWidget(scroll, 1)

        self.set_profiles([])

    # ---- construction ---------------------------------------------------

    def _build_picker_card(self) -> QFrame:
        card, form = _make_section_card("Preset", self)

        self._preset_combo = QComboBox(card)
        self._preset_combo.setObjectName("PresetPickerCombo")
        self._preset_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        form.addRow("Choose", self._preset_combo)

        self._active_radio = QPushButton("Use this one by default", card)
        self._active_radio.setObjectName("PresetMakeDefaultButton")
        self._active_radio.setCheckable(True)
        # A checkable button rather than a radio group: there is one
        # question — "is the open preset the one everything uses?" — and a
        # group of radios for it would have to carry off-state handling
        # for no gain.
        self._active_radio.toggled.connect(self._on_default_toggled)
        form.addRow("Used by default", self._active_radio)

        # One row, not a stack: three short labels stacked full-width
        # made the least likely of them (Delete) the biggest thing on
        # the card.
        buttons = QWidget(card)
        # A layout container, not a surface — see the ``role="plain"``
        # rule in base.qss. Without it this paints the window ground
        # inside the card.
        buttons.setProperty("role", "plain")
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        # 16, not the 8 the rest of the card uses. ``radius.sm`` is also
        # 8, so an 8px gap puts the straight edge of one button 8px from
        # the straight edge of the next while their 8px corners eat the
        # rest — measured, they read as touching at any card width.
        buttons_layout.setSpacing(16)

        self._new_btn = QPushButton("New preset", buttons)
        self._new_btn.setObjectName("PresetNewButton")
        self._new_btn.clicked.connect(self.preset_create_requested)
        buttons_layout.addWidget(self._new_btn)

        self._duplicate_btn = QPushButton("Duplicate", buttons)
        self._duplicate_btn.setObjectName("PresetDuplicateButton")
        self._duplicate_btn.clicked.connect(
            lambda: self.preset_duplicate_requested.emit(self._current_id)
        )
        buttons_layout.addWidget(self._duplicate_btn)

        self._delete_btn = QPushButton("Delete", buttons)
        self._delete_btn.setObjectName("PresetDeleteButton")
        # Destructive enough to deserve the muted role the rest of the app
        # uses for that, and never the accent: a button that can delete is
        # not a button the eye should chase.
        self._delete_btn.setProperty("role", "quiet-danger")
        self._delete_btn.clicked.connect(
            lambda: self.preset_delete_requested.emit(self._current_id)
        )
        buttons_layout.addWidget(self._delete_btn)

        form.addRow("", buttons)
        return card

    def _build_editor_card(self) -> QFrame:
        card, form = _make_section_card("Settings", self)

        self._name_edit = QLineEdit(card)
        self._name_edit.setObjectName("PresetNameEdit")
        self._name_edit.setPlaceholderText("Work, Letters, Quick notes")
        self._name_edit.editingFinished.connect(self._emit_change)
        form.addRow("Name", self._name_edit)

        self._provider_combo = QComboBox(card)
        self._provider_combo.setObjectName("PresetProviderCombo")
        self._provider_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Provider", self._provider_combo)

        self._base_edit = QLineEdit(card)
        self._base_edit.setObjectName("PresetBaseEdit")
        self._base_edit.editingFinished.connect(self._emit_change)
        # The privacy warning tracks the address as it is typed, while
        # the *save* waits for focus-out. Those are different questions
        # with different urgency: a warning that only appears once the
        # user has clicked away is a warning that arrives after the
        # decision, whereas every keystroke here spawns a config write.
        self._base_edit.textChanged.connect(self._sync_privacy)
        form.addRow("Server", self._base_edit)

        self._model_edit = QLineEdit(card)
        self._model_edit.setObjectName("PresetModelEdit")
        self._model_edit.setPlaceholderText("qwen3:8b, or gpt-5.4-mini")
        self._model_edit.editingFinished.connect(self._emit_change)
        form.addRow("Model", self._model_edit)

        self._key_edit = QLineEdit(card)
        self._key_edit.setObjectName("PresetKeyEdit")
        # Password: this is the one widget that must never render its
        # value on somebody's shoulder.
        self._key_edit.setEchoMode(QLineEdit.Password)
        self._key_edit.editingFinished.connect(self._emit_change)
        self._key_edit.textChanged.connect(
            lambda _t: self._sync_enabled()
            if not self._suspend_emit
            else None
        )

        self._clear_key_btn = QPushButton("Clear", card)
        self._clear_key_btn.setObjectName("PresetClearKeyButton")
        # Emits rather than clearing the field itself. A field that
        # clears itself looks like an accident, and the value has to be
        # written even when the user never leaves focus on the box —
        # same two-step shape the Hugging Face token has had all along.
        self._clear_key_btn.clicked.connect(self._on_clear_key_clicked)

        # The key and its discard on one row. As two rows the button
        # stretched the full width of the card, which reads as the most
        # important control in it — and it is the one that is disabled
        # until there is something to throw away.
        key_row = QWidget(card)
        # Same reason as the buttons row above.
        key_row.setProperty("role", "plain")
        key_row_layout = QHBoxLayout(key_row)
        key_row_layout.setContentsMargins(0, 0, 0, 0)
        key_row_layout.setSpacing(8)
        key_row_layout.addWidget(self._key_edit, 1)
        key_row_layout.addWidget(self._clear_key_btn)
        form.addRow("API key", key_row)

        self._mode_combo = QComboBox(card)
        self._mode_combo.setObjectName("PresetModeCombo")
        self._mode_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._mode_combo.currentIndexChanged.connect(self._emit_change)
        form.addRow("What it does", self._mode_combo)

        self._prompt_edit = QPlainTextEdit(card)
        self._prompt_edit.setObjectName("PresetPromptEdit")
        self._prompt_edit.setPlaceholderText(
            "Leave empty to use the mode's own wording."
        )
        self._prompt_edit.setFixedHeight(96)
        self._prompt_edit.textChanged.connect(self._emit_change)
        form.addRow("Own wording", self._prompt_edit)

        self._prompt_hint = QLabel(_CUSTOM_PROMPT_HINT, card)
        self._prompt_hint.setObjectName("PresetPromptHint")
        self._prompt_hint.setProperty("role", "muted")
        self._prompt_hint.setWordWrap(True)
        card.layout().addWidget(self._prompt_hint)

        self._privacy_hint = QLabel("", card)
        self._privacy_hint.setObjectName("PresetPrivacyHint")
        self._privacy_hint.setProperty("role", "muted")
        self._privacy_hint.setWordWrap(True)
        card.layout().addWidget(self._privacy_hint)

        return card

    # ---- population -----------------------------------------------------

    def set_profiles(
        self,
        profiles: List[Dict[str, Any]],
        active_id: str = "",
    ) -> None:
        """Show *profiles*, opening on the active one.

        Named ``profiles`` still: that is the config key it reads and
        writes, and renaming stored data to match a screen title would
        break every file already written for no reader-visible gain."""
        self._suspend_emit = True
        try:
            self._profiles = [dict(p) for p in profiles]
            self._active_id = active_id

            from app.llm import PROVIDERS, default_url_for

            self._provider_combo.clear()
            for provider in PROVIDERS:
                self._provider_combo.addItem(provider.label, userData=provider.id)

            from app.llm import MODES

            self._mode_combo.clear()
            for mode in MODES:
                self._mode_combo.addItem(mode.label, userData=mode.id)

            if not self._profiles:
                # Nothing to edit. An editor full of the previous
                # profile's values is a lie: they would be saved to
                # whatever gets created next.
                self._current_id = ""
                self._clear_editor()
                self._populate_combo()
                self._sync_enabled()
                return

            # Decide what to open *before* filling the picker. The
            # picker positions itself on ``_current_id``, so choosing
            # after populating leaves the dropdown showing one profile
            # while the editor shows another — measured here as a
            # controller reload landing on "A" with "B" in the fields.
            available = {p.get("id") for p in self._profiles}
            if self._current_id not in available:
                self._current_id = (
                    active_id
                    if active_id in available
                    else self._profiles[0]["id"]
                )
            self._populate_combo()
            self._open_profile(self._current_id)
        finally:
            self._suspend_emit = False

    def _populate_combo(self) -> None:
        self._preset_combo.clear()
        for profile in self._profiles:
            self._preset_combo.addItem(
                profile.get("name") or profile.get("id", ""),
                userData=profile.get("id", ""),
            )
        index = self._preset_combo.findData(self._current_id)
        self._preset_combo.setCurrentIndex(max(index, 0))

    def _clear_editor(self) -> None:
        for widget in (
            self._name_edit,
            self._base_edit,
            self._model_edit,
            self._key_edit,
        ):
            widget.clear()
        self._provider_combo.setCurrentIndex(0)
        self._mode_combo.setCurrentIndex(0)
        self._prompt_edit.clear()
        self._privacy_hint.setText("")

    def _current_profile(self) -> Optional[Dict[str, Any]]:
        for profile in self._profiles:
            if profile.get("id") == self._current_id:
                return profile
        return None

    def open_preset(self, profile_id: str) -> None:
        """Show *profile_id*, moving the picker to it as well.

        Public because the controller creates presets and then has to
        land the user on the new one. Without this, pressing New
        re-opened whichever preset was already active and appeared to
        do nothing.
        """
        if any(p.get("id") == profile_id for p in self._profiles):
            self._current_id = profile_id
            self._populate_combo()
            self._open_profile(profile_id)

    def _select_provider(self, provider_id: str) -> None:
        """Show *provider_id*, landing on Custom when it is unknown.

        A provider this build does not know — named by a newer build, or
        typed by hand into the config — has to land on Custom rather
        than on the first row. Landing on Ollama instead would show a
        card claiming the model runs on this machine, and then post to
        somebody else's server.
        """
        from app.llm import PROVIDER_CUSTOM

        index = self._provider_combo.findData(provider_id)
        if index < 0:
            index = self._provider_combo.findData(PROVIDER_CUSTOM)
        self._provider_combo.setCurrentIndex(max(index, 0))

    def _open_profile(self, profile_id: str) -> None:
        profile = next(
            (p for p in self._profiles if p.get("id") == profile_id), None
        )
        if profile is None:
            self._clear_editor()
            self._sync_enabled()
            return

        self._current_id = profile_id
        self._suspend_emit = True
        try:
            self._name_edit.setText(profile.get("name", ""))
            self._select_provider(str(profile.get("provider") or ""))
            self._base_edit.setText(profile.get("base_url", ""))
            self._model_edit.setText(profile.get("model", ""))
            self._key_edit.setText(profile.get("api_key", ""))
            mode_index = self._mode_combo.findData(profile.get("mode", ""))
            self._mode_combo.setCurrentIndex(max(mode_index, 0))
            self._prompt_edit.setPlainText(profile.get("custom_prompt", ""))
            self._sync_enabled()
            self._sync_active_button()
            self._sync_privacy()
        finally:
            self._suspend_emit = False

    def _sync_enabled(self) -> None:
        have_profile = bool(self._profiles)
        for widget in (
            self._name_edit,
            self._base_edit,
            self._model_edit,
            self._key_edit,
            self._provider_combo,
            self._mode_combo,
            self._prompt_edit,
        ):
            widget.setEnabled(have_profile)

        # Deleting the only preset is not an operation — it would leave
        # the app with no way to post-process and no way to undo that.
        # Duplicate and Delete are disabled together for that reason.
        self._delete_btn.setEnabled(len(self._profiles) > 1)
        # A discard button with nothing to discard is noise, and the key
        # field is empty on a fresh install.
        self._clear_key_btn.setEnabled(bool(self._key_edit.text()))
        self._duplicate_btn.setEnabled(have_profile)
        self._active_radio.setEnabled(have_profile)
        self._empty_state.setVisible(not have_profile)

    def _sync_active_button(self) -> None:
        checked = bool(self._profiles) and self._current_id == self._active_id
        self._active_radio.blockSignals(True)
        self._active_radio.setChecked(checked)
        self._active_radio.setText(
            "In use by default" if checked else "Use this one by default"
        )
        self._active_radio.blockSignals(False)

    def _sync_privacy(self) -> None:
        from app.llm import is_local_url

        url = self._base_edit.text().strip()
        if not url:
            from app.llm import default_url_for

            provider = self._provider_combo.currentData() or "ollama"
            url = default_url_for(provider)

        if is_local_url(url):
            self._privacy_hint.setText(
                "Runs on this machine. No API key is needed and the text "
                "does not leave."
            )
        else:
            self._privacy_hint.setText(
                "Runs on a remote server: the dictated text is sent there, "
                "along with the key."
            )

    # ---- events ---------------------------------------------------------

    def _on_preset_selected(self, index: int) -> None:
        if self._suspend_emit or index < 0:
            return
        profile_id = self._preset_combo.itemData(index)
        if profile_id:
            self._open_profile(profile_id)
            self.preset_selected.emit(profile_id)

    def _on_default_toggled(self, checked: bool) -> None:
        if self._suspend_emit or not checked or not self._current_id:
            return
        self._active_id = self._current_id
        self._sync_active_button()
        self.preset_activated.emit(self._current_id)

    def _on_provider_changed(self, index: int) -> None:
        if self._suspend_emit or index < 0:
            return
        from app.llm import PROVIDER_CUSTOM, default_url_for, known_default_urls

        chosen = self._provider_combo.itemData(index)
        current = self._base_edit.text().strip()
        # Custom stands for an address typed by hand, and has no default
        # to move to — and rewriting one would be the same class of bug
        # as overwriting a saved model name.
        if chosen != PROVIDER_CUSTOM and (
            not current or current in known_default_urls()
        ):
            self._base_edit.setText(default_url_for(chosen))
        self._sync_privacy()
        self._emit_change()

    def values(self) -> Optional[Dict[str, Any]]:
        """The open profile's fields, or None when there is none.

        The whole profile rather than a diff, so the controller cannot
        write a field this editor never showed.
        """
        if not self._current_id:
            return None
        return {
            "id": self._current_id,
            "name": self._name_edit.text().strip() or self._current_id,
            "provider": self._provider_combo.currentData() or "ollama",
            "base_url": self._base_edit.text().strip(),
            "model": self._model_edit.text().strip(),
            "api_key": self._key_edit.text(),
            "mode": self._mode_combo.currentData() or "clean",
            "custom_prompt": self._prompt_edit.toPlainText(),
        }

    def _on_clear_key_clicked(self) -> None:
        """Discard the open preset's key.

        The field is emptied *and* the write is announced, rather than
        the field merely being emptied: a key that stayed in the file
        after the box looked empty is the kind of state nobody can
        look at and reason about.
        """
        if self._suspend_emit or not self._current_id:
            return
        self._key_edit.clear()
        self._sync_privacy()
        self.preset_key_reset_requested.emit(self._current_id)

    def _emit_change(self) -> None:
        """Commit the open profile.

        Bound to ``editingFinished`` rather than ``textChanged`` on the
        line edits, matching every other auto-saving field in this app.
        Per keystroke it would spawn a config write — the config manager
        writes on its own thread — for a value that is not finished yet.
        """
        if self._suspend_emit:
            return
        self._sync_privacy()
        payload = self.values()
        if payload is not None:
            self.preset_changed.emit(payload)