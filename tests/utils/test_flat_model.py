"""The flat-directory workaround for onnxruntime's external-data check.

onnx-asr 0.12.0 brings onnxruntime 1.30, which validates that a model's
external weights do not resolve outside its own directory. The hub cache
cannot satisfy that: huggingface_hub stores ``encoder-model.onnx`` and
``encoder-model.onnx.data`` as two *separate symlinks* into ``blobs/``,
while the .onnx names its data by the plain relative string
``encoder-model.onnx.data``. Resolve that against the blob directory and
the file is not there.

``materialize_flat_model`` re-exposes the same bytes as real sibling
files. These tests pin the two properties that make it work — real
files, and no duplicated bytes — plus the precision guard, which exists
because handing onnx-asr a ``path`` also *seals* its search.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.utils import flat_model_dir, materialize_flat_model


@pytest.fixture
def hub_cache(tmp_path, monkeypatch):
    """A hub cache holding one symlinked snapshot, laid out as HF writes it.

    The real shape matters: blobs live at ``<repo>/blobs/<name>`` and
    ``<repo>/snapshots/<rev>/<file>`` is a symlink reaching *up two
    levels* into them. A fixture that got that wrong would let a
    ``materialize`` that resolved symlinks correctly still look broken.
    """
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    repo = tmp_path / "hub" / "models--owner--repo"
    blobs = repo / "blobs"
    snapshot = repo / "snapshots" / "abc123"
    blobs.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    for name, size in (
        ("config.json", 40),
        ("encoder-model.onnx", 64),
        ("encoder-model.onnx.data", 4096),
    ):
        (blobs / name).write_bytes(b"x" * size)
        (snapshot / name).symlink_to(Path("..") / ".." / "blobs" / name)
    return snapshot


def test_materialize_produces_real_files_not_symlinks(hub_cache):
    flat = materialize_flat_model("owner/repo")
    assert flat is not None
    files = sorted(p.name for p in flat.iterdir())
    assert files == [
        "config.json",
        "encoder-model.onnx",
        "encoder-model.onnx.data",
    ]
    # The whole point: ORT cannot follow a symlink out of the tree.
    assert all(not p.is_symlink() for p in flat.iterdir())


def test_materialize_costs_no_extra_disk(hub_cache):
    """A copy would double a 2.4 GB model; a hardlink is the same inode."""
    flat = materialize_flat_model("owner/repo")
    assert flat is not None
    blob = (hub_cache / ".." / ".." / "blobs" / "encoder-model.onnx.data")
    assert blob.is_file()
    assert (flat / "encoder-model.onnx.data").stat().st_ino == blob.stat().st_ino


def test_materialize_is_idempotent(hub_cache):
    first = materialize_flat_model("owner/repo")
    before = sorted((p.name, p.stat().st_ino) for p in first.iterdir())
    second = materialize_flat_model("owner/repo")
    after = sorted((p.name, p.stat().st_ino) for p in second.iterdir())
    assert before == after


def test_materialize_returns_none_when_nothing_is_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert materialize_flat_model("owner/absent") is None
    assert materialize_flat_model("") is None


def test_materialize_refuses_a_snapshot_with_no_weights(tmp_path, monkeypatch):
    """A partial download must not produce a directory that looks loadable.

    huggingface_hub writes ``config.json`` first and the gigabytes after
    it, so a cancelled or failed download leaves exactly this behind —
    which is the whole reason ``is_onnx_model_cached`` insists on a real
    ``.onnx``. Handing such a snapshot over would seal onnx-asr's search
    onto an empty directory and turn a resumable download into
    "File not found in path".
    """
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    repo = tmp_path / "hub" / "models--owner--partial"
    snapshot = repo / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")

    assert materialize_flat_model("owner/partial") is None


def test_flat_dir_sits_under_the_models_root(tmp_path, monkeypatch):
    """So the Storage card's size figure keeps covering every byte."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    flat = flat_model_dir("owner/repo")
    assert flat.parent.parent == tmp_path
    assert flat.name == "owner__repo"


# ---- the precision guard ---------------------------------------------------


@pytest.mark.parametrize(
    "present,quantization,expected",
    [
        (["m_ctc.int8.onnx"], "int8", True),
        (["m_ctc.int8.onnx"], None, False),
        (["m_ctc.int8.onnx"], "fp16", False),
        (["m_ctc.onnx"], None, True),
        (["m_ctc.onnx"], "int8", False),
        (["m_ctc.fp16.onnx"], "fp16", True),
        (["m_ctc.fp16.onnx"], None, False),
        (["a.onnx", "b.int8.onnx"], None, True),
        ([], None, False),
    ],
)
def test_flat_has_precision(present, quantization, expected, tmp_path):
    """Passing ``path`` seals onnx-asr's search, so a precision that isn't
    on disk has to fall through to a normal download rather than
    surfacing as "File not found in path"."""
    from app.backends.onnx_backend import _flat_has_precision

    flat = tmp_path / "flat"
    flat.mkdir()
    for name in present:
        (flat / name).write_bytes(b"x")

    assert _flat_has_precision(flat, quantization) is expected


def test_load_kwargs_only_seal_the_path_when_the_precision_is_present(
    hub_cache, monkeypatch
):
    """End to end on the kwargs the backend actually builds.

    This fixture holds only full-precision weights, so the ``None`` (fp32)
    request gets the directory and the ``int8`` request must *not* — the
    int8 file simply is not on disk, and sealing the path there would
    turn a precision switch into "File not found in path" instead of a
    download.
    """
    from app.backends.onnx_backend import OnnxAsrBackend

    def kwargs_for(quantization):
        backend = OnnxAsrBackend(
            model="owner/repo", family="parakeet", device="cpu",
            quantization=quantization, load_id="owner/repo",
        )
        return backend._build_load_kwargs(["CPUExecutionProvider"])

    fp32 = kwargs_for(None)
    assert fp32["path"] is not None
    assert not fp32["path"].is_symlink()
    assert (fp32["path"] / "encoder-model.onnx.data").is_file()

    assert "path" not in kwargs_for("int8")
