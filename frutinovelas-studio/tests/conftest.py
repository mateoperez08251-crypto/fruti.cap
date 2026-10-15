"""Fixtures compartidas: cada prueba usa un directorio de datos aislado."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from frutinovelas.config import reset_settings_cache
from frutinovelas.db import reset_engine_cache


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "datos ñ con espacios"
    monkeypatch.setenv("FRUTINOVELAS_DATA_DIR", str(d))
    monkeypatch.setenv("FRUTINOVELAS_API_TOKEN", "")
    monkeypatch.delenv("FRUTINOVELAS_API_TOKEN", raising=False)
    reset_settings_cache()
    reset_engine_cache()
    yield d
    reset_settings_cache()
    reset_engine_cache()


@pytest.fixture
def client(data_dir):
    from fastapi.testclient import TestClient

    from frutinovelas.api import create_app

    with TestClient(create_app()) as c:
        yield c


def png_bytes(color=(200, 180, 40), size=(64, 112), fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()
