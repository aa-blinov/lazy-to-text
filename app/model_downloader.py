"""Download the model files used by this app from its public object store."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from app.backends._progress import report_progress
from app.utils import _hub_root, flat_model_dir

log = logging.getLogger(__name__)

PUBLIC_ROOT = "https://f003.backblazeb2.com/file/lazy-to-text-models/lazy-to-text"
_CHUNK_BYTES = 1024 * 1024
_URL_TIMEOUT_S = 15


class DownloadCancelled(Exception):
    """The user cancelled a model transfer."""


class _CorruptDownload(IOError):
    """A file arrived with the wrong size or hash."""


def _manifest() -> dict:
    path = Path(__file__).with_name("model_manifest.json")
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def quantization_for(compute_type: Optional[str]) -> Optional[str]:
    """Translate a card's ``compute_type`` to onnx-asr's ``quantization``."""
    if compute_type in ("int8", "int8_float16"):
        return "int8"
    return None


def effective_quantization(load_id: str, quantization: Optional[str]) -> Optional[str]:
    """The precision a card really loads at.

    The mirror holds the Vosk models at int8 only, whatever the card's
    ``compute_type`` says.
    """
    if load_id.lower().startswith("alphacep/vosk-"):
        return "int8"
    return quantization


def variant_present(directory: Path, canonical: str, load_id: str,
                    quantization: Optional[str]) -> bool:
    """Whether ``directory`` already holds every graph this card needs.

    Cards that share one repository (GigaAM v3 CTC and RNN-T) select
    different graphs from it; a directory built for one is not enough for
    the other.
    """
    repo_files = [f for f in _manifest()["files"] if f["repo"] == canonical]
    wanted = [f["path"] for f in _files_for(repo_files, load_id, quantization)
              if f["path"].endswith(".onnx")]
    return bool(wanted) and all((directory / name).exists() for name in wanted)


def card_key(load_id: str, quantization: Optional[str]) -> str:
    return f"{load_id}|{quantization or ''}"


def _files_for(repo_files: list[dict], load_id: str, quantization: Optional[str]) -> list[dict]:
    """The files one model card needs from its repository.

    The manifest lists them per card (``scripts/mirror_models.py`` works them out
    from what onnx-asr's loader looks for). A model without an entry (the speaker
    models, the VAD) takes the files that suit the precision.
    """
    entry = _manifest().get("cards", {}).get(card_key(load_id, quantization))
    if entry is not None:
        wanted = set(entry["files"])
        return [item for item in repo_files if item["path"] in wanted]
    return _guess_files_for(repo_files, load_id, quantization)


def _guess_files_for(repo_files: list[dict], load_id: str, quantization: Optional[str]) -> list[dict]:
    """Pick support files and the selected graph variant for one model card."""
    onnx = [item for item in repo_files if item["path"].endswith(".onnx")]
    int8_available = any(".int8.onnx" in item["path"] for item in onnx)
    is_vosk = load_id.lower().startswith("alphacep/vosk-")
    if is_vosk:
        quantization = "int8"
    selected = []
    for item in repo_files:
        name = item["path"]
        if (name.endswith((".onnx.data", ".onnx_data"))
                and quantization == "int8"):
            continue
        if is_vosk and not ("int8.onnx" in name or name.startswith("lang/")):
            continue
        if name.endswith(".onnx"):
            lower_id = load_id.lower()
            if "gigaam-v3" in lower_id or "gigaam-v3-onnx" in lower_id:
                want_rnnt = "rnnt" in lower_id
                if name.endswith(".onnx") and name.startswith("v3_"):
                    if want_rnnt != name.startswith("v3_e2e_rnnt_"):
                        continue
            if quantization == "int8" and int8_available:
                if ".int8.onnx" not in name:
                    continue
            elif quantization != "int8" and int8_available:
                if ".int8.onnx" in name:
                    continue
        selected.append(item)
    return selected


def _cancelled(check: Optional[Callable[[], bool]]) -> bool:
    return bool(check and check())


def _hash_file(path: Path, check: Optional[Callable[[], bool]]) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            if _cancelled(check):
                raise DownloadCancelled("Model download cancelled")
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model_downloaded(
    canonical: str,
    load_id: str,
    quantization: Optional[str],
    *,
    cancelled: Optional[Callable[[], bool]] = None,
) -> Path:
    """Fetch and verify one model snapshot, returning its local directory.

    Files land in a staging directory outside ``snapshots`` and become visible
    to cache discovery only after every selected object passes size and hash
    checks. Completed files are kept in staging so a retry can reuse them.
    """
    if _cancelled(cancelled):
        raise DownloadCancelled("Model download cancelled")

    manifest = _manifest()
    repo = next((item for item in manifest["repos"] if item["repo"] == canonical), None)
    if repo is None:
        raise RuntimeError(f"No public model manifest entry for {canonical}")
    repo_files = [item for item in manifest["files"] if item["repo"] == canonical]
    files = _files_for(repo_files, load_id, quantization)
    if not files:
        raise RuntimeError(f"No public model files selected for {canonical}")

    cache_root = _hub_root()
    repo_dir = cache_root / f"models--{canonical.replace('/', '--')}"
    revision = str(repo["revision"])
    snapshot = repo_dir / "snapshots" / revision
    variant = _variant_key(load_id, quantization)
    # The marker names the exact files it vouches for: when the manifest changes
    # what a card needs, an older marker no longer counts and the card is topped up.
    fingerprint = hashlib.sha256(
        "\n".join(sorted(f"{item['path']}:{item['sha256']}" for item in files)).encode()
    ).hexdigest()[:10]
    complete = snapshot / f".l2t-complete-{variant}-{fingerprint}"
    if complete.is_file():
        return snapshot

    # The flat directory is shared by cards that point at the same canonical
    # repository. Keep it out of the way while a missing variant is staged;
    # otherwise the backend could mistake yesterday's variant for this one.
    shutil.rmtree(flat_model_dir(canonical), ignore_errors=True)

    staging = repo_dir / ".s3-staging" / revision / variant
    staging.mkdir(parents=True, exist_ok=True)
    total = sum(int(item["size"]) for item in files)
    done = 0
    for item in files:
        if _cancelled(cancelled):
            raise DownloadCancelled("Model download cancelled")
        relative = Path(item["path"])
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        expected_size = int(item["size"])
        expected_hash = str(item["sha256"])
        if (target.is_file() and target.stat().st_size == expected_size
                and _hash_file(target, cancelled) == expected_hash):
            done += expected_size
            _report(done, total, item["path"])
            continue
        # Already in the snapshot from an earlier download (and still the right
        # bytes): nothing to fetch, nothing to move.
        placed = snapshot / relative
        if (placed.is_file() and placed.stat().st_size == expected_size
                and _hash_file(placed, cancelled) == expected_hash):
            done += expected_size
            _report(done, total, item["path"])
            continue

        partial = target.with_name(target.name + ".part")
        escaped_repo = urllib.parse.quote(canonical, safe="/")
        escaped_path = urllib.parse.quote(item["path"], safe="/")
        url = f"{PUBLIC_ROOT}/{escaped_repo}/{escaped_path}"
        digest = hashlib.sha256()
        received = 0
        headers = {"User-Agent": "LazyToText/1"}
        # A cancelled or interrupted transfer keeps its partial file, so a
        # retry continues from where it stopped instead of from zero.
        if partial.is_file():
            have = partial.stat().st_size
            if 0 < have < expected_size:
                with partial.open("rb") as earlier:
                    while chunk := earlier.read(_CHUNK_BYTES):
                        if _cancelled(cancelled):
                            raise DownloadCancelled("Model download cancelled")
                        digest.update(chunk)
                received = have
                headers["Range"] = f"bytes={have}-"
            else:
                partial.unlink(missing_ok=True)
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=_URL_TIMEOUT_S) as response:
                if received and response.status != 206:
                    # The server sent the whole file again: start over.
                    digest = hashlib.sha256()
                    received = 0
                elif response.status not in (200, 206):
                    raise RuntimeError(f"Model server returned HTTP {response.status}")
                with partial.open("ab" if received else "wb") as output:
                    while True:
                        if _cancelled(cancelled):
                            raise DownloadCancelled("Model download cancelled")
                        chunk = response.read(_CHUNK_BYTES)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        if received > expected_size:
                            raise _CorruptDownload(
                                f"Downloaded more than expected for {item['path']}"
                            )
                        _report(done + received, total, item["path"])
            if received != expected_size:
                raise _CorruptDownload(
                    f"Downloaded size mismatch for {item['path']}: "
                    f"got {received}, expected {expected_size}"
                )
            if digest.hexdigest() != expected_hash:
                raise _CorruptDownload(f"SHA-256 mismatch for {item['path']}")
            os.replace(partial, target)
            done += expected_size
        except _CorruptDownload:
            # Wrong content cannot be resumed.
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    if _cancelled(cancelled):
        raise DownloadCancelled("Model download cancelled")
    repo_dir.joinpath("snapshots").mkdir(parents=True, exist_ok=True)
    snapshot.mkdir(parents=True, exist_ok=True)
    for item in files:
        relative = Path(item["path"])
        source = staging / relative
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            os.replace(source, target)
    complete.write_text(revision, encoding="ascii")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(flat_model_dir(canonical), ignore_errors=True)
    log.info("Verified public model files for %s at revision %s", canonical, revision)
    return snapshot


def _variant_key(load_id: str, quantization: Optional[str]) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in load_id.lower())
    precision = quantization or "default"
    return f"{safe}-{precision}"


def _report(current: int, total: int, desc: str) -> None:
    report_progress(current, total, desc)

