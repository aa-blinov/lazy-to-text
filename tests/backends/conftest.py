"""Backend tests stub onnx-asr; they must not reach the public model store
or depend on a mirrored snapshot being on disk."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_model_downloads(monkeypatch, tmp_path):
    from app.backends import onnx_backend

    flat = tmp_path / "flat-model"
    flat.mkdir()
    (flat / "model.onnx").write_bytes(b"x")
    (flat / "model.int8.onnx").write_bytes(b"x")
    monkeypatch.setattr(
        onnx_backend, "ensure_model_downloaded", lambda *args, **kwargs: flat,
    )
    monkeypatch.setattr(onnx_backend, "materialize_flat_model", lambda name: flat)
