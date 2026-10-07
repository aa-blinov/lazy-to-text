"""Tests for the ONNX-only model registry."""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


# ---- The measurement --------------------------------------------------------
#
# Golos test split, 400 clips, 1311.7 s of audio, 370 of them spoken in
# the 1554-reference-word bucket. No model in the catalog trained on it.
# WER is scored for ordinary speech; clips the corpus spells out as
# words where every model writes digits are counted separately, because
# for a dictation app digits are the output you want.
#
# At 1554 words the 95% interval is roughly +-1.0-1.8 points, so a gap
# under ~2 points is a tie and the table keeps its order anyway — that
# is what the numbers say.
#
# THIS IS THE ONLY COPY. Every public surface that quotes these numbers
# is held to it below: the model cards, the landing page and the README.
# Re-measuring is one edit here, in the same commit as the re-run. Size
# and languages are not here because the registry already owns them.
MEASURED: dict[str, tuple[float, str]] = {
    # alias: (WER %, RTF as printed)
    "gigaam-v2": (3.5, "0.015"),
    "vosk-ru-small": (4.5, "0.006"),
    "gigaam-multilingual-large-ctc": (4.6, "0.028"),
    "vosk-ru": (4.7, "0.007"),
    "fastconformer-ru": (4.9, "0.009"),
    "parakeet-tdt-v3": (5.0, "0.020"),
    "gigaam-multilingual-ctc": (6.2, "0.026"),
    "gigaam-v3-ctc": (7.1, "0.018"),
    "gigaam-v3-rnnt": (7.4, "0.012"),
    "t-one": (10.8, "0.030"),
    "canary-1b-v2": (11.4, "0.059"),
    "whisper-large-v3-turbo": (16.2, "0.457"),
    "whisper-base": (55.6, "0.039"),
    # English-only models, measured on our Russian corpus. These are not
    # "weak Russian" — they are transliteration. Kept at the bottom of
    # the table because that is where the number puts them.
    "parakeet-ctc-0.6b": (122.8, "0.019"),
    "parakeet-tdt-v2": (124.4, "0.020"),
    "parakeet-rnnt-0.6b": (126.3, "0.022"),
}


# ---- ModelInfo dataclass ----------------------------------------------------


def test_model_info_exposes_required_fields():
    from app.model_mapping import ModelInfo

    info = ModelInfo(
        alias="whisper-large-v3",
        canonical="onnx-community/whisper-large-v3",
        display_name="Whisper Large v3",
        size_mb=3000,
        vram_gb=6.0,
        speed="slow",
        quality="excellent",
        languages="multilingual",
        description="Highest-quality multilingual Whisper.",
    )
    assert info.alias == "whisper-large-v3"
    assert info.canonical == "onnx-community/whisper-large-v3"
    assert info.display_name == "Whisper Large v3"
    assert info.size_mb == 3000
    assert info.vram_gb == 6.0
    assert info.speed == "slow"
    assert info.quality == "excellent"
    assert info.languages == "multilingual"
    assert info.description
    # Defaults
    assert info.backend_kind == "onnx_asr"
    assert info.onnx_family == "whisper"


def test_model_info_rejects_invalid_speed():
    from app.model_mapping import ModelInfo

    with pytest.raises(ValueError):
        ModelInfo(
            alias="x",
            canonical="x",
            display_name="X",
            size_mb=1,
            vram_gb=0.1,
            speed="warp",  # invalid
            quality="good",
            languages="multilingual",
            description="",
        )


def test_model_info_rejects_invalid_quality():
    from app.model_mapping import ModelInfo

    with pytest.raises(ValueError):
        ModelInfo(
            alias="x",
            canonical="x",
            display_name="X",
            size_mb=1,
            vram_gb=0.1,
            speed="fast",
            quality="perfect",  # invalid
            languages="multilingual",
            description="",
        )


def test_model_info_onnx_load_id_defaults_to_canonical():
    """When the registry entry doesn't specify a separate load id (the
    common case — most onnx-asr models accept their HF repo path
    directly), ``onnx_load_id`` mirrors ``canonical``."""
    from app.model_mapping import ModelInfo

    info = ModelInfo(
        alias="x",
        canonical="onnx-community/whisper-large-v3",
        display_name="X",
        size_mb=1, vram_gb=0.1,
        speed="fast", quality="good",
        languages="multilingual", description="",
    )
    assert info.onnx_load_id == "onnx-community/whisper-large-v3"


def test_model_info_onnx_load_id_can_differ_from_canonical():
    """T-One's repo is at ``t-tech/T-one`` (capital T) on HF, but
    ``onnx_asr.load_model`` only accepts the lowercase identifier
    ``t-tech/t-one``.  ``onnx_load_id`` decouples the two so we can
    cache by HF path while loading by the canonical onnx-asr id."""
    from app.model_mapping import ModelInfo

    info = ModelInfo(
        alias="x",
        canonical="t-tech/T-one",
        display_name="X",
        size_mb=1, vram_gb=0.1,
        speed="fast", quality="good",
        languages="Russian (only)", description="",
        family="T-One",
        onnx_family="gigaam",
        onnx_load_id="t-tech/t-one",
    )
    assert info.canonical == "t-tech/T-one"
    assert info.onnx_load_id == "t-tech/t-one"


def test_model_info_rejects_invalid_onnx_family():
    from app.model_mapping import ModelInfo

    with pytest.raises(ValueError):
        ModelInfo(
            alias="x",
            canonical="x",
            display_name="X",
            size_mb=1,
            vram_gb=0.1,
            speed="fast",
            quality="good",
            languages="multilingual",
            description="",
            onnx_family="bogus",
        )


def test_model_info_is_frozen():
    from app.model_mapping import ModelInfo

    info = ModelInfo(
        alias="x",
        canonical="x",
        display_name="X",
        size_mb=1,
        vram_gb=0.1,
        speed="fast",
        quality="good",
        languages="multilingual",
        description="",
    )
    with pytest.raises((AttributeError, Exception)):
        info.alias = "y"  # type: ignore[misc]


# ---- Registry ---------------------------------------------------------------


def test_registry_contains_core_models():
    """The post-ONNX-only lineup: a Whisper turbo, a small Whisper for
    CPU users, GigaAM for Russian, Parakeet for multilingual."""
    from app.model_mapping import MODELS, aliases

    expected = {
        "whisper-large-v3-turbo",
        "vosk-ru-small",
        "gigaam-v3-rnnt",
        "parakeet-tdt-v3",
    }
    assert expected.issubset(set(aliases()))
    assert len(MODELS) == len(aliases())


def test_every_registry_entry_uses_onnx_asr_backend():
    """The single-engine invariant: every model goes through onnx_asr."""
    from app.model_mapping import MODELS

    for info in MODELS:
        assert info.backend_kind == "onnx_asr", (
            f"{info.alias} should use onnx_asr backend, got {info.backend_kind!r}"
        )


def test_every_registry_entry_has_a_valid_onnx_family():
    from app.model_mapping import MODELS, ONNX_FAMILIES

    for info in MODELS:
        assert info.onnx_family in ONNX_FAMILIES, (
            f"{info.alias} has invalid onnx_family {info.onnx_family!r}"
        )


def test_known_coreml_incompatible_models_prefer_cpu_provider():
    """These models are known to stall/fail on CoreML session-create on
    macOS, so the registry must steer them straight to CPU."""
    from app.model_mapping import get_model

    assert get_model("t-one").prefer_cpu_provider is True
    assert get_model("vosk-ru-small").prefer_cpu_provider is True
    assert get_model("vosk-ru").prefer_cpu_provider is True


def test_registry_preserves_order_between_models_and_aliases():
    from app.model_mapping import MODELS, aliases

    assert [m.alias for m in MODELS] == aliases()


def test_get_model_returns_info_by_alias():
    from app.model_mapping import ModelInfo, get_model

    info = get_model("whisper-large-v3-turbo")
    assert isinstance(info, ModelInfo)
    assert info.alias == "whisper-large-v3-turbo"
    assert info.canonical == "onnx-community/whisper-large-v3-turbo"


def test_get_model_raises_on_unknown_alias():
    from app.model_mapping import get_model

    with pytest.raises(KeyError):
        get_model("not-a-model")


# ---- Backward compatibility -------------------------------------------------


def test_alias_to_model_derived_from_registry():
    from app.model_mapping import ALIAS_TO_MODEL, MODELS

    for m in MODELS:
        assert ALIAS_TO_MODEL[m.alias] == m.canonical


def test_canonical_for_returns_canonical_for_known_alias():
    from app.model_mapping import canonical_for

    assert canonical_for("whisper-large-v3-turbo") == (
        "onnx-community/whisper-large-v3-turbo"
    )


def test_canonical_for_passes_through_unknown_names():
    from app.model_mapping import canonical_for

    assert canonical_for("custom/model-id") == "custom/model-id"


def test_alias_for_returns_alias_for_known_canonical():
    from app.model_mapping import alias_for

    assert alias_for("onnx-community/whisper-large-v3-turbo") == (
        "whisper-large-v3-turbo"
    )


def test_alias_for_passes_through_unknown_canonicals():
    from app.model_mapping import alias_for

    assert alias_for("unknown/model") == "unknown/model"


def test_every_registry_entry_carries_a_known_family():
    from app.model_mapping import FAMILIES, MODELS

    for info in MODELS:
        assert info.family in FAMILIES, (
            f"{info.alias} has unknown family {info.family!r}"
        )


def test_gigaam_multilingual_is_registered():
    """The reason the onnx-asr floor is 0.12.0, stated as a test.

    0.12.0 is the release that added these weights; 0.11.0 answers
    ``Invalid model type 'gigaam-multilingual-ctc' in config.json``,
    which reads like a broken export rather than a missing feature and
    is exactly the kind of thing that gets "fixed" by deleting the card.
    """
    from app.model_mapping import get_model

    info = get_model("gigaam-multilingual-ctc")
    assert info.canonical == "istupakov/gigaam-multilingual-ctc-onnx"
    assert info.family == "GigaAM"
    assert info.onnx_family == "gigaam"
    # Measured: CoreML 99 ms vs 85 ms on CPU for the same clip.
    assert info.prefer_cpu_provider is True
    for lang in ("Russian", "Kazakh", "Kyrgyz", "Uzbek"):
        assert lang in info.languages


def test_every_card_states_its_own_measured_wer():
    """The whole class of bug this project keeps hitting, as a test.

    Six cards in a row were found quoting a number nobody had checked: a
    vendor's figure from another corpus, a superlative instead of a
    measurement, "207 s to load" that was really a download. The cause was
    always the same — figures accumulated across sessions and were never
    re-checked against the run that produced them.

    So the measurement is written down once, at the top of this module,
    and every surface that quotes a number has to carry its own figure
    from it. Re-measuring is a deliberate act: edit ``MEASURED`` in the
    same commit as the re-run, and a card that drifts out of step with
    it fails.
    """
    from app.model_mapping import MODELS, get_model

    assert set(MEASURED) == {m.alias for m in MODELS}, (
        "a card was added or removed — re-measure it and update MEASURED"
    )

    missing, wrong = [], []
    for alias, (wer, _rtf) in MEASURED.items():
        description = get_model(alias).description
        if f"{wer}%" not in description:
            missing.append(alias)
    assert not missing, (
        f"cards not stating their measured WER: {missing} — a card that "
        f"gives no number is a card asserting something unverified"
    )
    assert not wrong, wrong


def test_cards_do_not_promise_punctuation_they_do_not_produce():
    """These strings are shown to the user in the model picker.

    T-One's card claimed "Built-in KenLM beam search yields strong
    punctuation" — measured, it returns lowercase text with no marks at
    all. A card description is a promise, and this one was false.
    """
    from app.model_mapping import get_model

    t_one = get_model("t-one").description.lower()
    assert "kenlm" not in t_one
    assert "punctuation" not in t_one.replace("unpunctuated", "")

    # The multilingual card is a plain CTC head — it must say so too, or
    # it reads as a GigaAM v3 replacement it is not. ``display_name`` is
    # the heading the picker shows, so it counts too: a card can promise
    # punctuation in its description and contradict it in its title.
    multi = get_model("gigaam-multilingual-ctc")
    assert "unpunctuated" in multi.description.lower()
    assert "punctuation" in multi.display_name.lower()

    # And the punctuated GigaAM cards may still say it.
    assert "punctuation" in get_model("gigaam-v3-ctc").description.lower()


def test_model_url_points_at_hf_repo():
    from app.model_mapping import get_model, model_url

    info = get_model("whisper-large-v3-turbo")
    assert model_url(info) == (
        "https://huggingface.co/onnx-community/whisper-large-v3-turbo"
    )

    gigaam = get_model("gigaam-v3-rnnt")
    assert model_url(gigaam) == "https://huggingface.co/istupakov/gigaam-v3-onnx"

    parakeet = get_model("parakeet-tdt-v3")
    assert model_url(parakeet) == (
        "https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx"
    )


# ---- The landing page -------------------------------------------------------


def _landing_page() -> str:
    return (_ROOT / "docs" / "index.html").read_text(encoding="utf-8")


def test_landing_page_lists_exactly_the_models_that_ship():
    """The site advertised nine models while the app shipped eleven —
    and one of the nine had been withdrawn from the app entirely.

    That is the same disease the model cards had, one layer out: a list
    of models maintained by hand in a second place, which nobody
    re-checked against the registry that actually decides what the user
    can download. ``whisper-large-v3`` was the worst case — the page
    still told visitors to pick "best raw quality" from a card the app
    had stopped offering.

    So the page is held to the registry: every alias in the catalog
    appears, and nothing appears that is not in the catalog. Adding a
    model without updating the page fails here, and so does leaving a
    withdrawn one on it.
    """

    from app.model_mapping import MODELS

    page = _landing_page()
    # Only the model table, so a passing alias elsewhere on the page
    # (a code sample, a sentence) cannot stand in for a table row.
    table = page.split('class="model-table"')[1].split("</table>")[0]
    listed = set(re.findall(r"<code>([a-z0-9][a-z0-9.-]*)</code>", table))
    # The HF repo column is also <code>-wrapped, so drop anything that
    # looks like an org/repo path rather than an alias.
    listed = {name for name in listed if "/" not in name}

    shipped = {m.alias for m in MODELS}
    assert shipped - listed == set(), (
        f"the landing page is missing shipped models: "
        f"{sorted(shipped - listed)}"
    )
    assert listed - shipped == set(), (
        f"the landing page advertises models the app does not ship: "
        f"{sorted(listed - shipped)}"
    )


def test_landing_page_quotes_the_measured_wer_and_rtf():
    """The table carries the numbers in ``MEASURED``, and nothing else.

    The landing page is the second public copy of these figures, and it
    had already drifted once — it named nine models where the app
    shipped eleven. Each alias's row has to name its own measured WER
    and real-time factor, which is the same contract
    ``test_every_card_states_its_own_measured_wer`` enforces in the app.

    RTF is compared as the exact string the page prints, not as a float:
    0.020 and 0.03 are the same number, but a table that mixed one with
    the other cannot be diffed against the README by eye.
    """
    from app.model_mapping import MODELS

    assert set(MEASURED) == {m.alias for m in MODELS}

    page = _landing_page()
    table = page.split('class="model-table"')[1].split("</table>")[0]
    # Capture the whole row, not just the alias: the numbers live in the
    # cells after it, and the default card carries an <em> marker
    # between the alias and the rest of the row.
    row_re = re.compile(r"<tr><td><code>([a-z0-9][a-z0-9.-]*)</code>(.*?)</tr>", re.S)
    rows = {m.group(1): m.group(2) for m in row_re.finditer(table)}
    wrong = []
    for alias, (wer, rtf) in MEASURED.items():
        row = rows.get(alias, "")
        if f"{wer}%" not in row or f">{rtf}<" not in row:
            wrong.append(f"{alias} (want {wer}% / {rtf})")
    assert not wrong, f"landing-page rows missing their measurement: {wrong}"


def test_the_configured_default_model_is_the_one_the_docs_call_default():
    """``DEFAULT_CONFIG`` and the two tables must name the same model.

    They did not. The app's first run loaded ``whisper-large-v3-turbo``
    while the card, the README and the landing page all called
    ``gigaam-v3-ctc`` "the default" — and the measurements are not
    close: 7.1% WER and RTF 0.018 against 16.2% and 0.457. A fresh
    install was getting a model 2.3x less accurate and 25x slower than
    the one documented, and nothing anywhere objected.

    The invariant is agreement, not a literal: whichever model is
    chosen, the three surfaces have to say the same one.
    """
    from app.config_manager import DEFAULT_CONFIG

    configured = DEFAULT_CONFIG["whisper"]["model"]

    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    readme_default = re.search(
        r"^\|\s*`([a-z0-9][a-z0-9.-]*)`\s*\*\(default\)\*", readme, re.M
    )
    page = _landing_page()
    page_default = re.search(
        r"<td><code>([a-z0-9][a-z0-9.-]*)</code>\s*<em>\(default\)</em>", page
    )

    marked = {
        "DEFAULT_CONFIG": configured,
        "README.md": readme_default.group(1) if readme_default else None,
        "docs/index.html": page_default.group(1) if page_default else None,
    }
    assert len(set(marked.values())) == 1, (
        f"the surfaces disagree about which model is the default: "
        f"{marked}. Either the app loads the wrong model on first run or "
        f"the docs advertise one it does not use — and the two are not "
        f"equally accurate."
    )


def test_readme_table_carries_the_same_numbers():
    """The README is the third public copy, and it was pinned by nothing.

    The model cards are held to ``MEASURED``, the landing page is held
    to it, and the README sat between them with the same eleven rows and
    no test at all — so it could drift on its own and nobody would find
    out until a reader spotted two different figures for the same model.
    The size column is checked against the registry, because that is
    where size actually lives.
    """
    from app.model_mapping import MODELS

    assert set(MEASURED) == {m.alias for m in MODELS}

    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    # Only the model table. Widening the alias pattern to accept a dot —
    # parakeet-ctc-0.6b needs one — also lets `config.yaml` and
    # `app.log` in the configuration table match, which is how they were
    # excluded before: by accident, not by design. Scoping to the section
    # is the fix that stays true either way.
    section = readme.split("\n## Models", 1)
    section = section[1].split("\n## ", 1)[0] if len(section) > 1 else ""
    rows = {
        m.group(1): m.group(0)
        # ``[^|]*`` after the alias absorbs the default marker
        # (``*(default)*``), the same way the landing-page row regex
        # absorbs its ``<em>`` — without it the default model simply
        # has no row, which reads as "the README is missing the model
        # the app ships as default".
        for m in re.finditer(
            r"^\|\s*`([a-z0-9][a-z0-9.-]*)`[^|]*\|.*$", section, re.M
        )
    }
    assert section, "the README lost its ## Models section"
    assert set(rows) == set(MEASURED), (
        f"README table is missing {sorted(set(MEASURED) - set(rows))} or "
        f"carries rows the app does not ship "
        f"{sorted(set(rows) - set(MEASURED))}"
    )

    wrong = []
    for alias, (wer, rtf) in MEASURED.items():
        row = rows[alias]
        if f"{wer}%" not in row:
            wrong.append(f"{alias}: WER {wer}%")
        if f"| {rtf} |" not in row:
            wrong.append(f"{alias}: RTF {rtf}")
        info = next(m for m in MODELS if m.alias == alias)
        want = (
            f"{info.size_mb / 1024:.1f} GB"
            if info.size_mb >= 1024
            else f"{info.size_mb} MB"
        )
        if f"| {want} |" not in row:
            wrong.append(f"{alias}: size {want}")
    assert not wrong, f"README rows disagree with the measurement: {wrong}"

def test_landing_page_states_where_the_numbers_came_from():
    """A WER with no corpus behind it is a number, not a measurement.

    The page now leads with Russian accuracy, so it owes the reader the
    same caveats the cards do: which split, how many words, and the
    fact that a sub-2-point gap is inside the noise. A site that quotes
    4.5% next to 4.7% and calls the second one worse is making a claim
    the sample cannot support.
    """
    page = _landing_page().lower()
    for phrase in (
        "golos",
        "1554",
        "confidence interval",
        "tie",
    ):
        assert phrase in page, f"the landing page never says '{phrase}'"

