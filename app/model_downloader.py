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


def _manifest() -> dict:
    path = Path(__file__).with_name("model_manifest.json")
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _files_for(repo_files: list[dict], load_id: str, quantization: Optional[str]) -> list[dict]:
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
    complete = snapshot / f".l2t-complete-{variant}"
    if complete.is_file():
        return snapshot

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

        partial = target.with_name(target.name + ".part")
        escaped_repo = urllib.parse.quote(canonical, safe="/")
        escaped_path = urllib.parse.quote(item["path"], safe="/")
        url = f"{PUBLIC_ROOT}/{escaped_repo}/{escaped_path}"
        digest = hashlib.sha256()
        received = 0
        request = urllib.request.Request(url, headers={"User-Agent": "LazyToText/1"})
        try:
            with urllib.request.urlopen(request, timeout=_URL_TIMEOUT_S) as response:
                if response.status != 200:
                    raise RuntimeError(f"Model server returned HTTP {response.status}")
                with partial.open("wb") as output:
                    while True:
                        if _cancelled(cancelled):
                            raise DownloadCancelled("Model download cancelled")
                        chunk = response.read(_CHUNK_BYTES)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        _report(done + received, total, item["path"])
            if received != expected_size:
                raise IOError(
                    f"Downloaded size mismatch for {item['path']}: "
                    f"got {received}, expected {expected_size}"
                )
            if digest.hexdigest() != expected_hash:
                raise IOError(f"SHA-256 mismatch for {item['path']}")
            os.replace(partial, target)
            done += expected_size
        except BaseException:
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

