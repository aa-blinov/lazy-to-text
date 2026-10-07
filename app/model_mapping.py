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
    # Re-measured 2026-10-05 on the Golos test split (400 clips, 370 of
    # them in the 1554-word speech bucket), because two numbers in the
    # version below did not survive it.
    #
    # It used to say "not for Russian" in the heading, "the weakest
    # usable model here" in the body, and "if you dictate in Russian,
    # pick anything else". Only the middle of those three is a
    # measurement — 16.2% WER is 16.2% WER. The other two are verdicts
    # about a use this test cannot speak to: Golos is voice-assistant
    # commands, two seconds each, not the free dictation this app is
    # for, and a user who says the model handles their dictation is
    # reporting on a domain we never scored. So the card states the
    # numbers and the reason the card is in the catalogue, and stops
    # there. Do not re-add a suitability verdict without a measurement
    # of dictation, not of commands.
    #
    # "207 s to load" was wrong and is gone: that was the first-run
    # download, not a load. Loading is 1.9 s — the same order as
    # everything else here. What genuinely costs something is inference:
    # RTF 0.46 on CPU against 0.018 for the GigaAM v3 default on the same
    # audio, 25x, which is why the card leads with time rather than
    # size. The old "42x" compared against an earlier, faster reading
    # of the default; both are re-measured numbers now.
    #
    # "6x faster than large-v3" remains the vendor's claim about a model
    # we could not benchmark here (gated), so it stays attributed.
    ModelInfo(
        alias="whisper-large-v3-turbo",
        canonical="onnx-community/whisper-large-v3-turbo",
        display_name="Whisper Large v3 Turbo (multilingual)",
        size_mb=1620,
        vram_gb=4.0,
        speed="fast",
        quality="excellent",
        languages="multilingual",
        description=(
            "OpenAI Whisper Large v3 Turbo — distilled large-v3, multilingual "
            "with auto-detect.  On our Russian test set it scores 16.2% WER "
            "and 5.5% CER, against 7.1% / 3.2% for the GigaAM v3 default "
            "and 4.9% for FastConformer RU.  Loading takes 1.9 s; what costs "
            "you is transcription time — RTF 0.46 on CPU, about 25x the "
            "GigaAM v3 default on the same audio.  We keep it for the "
            "languages the Russian-only cards do not cover."
        ),
        compute_type="float16",
        family="Whisper Turbo",
        onnx_family="whisper",
    ),
    # ---- Whisper Large v3 (full) — WITHDRAWN -------------------------------
    # Removed 2026-10-05 after it was finally measured. Do not re-add it
    # without re-measuring, and read this before you try.
    #
    # The card pointed at ``onnx-community/whisper-large-v3``, which is not
    # a repository. The export is ``onnx-community/whisper-large-v3-ONNX``,
    # with the suffix, and Hugging Face answers 404 — not 403 — for a repo
    # that does not exist, which at the call site is indistinguishable from
    # a gated repo you have not been granted. The card had answered that
    # silence with a story: "gated on Hugging Face, so it needs a token in
    # Settings". It is not gated; it is public and downloads anonymously.
    # If a card ever claims a repo is unreachable, check the name first.
    #
    # With the name fixed it downloaded, and then it would not load. The
    # unquantised export is the one with external weights, and onnxruntime
    # 1.30 refuses those twice over — first as a symlink pointing out of
    # the model directory, then, once the flat directory is built with
    # hard links, as "multiple hard links, indicating a potential hardlink
    # attack". The only precision that loads is fp16, which has no external
    # weights at all.
    #
    # And fp16 is not worth having. Full run over the Golos test split,
    # 400 clips, the same 370-clip / 1554-word speech bucket as every other
    # number in this file:
    #
    #     precision   WER%    CER%   numeric%   RTF      loads
    #     fp32        15.5    5.3    46         0.716    no
    #     fp16        15.6    5.3    46         1.432    yes
    #
    # Identical accuracy, twice the time — CPU execution providers have no
    # native fp16 kernels, so the smaller graph buys nothing here. And even
    # taking the numbers at face value, 15.5% is a tie with the
    # Whisper Large v3 *Turbo* (16.2%, RTF 0.457, 1.6 GB): a 3.1 GB
    # download for a third of the speed and no accuracy. Against the models
    # built for this language it was never close — 7.1% for the GigaAM v3
    # default at 40x the speed.
    #
    # A 40-clip probe suggested fp16 might reach 11.4%, which would have
    # made it the best multilingual card here by a wide margin. That was
    # 185 words; the full run says 15.6%. Small samples do not get to
    # decide things.
    #
    # A config still naming this model goes inactive with a logged warning
    # rather than being silently remapped to the Turbo — quietly switching
    # someone's model under them is worse than an empty selection they can
    # see and fix.
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
            "Sber GigaAM v3 with CTC decoder — the default.  7.1% WER and "
            "3.2% CER on our Russian test set, RTF 0.018, 260 MB.  It is "
            "not the most accurate Russian card here — Vosk Small, Vosk "
            "RU, FastConformer RU and Parakeet TDT all beat it, and three "
            "of those are smaller and quicker.  What it has is punctuation "
            "and capitalisation built into the output, which is the whole "
            "reason it is the default for text that gets pasted into a "
            "document.  Spoken numbers come out at 46%, so for digits "
            "reach for FastConformer RU or Parakeet TDT instead."
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
    # It is NOT a drop-in replacement for gigaam-v3-ctc. This is a plain
    # CTC head — no punctuation, no capitalisation. Measured on the same
    # clips, the v3 e2e models return capitalised, punctuated text from
    # the same audio. Reach for this card when the audio is not Russian:
    # on a Kazakh clip it returns the sentence essentially verbatim,
    # where v3 e2e produces Russian-alphabet mush ("Бугун аварая жахсы
    # Безакай") and T-One transliterates it.
    #
    # What the card used to get wrong is the other half of that. It said
    # "for Russian dictation GigaAM v3 is better", and the measurement
    # says the opposite, or rather says nothing of the kind: 6.2% WER
    # against v3's 7.1% is a tie inside the +-1.0-1.8 confidence interval
    # a 1554-word sample buys. Two other columns are not a tie, though.
    # CER 1.4% against 3.2%, and spoken numbers at 0% WER against v3's
    # 46% — this card writes "407 745" where v3 garbles it. For a dictation
    # app those numbers get pasted into a document, so the tie on words
    # is not the whole story.
    #
    # The real reason to prefer v3 is the output shape, not the accuracy:
    # punctuation and capitals. Say that, and only that.
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
            "English in one 240M model.  On our Russian test set it scores "
            "6.2% WER and 1.4% CER, level with the GigaAM v3 default's 7.1% "
            "on words and ahead of its 3.2% on characters, and it writes "
            "spoken numbers correctly where v3 garbles them (0% against "
            "46%).  Returns lowercase unpunctuated text, so it is the one "
            "to pick for Kazakh, Kyrgyz or Uzbek audio; for Russian pick "
            "GigaAM v3 when you want punctuation and capitals."
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
    # wrong in the model's favour: 4.9% WER against 7.1% for the GigaAM
    # v3 default.
    #
    # "the most accurate Russian model here" was on this card too, and it
    # was false in a way the comment above already had the numbers for:
    # Vosk Small measured 4.5% and Vosk RU 4.7%, so the two smallest
    # cards in the catalogue beat this one. On speed the 51 ms / 59 ms
    # pair is from the `say` clip this card was written from, which that
    # same comment calls wrong; RTF on the real set is Vosk Small 0.006,
    # Vosk RU 0.007, this one 0.009 — third, not first. A superlative is a
    # measurement, and this one was measuring the wrong thing.
    #
    # What is actually true and worth saying: it is 137 MB and faster than
    # almost everything here, its CER is 1.3%, and it is one of only three
    # cards that write spoken numbers correctly — 0% WER, against 46% for
    # the GigaAM v3 default and 45% for Whisper Turbo. For output that gets
    # pasted into a document that is not a rounding error.
    #
    # It does emit commas and a leading capital, and it does not end the
    # sentence with a full stop — RNN-T without a punctuation head, so
    # the card says "partial punctuation" rather than claiming what
    # GigaAM v3 does properly.
    ModelInfo(
        alias="fastconformer-ru",
        canonical="istupakov/stt_ru_fastconformer_hybrid_large_pc_onnx",
        display_name="FastConformer RU (leading Russian, partial punctuation)",
        size_mb=137,
        vram_gb=0.8,
        speed="fast",
        quality="good",
        languages="Russian (only)",
        description=(
            "NVIDIA FastConformer-Hybrid Large, Russian only — 4.9% WER "
            "and 1.3% CER, third in the Russian group behind Vosk Small "
            "(4.5%) and Vosk RU (4.7%), and ahead of Parakeet TDT (5.0%) "
            "and the GigaAM v3 default (7.1%).  137 MB, RTF 0.009.  It is "
            "one of only three cards here that get spoken numbers right "
            "(0% against 46% for the default).  Capitalises and inserts "
            "commas but does not close sentences."
        ),
        compute_type="int8",
        family="Parakeet",
        onnx_family="parakeet",
        onnx_load_id="nemo-fastconformer-ru-rnnt",
        # CoreML rejects this graph at session-init (HandleNegativeAxis,
        # on the preprocessor). The CPU retry recovers it, so the flag
        # costs nothing and only skips an attempt that is going to fail —
        # see `_resolve_providers` for why a rejected graph is worth
        # not attempting. Set from a real load on Apple Silicon; re-check
        # it when onnxruntime is upgraded.
        prefer_cpu_provider=True,
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
    # The card used to say "fastest multilingual ASR on the HF leaderboard"
    # and nothing else — a superlative from a third party, about a
    # leaderboard we have never looked at, standing in for a number. What
    # we can say from our own run: 5.0% WER and 1.4% CER on the Russian
    # test set, RTF 0.020, 3.7 s to load.
    #
    # 5.0% puts it in the leading group for Russian as well — with Vosk
    # RU (4.7%), Vosk Small (4.5%) and FastConformer RU (4.9%) — and it
    # writes spoken numbers correctly (0% WER). It is also the fastest of
    # the multilingual cards here by a wide margin: Canary 1B v2 runs at
    # RTF 0.059 and Whisper Large v3 at 0.716, on the same audio. That is
    # our measurement of our catalogue, and it is the claim the old line
    # was gesturing at.
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
            "auto-detect.  5.0% WER and 1.4% CER on our Russian test set, "
            "RTF 0.020: in the leading group for Russian, and the fastest "
            "of the multilingual cards here by a wide margin (Canary 1B v2 "
            "is 0.059, Whisper Large v3 is 0.716 on the same audio).  Gets "
            "spoken numbers right.  Returns text without punctuation."
        ),
        compute_type="float32",
        family="Parakeet",
        onnx_family="parakeet",
        onnx_load_id="nemo-parakeet-tdt-0.6b-v3",
        # Same story as the other Parakeet graphs above: CoreML rejects
        # this one at session-init, the CPU retry recovers it. Measured
        # on Apple Silicon against a real load, not assumed.
        prefer_cpu_provider=True,
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
    # ---- Vosk Small (alphacep, Zipformer2 RNN-T, ONNX) --------------------
    # 30 MB, so it is the card for a machine that cannot hold anything
    # else.  Apache 2.0.
    #
    # "Quality dips on accented speech but fine for clean dictation" was
    # on this card and there is no measurement behind either half of it —
    # the Golos split is read speech with room tone, not accented
    # dictation, so we cannot say which way it goes. Rather than keep a
    # plausible-sounding line we cannot check, the card now carries what
    # we did measure: 4.5% WER, 0.6% CER, RTF 0.006. That is the second
    # best Russian result in the catalogue, from 30 MB.
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
            "Vosk small Russian (Zipformer2 RNN-T) — 4.5% WER and 0.6% "
            "CER on our Russian test set, RTF 0.006, and 30 MB.  That is "
            "the most accurate *and* the fastest card in this catalogue, "
            "from a download smaller than a screenshot.  Returns plain "
            "lowercase text; no punctuation."
        ),
        compute_type="float16",
        family="Vosk",
        onnx_family="gigaam",
        # Zipformer streaming graphs fail on CoreML EP shape
        # handling; go straight to CPU to avoid the long retry path.
        prefer_cpu_provider=True,
    ),
    # ---- Vosk Russian (alphacep, Zipformer2 RNN-T, ONNX) ------------------
    # The vendor reports 6.1 % WER on Common Voice ru.  That number used
    # to be this card's only figure, which is a problem twice over: it is
    # somebody else's corpus, and it is *worse* than what the model
    # actually does on the split we measure — 4.7% WER, 2.2% CER, RTF
    # 0.007, 50 MB.
    #
    # "Best speed/size/quality balance on CPU" was the other line here,
    # and it is the kind that cannot be checked: three models trade off
    # differently depending on whether you are short of disk, short of
    # RAM, or short of patience. The numbers are on the card instead and
    # a user can weigh them.
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
            "Vosk Russian (Zipformer2 RNN-T) — 4.7% WER and 2.2% CER on "
            "our Russian test set, RTF 0.007, 50 MB.  In the leading group "
            "with FastConformer RU (4.9%) and Parakeet TDT (5.0%), at a "
            "fraction of their size.  Returns plain lowercase text; no "
            "punctuation."
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
        # CoreML rejects the encoder graph before it ever runs, so the
        # only provider this card can use is CPU. Measured on Apple
        # Silicon against a real load.
        prefer_cpu_provider=True,
        auto_language="ru",
    ),
    # ---- GigaAM v2 (ru, CTC) -----------------------------------------------
    # Measured on Golos alongside the rest, not inherited from a vendor
    # description. It beats its own successor: 3.5% against v3's 7.1% on
    # the same corpus, at a smaller footprint. The repo ships a single
    # CTC decoder (v2_ctc.onnx), so the load_id is the CTC key and the
    # card gets no punctuation — the trade the multilingual card makes.
    # CoreML refuses this graph the same way it refuses v3's, so the
    # accelerator is short-circuited: measured 1.1 s load on CPU.
    ModelInfo(
        alias="gigaam-v2",
        canonical="istupakov/gigaam-v2-onnx",
        display_name="GigaAM v2 CTC (Russian, unpunctuated)",
        size_mb=889,
        vram_gb=1.1,
        speed="fast",
        quality="excellent",
        languages="Russian (only)",
        description=(
            "GigaAM v2 — the predecessor of the v3 cards, and the most "
            "accurate model in this catalogue.  3.5% WER and 0.8% CER on "
            "our Russian test set, against 4.5% for the next best and "
            "7.1% for the GigaAM v3 default; spoken numbers come out at "
            "0% error and loading takes 1.1 s at RTF 0.015.  It writes "
            "lowercase unpunctuated text, so reach for GigaAM v3 when "
            "the output is going into a document — that is the whole "
            "difference between them."
        ),
        compute_type="float16",
        family="GigaAM",
        onnx_family="gigaam",
        onnx_load_id="gigaam-v2-ctc",
        prefer_cpu_provider=True,
    ),
    # ---- GigaAM Multilingual Large (ru/kk/ky/uz) ---------------------------
    # Released the same day as the 225 MB card we already ship, with the
    # same model_type in onnx-asr and the same language set — only the
    # weights differ. int8 only; the repo ships no fp32.
    ModelInfo(
        alias="gigaam-multilingual-large-ctc",
        canonical="istupakov/gigaam-multilingual-large-ctc-onnx",
        display_name="GigaAM Multilingual Large (ru/kk/ky/uz)",
        size_mb=564,
        vram_gb=1.7,
        speed="fast",
        quality="excellent",
        languages="Russian, Kazakh, Kyrgyz, Uzbek, English",
        description=(
            "The large variant of GigaAM Multilingual.  Measured at 4.6% "
            "WER and 1.0% CER on our Russian test set — a clear 1.6 "
            "points ahead of the 225 MB card it grows from (6.2%), and "
            "inside the noise of Vosk RU (4.7%).  564 MB of int8 "
            "weights, RTF 0.028, loads in 1.3 s.  Spoken numbers are "
            "correct, like its smaller sibling.  It returns lowercase "
            "unpunctuated text, so it is the one for Kazakh, Kyrgyz or "
            "Uzbek audio; for Russian with punctuation pick GigaAM v3."
        ),
        compute_type="int8",
        family="GigaAM",
        onnx_family="gigaam",
        onnx_load_id="gigaam-multilingual-large-ctc",
        prefer_cpu_provider=True,
    ),
    # ---- Parakeet 0.6B — CTC / RNNT / TDT v2 (en) --------------------------
    # Three NVIDIA Parakeet 0.6B heads published by istupakov but never
    # bundled. Measured here rather than described: all three are
    # English-only, and English-only on Russian audio is not "a lower
    # score", it is transliteration — 122-126% WER with substitutions
    # on every word. We cannot report their English quality; our corpus
    # is Russian, and the honest thing the enum can say about an
    # untested axis is `basic`.
    #
    # `prefer_cpu_provider` is not optional for these: measured on this
    # machine CoreML raises "axis 2 is not in valid range" and the
    # CPU retry takes the load to 520 s / 543 s. Starting on CPU brings
    # it to 1.2 s for the same weights and the same answer.
    ModelInfo(
        alias="parakeet-ctc-0.6b",
        canonical="istupakov/parakeet-ctc-0.6b-onnx",
        display_name="Parakeet CTC 0.6B (English)",
        size_mb=623,
        vram_gb=1.8,
        speed="fast",
        quality="basic",
        languages="English (only)",
        description=(
            "NVIDIA Parakeet 0.6B with a CTC head, English only.  On our "
            "Russian test set it scores 122.8% WER and 96.2% CER — not "
            "a weak result but a category error: it transliterates "
            "rather than transcribes ('afina vaspresvy muzhakov' for "
            "'афина воспроизведи').  We have no English corpus here, so "
            "its English quality is untested and the card reports the "
            "lowest grade rather than inventing one.  623 MB of int8 "
            "weights, RTF 0.019, loads in 1.2 s on CPU."
        ),
        compute_type="int8",
        family="Parakeet",
        onnx_family="parakeet",
        onnx_load_id="nemo-parakeet-ctc-0.6b",
        prefer_cpu_provider=True,
    ),
    ModelInfo(
        alias="parakeet-rnnt-0.6b",
        canonical="istupakov/parakeet-rnnt-0.6b-onnx",
        display_name="Parakeet RNN-T 0.6B (English)",
        size_mb=631,
        vram_gb=1.8,
        speed="fast",
        quality="basic",
        languages="English (only)",
        description=(
            "NVIDIA Parakeet 0.6B with an RNN-T head, English only — the "
            "transducer sibling of the CTC card.  On our Russian test "
            "set it scores 126.3% WER and 102.2% CER, transliterating "
            "the same way ('naiki serale gregory air' for 'найти "
            "сериал григорий р').  English quality is untested here; the "
            "grade is the lowest the catalogue offers, not an estimate.  "
            "631 MB of int8 weights, RTF 0.022, loads in 1.2 s on CPU."
        ),
        compute_type="int8",
        family="Parakeet",
        onnx_family="parakeet",
        onnx_load_id="nemo-parakeet-rnnt-0.6b",
        prefer_cpu_provider=True,
    ),
    ModelInfo(
        alias="parakeet-tdt-v2",
        canonical="istupakov/parakeet-tdt-0.6b-v2-onnx",
        display_name="Parakeet TDT v2 (English)",
        size_mb=2397,
        vram_gb=3.0,
        speed="fast",
        quality="basic",
        languages="English (only)",
        description=(
            "NVIDIA Parakeet TDT v2, English only — the generation before "
            "the v3 card.  On our Russian test set it scores 124.4% WER "
            "and 102.0% CER, producing transliterations rather than "
            "words; our English corpus does not exist, so this card "
            "reports no English grade.  2,397 MB of fp32 weights (the "
            "largest file here), RTF 0.020, loads in 4.7 s.  The v3 "
            "card shares this architecture and scores 5.0% on Russian — "
            "the difference is that v3 is multilingual where v2 is not, "
            "which is also why v2 exists as a separate card."
        ),
        compute_type="float32",
        family="Parakeet",
        onnx_family="parakeet",
        onnx_load_id="nemo-parakeet-tdt-0.6b-v2",
        prefer_cpu_provider=True,
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

# Canonical ids this app used to write out, mapped to the alias that
# replaced them. A card's canonical lands in ``config.yaml`` the moment a
# user picks it and in every history row it transcribes, so renaming one
# without this leaves those files naming a model the registry no longer
# knows: ``alias_for`` returns the string unchanged, ``get_model`` raises,
# and the controller quietly leaves the model inactive — a selection the
# user made disappearing with no error and no way back.
#
# ``onnx-community/whisper-large-v3`` was never a repository — the wrong
# name for ``onnx-community/whisper-large-v3-ONNX`` — and the card is now
# withdrawn (see the note where it used to be). Its old id is kept here
# pointing nowhere on purpose: a config still holding it goes inactive
# with a logged warning, which a user can see and change. Remapping it
# onto the Turbo would be quieter and worse, swapping a 1.6 GB model for
# a 3.1 GB one behind their back.
_RETIRED_CANONICALS: dict[str, str] = {}

MODEL_TO_ALIAS: dict[str, str] = {}
for _m in MODELS:
    MODEL_TO_ALIAS.setdefault(_m.canonical, _m.alias)
# A retired id never shadows a live one: if a future card legitimately
# takes the old name back, the loop above has already claimed it.
for _old, _alias in _RETIRED_CANONICALS.items():
    MODEL_TO_ALIAS.setdefault(_old, _alias)


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
