"""The worker that must not be felt: its thread budget and its priority."""

import subprocess
import sys

import pytest

from app import background


def test_the_normal_worker_keeps_the_thread_count_it_asked_for(monkeypatch):
    monkeypatch.delenv("L2T_BACKGROUND_WORKER", raising=False)

    assert background.is_background() is False
    assert background.thread_budget(4) == 4
    assert background.session_options() is None


def test_the_background_worker_takes_at_most_half_of_the_cores(monkeypatch):
    monkeypatch.setenv("L2T_BACKGROUND_WORKER", "1")
    monkeypatch.setattr(background.os, "cpu_count", lambda: 8)

    assert background.thread_budget(4) == 4
    assert background.thread_budget(16) == 4

    monkeypatch.setattr(background.os, "cpu_count", lambda: 2)
    assert background.thread_budget(4) == 1

    monkeypatch.setattr(background.os, "cpu_count", lambda: None)
    assert background.thread_budget(4) == 1


def test_session_options_carry_the_budget(monkeypatch):
    monkeypatch.setenv("L2T_BACKGROUND_WORKER", "1")
    monkeypatch.setattr(background.os, "cpu_count", lambda: 8)

    options = background.session_options()

    assert options.intra_op_num_threads == 4
    assert options.inter_op_num_threads == 1


@pytest.mark.skipif(sys.platform == "win32", reason="nice values are POSIX")
def test_entering_the_background_lowers_this_process_only_in_its_own_process():
    # Run in a child: a test process that lowered its own priority would slow
    # every test after it.
    code = (
        "from app import background;"
        "before = background.current_priority();"
        "ok = background.enter();"
        "print(ok, background.is_background(), before, background.current_priority())"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
    ).stdout.split()

    assert out[0] == "True"
    assert out[1] == "True"
    assert int(out[3]) > int(out[2]), "the process should have been made nicer"
