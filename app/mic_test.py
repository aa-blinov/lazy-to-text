"""What a microphone test result means, without Qt.

The test records a few seconds and reports the loudest sample (``peak``) and
the average power (``rms``), both on a 0..1 scale. Both interfaces turn
those two numbers into the same three verdicts, so the thresholds are here
and nowhere else.
"""

from __future__ import annotations

#: Below this peak the input is treated as silent: wrong device, muted, or
#: no permission. The OS gives a denied microphone silence, not an error.
SILENT_BELOW = 0.01
#: Below this peak (and above silence) the signal is usable only barely.
QUIET_BELOW = 0.08

SILENT = "silent"
QUIET = "quiet"
GOOD = "good"


def classify_input_level(peak: float) -> str:
    """``silent``, ``quiet`` or ``good`` for a measured peak."""
    if peak < SILENT_BELOW:
        return SILENT
    if peak < QUIET_BELOW:
        return QUIET
    return GOOD
