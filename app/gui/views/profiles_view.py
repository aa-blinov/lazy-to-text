"""Profiles — the named bundles a dictation actually runs.

Post-processing settings are five fields that always change together:
provider, endpoint, model, credential and mode. Making somebody edit
all five to switch from a local model to a cloud one is a form, not a
setting, so this screen makes a bundle the thing you name and switch
between. The Profiles screen edits the bundle; the Transcribe screen
chooses one.

Kept out of Settings on purpose. Settings is a flat list of switches and
the post-processing card is the only part of it with a second dimension —
a list of things you can own several of — and the screen that grew it
into a form-within-a-form was the reason the card's own labels had to be
stretched. One list, one screen, one thing per row.

The editing surface reuses the post-processing card's own widgets and its
``_make_section_card``, so a profile and the flat settings render the
same way. What it does *not* reuse is the checkbox: whether
post-processing runs at all is the app's switch and lives in Settings,
above every profile, because two profiles disagreeing about it is a
setting with no answer.

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


class ProfilesView(QWidget):
    """A list of profiles and an editor for the selected one."""

    #: Emitted when the user edits a field of the open profile. The
    #: payload is one profile's complete dict, not a partial — a
    #: profile is a value, and merging field-by-field in the controller
    #: is how a half-saved profile becomes possible.
    profile_changed = Signal(dict)
    #: Emitted when a different profile is selected.
    selection_changed = Signal(str)
    #: Emitted when the active profile changes from this screen.
    active_changed = Signal(str)
    profile_create_requested = Signal()
    profile_delete_requested = Signal(str)
    profile_duplicate_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProfilesView")

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
            "Profiles",
            "A profile is the model, the server and the wording that "
            "dictated text goes through. Switch on the Transcribe screen, "
            "or pick one to make the default.",
            header_wrapper,
        )
        header_layout.addWidget(self._header)
        outer.addWidget(header_wrapper)

        scroll = QScrollArea(self)
        scroll.setObjectName("ProfilesScrollArea")
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

        # Empty state — a fresh install has exactly one implicit profile
        # and no list, so this is what the user sees before they make
        # anything. A blank column is not an answer.
        self._empty_state = QLabel(
            "No profiles yet. The settings you have now are the "
            "default profile — create another to keep them alongside a "
            "second model.",
            column,
        )
        self._empty_state.setObjectName("ProfilesEmptyState")
        self._empty_state.setProperty("role", "muted")
        self._empty_state.setWordWrap(True)
        column_layout.addWidget(self._empty_state)

        column_layout.addStretch(1)
        scroll.setWidget(column)
        outer.addWidget(scroll, 1)

        self.set_profiles([])

    # ---- construction ---------------------------------------------------

    def _build_picker_card(self) -> QFrame:
        card, form = _make_section_card("Profile", self)

        self._profile_combo = QComboBox(card)
        self._profile_combo.setObjectName("ProfilePickerCombo")
        self._profile_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._profile_combo.currentIndexChanged.connect(self._on_selection_changed)
        form.addRow("Choose", self._profile_combo)

        self._active_radio = QPushButton("Make this the default", card)
        self._active_radio.setObjectName("ProfileMakeDefaultButton")
        self._active_radio.setCheckable(True)
        # A checkable button rather than a radio group: there is one
        # question — "is the open profile the default?" — and a group of
        # radios for it would have to carry off-state handling for no
        # gain.
        self._active_radio.toggled.connect(self._on_active_toggled)
        form.addRow("Default", self._active_radio)

        buttons = QWidget(card)
        buttons_layout = QVBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)

        self._new_btn = QPushButton("New profile", buttons)
        self._new_btn.setObjectName("ProfileNewButton")
        self._new_btn.clicked.connect(self.profile_create_requested)
        buttons_layout.addWidget(self._new_btn)

        self._duplicate_btn = QPushButton("Duplicate", buttons)
        self._duplicate_btn.setObjectName("ProfileDuplicateButton")
        self._duplicate_btn.clicked.connect(
            lambda: self.profile_duplicate_requested.emit(self._current_id)
        )
        buttons_layout.addWidget(self._duplicate_btn)

        self._delete_btn = QPushButton("Delete", buttons)
        self._delete_btn.setObjectName("ProfileDeleteButton")
        # Destructive enough to deserve the muted role the rest of the app
        # uses for that, and never the accent: a button that can delete is
        # not a button the eye should chase.
        self._delete_btn.setProperty("role", "quiet-danger")
        self._delete_btn.clicked.connect(
            lambda: self.profile_delete_requested.emit(self._current_id)
        )
        buttons_layout.addWidget(self._delete_btn)

        form.addRow("", buttons)
        return card

    def _build_editor_card(self) -> QFrame:
        card, form = _make_section_card("Settings", self)

        self._name_edit = QLineEdit(card)
        self._name_edit.setObjectName("ProfileNameEdit")
        self._name_edit.setPlaceholderText("Work, Letters, Quick notes")
        self._name_edit.editingFinished.connect(self._emit_change)
        form.addRow("Name", self._name_edit)

        self._provider_combo = QComboBox(card)
        self._provider_combo.setObjectName("ProfileProviderCombo")
        self._provider_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Provider", self._provider_combo)

        self._base_edit = QLineEdit(card)
        self._base_edit.setObjectName("ProfileBaseEdit")
        self._base_edit.editingFinished.connect(self._emit_change)
        # The privacy warning tracks the address as it is typed, while
        # the *save* waits for focus-out. Those are different questions
        # with different urgency: a warning that only appears once the
        # user has clicked away is a warning that arrives after the
        # decision, whereas every keystroke here spawns a config write.
        self._base_edit.textChanged.connect(self._sync_privacy)
        form.addRow("Server", self._base_edit)

        self._model_edit = QLineEdit(card)
        self._model_edit.setObjectName("ProfileModelEdit")
        self._model_edit.setPlaceholderText("qwen3:8b, or gpt-5.4-mini")
        self._model_edit.editingFinished.connect(self._emit_change)
        form.addRow("Model", self._model_edit)

        self._key_edit = QLineEdit(card)
        self._key_edit.setObjectName("ProfileKeyEdit")
        # Password, for the same reason the Settings card's is: this is
        # the one widget that must never render its value on somebody's
        # shoulder.
        self._key_edit.setEchoMode(QLineEdit.Password)
        self._key_edit.editingFinished.connect(self._emit_change)
        form.addRow("API key", self._key_edit)

        self._mode_combo = QComboBox(card)
        self._mode_combo.setObjectName("ProfileModeCombo")
        self._mode_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._mode_combo.currentIndexChanged.connect(self._emit_change)
        form.addRow("What it does", self._mode_combo)

        self._prompt_edit = QPlainTextEdit(card)
        self._prompt_edit.setObjectName("ProfilePromptEdit")
        self._prompt_edit.setPlaceholderText(
            "Leave empty to use the mode's own wording."
        )
        self._prompt_edit.setFixedHeight(96)
        self._prompt_edit.textChanged.connect(self._emit_change)
        form.addRow("Own wording", self._prompt_edit)

        self._prompt_hint = QLabel(_CUSTOM_PROMPT_HINT, card)
        self._prompt_hint.setObjectName("ProfilePromptHint")
        self._prompt_hint.setProperty("role", "muted")
        self._prompt_hint.setWordWrap(True)
        card.layout().addWidget(self._prompt_hint)

        self._privacy_hint = QLabel("", card)
        self._privacy_hint.setObjectName("ProfilePrivacyHint")
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
        """Show *profiles*, opening on the active one."""
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
        self._profile_combo.clear()
        for profile in self._profiles:
            self._profile_combo.addItem(
                profile.get("name") or profile.get("id", ""),
                userData=profile.get("id", ""),
            )
        index = self._profile_combo.findData(self._current_id)
        self._profile_combo.setCurrentIndex(max(index, 0))

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
            index = self._provider_combo.findData(profile.get("provider", ""))
            self._provider_combo.setCurrentIndex(max(index, 0))
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

        # Deleting the only profile is not an operation — it would leave
        # the app with no way to post-process and no way to undo that.
        # Duplicate and Delete are disabled together for that reason.
        self._delete_btn.setEnabled(len(self._profiles) > 1)
        self._duplicate_btn.setEnabled(have_profile)
        self._active_radio.setEnabled(have_profile)
        self._empty_state.setVisible(not have_profile)

    def _sync_active_button(self) -> None:
        checked = bool(self._profiles) and self._current_id == self._active_id
        self._active_radio.blockSignals(True)
        self._active_radio.setChecked(checked)
        self._active_radio.setText(
            "The default" if checked else "Make this the default"
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

    def _on_selection_changed(self, index: int) -> None:
        if self._suspend_emit or index < 0:
            return
        profile_id = self._profile_combo.itemData(index)
        if profile_id:
            self._open_profile(profile_id)
            self.selection_changed.emit(profile_id)

    def _on_active_toggled(self, checked: bool) -> None:
        if self._suspend_emit or not checked or not self._current_id:
            return
        self._active_id = self._current_id
        self._sync_active_button()
        self.active_changed.emit(self._current_id)

    def _on_provider_changed(self, index: int) -> None:
        if self._suspend_emit or index < 0:
            return
        provider = self._provider_combo.itemData(index)
        from app.llm import default_url_for, known_default_urls

        # Only rewrite the address when what is there is a default this
        # picker knows. A hand-typed endpoint is the user's, and silently
        # replacing it with a cloud default would be the same class of
        # bug as overwriting a saved model name.
        current = self._base_edit.text().strip()
        if not current or current in known_default_urls():
            self._base_edit.setText(default_url_for(provider))
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
            self.profile_changed.emit(payload)