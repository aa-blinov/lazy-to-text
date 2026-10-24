"""Process environment that keeps the app from talking to anyone.

``onnxruntime`` ships native telemetry that is on by default on some
platforms: on the first inference session it writes a device id into a
vendor-named folder of the user's profile and opens a TLS connection to
Microsoft, outside any proxy setting. ``ort.disable_telemetry_events()``
called from Python does not stop it - the id is created and the
connection made before Python can call it. Only the environment variable,
set before the library is imported, does.

Importing this module is the act: every entry point that can load
``onnxruntime`` (the headless runtime, the inference worker and its parent) imports it first. The value is forced rather than
defaulted, because "no telemetry by design" is not a preference.
"""

from __future__ import annotations

import os

#: Variables set at import, name to value.
ENVIRONMENT = {"ORT_DISABLE_TELEMETRY": "1"}


def apply() -> None:
    os.environ.update(ENVIRONMENT)


apply()
