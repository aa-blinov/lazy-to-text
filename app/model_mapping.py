"""Central model registry.

Single source of truth mapping user-facing aliases to canonical Hugging
Face model IDs, together with rich metadata used by the UI (size, VRAM,
speed, quality tier, language support, description, recommended
``compute_type``).

The app is **ONNX-only** — every model here is an ONNX-exported variant
loaded by ``OnnxAsrBackend``.  Older heterogeneous backends (NeMo,
GigaAM-Python, faster-whisper) were dropped; the ONNX equivalents
provide identical accuracy at a fraction of the install size.

Public API:
- ``ModelInfo``: metadata for a single model preset
- ``MODELS``: ordered tuple of all supported presets
- ``aliases()``: list of aliases in display order
- ``get_model(alias)``: ``ModelInfo`` lookup, ``KeyError`` if unknown
- ``ALIAS_TO_MODEL`` / ``MODEL_TO_ALIAS``: backward-compatible mappings
- ``canonical_for(x)`` / ``alias_for(x)``: string helpers
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


_SPEED_VALUES = ("fast", "medium", "slow")
_QUALITY_VALUES = ("basic", "good", "excellent")
# Precision label for the model card UI.  ONNX picks precision via
# the ``quantization`` parameter to ``onnx_asr.load_model`` (one of
# ``int8`` / ``fp16`` / ``None``).  The mapping happens in
# ``OnnxAsrBackend.__init__`` based on this hint.
_COMPUTE_VALUES = ("float32", "float16", "int8")
# Single-engine app: every model goes through ``OnnxAsrBackend``.  The
# ``family`` field tells the backend which onnx-asr behaviour to use
# (Whisper takes a language kwarg, others don't; GigaAM is RU-only,
# Parakeet auto-detects, …).
BACKEND_KINDS = ("onnx_asr",)
ONNX_FAMILIES = ("whisper", "gigaam", "parakeet")
# Visual grouping shown on the card.
FAMILIES = (
    "Whisper",
    "Whisper Turbo",
    "GigaAM",
    "Parakeet",
    "T-One",
    "Vosk",
    "Canary",
)


@dataclass(frozen=True)
class ModelInfo:
    alias: str
    canonical: str
    display_name: str
    size_mb: int
    vram_gb: float
    speed: str
    quality: str
    languages: str
    description: str
    compute_type: str = "float16"
    backend_kind: str = "onnx_asr"
    family: str = "Whisper"
    # Some models are known to fail on CoreMLExecutionProvider /
    # CUDAExecutionProvider with op-level errors that ORT's session-
    # create takes a long time to surface (e.g. Istupakov's
    # GigaAM-v3 / T-One / Vosk all fail with
    # ``HandleNegativeAxis ... axis 2 is not in valid range`` after
    # ~75 s of CoreML compilation).  Setting this flag tells the
    # backend to skip the accelerator entirely for the model and
    # load straight into CPU, removing the wait without changing
    # the eventual outcome (the backend would have retried on CPU
    # anyway after the timeout).  Only mark a model True after
    # confirming the failure empirically.
    prefer_cpu_provider: bool = False
    # Which onnx-asr family adapter to use.  Drives backend behaviour
    # (language passing, language reporting).  Independent of the UI
    # ``family`` label which is purely cosmetic.
    onnx_family: str = "whisper"
    # Source language to assume when the user leaves the language
    # setting on "auto".  ``None`` keeps auto-detect.
    #
    # Two cards need it, both for a measured reason on the Golos test
    # split (370 real Russian clips, 1554 words):
    #
    # canary-1b-v2 — it is an AED model, and with no source language it
    # does not transcribe Russian at all, it *translates* it: "афина
    # воспроизведи музыку" came back as "athena reproduce music",
    # WER 131%. Passing ``language="ru"`` explicitly changed nothing,
    # because the backend only forwarded a language for the ``whisper``
    # family and this card is ``onnx_family="parakeet"``.
    #
    # whisper-base — auto-detect is 7x worse than just saying "ru":
    # WER 367.8% against 51.2% on the same clips, because on 2-second
    # commands an unconstrained decoder invents text. whisper-large-v3-
    # turbo is left on auto on purpose: measured identical either way
    # (14.1% both), so it keeps its multilingual ability for free.
    auto_language: Optional[str] = None
    # Identifier passed verbatim to ``onnx_asr.load_model``.  Defaults
    # to ``canonical`` (the HF repo path), which works for most
    # models.  Override when ``onnx-asr`` knows the model under a
    # different name — e.g. ``t-tech/t-one`` (lowercase) for the
    # capital-T HF repo, or short names like ``gigaam-v3-e2e-rnnt``
    # for the punctuated GigaAM decoder variant.  ``canonical`` is
    # still used for the HF cache check and the model URL.
    onnx_load_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.speed not in _SPEED_VALUES:
            raise ValueError(
                f"speed must be one of {_SPEED_VALUES}, got {self.speed!r}"
            )
        if self.quality not in _QUALITY_VALUES:
            raise ValueError(
                f"quality must be one of {_QUALITY_VALUES}, got {self.quality!r}"
            )
        if self.compute_type not in _COMPUTE_VALUES:
            raise ValueError(
                f"compute_type must be one of {_COMPUTE_VALUES}, got {self.compute_type!r}"
            )
        if self.backend_kind not in BACKEND_KINDS:
            raise ValueError(
                f"backend_kind must be one of {BACKEND_KINDS}, got {self.backend_kind!r}"
            )
        if self.family not in FAMILIES:
            raise ValueError(
                f"family must be one of {FAMILIES}, got {self.family!r}"
            )
        if self.onnx_family not in ONNX_FAMILIES:
            raise ValueError(
                f"onnx_family must be one of {ONNX_FAMILIES}, got {self.onnx_family!r}"
            )
        # Default ``onnx_load_id`` to ``canonical`` so callers can
        # always read ``info.onnx_load_id`` without an extra ``or``.
        # ``object.__setattr__`` is the dataclass-friendly way to
        # mutate a frozen instance from inside ``__post_init__``.
        if self.onnx_load_id is None:
            object.__setattr__(self, "onnx_load_id", self.canonical)


MODELS: Tuple[ModelInfo, ...] = (
    # ---- Whisper Turbo (large-v3 distilled, multilingual) ------------------
    # The card used to call this "best general-purpose multilingual
    # model".  On Russian it is the worst practical option in the
    # catalogue: 16.2% WER on 370 spoken clips, against 4.9% for
    # FastConformer RU and 7.1% for the GigaAM v3 default.  It also
    # costs 207 s to load and runs at RTF 0.46 on CPU — 42x slower than
    # GigaAM v3 on the same audio.  "6x faster than large-v3" is the
    # vendor's number against a model we could not benchmark here; it
    # says nothing about being good at Russian.
    ModelInfo(
        alias="whisper-large-v3-turbo",
        canonical="onnx-community/whisper-large-v3-turbo",
        display_name="Whisper Large v3 Turbo (multilingual, not for Russian)",
        size_mb=1620,
        vram_gb=4.0,
        speed="fast",
        quality="excellent",
        languages="multilingual",
        description=(
            "OpenAI Whisper Large v3 Turbo — distilled large-v3, kept for "
            "non-Russian audio.  On Russian it is the weakest usable "
            "model here (16.2% WER against 4.9% for FastConformer RU) and "
            "by far the slowest (207 s to load, RTF 0.46 on CPU).  If you "
            "dictate in Russian, pick anything else."
        ),
        compute_type="float16",
        family="Whisper Turbo",
        onnx_family="whisper",
    ),
    # ---- Whisper Large v3 (full) -------------------------------------------
    ModelInfo(
        alias="whisper-large-v3",
        canonical="onnx-community/whisper-large-v3",
        display_name="Whisper Large v3",
        size_mb=3145,
        vram_gb=6.0,
        speed="slow",
        quality="excellent",
        languages="multilingual",
        description=(
            "OpenAI Whisper Large v3 — the largest download here, kept for "
            "non-Russian audio.  Gated on Hugging Face, so it needs a "
            "token in Settings before it will download; we could not "
            "benchmark it here and are not claiming a number for it."
        ),
        compute_type="float16",
        family="Whisper",
        onnx_family="whisper",
    ),
    # ---- GigaAM v3 (Sber, Russian-only, ONNX) ------------------------------
    # GigaAM v3 e2e variants include built-in punctuation and
    # normalisation in the output, which matters for the clipboard-paste
    # flow (we don't have a separate punctuator).
    ModelInfo(
        alias="gigaam-v3-ctc",
        canonical="istupakov/gigaam-v3-onnx",
        display_name="GigaAM v3 CTC (Russian, punctuated)",
        size_mb=260,
        vram_gb=2.0,
        speed="fast",
        quality="excellent",
        languages="Russian (only)",
        description=(
            "Sber GigaAM v3 with CTC decoder — fast Russian transcription "
            "with built-in punctuation."
        ),
        compute_type="float16",
        family="GigaAM",
        onnx_family="gigaam",
        # The ``-e2e-`` variant emits text already punctuated and
        # normalised — no separate punctuator needed for our paste flow.
        onnx_load_id="gigaam-v3-e2e-ctc",
        # CoreML does not help this model, and the reason is not the one
        # the old comment here gave.
        #
        # It *can* be made to work: the provider options in
        # onnx_backend.py set ``RequireStaticInputShapes: "0"``, and
        # CoreML's MIL builder cannot handle an unbounded input
        # dimension. Flip it to "1" and the model compiles in ~2.3 s
        # instead of dying after ~15 s of ``unbounded dimension which is
        # not supported`` on every intermediate tensor — the
        # ``HandleNegativeAxis ... axis 2 is not in valid range`` at the
        # end of that log is the last of ~100 shape-propagation
        # failures, not the cause.
        #
        # Measured, 11.4 s of Russian on an M4 Pro, best of 3:
        #
        #   CPU only              124 ms   (RTF 0.011, ~92x realtime)
        #   CoreML (static)       147 ms   (RTF 0.013, ~78x realtime)
        #
        # So CoreML takes 81% of the nodes (1304 of 1608, per ORT's own
        # GetCapability) and is *slower* — the dispatch overhead exceeds
        # the gain on a model this small. A 30-second dictation is ~0.35 s
        # on CPU; there is nothing left for the ANE to win.
        #
        # ``prefer_cpu_provider`` therefore stays, but on a measured
        # basis. If someone "fixes" the flag, it gets slower — that is
        # the reason worth writing down.
        prefer_cpu_provider=True,
    ),
    # The card said "best Russian quality" and "recommended for Russian
    # speakers".  Both are measured claims and both fail: on 370 spoken
    # clips the RNN-T decoder scores 7.4% WER, against 4.9% for
    # FastConformer RU, 5.0% for Parakeet TDT and 4.7% for Vosk RU.  It
    # is the better pick only when you want built-in punctuation *and*
    # accept being ~50% behind on error rate — the GigaAM v3 CTC decoder
    # is the same 7.1%, and the default does not have to change.
    ModelInfo(
        alias="gigaam-v3-rnnt",
        canonical="istupakov/gigaam-v3-onnx",
        display_name="GigaAM v3 RNN-T (Russian, punctuated)",
        size_mb=290,
        vram_gb=2.5,
        speed="medium",
        quality="excellent",
        languages="Russian (only)",
        description=(
            "Sber GigaAM v3 with an RNN-T decoder — same built-in "
            "punctuation as the default CTC card, at 7.4% WER against "
            "that card's 7.1% and FastConformer RU's 4.9%.  Pick it only "
            "if you want the decoder; on accuracy the default is the "
            "better Russian card."
        ),
        compute_type="float16",
        family="GigaAM",
        onnx_family="gigaam",
        onnx_load_id="gigaam-v3-e2e-rnnt",
        # See gigaam-v3-ctc — CoreML takes 81% of the nodes and is still
        # slower than CPU, so this is a measured preference, not a
        # workaround.
        prefer_cpu_provider=True,
    ),
    # ---- GigaAM Multilingual (ru / kk / ky / uz, CTC) ----------------------
    # 240M params, pretrained on 2M hours over 70+ languages (Interspeech
    # 2026), then fine-tuned on ru/kk/ky/uz/en.  MIT.
    #
    # This is the reason the onnx-asr floor moved to 0.12.0: 0.12.0 is
    # the release that taught the loader to read these weights at all,
    # and 0.11.0 answers "Invalid model type 'gigaam-multilingual-ctc'".
    #
    # It is NOT a replacement for gigaam-v3-ctc. This is a plain CTC
    # head — no punctuation, no capitalisation, no ITN. Measured on the
    # same clips, the v3 e2e models return capitalised, punctuated text
    # from the same audio. Reach for this card when the audio is not
    # Russian: on a Kazakh clip it returns the sentence essentially
    # verbatim, where v3 e2e produces Russian-alphabet mush
    # ("Бугун аварая жахсы Безакай") and T-One transliterates it.
    #
    # int8 is the default, not an accident: 225 MB instead of the 885 MB
    # full-precision weights, with no measured loss on either test clip.
    ModelInfo(
        alias="gigaam-multilingual-ctc",
        canonical="istupakov/gigaam-multilingual-ctc-onnx",
        display_name="GigaAM Multilingual (ru/kk/ky/uz, no punctuation)",
        size_mb=225,
        vram_gb=0.6,
        speed="fast",
        quality="excellent",
        languages="Russian, Kazakh, Kyrgyz, Uzbek, English",
        description=(
            "GigaAM Multilingual — Russian, Kazakh, Kyrgyz, Uzbek and "
            "English in one 240M model.  Returns lowercase unpunctuated "
            "text, so it is the one to pick for Kazakh, Kyrgyz or Uzbek "
            "audio; for Russian dictation GigaAM v3 is better and comes "
            "with punctuation."
        ),
        compute_type="int8",
        family="GigaAM",
        onnx_family="gigaam",
        onnx_load_id="istupakov/gigaam-multilingual-ctc-onnx",
        # CoreML is slower here for the same reason as v3: 99 ms against
        # 85 ms on CPU for 7.6 s of Russian.
        prefer_cpu_provider=True,
    ),
    # ---- FastConformer-Hybrid Large (ru, NVIDIA) ----------------------------
    # ~250M params, Russian only, trained by NVIDIA on the.ru common-crawl
    # corpus.  CC-BY-4.0 — the card already links the HF repo, which is
    # the attribution the licence asks for; keep that link if this moves.
    #
    # This card was first written off a 7.6 s `say`-synthesised clip and
    # read as "fastest, but only by 8 ms, so really a second opinion".
    # On 370 real spoken clips (Golos test split, 1554 words) that was
    # wrong in the model's favour: 4.9% WER, the best Russian-capable
    # model in the catalogue, against 7.1% for the GigaAM v3 default.
    # The 2.2-point gap sits just outside the +-1.3 point confidence
    # interval, so it is real but not decisive — Vosk RU (4.7%) and
    # Parakeet TDT (5.0%) are statistically tied with it.
    #
    # It does emit commas and a leading capital, and it does not end the
    # sentence with a full stop — RNN-T without a punctuation head, so
    # the card says "partial punctuation" rather than claiming what
    # GigaAM v3 does properly.
    ModelInfo(
        alias="fastconformer-ru",
        canonical="istupakov/stt_ru_fastconformer_hybrid_large_pc_onnx",
        display_name="FastConformer RU (most accurate Russian, partial punctuation)",
        size_mb=137,
        vram_gb=0.8,
        speed="fast",
        quality="good",
        languages="Russian (only)",
        description=(
            "NVIDIA FastConformer-Hybrid Large, Russian only — the most "
            "accurate Russian model here (4.9% WER against the GigaAM v3 "
            "default's 7.1%) and the fastest (51 ms on our reference "
            "clip against 59).  Vosk RU and Parakeet TDT match it within "
            "the margin of error.  Capitalises and inserts commas but "
            "does not close sentences."
        ),
        compute_type="int8",
        family="Parakeet",
        onnx_family="parakeet",
        onnx_load_id="nemo-fastconformer-ru-rnnt",
    ),
    # ---- Whisper Base (smallest Whisper) ------------------------------------
    # 74M params.  Apache-2.0.  The smallest download here — and the
    # weakest model here.  The display name used to sell it as the
    # "smallest punctuated" option, which was a TTS-clip artefact.
    ModelInfo(
        alias="whisper-base",
        canonical="istupakov/whisper-base-onnx",
        display_name="Whisper Base (smallest, least accurate)",
        size_mb=107,
        vram_gb=0.3,
        speed="medium",
        quality="good",
        languages="multilingual",
        description=(
            "Whisper Base — 74M params, the smallest download here, and "
            "the weakest model here by a wide margin: 55.6% WER on our "
            "Russian test set against 4.9% for FastConformer RU and 7.1% "
            "for the GigaAM v3 default.  Pinned to Russian because "
            "auto-detect made it worse still (287% WER on 2-second "
            "commands — it invents text).  Pick it for the 107 MB, not "
            "for the accuracy."
        ),
        compute_type="int8",
        family="Whisper",
        onnx_family="whisper",
        onnx_load_id="whisper-base",
        auto_language="ru",
    ),
    # ---- Parakeet TDT v3 (NVIDIA, multilingual, ONNX) ----------------------
    ModelInfo(
        alias="parakeet-tdt-v3",
        canonical="istupakov/parakeet-tdt-0.6b-v3-onnx",
        display_name="Parakeet TDT v3 (multilingual)",
        size_mb=1200,
        vram_gb=2.0,
        speed="fast",
        quality="excellent",
        languages="25 langs incl. Russian, Ukrainian",
        description=(
            "NVIDIA Parakeet TDT 0.6B v3 — 25 European languages with "
            "auto-detect.  Fastest multilingual ASR on the HF leaderboard."
        ),
        compute_type="float32",
        family="Parakeet",
        onnx_family="parakeet",
        onnx_load_id="nemo-parakeet-tdt-0.6b-v3",
    ),
    # ---- T-One (T-Tech, Russian, Conformer-CTC, ONNX) ---------------------
    # 71.7M params, trained on 80k hours of Russian (57.9k of telephony).
    # WER 8.63% on call-center / 6.20% on other Russian telephony — beats
    # Whisper large-v3 (19.39%) on real-world speech with noise/codecs.
    # Apache 2.0.
    #
    # This card used to claim "Built-in KenLM beam search yields strong
    # punctuation". It does not. Measured on a clean 7.6 s Russian
    # sample through onnx-asr 0.12.0, ``t-tech/t-one`` returns:
    #
    #   "привет это тестовая фраза для измерения скорости распознавания
    #    сегодня хорошая погода и я собираюсь пойти гулять"
    #
    # No punctuation, no sentence capitals — GigaAM v3 e2e returns the
    # same audio with both, at a third of the time. The KenLM beam
    # search is evidently not enabled by the path this app loads, and
    # gigastt's notes on the model agree ("T-one emits none"). Do not
    # re-add that sentence without a measurement to back it: it is the
    # kind of claim a user acts on.
    #
    # Uses ``gigaam`` onnx_family because the runtime behaviour matches:
    # Russian-only, no language kwarg passed to recognize().
    ModelInfo(
        alias="t-one",
        canonical="t-tech/T-one",
        display_name="T-One (Russian, telephony-tuned)",
        size_mb=290,
        vram_gb=1.5,
        speed="fast",
        quality="excellent",
        languages="Russian (only)",
        description=(
            "T-Tech T-One — Russian Conformer-CTC trained on 80k h of "
            "speech, mostly telephony.  The vendor reports 8.63% WER on "
            "call-centre audio against Whisper's 19.39%; we could not "
            "reproduce that, our test set holding no telephony, and on "
            "ordinary dictation it scores 10.8% — behind the GigaAM v3 "
            "default's 7.1%.  Returns lowercase unpunctuated text; for "
            "everyday dictation prefer GigaAM v3."
        ),
        compute_type="float16",
        family="T-One",
        onnx_family="gigaam",
        # HF repo is published at ``t-tech/T-one`` (capital T), but
        # ``onnx_asr.load_model`` only matches its registry against the
        # lowercase identifier.  Pass lowercase to load_model; keep the
        # canonical case for cache directory + URL display.
        onnx_load_id="t-tech/t-one",
        # CoreML EP rejects this Conformer-CTC graph after a long
        # session-create attempt; skip straight to CPU on macOS
        # instead of making every switch look hung for ~1-2 minutes.
        prefer_cpu_provider=True,
    ),
    # ---- Vosk Russian (alphacep, Zipformer2 RNN-T, ONNX) ------------------
    # The lightweight option.  ``vosk-model-small-ru`` is ~30 MB,
    # ``vosk-model-ru`` is ~50 MB; both run comfortably on CPU.  Useful
    # for low-spec laptops or as a quick fallback when a heavier model
    # is mid-download.  WER 6.1 % on Common Voice ru.  Apache 2.0.
    ModelInfo(
        alias="vosk-ru-small",
        canonical="alphacep/vosk-model-small-ru",
        display_name="Vosk Small (Russian, 30 MB)",
        size_mb=30,
        vram_gb=0.5,
        speed="fast",
        quality="good",
        languages="Russian (only)",
        description=(
            "Vosk small Russian (Zipformer2 RNN-T) — ultra-lightweight, "
            "~30 MB, runs easily on CPU.  Quality dips on accented speech "
            "but fine for clean dictation."
        ),
        compute_type="float16",
        family="Vosk",
        onnx_family="gigaam",
        # Zipformer streaming graphs fail on CoreML EP shape
        # handling; go straight to CPU to avoid the long retry path.
        prefer_cpu_provider=True,
    ),
    ModelInfo(
        alias="vosk-ru",
        canonical="alphacep/vosk-model-ru",
        display_name="Vosk (Russian, 50 MB)",
        size_mb=50,
        vram_gb=1.0,
        speed="fast",
        quality="excellent",
        languages="Russian (only)",
        description=(
            "Vosk Russian (Zipformer2 RNN-T) — 6.1 % WER on Common Voice "
            "ru, ~50 MB.  Best speed/size/quality balance on CPU."
        ),
        compute_type="float16",
        family="Vosk",
        onnx_family="gigaam",
        prefer_cpu_provider=True,
    ),
    # ---- NVIDIA Canary 1B v2 (multilingual, ONNX) -------------------------
    # 1B-param transformer encoder-decoder; 25 languages incl. Russian.
    #
    # It is an AED model, which changes what "no language" means: with
    # no source language onnx-asr does not transcribe, it *translates*.
    # Measured on the Golos test split before this card declared
    # ``auto_language="ru"``: Russian speech came back as English
    # ("афина воспроизведи музыку" -> "athena reproduce music"),
    # 131.0% WER and 100.6% CER, with spoken numbers turning into
    # 115% WER. After the fix: 11.4% / 3.4%, numbers 2%.
    #
    # The earlier "auto-detects language" note was the bug, not a
    # property of the model — the backend gated the language kwarg on
    # ``family == "whisper"`` and this card is a parakeet. It is now
    # 4th of the Russian-capable models here, and the only one in the
    # catalogue that needs a source language rather than tolerating one.
    ModelInfo(
        alias="canary-1b-v2",
        canonical="istupakov/canary-1b-v2-onnx",
        display_name="Canary 1B v2 (multilingual)",
        size_mb=2000,
        vram_gb=4.0,
        speed="medium",
        quality="excellent",
        languages="25 langs incl. Russian, Ukrainian",
        description=(
            "NVIDIA Canary 1B v2 — multilingual encoder-decoder, 25 "
            "languages.  11.4% WER on our Russian test set; the only "
            "card here that needs a source language, so it is pinned to "
            "Russian unless you pick another.  Heavier than Parakeet "
            "(1B params)."
        ),
        compute_type="float16",
        family="Canary",
        onnx_family="parakeet",
        onnx_load_id="nemo-canary-1b-v2",
        auto_language="ru",
    ),
)


_BY_ALIAS = {m.alias: m for m in MODELS}


def aliases() -> List[str]:
    return [m.alias for m in MODELS]


def get_model(alias: str) -> ModelInfo:
    if alias not in _BY_ALIAS:
        raise KeyError(alias)
    return _BY_ALIAS[alias]


# ``ALIAS_TO_MODEL`` maps alias → canonical. ``MODEL_TO_ALIAS`` is the
# reverse — first alias wins when several presets share a canonical id.
ALIAS_TO_MODEL = {m.alias: m.canonical for m in MODELS}

MODEL_TO_ALIAS: dict[str, str] = {}
for _m in MODELS:
    MODEL_TO_ALIAS.setdefault(_m.canonical, _m.alias)


def canonical_for(name: str) -> str:
    return ALIAS_TO_MODEL.get(name, name)


def alias_for(canonical: str) -> str:
    return MODEL_TO_ALIAS.get(canonical, canonical)


def model_url(info: ModelInfo) -> str:
    """Resolve the canonical web home for a model card's link icon.

    Every supported model is now hosted on Hugging Face, so we always
    return the HF repo URL.
    """
    return f"https://huggingface.co/{info.canonical}"
