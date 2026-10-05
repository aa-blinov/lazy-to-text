"""Tests for the ONNX-only model registry."""

import pytest


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

    So the measurement is written down here, once, and every card has to
    carry its own number. Re-measuring is a deliberate act: update this
    table in the same commit as the re-run, and a card that drifts out of
    step with it fails.

    Golos test split, 400 clips, 1311.7 s, 370 spoken clips in the
    1554-word bucket. At that sample size the 95% interval is roughly
    +-1.0-1.8 points, so a gap under ~2 points is a tie — the table keeps
    them in that order anyway, because that is what the numbers say.
    """
    from app.model_mapping import MODELS, get_model

    measured = {
        "vosk-ru-small": 4.5,
        "vosk-ru": 4.7,
        "fastconformer-ru": 4.9,
        "parakeet-tdt-v3": 5.0,
        "gigaam-multilingual-ctc": 6.2,
        "gigaam-v3-ctc": 7.1,
        "gigaam-v3-rnnt": 7.4,
        "t-one": 10.8,
        "canary-1b-v2": 11.4,
        "whisper-large-v3-turbo": 16.2,
        "whisper-base": 55.6,
    }
    assert set(measured) == {m.alias for m in MODELS}, (
        "a card was added or removed — re-measure it and update this table"
    )

    missing, wrong = [], []
    for alias, wer in measured.items():
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
    from pathlib import Path

    page = Path(__file__).resolve().parents[1] / "docs" / "index.html"
    return page.read_text(encoding="utf-8")


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
    import re

    from app.model_mapping import MODELS

    page = _landing_page()
    # Only the model table, so a passing alias elsewhere on the page
    # (a code sample, a sentence) cannot stand in for a table row.
    table = page.split('class="model-table"')[1].split("</table>")[0]
    listed = set(re.findall(r"<code>([a-z0-9][a-z0-9-]+)</code>", table))
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
    """The table carries the same numbers the cards carry.

    Two hand-written tables holding the same eleven models is one table
    too many, and the second one had already drifted. So each alias's
    row must name its own measured WER and its real-time factor —
    the same contract ``test_every_card_states_its_own_measured_wer``
    enforces inside the app.
    """
    import re

    from app.model_mapping import MODELS

    # Read the numbers from the page rather than restating them: the
    # invariant is "the page agrees with the registry", not "the page
    # agrees with a third copy of the table".
    #
    # RTF is the exact string the page prints, not a float — 0.020 and
    # 0.03 are the same number, but a table that mixed one with the
    # other is a table nobody can diff against the README by eye, and
    # the README prints all of them to three places.
    measured = {
        "vosk-ru-small": (4.5, "0.006"),
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
    }
    assert set(measured) == {m.alias for m in MODELS}

    page = _landing_page()
    table = page.split('class="model-table"')[1].split("</table>")[0]
    # Capture the whole row, not just the alias: the numbers live in the
    # cells after it, and the default card carries an <em> marker
    # between the alias and the rest of the row.
    row_re = re.compile(r"<tr><td><code>([a-z0-9-]+)</code>(.*?)</tr>", re.S)
    rows = {m.group(1): m.group(2) for m in row_re.finditer(table)}
    wrong = []
    for alias, (wer, rtf) in measured.items():
        row = rows.get(alias, "")
        if f"{wer}%" not in row or f">{rtf}<" not in row:
            wrong.append(f"{alias} (want {wer}% / {rtf})")
    assert not wrong, f"landing-page rows missing their measurement: {wrong}"

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

