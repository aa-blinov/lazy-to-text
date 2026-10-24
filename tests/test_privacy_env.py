"""onnxruntime telemetry is off before onnxruntime can be imported.

QA-SEC-1: the library registers a device id and opens a TLS connection to
Microsoft on the first inference session, outside any proxy, unless
``ORT_DISABLE_TELEMETRY`` is set before the import. Every entry that can
load it imports ``app.privacy_env`` first; these run in a fresh
interpreter so an import order that regresses is caught for real.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

ENTRIES = [
    "app.privacy_env",
    "app.backends.onnx_backend",
    "app.backends.subprocess_worker",
    "app.backends.subprocess_backend",
    "app.bootstrap",
    "app.server.runtime",
]


@pytest.mark.parametrize("module", ENTRIES)
def test_importing_an_entry_point_turns_the_telemetry_off(module):
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    code = (
        "import sys, os\n"
        f"import {module}\n"
        "assert 'onnxruntime' not in sys.modules, 'imported ort too early'\n"
        "print(os.environ.get('ORT_DISABLE_TELEMETRY'))\n"
    )

    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True,
        cwd=os.getcwd(), timeout=60,
    )

    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "1"


def test_a_user_value_of_zero_does_not_turn_it_back_on():
    env = dict(os.environ, ORT_DISABLE_TELEMETRY="0")
    out = subprocess.run(
        [sys.executable, "-c",
         "import os, app.privacy_env; print(os.environ['ORT_DISABLE_TELEMETRY'])"],
        env=env, capture_output=True, text=True, cwd=os.getcwd(), timeout=60,
    )

    assert out.stdout.strip() == "1"


def test_the_inference_worker_child_inherits_it_from_a_parent_that_imported_the_backend(tmp_path):
    """The worker is a spawned child: it gets the parent's environment, and
    imports the worker module (which sets it again) on its own."""
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    script = tmp_path / "spawn_probe.py"
    script.write_text(
        "import app.backends.subprocess_backend, multiprocessing as mp, os\n"
        "def child(q):\n"
        "    q.put(os.environ.get('ORT_DISABLE_TELEMETRY'))\n"
        "if __name__ == '__main__':\n"
        "    ctx = mp.get_context('spawn'); q = ctx.Queue()\n"
        "    p = ctx.Process(target=child, args=(q,)); p.start()\n"
        "    print(q.get(timeout=30)); p.join()\n"
    )
    out = subprocess.run(
        [sys.executable, str(script)], env=env, capture_output=True, text=True,
        cwd=str(tmp_path), timeout=90,
    )

    assert out.stdout.strip().splitlines()[-1] == "1", out.stderr
