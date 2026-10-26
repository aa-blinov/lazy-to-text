"""The diarization model on disk: where it is, whether it is whole, how it is
fetched and removed.

It is two Hugging Face repositories (see ``model_mapping.DIARIZATION``), kept
in the same hub cache as the speech models, so the Storage card measures it,
moving the models folder moves it and the HF token applies to it. Nothing here
touches ``onnx_asr`` or ``onnxruntime``: the runtime process only asks whether
the files are there, and the worker is the one that opens them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional, Tuple

from app import utils
from app.model_mapping import DIARIZATION

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, int], None]


def is_cached() -> bool:
    """Both repositories hold their weights.

    ``is_onnx_model_cached`` wants a real ``.onnx`` under a snapshot, which
    ``huggingface_hub`` only creates once a file has fully arrived, so a download
    that was cut off reads as absent.
    """
    return all(utils.is_onnx_model_cached(repo) for repo, _ in DIARIZATION.parts)


def _snapshot(repo: str) -> Optional[Path]:
    snapshots = utils._hub_root() / f"models--{repo.replace('/', '--')}" / "snapshots"
    if not snapshots.is_dir():
        return None
    for snap in sorted(snapshots.iterdir()):
        if snap.is_dir() and next(snap.rglob("*.onnx"), None) is not None:
            return snap
    return None


def paths() -> Optional[Tuple[Path, Path]]:
    """``(segmentation directory, embedding file)``, or ``None`` when absent."""
    seg = _snapshot(DIARIZATION.segmentation)
    emb_dir = _snapshot(DIARIZATION.embedding)
    if seg is None or emb_dir is None:
        return None
    emb = next(iter(sorted(emb_dir.glob("*.onnx"))), None)
    return (seg, emb) if emb is not None else None


def cached_size() -> int:
    return sum(utils.cached_model_size(repo) for repo, _ in DIARIZATION.parts)


def delete() -> bool:
    """Remove both repositories; ``True`` when nothing is left of either."""
    results = [utils.delete_cached_model(repo) for repo, _ in DIARIZATION.parts]
    return any(results) and not any(
        (utils._hub_root() / f"models--{repo.replace('/', '--')}").exists()
        for repo, _ in DIARIZATION.parts
    )


def download(progress: Optional[ProgressFn] = None) -> None:
    """Fetch both repositories, calling ``progress(done_bytes, total_bytes)``.

    Raises whatever ``huggingface_hub`` raises; the caller reports it. Only the
    fp32 embedder and the segmentation weights are fetched, not every precision
    the repositories carry.
    """
    from huggingface_hub import snapshot_download
    from tqdm.auto import tqdm

    totals: dict[int, Tuple[int, int]] = {}

    class _Bar(tqdm):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["disable"] = True
            # A disabled bar returns from __init__ before it stores its unit.
            self._bytes = kwargs.get("unit") == "B"
            super().__init__(*args, **kwargs)
            self._report()

        def update(self, n=1):
            self.n = (self.n or 0) + (n or 0)
            self._report()
            return True

        def _report(self) -> None:
            if not self._bytes:
                return
            totals[id(self)] = (int(self.n or 0), int(self.total or 0))
            if progress is not None:
                done = sum(v[0] for v in totals.values())
                total = sum(v[1] for v in totals.values())
                try:
                    progress(done, total)
                except Exception:  # pragma: no cover - a callback must not stop a download
                    pass

    for repo, patterns in DIARIZATION.parts:
        log.info("Downloading diarization part %s", repo)
        snapshot_download(repo, allow_patterns=list(patterns), tqdm_class=_Bar)
