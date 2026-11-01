"""The diarization model on disk: cache checks, paths, download and removal."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional, Tuple

from app import utils
from app.model_mapping import DIARIZATION
from app.model_downloader import ensure_model_downloaded

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, int], None]


def is_cached() -> bool:
    """Both repositories hold their weights.

    Only completed mirror snapshots count as cached.
    """
    return all(_snapshot(repo) is not None for repo, _ in DIARIZATION.parts)


def _snapshot(repo: str) -> Optional[Path]:
    snapshots = utils._hub_root() / f"models--{repo.replace('/', '--')}" / "snapshots"
    if not snapshots.is_dir():
        return None
    for snap in sorted(snapshots.iterdir()):
        if (snap.is_dir() and utils.snapshot_is_complete(snap)
                and next(snap.rglob("*.onnx"), None) is not None):
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


def download(progress: Optional[ProgressFn] = None, cancelled=None) -> None:
    """Fetch both repositories, calling ``progress(done_bytes, total_bytes)``.

    Files are downloaded from the public object store and verified by hash.
    """
    from app.model_downloader import _manifest

    parts = DIARIZATION.parts
    total = sum(int(item["size"]) for item in _manifest()["files"]
                if any(item["repo"] == repo and item["path"] in patterns
                       for repo, patterns in parts))
    done = 0
    for repo, patterns in parts:
        log.info("Downloading diarization part %s", repo)
        ensure_model_downloaded(repo, "diarization", "float32", cancelled=cancelled)
        if progress is not None:
            done += sum(int(item["size"]) for item in _manifest()["files"]
                        if item["repo"] == repo and item["path"] in patterns)
            progress(done, total)
