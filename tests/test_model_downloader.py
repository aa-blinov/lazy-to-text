"""The public-store downloader: cancel stops it, and a stop leaves no half model."""

from __future__ import annotations

import hashlib
import io
import json

import pytest

from app import model_downloader as md

REPO = "owner/tiny"
BODY = b"x" * (3 * md._CHUNK_BYTES)


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def store(monkeypatch, tmp_path):
    manifest = {
        "repos": [{"repo": REPO, "revision": "r1", "aliases": ["tiny"],
                   "files": [{"path": "model.onnx", "size": len(BODY)}]}],
        "files": [{"repo": REPO, "revision": "r1", "path": "model.onnx",
                   "size": len(BODY), "sha256": hashlib.sha256(BODY).hexdigest()}],
    }
    monkeypatch.setattr(md, "_manifest", lambda: manifest)
    monkeypatch.setattr(md, "_hub_root", lambda: tmp_path / "hub")
    monkeypatch.setattr(md, "flat_model_dir", lambda canonical: tmp_path / "flat")
    monkeypatch.setattr(md.urllib.request, "urlopen", lambda *a, **k: _Response(BODY))
    return tmp_path / "hub" / "models--owner--tiny"


def test_a_download_that_is_not_cancelled_publishes_the_snapshot(store):
    snapshot = md.ensure_model_downloaded(REPO, "tiny", None)

    assert (snapshot / "model.onnx").read_bytes() == BODY
    assert any(snapshot.glob(".l2t-complete-*"))


def test_cancel_mid_transfer_raises_and_publishes_nothing(store):
    seen = []

    def cancelled():
        seen.append(1)
        return len(seen) > 2  # let the first chunk through, then stop

    with pytest.raises(md.DownloadCancelled):
        md.ensure_model_downloaded(REPO, "tiny", None, cancelled=cancelled)

    assert not (store / "snapshots").exists() or not any((store / "snapshots").rglob(".l2t-complete-*"))
    assert not list(store.rglob("*.part"))


def test_cancel_before_start_touches_nothing(store):
    with pytest.raises(md.DownloadCancelled):
        md.ensure_model_downloaded(REPO, "tiny", None, cancelled=lambda: True)

    assert not store.exists()


def test_a_corrupt_download_is_refused(store, monkeypatch):
    monkeypatch.setattr(md.urllib.request, "urlopen",
                        lambda *a, **k: _Response(b"y" * len(BODY)))

    with pytest.raises(IOError, match="SHA-256"):
        md.ensure_model_downloaded(REPO, "tiny", None)

    assert not any(store.rglob(".l2t-complete-*"))
