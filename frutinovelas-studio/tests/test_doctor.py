"""Pruebas del comando de diagnóstico (sin red real ni ComfyUI)."""

from __future__ import annotations

import json

import httpx
import respx

from frutinovelas import doctor
from frutinovelas.config import Settings


def _settings(tmp_path, **kw) -> Settings:
    return Settings(FRUTINOVELAS_DATA_DIR=str(tmp_path / "datos con espacio ñ"), **kw)


def test_mask_url_hides_credentials_and_query():
    masked = doctor.mask_url("https://user:secreto@abc.trycloudflare.com:8443/path?token=XYZ")
    assert "secreto" not in masked
    assert "XYZ" not in masked
    assert "user" not in masked
    assert "abc.trycloudflare.com:8443" in masked


def test_storage_creates_dirs_and_writes_unicode(tmp_path):
    s = _settings(tmp_path)
    checks = doctor.check_storage(s)
    assert checks[0].status == doctor.OK
    assert s.assets_dir.is_dir()
    # La sonda temporal no deja basura.
    assert list(s.tmp_dir.iterdir()) == []


def test_sqlite_check_cleans_up(tmp_path):
    s = _settings(tmp_path)
    s.ensure_dirs()
    checks = doctor.check_sqlite(s)
    assert checks[0].status in (doctor.OK, doctor.WARN)
    assert list(s.tmp_dir.iterdir()) == []


def test_ffmpeg_missing_is_failure(tmp_path):
    s = _settings(tmp_path, FFMPEG_PATH="no-existe-ffmpeg-xyz", FFPROBE_PATH="no-existe-ffprobe-xyz")
    checks = doctor.check_ffmpeg(s)
    assert all(c.status == doctor.FAIL for c in checks)
    assert all(c.hint for c in checks)


@respx.mock
def test_comfyui_ok_reports_version_and_vram():
    respx.get("http://comfy.test:8188/system_stats").mock(
        return_value=httpx.Response(
            200,
            json={
                "system": {"comfyui_version": "0.9.9"},
                "devices": [{"name": "cuda:0 NVIDIA L4", "vram_total": 24 * 1024**3, "vram_free": 20 * 1024**3}],
            },
        )
    )
    checks = doctor.check_comfyui("http://comfy.test:8188", timeout=2)
    assert checks[0].status == doctor.OK
    assert "0.9.9" in checks[0].detail
    assert any("VRAM" in c.detail for c in checks)


@respx.mock
def test_comfyui_unreachable_is_warning_not_failure():
    respx.get("http://comfy.test:8188/system_stats").mock(side_effect=httpx.ConnectError("sin conexión"))
    checks = doctor.check_comfyui("http://comfy.test:8188", timeout=1)
    assert checks[0].status == doctor.WARN


@respx.mock
def test_comfyui_url_with_token_is_not_leaked():
    respx.get(url__startswith="http://comfy.test:8188/").mock(side_effect=httpx.ConnectError("x"))
    checks = doctor.check_comfyui("http://admin:clave@comfy.test:8188", timeout=1)
    assert "clave" not in checks[0].detail


def test_main_json_output_and_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FRUTINOVELAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FFMPEG_PATH", "no-existe-ffmpeg-xyz")
    monkeypatch.setenv("FRUTINOVELAS_API_TOKEN", "token-super-secreto")
    code = doctor.main(["--json", "--skip-comfy"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 1  # FFmpeg ausente es bloqueante
    assert payload["summary"]["falla"] >= 1
    assert "token-super-secreto" not in out
