"""What the post-processing step can be asked to do.

A mode is a system prompt and nothing else — no parameters, no target
language, no second field in Settings. That constraint is deliberate:
every mode here has to work on whatever was dictated, in whatever
language it was dictated, without the user configuring anything first.
The first version of this list wanted a "translate to English" mode,
which is genuinely useful and quietly smuggles in an assumption —
English, specifically, because English is the target whoever wrote the
list speaks. A mode that needs a target language is a mode that needs
a field, and a field is a second thing to get wrong.

So the three here are all language-preserving and take no arguments.
Adding translation later means adding the field with it, not bolting
one onto a list that promised otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    """One thing the step can be asked to do."""

    id: str
    label: str
    # Shown under the picker in Settings. Says what the mode does to
    # the words, not what it is for, because the user is choosing a
    # transformation and not reading about a feature.
    description: str
    prompt: str


#: Rules every mode shares, appended to all three prompts.
#:
#: Held in one place because a rule written into one prompt is a rule
#: the other two quietly lack, and the modes differ in what they *do*
#: with the words — not in how careful they are about them. The two
#: that matter most are the two whose failure is invisible: an answer
#: in English to a Russian dictation, and "сорок два" left as words in
#: a document that wanted a digit. Both look like a working feature.
#:
#: The language rule is phrased positively and names its own trap on
#: purpose. The old wording was "never translate" and
#: "Stay in the original language" — a prohibition, in English, about
#: an input that is usually not English. A prohibition does not tell a
#: model what to write instead, and the language of the instructions
#: is a much stronger prior than the language of a prohibition.
_HOUSE_RULES = (
    "\n\n"
    "Applies to every job:\n"
    "- Answer in the language the dictation is in. These instructions "
    "are written in English; that is not a reason to answer in "
    "English.\n"
    "- Write numbers as digits: quantities, dates, amounts, ordinals, "
    "measurements, phone and account numbers. So \"сорок два\" becomes "
    "\"42\", and \"тридцать первого\" becomes \"31-го\". Spell a number "
    "out only where the language requires it.\n"
    "- Use real typographic marks: an em dash (—) rather than a hyphen, "
    "the quotation marks the language expects (« » in Russian, “ ” in "
    "English), and the ellipsis character (…) rather than three dots.\n"
    "- Remove only accidental repetition — a stumble, or a word repeated "
    "because a sentence was restarted. Keep repetition the speaker chose, "
    "including emphasis.\n"
    "- Return plain text and nothing else: no preamble, no explanation, "
    "no markdown, no bold, no code fences, no quotation marks around the "
    "whole answer."
)


_CLEAN_PROMPT = (
    "Rewrite the dictated text exactly as it was spoken, with correct "
    "punctuation, capitalisation and paragraph breaks.\n\n"
    "Remove disfluencies: filler words, false starts — a sentence the "
    "speaker begins and abandons — and any artifact that only makes "
    "sense while someone is speaking. Keep a word the speaker meant, "
    "however casually it was said. If the speaker enumerated items, keep "
    "them as separate lines in the same order.\n\n"
    "Change no meaning, add no content that was not said, and do not "
    "smooth away a hesitation that carried one.\n"
) + _HOUSE_RULES


_CONCISE_PROMPT = (
    "Rewrite the dictated text as a short, information-dense summary of "
    "what was said.\n\n"
    "Keep every fact, name, number, date and commitment, and keep them "
    "attributable — nothing that was hedged may come out asserted. Drop "
    "repetition, padding and throat-clearing. Change no word to its "
    "opposite and invent nothing that was not said.\n"
) + _HOUSE_RULES


_FORMAL_PROMPT = (
    "Rewrite the dictated text as formal written prose, suitable for an "
    "official letter or a business document.\n\n"
    "Keep every fact, name, number and commitment. Make the register "
    "formal and the sentences well-formed, but do not add anything the "
    "speaker did not say and do not resolve an ambiguity they left in "
    "place.\n"
) + _HOUSE_RULES


MODES: tuple[Mode, ...] = (
    Mode(
        id="clean",
        label="Clean up",
        description="Punctuation, capitals and paragraphs. Drops filler "
        "and false starts, keeps every word that was meant.",
        prompt=_CLEAN_PROMPT,
    ),
    Mode(
        id="concise",
        label="Make concise",
        description="A short summary of what was said. Keeps every fact, "
        "number and commitment, drops the padding.",
        prompt=_CONCISE_PROMPT,
    ),
    Mode(
        id="formal",
        label="Formal letter",
        description="The same content as formal written prose, for an "
        "official letter or a business document.",
        prompt=_FORMAL_PROMPT,
    ),
)

#: What a fresh install uses. The first mode in the tuple is the one
#: that is "tidy it up", which is the least surprising thing to have
#: happen to text nobody asked to be changed in any particular way.
DEFAULT_MODE = MODES[0].id

_BY_ID = {m.id: m for m in MODES}


def mode_by_id(mode_id: str) -> Mode:
    """The mode named by *mode_id*.

    Falls back to :data:`DEFAULT_MODE` rather than raising, because the
    id arrives from ``config.yaml``, which is a file on disk that a
    user can edit and that an older build may not have written. A
    config naming a mode this build does not have is a settings
    mismatch, not a crash: dictating should keep working.
    """
    return _BY_ID.get(mode_id, MODES[0])
