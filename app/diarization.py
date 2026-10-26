"""Speaker diarization on CPU: who spoke when.

Taken from the protokol project and kept ONNX-only, like the rest of the
runtime: no torch, no GPU, no new dependency (``onnx-asr`` and ``onnxruntime``
are already shipped).

* ``onnx-community/pyannote-segmentation-3.0`` marks where the speaker changes
  (its powerset head emits no-speech / speaker-1..3 / two-speaker frames);
* a 3D-Speaker ``CAM++`` model turns each speech turn into a voice embedding;
* average-linkage clustering over cosine similarity groups the turns into the
  recording's speakers.

The segmentation model's own speaker indices are local (up to three per 10 s
window, re-numbered window to window), so they only say *where* a turn begins
and ends. The embeddings decide *who* it is across the whole recording.

The embedder is CAM++ (``campplus_zh_en``), not ERes2Net and not an end-to-end
diarizer: it separated all speakers of a seven-speaker call where ERes2Net
merged voices and Sortformer is capped at four. Its embeddings need
per-utterance mean normalisation (CMN) and sit on a different cosine scale,
hence the threshold. The 80-dim Kaldi fbank it was trained on is the one
``onnx_asr`` already ships.

The module imports no UI toolkit and loads the two models only when a
``Diarizer`` is built, so importing it is free.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import numpy as np
import onnxruntime as ort

SAMPLE_RATE = 16_000

# pyannote segmentation frame geometry, mirroring the ONNX wrapper.
_RECEPTIVE_FIELD = 991
_STRIDE = 270
_OFFSET = 135
_WINDOW_SECONDS = 10.0
_OVERLAP_SECONDS = 5.0

# A turn shorter than this carries too little voice to embed reliably.
_MIN_EMBED_SECONDS = 0.4
# no-speech probability at or above this is silence.
_SPEECH_THRESHOLD = 0.5
# Average cosine similarity below which two clusters are different speakers.
# CAM++ embeddings sit higher on the scale than ERes2Net's. Picked in protokol
# by sweeping the threshold over VoxConverse and AMI; not re-measured here.
_CLUSTER_THRESHOLD = 0.46
# A cluster this small (in turns) is noise, not a speaker; fold it into the
# nearest one instead of inventing a speaker for it.
_MIN_CLUSTER_TURNS = 2
# A cluster holding less than this share of the recording's speech is a
# fragment, not a speaker — fold it into its nearest neighbour. On a noisy
# phone call the similarity threshold still leaves a long tail of such slivers.
_MIN_CLUSTER_SHARE = 0.02
# ...and only if it is also a few seconds of voice. On a two-hour call 2% is
# 144 s, so a real quiet speaker (110 s) would pass the share test alone.
# Picked in protokol on a two-speaker recording and an interview whose spurious
# clusters hold several seconds of voice each.
_MAX_FRAGMENT_SECONDS = 20.0


@dataclass(frozen=True)
class Turn:
    """One speaker's continuous speech interval, ``end`` exclusive, in seconds."""

    start: float
    end: float
    speaker: int


def merge_turns(turns: list[Turn], gap: float = 0.5, max_seconds: float = 120.0) -> list[Turn]:
    """Join adjacent turns of the same speaker across short gaps, and split any
    turn longer than ``max_seconds`` so the ASR never sees one long block."""
    merged: list[Turn] = []
    for turn in turns:
        if merged and merged[-1].speaker == turn.speaker and turn.start - merged[-1].end <= gap:
            previous = merged[-1]
            # Overlapping turns of one speaker can come in any order: the join must
            # keep the later end, or a contained turn would shorten the one before it.
            merged[-1] = Turn(previous.start, max(previous.end, turn.end), turn.speaker)
        else:
            merged.append(turn)
    split: list[Turn] = []
    for turn in merged:
        start = turn.start
        while turn.end - start > max_seconds:
            split.append(Turn(start, start + max_seconds, turn.speaker))
            start += max_seconds
        split.append(Turn(start, turn.end, turn.speaker))
    return [t for t in split if t.end > t.start]


def _cosine_similarity(embeddings: np.ndarray) -> np.ndarray:
    embeddings = np.asarray(embeddings, dtype=np.float64)
    normalized = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-9)
    return normalized @ normalized.T


def _cmn(features: np.ndarray) -> np.ndarray:
    """Per-utterance mean normalisation over time.

    CAM++ expects features centred over time. The fbank output is
    (batch, time, 80), so the shape check matters: a transposed or unbatched
    array would centre each frame over its 80 bins and give garbage with no error.
    """
    if features.ndim != 3 or features.shape[2] != 80:
        raise ValueError(f"expected (batch, time, 80) fbank features, got {features.shape}")
    return features - features.mean(axis=1, keepdims=True)


def cluster_embeddings(embeddings: np.ndarray, threshold: float = _CLUSTER_THRESHOLD) -> list[int]:
    """Agglomerative average-linkage clustering over cosine similarity.

    Merges the two closest clusters while their average similarity is at least
    ``threshold``; the number of speakers falls out of the data. Tiny clusters
    are folded into their most similar neighbour so a stray turn does not become
    a speaker of its own.

    Keeps one cluster-by-cluster average matrix. A merge rewrites only the kept
    cluster's row and column (Lance-Williams update), so each merge is one
    vectorised argmax, not a rescan of every cluster pair. The matrix is dense
    float64 n x n: about 32 MB at 2000 turns.
    """
    count = len(embeddings)
    if count == 0:
        return []
    average = _cosine_similarity(embeddings)
    np.fill_diagonal(average, -np.inf)
    sizes = np.ones(count)
    members: list[list[int]] = [[i] for i in range(count)]
    alive = np.ones(count, dtype=bool)

    def merge(keep: int, drop: int) -> None:
        # Average over the union is the size-weighted mean of the two averages.
        row = (sizes[keep] * average[keep] + sizes[drop] * average[drop]) / (sizes[keep] + sizes[drop])
        average[keep, :] = row
        average[:, keep] = row
        average[keep, keep] = -np.inf
        # Dead slots stay -inf, so argmax never picks them.
        average[drop, :] = -np.inf
        average[:, drop] = -np.inf
        sizes[keep] += sizes[drop]
        members[keep] += members[drop]
        alive[drop] = False

    # ponytail: each merge argmaxes the full matrix, so a run that never hits the
    # threshold costs ~17 s at 2000 turns; a real call stops early. Upgrade path:
    # nearest-neighbour chain, if that ever shows up in a profile.
    clusters = count
    while clusters > 1:
        i, j = divmod(int(np.argmax(average)), count)
        if average[i, j] < threshold:
            break
        merge(min(i, j), max(i, j))
        clusters -= 1

    # Fold noise clusters (< _MIN_CLUSTER_TURNS turns) into their best neighbour.
    while clusters > 1:
        small = np.flatnonzero(alive & (sizes < _MIN_CLUSTER_TURNS))
        if small.size == 0:
            break
        k = int(small[0])
        target = int(np.argmax(average[k]))
        merge(min(k, target), max(k, target))
        clusters -= 1

    labels = [0] * count
    for speaker, slot in enumerate(np.flatnonzero(alive)):
        for index in members[slot]:
            labels[index] = speaker
    return labels


def fold_small_clusters(
    embeddings: np.ndarray,
    labels: list[int],
    weights: list[float],
    min_share: float = _MIN_CLUSTER_SHARE,
    max_seconds: float | None = None,
) -> list[int]:
    """Fold clusters that are a sliver of the recording into their nearest neighbour.

    A noisy recording (a phone call, overlapping speech, cross-talk) still leaves
    a long tail of clusters each holding a few seconds — fragments of a voice,
    not speakers. The turn-count fold above cannot see them (they have several
    turns) and lowering the similarity threshold would merge genuinely distinct
    voices. A cluster is a fragment only when it is under ``min_share`` of the
    recording's speech *and* under ``max_seconds`` of it; the second test keeps a
    real quiet speaker on a long call. A fragment joins the cluster it is most
    similar to.
    """
    if len(embeddings) == 0 or min_share <= 0:
        return labels
    if max_seconds is None:
        max_seconds = _MAX_FRAGMENT_SECONDS
    total = float(sum(weights))
    if total <= 0:
        return labels
    similarity = _cosine_similarity(embeddings)
    groups: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        groups.setdefault(label, []).append(index)

    def seconds(members: list[int]) -> float:
        return float(sum(weights[i] for i in members))

    while len(groups) > 1:
        small = [
            label
            for label, members in groups.items()
            if seconds(members) / total < min_share and seconds(members) < max_seconds
        ]
        if not small:
            break
        label = min(small, key=lambda l: seconds(groups[l]))
        others = [o for o in groups if o != label]
        target = max(others, key=lambda o: float(similarity[np.ix_(groups[label], groups[o])].mean()))
        groups[target] = groups[target] + groups[label]
        del groups[label]

    result = [0] * len(labels)
    for new_label, members in enumerate(groups.values()):
        for index in members:
            result[index] = new_label
    return result


def _borrow_short_turns(turns: list[Turn], anchors: list[Turn]) -> list[Turn]:
    """Short turns take the speaker of the nearest long, labelled turn in time.

    Only ``anchors`` are candidates. Borrowing from earlier borrows would let one
    speaker spread along a chain of short turns.
    """
    borrowed: list[Turn] = []
    for turn in turns:
        if (turn.end - turn.start) >= _MIN_EMBED_SECONDS:
            continue
        # ponytail: linear scan over anchors, O(short x long); bisect if a profile shows it.
        nearest = min(anchors, key=lambda a: min(abs(a.start - turn.end), abs(turn.start - a.end)))
        borrowed.append(Turn(turn.start, turn.end, nearest.speaker))
    return borrowed


class Diarizer:
    """Recognize speaker turns. Construct once and reuse; ``diarize`` is thread-safe."""

    def __init__(
        self,
        segmentation_dir: str | Path,
        embedding_path: str | Path,
        threads: int = 4,
        cluster_threshold: float = _CLUSTER_THRESHOLD,
    ):
        self.segmentation_dir = Path(segmentation_dir)
        self.embedding_path = Path(embedding_path)
        if not (self.segmentation_dir / "config.json").is_file() or next(
            self.segmentation_dir.rglob("model.onnx"), None
        ) is None:
            raise FileNotFoundError(f"Missing diarization segmentation model in {self.segmentation_dir}")
        if not self.embedding_path.is_file():
            raise FileNotFoundError(f"Missing diarization embedding model: {self.embedding_path}")

        self.cluster_threshold = cluster_threshold
        # CPU only: on Apple Silicon the CoreML path split these graphs into many
        # subgraphs and ran slower than plain CPU, so the accelerator is not worth it.
        providers = ["CPUExecutionProvider"]
        # pyannote segmentation: loaded through onnx_asr so its powerset decoding
        # (and the window re-ordering that keeps local speaker order stable) is
        # the same code the library ships and tests.
        import onnx_asr
        from onnx_asr.preprocessors.numpy_preprocessor import KaldiPreprocessorNumpy

        self._vad = onnx_asr.load_vad(
            "onnx-community/pyannote-segmentation-3.0", path=self.segmentation_dir, providers=providers
        )
        self._fbank = KaldiPreprocessorNumpy("wespeaker")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self._embedding = ort.InferenceSession(str(self.embedding_path), options, providers=providers)
        self._lock = Lock()

    def _frames(self, samples: np.ndarray) -> list[tuple[int, int]]:
        """Per-frame (sample position, local speaker) — ``-1`` for silence."""
        waveform = samples[None, :].astype(np.float32)
        window = int(_WINDOW_SECONDS * SAMPLE_RATE)
        overlap = int(_OVERLAP_SECONDS * SAMPLE_RATE)
        # The segmentation model windows in fixed 10 s frames, so an input
        # shorter than one window has to be padded (with silence) or the
        # sliding-window view is larger than the array and raises. A short clip
        # is single-speaker in practice; padding keeps it on the normal path.
        if waveform.shape[1] < window:
            waveform = np.pad(waveform, ((0, 0), (0, window - waveform.shape[1])))
        encoded = self._vad._encode(waveform, window, overlap)
        frames: list[tuple[int, int]] = []
        for begin, block in self._vad._decode((batch[0] for batch in encoded), window, overlap):
            for index, row in enumerate(block):
                position = begin + (index - 1) * _STRIDE + _RECEPTIVE_FIELD + _OFFSET
                speaker = -1 if row[0] >= _SPEECH_THRESHOLD else int(np.argmax(row[1:4]))
                frames.append((position, speaker))
        return frames

    def _turns(self, samples: np.ndarray) -> list[Turn]:
        turns: list[Turn] = []
        for position, speaker in self._frames(samples):
            if turns and turns[-1].speaker == speaker:
                turns[-1] = Turn(turns[-1].start, position / SAMPLE_RATE, speaker)
            else:
                turns.append(Turn(position / SAMPLE_RATE, position / SAMPLE_RATE, speaker))
        return [t for t in turns if t.speaker >= 0 and t.end > t.start]

    def _embed(self, chunk: np.ndarray) -> np.ndarray:
        waveform = chunk[None, :].astype(np.float32)
        features, _ = self._fbank(waveform, np.array([waveform.shape[1]], dtype=np.int64))
        # Without CMN the same voice's turns drift apart and one speaker splits into several.
        return self._embedding.run(["embedding"], {"x": _cmn(features)})[0][0]

    def diarize(self, samples: np.ndarray) -> list[Turn]:
        """Return the speaker turns of a 16 kHz mono recording, or ``[]`` when
        there is no speech."""
        if len(samples) < _RECEPTIVE_FIELD:
            return []
        with self._lock:
            turns = self._turns(samples)
            long_enough = [t for t in turns if (t.end - t.start) >= _MIN_EMBED_SECONDS]
            if not long_enough:
                return []
            embeddings = np.asarray(
                [self._embed(samples[int(t.start * SAMPLE_RATE) : int(t.end * SAMPLE_RATE)]) for t in long_enough]
            )
            labels = cluster_embeddings(embeddings, self.cluster_threshold)
            # A fragment is judged by its seconds of speech, not by how many speakers
            # the clustering produced: a count gate let nine labels through as a
            # "plausible meeting" when eight of them were slivers.
            labels = fold_small_clusters(embeddings, labels, [t.end - t.start for t in long_enough])
            labelled = [Turn(t.start, t.end, label) for t, label in zip(long_enough, labels)]
            borrowed = _borrow_short_turns(turns, labelled)
        return merge_turns(sorted(labelled + borrowed, key=lambda t: t.start))
