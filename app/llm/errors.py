"""Failures from the optional text-processing step.

Two, not one, because they mean different things to the user and only
one of them is recoverable by retrying.

``LLMError`` is the general failure: the server refused, the key was
wrong, the model is not pulled, the socket died. ``LLMUnavailable`` is
the specific case of "there is nothing to talk to" — no daemon on the
port, nothing listening — which is what a user hits the first time they
switch the feature on without starting Ollama. It gets its own type
because that is the one they can fix themselves in ten seconds, and
telling them "post-processing failed" when the actual message is
"Ollama is not running" wastes their time.
"""

from __future__ import annotations


class LLMError(RuntimeError):
    """Post-processing ran and failed.

    Raised instead of returning the input unchanged. The caller owns
    the decision about what happens to the dictation when this fires,
    and it cannot make that decision if the helper silently swallows
    the error and hands back text that was never processed — which is
    exactly the "did nothing and said it did" shape this codebase has
    already paid for once, with ``None`` meaning both "heard nothing"
    and "failed".
    """


class LLMUnavailable(LLMError):
    """Nothing is listening at the configured address.

    Distinct from :class:`LLMError` so the Settings page can say
    "start the daemon" instead of showing a HTTP status to someone who
    has not decided to run a daemon yet.
    """
