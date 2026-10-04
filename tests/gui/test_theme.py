"""Tests for the theme tokens and QSS loader."""

import pytest


def test_tokens_expose_required_color_keys():
    from app.gui.theme import TOKENS

    required = {
        "bg_primary",
        "bg_secondary",
        "bg_elevated",
        "accent",
        "text_primary",
        "text_secondary",
        "border",
        "success",
        "danger",
        "warning",
    }
    assert required.issubset(TOKENS.colors.keys())


def test_tokens_expose_spacing_and_radius():
    from app.gui.theme import TOKENS

    for key in ("xs", "sm", "md", "lg", "xl"):
        assert key in TOKENS.spacing, f"missing spacing.{key}"
        assert isinstance(TOKENS.spacing[key], int)

    for key in ("sm", "md", "lg"):
        assert key in TOKENS.radius
        assert isinstance(TOKENS.radius[key], int)


def test_tokens_expose_font_family_and_sizes():
    from app.gui.theme import TOKENS

    assert isinstance(TOKENS.fonts["family"], str)
    assert TOKENS.fonts["family"]
    for key in ("size_title", "size_body", "size_small"):
        assert key in TOKENS.fonts
        assert isinstance(TOKENS.fonts[key], int)


def test_load_stylesheet_returns_non_empty_string_for_dark_theme():
    from app.gui.theme import load_stylesheet

    qss = load_stylesheet("dark")
    assert isinstance(qss, str)
    assert qss.strip()


def test_load_stylesheet_resolves_all_token_placeholders():
    """No unresolved {{token}} markers should remain after loading."""
    from app.gui.theme import load_stylesheet

    qss = load_stylesheet("dark")
    assert "{{" not in qss
    assert "}}" not in qss


def test_load_stylesheet_substitutes_actual_colors():
    from app.gui.theme import TOKENS, load_stylesheet

    qss = load_stylesheet("dark")
    assert TOKENS.colors["bg_primary"] in qss


def test_load_stylesheet_raises_for_unknown_theme():
    from app.gui.theme import load_stylesheet

    with pytest.raises(ValueError):
        load_stylesheet("does-not-exist")


def test_load_stylesheet_default_is_dark():
    from app.gui.theme import load_stylesheet

    assert load_stylesheet() == load_stylesheet("dark")


def test_apply_theme_sets_stylesheet_on_qapplication(qapp):
    from app.gui.theme import apply_theme, load_stylesheet

    apply_theme(qapp, "dark")
    assert qapp.styleSheet() == load_stylesheet("dark")


# --- text scale ---------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_text_scale():
    """Keep the module-level multiplier out of neighbouring tests."""
    from app.gui.theme import set_text_scale

    yield
    set_text_scale(1.0)


def test_text_scale_defaults_to_the_design_baseline():
    from app.gui.theme import set_text_scale, text_scale

    set_text_scale(1.0)
    assert text_scale() == 1.0


def test_text_scale_clamps_to_the_supported_band():
    from app.gui.theme import TEXT_SCALE_MAX, TEXT_SCALE_MIN, set_text_scale

    assert set_text_scale(0.1) == TEXT_SCALE_MIN
    assert set_text_scale(99.0) == TEXT_SCALE_MAX


def test_text_scale_rejects_junk_without_raising():
    from app.gui.theme import set_text_scale

    assert set_text_scale(None) == 1.0
    assert set_text_scale("not a number") == 1.0
    assert set_text_scale(float("nan")) == 1.0


def test_text_scale_multiplies_every_size_token():
    """The four UI sizes plus the transcribe reading size must all
    scale together, or the type scale loses its ratios."""
    import re
    from pathlib import Path

    from app.gui.theme import set_text_scale

    def sizes(scale):
        set_text_scale(scale)
        qss = load_dark()
        return sorted({int(n) for n in re.findall(r"font-size: (\d+)px", qss)})

    base = sizes(1.0)
    assert base == [11, 13, 14, 17, 22]

    scaled = sizes(1.5)
    assert scaled == [16, 20, 21, 26, 33]
    assert all(large > small for large, small in zip(scaled, base))


def test_text_scale_leaves_radius_and_spacing_alone():
    """Only the type scale is user-adjustable. Radii and spacing stay
    put so a larger text size grows the reading surface without
    breaking the four-step layout rhythm.

    Asserted at the substitution layer rather than by searching the
    rendered QSS, because not every token is referenced by a rule
    (``radius.xl`` is reserved and intentionally unused) and a
    substring search would say nothing about the ones that are.
    """
    from app.gui.theme import _build_substitutions, set_text_scale

    set_text_scale(1.0)
    baseline = _build_substitutions()
    set_text_scale(1.75)
    at_max = _build_substitutions()

    changed = {
        key
        for key in baseline
        if baseline[key] != at_max[key]
    }
    assert changed, "the scale had no effect at all"
    assert all(key.startswith("font.size_") for key in changed), (
        f"non-type tokens moved with the text scale: {sorted(changed)}"
    )


def test_every_font_size_in_qss_comes_from_a_token():
    """A hard-coded px size escapes the text scale, so the scale is only
    as good as the token coverage. The transcribe view used to carry two
    such rules."""
    import re
    from pathlib import Path
    from pathlib import Path

    from app.gui.theme import _STYLES_DIR, set_text_scale

    set_text_scale(1.0)
    raw = (_STYLES_DIR / "dark.qss").read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in raw.splitlines()
        if re.match(r"^\s*font-size:\s*\d+px", line)
    ]
    assert offenders == [], f"hard-coded font sizes: {offenders}"


def test_no_hex_literal_survives_in_qss_rules():
    """A colour written into a rule is a colour the palette cannot change.

    Comments are exempt on purpose: the Ink-on-Fill and log-console notes
    quote measured values and the hexes they were measured from, which is
    the documentation doing its job. What must not happen is a hex in a
    live declaration, because ``{{color.*}}`` substitution never touches
    it and the next palette change silently skips that rule.
    """
    import re

    from app.gui.theme import _STYLES_DIR

    raw = (_STYLES_DIR / "dark.qss").read_text(encoding="utf-8")
    without_comments = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    offenders = [
        line.strip()
        for line in without_comments.splitlines()
        if re.search(r"#[0-9a-fA-F]{3,8}\b", line)
    ]
    assert offenders == [], f"hex literals in QSS rules: {offenders}"


def test_every_colour_token_is_actually_used_somewhere():
    """A token nothing paints is a claim about the future nobody keeps.

    Engine Green sat in ``theme.py`` and DESIGN.md for years after the
    component that used it was replaced. A token counts as used when the
    stylesheet paints it *or* when Python names it — ``accent_focus`` is
    applied from ``sidebar.py`` and the Dock gradient, not from QSS, and
    checking the stylesheet alone would call that dead.
    """
    from pathlib import Path

    from app.gui.theme import TOKENS, _STYLES_DIR

    qss = (_STYLES_DIR / "dark.qss").read_text(encoding="utf-8")
    python = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(Path(app_dir()).rglob("*.py"))
    )
    unused = sorted(
        name for name in TOKENS.colors
        if name not in qss and f'"{name}"' not in python and f"'{name}'" not in python
    )
    assert unused == [], f"declared but never used: {unused}"


def app_dir() -> str:
    import app
    from pathlib import Path

    return str(Path(app.__file__).parent)


def load_dark():
    from app.gui.theme import load_stylesheet

    return load_stylesheet("dark")


# --- high contrast ------------------------------------------------------


def test_is_high_contrast_is_false_off_windows(monkeypatch):
    """macOS has no forced-colours mode; Windows is the only platform
    that answers True, and every other path must be False."""
    from app.gui import theme

    monkeypatch.setattr(theme.sys, "platform", "darwin")
    assert theme.is_high_contrast() is False
    monkeypatch.setattr(theme.sys, "platform", "linux")
    assert theme.is_high_contrast() is False


def test_load_stylesheet_defers_to_the_os_in_high_contrast(monkeypatch):
    """In forced-colours mode the user has hand-picked a palette they can
    read; painting Graphite over it defeats the point, so the stylesheet
    must be empty and the window falls back to the system palette."""
    from app.gui import theme

    monkeypatch.setattr(theme, "is_high_contrast", lambda: True)
    assert theme.load_stylesheet("dark") == ""


def test_high_contrast_detection_survives_a_broken_win32_call(monkeypatch):
    """A failed probe must never break startup — worst case we paint our
    own theme over a forced-colours session."""
    from app.gui import theme

    monkeypatch.setattr(theme.sys, "platform", "win32")

    import ctypes

    def _boom(*_args, **_kwargs):
        raise OSError("no user32 here")

    # ``ctypes.windll`` only exists on Windows, so the fake has to be
    # injected rather than overwritten.
    monkeypatch.setattr(
        ctypes, "windll", type("W", (), {"user32": _boom})(), raising=False,
    )
    assert theme.is_high_contrast() is False
