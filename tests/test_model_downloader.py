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
        return len(seen) > 3  # let the first chunk through, then stop

    with pytest.raises(md.DownloadCancelled):
        md.ensure_model_downloaded(REPO, "tiny", None, cancelled=cancelled)

    assert not (store / "snapshots").exists() or not any((store / "snapshots").rglob(".l2t-complete-*"))
    # The partial file stays so that a retry can continue it.
    assert list(store.rglob("*.part"))


def _ranged(requests):
    def urlopen(request, *a, **k):
        requests.append(request)
        start = int((request.headers.get("Range") or "bytes=0-").split("=")[1].split("-")[0])
        response = _Response(BODY[start:])
        response.status = 206 if start else 200
        return response
    return urlopen


def test_a_retry_resumes_the_partial_file_with_a_range_request(store, monkeypatch):
    seen = []

    def cancelled():
        seen.append(1)
        return len(seen) > 3

    with pytest.raises(md.DownloadCancelled):
        md.ensure_model_downloaded(REPO, "tiny", None, cancelled=cancelled)
    kept = next(store.rglob("*.part")).stat().st_size
    assert 0 < kept < len(BODY)

    requests = []
    monkeypatch.setattr(md.urllib.request, "urlopen", _ranged(requests))
    snapshot = md.ensure_model_downloaded(REPO, "tiny", None)

    assert requests[0].headers["Range"] == f"bytes={kept}-"
    assert (snapshot / "model.onnx").read_bytes() == BODY


def test_a_server_that_ignores_range_restarts_the_file(store, monkeypatch):
    seen = []

    def cancelled():
        seen.append(1)
        return len(seen) > 3

    with pytest.raises(md.DownloadCancelled):
        md.ensure_model_downloaded(REPO, "tiny", None, cancelled=cancelled)

    monkeypatch.setattr(md.urllib.request, "urlopen", lambda *a, **k: _Response(BODY))
    snapshot = md.ensure_model_downloaded(REPO, "tiny", None)

    assert (snapshot / "model.onnx").read_bytes() == BODY


def test_a_file_longer_than_the_manifest_says_is_refused_and_not_kept(store, monkeypatch):
    monkeypatch.setattr(md.urllib.request, "urlopen",
                        lambda *a, **k: _Response(BODY + b"extra"))

    with pytest.raises(IOError, match="more than expected"):
        md.ensure_model_downloaded(REPO, "tiny", None)

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


def test_a_marker_from_an_older_file_list_does_not_count(store, monkeypatch):
    """The manifest can change what a card needs; a marker written for the old
    list must not vouch for the new one."""
    snapshot = md.ensure_model_downloaded(REPO, "tiny", None)
    old = next(snapshot.glob(".l2t-complete-*"))
    old.rename(snapshot / ".l2t-complete-tiny-default")  # the form an earlier version wrote

    requests = []
    monkeypatch.setattr(md.urllib.request, "urlopen",
                        lambda request, *a, **k: requests.append(request) or _Response(BODY))
    md.ensure_model_downloaded(REPO, "tiny", None)

    assert requests == []  # the file was already there and verified: nothing fetched
    assert len(list(snapshot.glob(".l2t-complete-tiny-default-*"))) == 1


def test_a_card_whose_files_grew_is_topped_up_not_downloaded_again(store, monkeypatch):
    snapshot = md.ensure_model_downloaded(REPO, "tiny", None)
    extra = b"config"
    manifest = md._manifest()
    manifest["files"].append({"repo": REPO, "revision": "r1", "path": "config.json",
                              "size": len(extra), "sha256": hashlib.sha256(extra).hexdigest()})
    manifest["repos"][0]["files"].append({"path": "config.json", "size": len(extra)})
    fetched = []

    def urlopen(request, *a, **k):
        fetched.append(request.full_url.rsplit("/", 1)[-1])
        return _Response(extra if request.full_url.endswith("config.json") else BODY)

    monkeypatch.setattr(md.urllib.request, "urlopen", urlopen)
    md.ensure_model_downloaded(REPO, "tiny", None)

    assert fetched == ["config.json"]
    assert (snapshot / "config.json").read_bytes() == extra
    assert (snapshot / "model.onnx").read_bytes() == BODY


# ---- the shipped manifest -------------------------------------------------------


def test_the_manifest_is_well_formed():
    manifest = json.loads(
        (md.Path(md.__file__).with_name("model_manifest.json")).read_text(encoding="utf-8"))

    for item in manifest["files"]:
        assert len(item["sha256"]) == 64 and int(item["sha256"], 16) >= 0
        assert item["size"] > 0
        parts = item["path"].replace("\\", "/").split("/")
        assert not item["path"].startswith("/") and ".." not in parts and ":" not in item["path"]
    repos = {r["repo"] for r in manifest["repos"]}
    assert {f["repo"] for f in manifest["files"]} <= repos


def _cards():
    from app.model_mapping import MODELS

    for info in MODELS:
        load_id = info.onnx_load_id or info.canonical
        quantization = md.effective_quantization(
            info.canonical, md.quantization_for(info.compute_type))
        yield info, load_id, quantization


def test_every_card_has_its_files_listed_in_the_manifest():
    entries = md._manifest().get("cards", {})
    for info, load_id, quantization in _cards():
        entry = entries.get(md.card_key(load_id, quantization))
        assert entry is not None, f"{info.alias}: no files listed for {load_id} at {quantization}"
        assert entry["repo"] == info.canonical
        known = {f["path"] for f in md._manifest()["files"] if f["repo"] == info.canonical}
        assert set(entry["files"]) <= known, f"{info.alias}: lists files the store does not hold"


def test_the_files_listed_for_a_card_satisfy_the_loader(tmp_path):
    """onnx-asr looks for fixed names at a given precision. Load every card's
    listed files through its own file resolver (names only, no weights): a card
    that lacks a graph, a vocabulary or a config fails here, not on the user's
    first load."""
    from onnx_asr.loader import create_asr_resolver

    entries = md._manifest().get("cards", {})
    for info, load_id, quantization in _cards():
        entry = entries.get(md.card_key(load_id, quantization))
        if entry is None:
            continue
        folder = tmp_path / info.alias
        for relative in entry["files"]:
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
        if entry.get("model_type"):
            (folder / "config.json").write_text(json.dumps({"model_type": entry["model_type"]}))
        resolver = create_asr_resolver(load_id, local_dir=folder)
        found = resolver.resolve_model(quantization=quantization)
        assert found, info.alias
