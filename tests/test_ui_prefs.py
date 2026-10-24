"""The interface preferences the runtime stores: theme, palette, language, text scale."""

from __future__ import annotations

import pytest

from app import ui_prefs


@pytest.mark.parametrize(
    ("value", "expected"),
    [("ru", "ru"), (" RU ", "ru"), ("en", "en"), ("fr", "en"), ("", "en"), (None, "en")],
)
def test_unknown_or_empty_languages_fall_back_to_english(value, expected):
    assert ui_prefs.normalise_language(value) == expected


def test_an_unknown_theme_or_palette_falls_back_to_the_default():
    assert ui_prefs.normalise_theme("neon") == ui_prefs.DEFAULT_THEME
    assert ui_prefs.normalise_palette("neon") == ui_prefs.DEFAULT_PALETTE
    assert ui_prefs.normalise_theme("dark") == "dark"
    assert ui_prefs.normalise_palette(ui_prefs.PALETTES[-1]) == ui_prefs.PALETTES[-1]


@pytest.mark.parametrize("value", [None, "abc", float("nan")])
def test_a_text_scale_that_is_not_a_number_is_one(value):
    assert ui_prefs.clamp_text_scale(value) == 1.0


def test_the_text_scale_is_held_inside_its_range():
    assert ui_prefs.clamp_text_scale(0.1) == ui_prefs.TEXT_SCALE_MIN
    assert ui_prefs.clamp_text_scale(9) == ui_prefs.TEXT_SCALE_MAX
