"""The diarization maths, with no model: turns, merging, clustering, folding.

The two ONNX models are not loaded here (no test loads a model); the vectors
fed to the clustering are built by hand so what is checked is the grouping.
"""

from __future__ import annotations

import numpy as np
import pytest

from app import diarization as d


def _unit(angle: float) -> np.ndarray:
    return np.array([np.cos(angle), np.sin(angle), 0.0])


def test_importing_it_loads_no_model_and_no_ui_toolkit():
    import sys

    assert "PySide6" not in sys.modules
    assert not hasattr(d, "onnx_asr")  # imported inside Diarizer.__init__


def test_adjacent_turns_of_one_speaker_join_across_a_short_gap():
    turns = [d.Turn(0, 1, 0), d.Turn(1.3, 2, 0), d.Turn(2.2, 3, 1)]

    assert d.merge_turns(turns) == [d.Turn(0, 2, 0), d.Turn(2.2, 3, 1)]


def test_a_contained_turn_does_not_shorten_the_one_before_it():
    assert d.merge_turns([d.Turn(0, 10, 0), d.Turn(2, 3, 0)]) == [d.Turn(0, 10, 0)]


def test_a_turn_longer_than_the_cap_is_split():
    out = d.merge_turns([d.Turn(0, 250, 0)], max_seconds=120)

    assert [(t.start, t.end) for t in out] == [(0, 120), (120, 240), (240, 250)]


def test_clustering_separates_two_voices_and_keeps_one_voice_together():
    voices = np.array([_unit(0.0), _unit(0.05), _unit(0.02), _unit(1.5), _unit(1.52), _unit(1.48)])

    labels = d.cluster_embeddings(voices)

    assert labels[0] == labels[1] == labels[2]
    assert labels[3] == labels[4] == labels[5]
    assert labels[0] != labels[3]
    assert d.cluster_embeddings(voices[:3]) == [0, 0, 0]


def test_clustering_of_nothing_is_nothing():
    assert d.cluster_embeddings(np.zeros((0, 3))) == []


def test_a_lone_stray_turn_is_folded_into_the_nearest_speaker():
    voices = np.array([_unit(0.0), _unit(0.02), _unit(0.04), _unit(1.5), _unit(1.52), _unit(0.8)])

    labels = d.cluster_embeddings(voices)

    assert len(set(labels)) == 2


def test_a_sliver_of_a_speaker_is_folded_but_a_real_quiet_one_is_not():
    voices = np.array([_unit(0.0)] * 5 + [_unit(1.5)] * 2)
    labels = [0] * 5 + [1] * 2

    folded = d.fold_small_clusters(voices, labels, [30.0] * 5 + [0.5] * 2)
    kept = d.fold_small_clusters(voices, labels, [300.0] * 5 + [40.0] * 2)

    assert len(set(folded)) == 1
    assert len(set(kept)) == 2


def test_cmn_refuses_features_in_the_wrong_shape():
    with pytest.raises(ValueError):
        d._cmn(np.zeros((80, 200)))
    out = d._cmn(np.ones((1, 10, 80)) * 3)
    assert np.allclose(out, 0)


def test_short_turns_borrow_the_speaker_of_the_nearest_long_one():
    anchors = [d.Turn(0, 5, 0), d.Turn(10, 15, 1)]
    short = [d.Turn(5.1, 5.2, 9), d.Turn(9.9, 10.0, 9)]

    assert [t.speaker for t in d._borrow_short_turns(short, anchors)] == [0, 1]


def test_a_recording_too_short_to_hold_a_frame_has_no_turns(tmp_path):
    diarizer = d.Diarizer.__new__(d.Diarizer)
    import threading

    diarizer._lock = threading.Lock()

    assert diarizer.diarize(np.zeros(10, dtype=np.float32)) == []
