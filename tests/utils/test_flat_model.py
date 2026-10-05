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


def test_materialize_survives_a_link_that_does_not_dereference(
    hub_cache, monkeypatch
):
    """The bug this file's platform matrix found, made reproducible here.

    ``os.link`` on a symlink is not portable: macOS's ``link()``
    dereferences, Linux's does not. On Linux the same call therefore
    produced a hard link *to the symlink* — and since the hub cache's
    symlink points at a **relative** ``../../blobs/…``, that link is only
    resolvable from the snapshot directory. Moved into the flat
    directory it points at nothing, so the flat directory was full of
    dangling symlinks: the exact failure this function exists to
    prevent, and invisible on a Mac.

    Forcing ``follow_symlinks=False`` reproduces the Linux behaviour on
    whichever machine the suite runs on, so the fix is checked by
    something that fails on all three platforms rather than only on the
    two that are not this one.
    """
    from app import utils

    real_link = os.link

    def posix_link(src, dst, **kwargs):
        kwargs.setdefault("follow_symlinks", False)
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(utils.os, "link", posix_link)

    flat = utils.materialize_flat_model("owner/repo")
    assert flat is not None
    assert all(not p.is_symlink() for p in flat.iterdir()), (
        "a link was made to the symlink instead of through it"
    )
    data = flat / "encoder-model.onnx.data"
    assert data.is_file()
    blob = (hub_cache / ".." / ".." / "blobs" / "encoder-model.onnx.data")
    assert data.stat().st_ino == blob.stat().st_ino


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


@pytest.fixture
def nested_onnx_cache(tmp_path, monkeypatch):
    """A hub cache laid out the way the whisper exports actually ship.

    ``onnx-community/whisper-large-v3-ONNX`` has no top-level ``.onnx``
    at all — every weight sits in ``onnx/``, and the graph names its
    external data by a *bare* relative string
    (``decoder_model_merged.onnx_data``). Built as real directories
    rather than symlinked ones, because that is the difference between
    "onnx-asr finds the weights" and "onnx-asr is handed a directory with
    no model in it".
    """
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    repo = tmp_path / "hub" / "models--onnx-community--whisper-large-v3-ONNX"
    blobs = repo / "blobs"
    snapshot = repo / "snapshots" / "abc123"
    onnx = snapshot / "onnx"
    blobs.mkdir(parents=True)
    onnx.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")
    for name, size in (
        ("decoder_model_merged.onnx", 64),
        ("decoder_model_merged.onnx_data", 4096),
        ("encoder_model.onnx", 32),
    ):
        (blobs / name).write_bytes(b"x" * size)
        (onnx / name).symlink_to(Path("..") / ".." / ".." / "blobs" / name)
    return onnx


def test_weights_in_a_nested_onnx_dir_are_still_materialised(nested_onnx_cache):
    """The bug that kept ``whisper-large-v3`` from ever loading.

    A top-level-only pass links the ``onnx/`` *directory* and finds no
    ``.onnx``, so it returned ``None``, and the backend fell back to
    loading straight out of the symlinked snapshot. onnxruntime then
    refused the graph:

        …decoder_model_merged.onnx_data, but it is a symbolic link

    which is this function's entire reason to exist, reached by a
    layout it did not know about.
    """
    flat = materialize_flat_model("onnx-community/whisper-large-v3-ONNX")
    assert flat is not None, "no flat directory for a repo whose weights are nested"
    names = {p.name for p in flat.iterdir()}
    assert {"decoder_model_merged.onnx", "decoder_model_merged.onnx_data"} <= names


def test_the_graph_and_its_external_data_end_up_as_siblings(nested_onnx_cache):
    """ORT resolves the data name against the model's own directory, so
    the two have to land next to each other under their bare names."""
    flat = materialize_flat_model("onnx-community/whisper-large-v3-ONNX")
    graph = flat / "decoder_model_merged.onnx"
    data = flat / "decoder_model_merged.onnx_data"
    assert graph.is_file() and data.is_file()
    assert all(not p.is_symlink() for p in (graph, data))


def test_nested_weights_cost_no_extra_disk(nested_onnx_cache):
    """The same hardlink guarantee as the top-level case, on a 3.1 GB model."""
    flat = materialize_flat_model("onnx-community/whisper-large-v3-ONNX")
    repo = nested_onnx_cache.parent.parent.parent  # .../models--<repo>
    blob = repo / "blobs" / "decoder_model_merged.onnx_data"
    assert (flat / "decoder_model_merged.onnx_data").stat().st_ino == blob.stat().st_ino


def test_a_nested_repo_reads_as_cached(nested_onnx_cache):
    """``is_onnx_model_cached`` looked only at the snapshot's top level, so
    a fully downloaded 3.1 GB model read as absent: the Storage card
    never filled in and every launch went looking for it again."""
    from app.utils import is_onnx_model_cached

    assert is_onnx_model_cached("onnx-community/whisper-large-v3-ONNX") is True


def test_a_top_level_file_is_not_overwritten_by_a_nested_one(
    nested_onnx_cache, monkeypatch
):
    """Same name at both levels: the top-level file keeps it.

    ``iterdir`` returns whatever order the filesystem feels like, and on
    the machine this was written on it handed back ``onnx/`` first — so
    the nested file claimed ``encoder_model.onnx`` before the top-level
    one was ever looked at. Rather than rely on getting that ordering by
    luck, the snapshot is made to yield the directory first explicitly,
    which is the hostile order on every platform.
    """
    from app import utils

    snapshot = nested_onnx_cache.parent
    real_iterdir = Path.iterdir

    def hostile(self):
        entries = list(real_iterdir(self))
        return iter(sorted(entries, key=lambda p: not p.is_dir()))

    monkeypatch.setattr(utils.Path, "iterdir", hostile)
    top = snapshot / "encoder_model.onnx"
    top.write_bytes(b"top-level")

    flat = materialize_flat_model("onnx-community/whisper-large-v3-ONNX")
    assert (flat / "encoder_model.onnx").read_bytes() == b"top-level"


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
