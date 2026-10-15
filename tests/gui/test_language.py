"""UI language: the catalogue loads, and every switch reaches live widgets.

Each test ends on English, because the translator is process-wide and the
rest of the suite assumes the source strings.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication

from app.language import (
    DEFAULT_LANGUAGE,
    apply_language,
    current_language,
    normalise_language,
)


@pytest.fixture(autouse=True)
def _english_after(qapp):
    yield
    apply_language(qapp, DEFAULT_LANGUAGE)


def _tr(context: str, source: str) -> str:
    return QCoreApplication.translate(context, source)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("ru", "ru"), (" RU ", "ru"), ("en", "en"), ("fr", "en"), ("", "en"), (None, "en")],
)
def test_unknown_or_empty_languages_fall_back_to_english(value, expected):
    assert normalise_language(value) == expected


def test_russian_catalogue_loads_and_english_is_restored(qapp):
    assert apply_language(qapp, "ru") == "ru"
    assert current_language() == "ru"
    assert _tr("Sidebar", "Models") == "Модели"

    assert apply_language(qapp, "en") == "en"
    assert _tr("Sidebar", "Models") == "Models"


def test_a_missing_catalogue_leaves_the_ui_in_english(qapp, monkeypatch):
    import app.language as language

    monkeypatch.setattr(
        language, "resolve_asset_path",
        lambda _rel: "/nonexistent/app_xx.qm",
    )
    assert apply_language(qapp, "ru") == "en"
    assert _tr("Sidebar", "Models") == "Models"


def test_the_sidebar_relabels_itself_when_the_language_changes(qapp, qtbot):
    from app.gui.widgets.sidebar import Sidebar

    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    assert sidebar.label_for("models") == "Models"

    apply_language(qapp, "ru")
    assert sidebar.label_for("models") == "Модели"
    assert sidebar._list.item(0).text() == "Модели"

    apply_language(qapp, "en")
    assert sidebar._list.item(0).text() == "Models"


def test_the_tray_menu_and_tooltip_follow_the_language(qapp):
    from app.gui.widgets.tray_icon import AppTrayIcon

    tray = AppTrayIcon(parent=qapp)
    tray.set_state("recording")
    assert tray._show_action.text() == "Show window"
    assert tray.toolTip() == "Lazy to Text: recording"

    apply_language(qapp, "ru")
    assert tray._show_action.text() == "Показать окно"
    assert tray._quit_action.text() == "Выйти"
    assert tray.toolTip() == "Lazy to Text: запись"

    apply_language(qapp, "en")
    assert tray._show_action.text() == "Show window"


def test_the_overlay_copy_is_retranslated_while_it_is_up(qapp, qtbot):
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    overlay.set_state("recording")
    assert overlay._title.text() == "Recording"

    apply_language(qapp, "ru")
    assert overlay._title.text() == "Запись"
    assert overlay._body.text() == "Говорите"

    apply_language(qapp, "en")
    assert overlay._title.text() == "Recording"


def test_the_runtime_shortcut_is_put_into_the_translated_title_as_given(qapp, qtbot):
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    apply_language(qapp, "ru")
    overlay.show_delivery("copied", "Ctrl+V", "текст")
    # The shortcut came from the platform, so it is substituted, not looked up.
    assert overlay._title.text() == "Скопировано — нажмите Ctrl+V"
    # The transcript is the user's own words and is never translated.
    assert overlay._body.text() == "текст"


def test_the_settings_language_combo_applies_and_persists(qapp, qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    saved = []
    view.save_requested.connect(saved.append)

    apply_language(qapp, "ru")
    assert view._language_label.text() == "Язык"
    apply_language(qapp, "en")
    assert view._language_label.text() == "Language"

    view.set_language("ru")
    assert view.language() == "ru"
    assert saved == [], "loading a stored value is not a user edit"

    view._language_combo.setCurrentIndex(view._language_combo.findData("en"))
    assert current_language() == "en"
    assert saved and saved[-1]["language"] == "en"


def test_the_topbar_model_pill_and_cancel_button_follow_the_language(qapp, qtbot):
    from app.gui.widgets.topbar import TopBar

    bar = TopBar()
    qtbot.addWidget(bar)
    bar.set_active_model("GigaAM v3")
    assert bar._model_pill.text() == "Current model: GigaAM v3"

    apply_language(qapp, "ru")
    assert bar._model_pill.text() == "Модель: GigaAM v3"
    assert bar._cancel_load_button.text() == "Отмена"

    apply_language(qapp, "en")
    assert bar._model_pill.text() == "Current model: GigaAM v3"
    assert bar._cancel_load_button.text() == "Cancel"


@pytest.mark.parametrize(
    ("n", "form"),
    [(1, "one"), (21, "one"), (2, "few"), (23, "few"), (5, "many"),
     (11, "many"), (12, "many"), (14, "many"), (100, "many"), (111, "many")],
)
def test_russian_plural_forms(n, form):
    from app.language import ru_plural_form

    assert ru_plural_form(n) == form


def test_tr_format_fills_placeholders_by_number(qapp):
    from app.language import tr_format

    apply_language(qapp, "ru")
    assert tr_format("ShortcutsView", "Test failed: %1", "mic offline") == (
        "Проверка не удалась: mic offline"
    )
    apply_language(qapp, "en")
    assert tr_format("ShortcutsView", "Test failed: %1", "mic offline") == (
        "Test failed: mic offline"
    )


def test_tr_count_uses_the_russian_form_for_the_number(qapp):
    from app.language import tr_count

    forms = dict(one="%1 entry", few="%1 entries (few)", many="%1 entries")
    apply_language(qapp, "ru")
    assert tr_count("HistoryView", 1, **forms) == "1 запись"
    assert tr_count("HistoryView", 3, **forms) == "3 записи"
    assert tr_count("HistoryView", 7, **forms) == "7 записей"
    apply_language(qapp, "en")
    assert tr_count("HistoryView", 1, **forms) == "1 entry"
    assert tr_count("HistoryView", 3, **forms) == "3 entries"
