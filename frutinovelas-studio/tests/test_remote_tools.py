"""Regresiones del kit remoto, sin GPU, pesos ni servicios externos."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_colab_connection as checker  # noqa: E402
import fruti_remote as remote  # noqa: E402

GRAPH = {"1": {"class_type": "SaveImage", "inputs": {}}}
OBJECT_INFO = {"SaveImage": {"input": {"required": {}}}}


def test_export_cache_checks_hash_nodes_and_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, "API_DIR", tmp_path)
    path = tmp_path / "test.api.json"
    body = json.dumps(GRAPH).encode()
    path.write_bytes(body)
    key = {"kit": "test"}
    report = {"clave": key, "flujos": {path.name: {"sha256": hashlib.sha256(body).hexdigest()}}}
    assert remote.cache_exportacion_valida(report, key, {path.name}, OBJECT_INFO)
    assert not remote.cache_exportacion_valida(report, key, {path.name, "missing.api.json"}, OBJECT_INFO)
    assert not remote.cache_exportacion_valida(report, key, {path.name}, {})
    path.write_bytes(body + b" ")
    assert not remote.cache_exportacion_valida(report, key, {path.name}, OBJECT_INFO)
    assert not remote.cache_exportacion_valida({"clave": key, "flujos": {}}, key, {path.name}, OBJECT_INFO)


def test_identity_drops_test_results_when_profile_or_workflow_changes(tmp_path, monkeypatch):
    path = tmp_path / "identity.json"
    monkeypatch.setattr(remote, "IDENTITY_FILE", path)
    monkeypatch.setattr(remote, "cfg", lambda: dict(remote.DEFAULT_CFG))
    report = {"flujos": {"h3.api.json": {"sha256": "a" * 64}}}
    current = remote.escribir_identidad({"system": {}}, report)
    current["pruebas"] = {"h3_i2va": {"ok": True}}
    current["estado_compatibilidad"] = "prueba_real_ok"
    remote.save_json(path, current)
    assert remote.escribir_identidad({"system": {}}, report)["pruebas"] == current["pruebas"]
    report["flujos"]["h3.api.json"]["sha256"] = "b" * 64
    new = remote.escribir_identidad({"system": {}}, report)
    assert new["pruebas"] == {}
    assert new["estado_compatibilidad"] == "pendiente_prueba_real"


def stub_connection(monkeypatch, name, graph=GRAPH, expected=None):
    body = json.dumps(graph).encode()
    digest = hashlib.sha256(body).hexdigest() if expected is None else expected
    ident = {"workflows": {name: digest}}

    def request(url, token=None, timeout=30):
        if url.endswith("/healthz"):
            return 200, b"{}"
        if url.endswith("/system_stats"):
            return (200, b'{"system": {}, "devices": []}') if token else (401, b"{}")
        if url.endswith("/identity"):
            return 200, json.dumps(ident).encode()
        if url.endswith("/workflows"):
            return 200, json.dumps({"workflows": [name]}).encode()
        return 200, body

    monkeypatch.setenv("FRUTI_COMFY_TOKEN", "test-token-at-least-16")
    monkeypatch.setattr(checker, "request", request)
    return body


def test_connection_checker_downloads_only_verified_api(tmp_path, monkeypatch):
    body = stub_connection(monkeypatch, "sample.api.json")
    assert checker.main(["--url", "https://remote.test", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "sample.api.json").read_bytes() == body


@pytest.mark.parametrize(
    "name,graph,digest",
    [
        ("../outside.api.json", GRAPH, None),
        ("sample.api.json", GRAPH, ""),
        ("sample.api.json", GRAPH, "0" * 64),
        ("sample.api.json", {"not": "a graph"}, None),
    ],
)
def test_connection_checker_rejects_untrusted_downloads(tmp_path, monkeypatch, name, graph, digest):
    stub_connection(monkeypatch, name, graph, digest)
    assert checker.main(["--url", "https://remote.test", "--out", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []


def test_connection_checker_rejects_credentials_in_url(monkeypatch):
    monkeypatch.setattr(
        checker.getpass, "getpass", lambda *args: pytest.fail("must validate before asking for token")
    )
    assert checker.main(["--url", "https://user:secret@remote.test"]) == 2


def test_failed_render_invalidates_previous_success(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, "IDENTITY_FILE", tmp_path / "identity.json")
    remote.registrar_prueba("h3_i2va", {"ok": True})
    assert remote.load_json(remote.IDENTITY_FILE)["estado_compatibilidad"] == "prueba_real_ok"
    remote.registrar_prueba("h3_i2va", {"ok": False})
    assert remote.load_json(remote.IDENTITY_FILE)["estado_compatibilidad"] == "prueba_real_fallida"


def test_gateway_restarts_after_token_rotation(monkeypatch):
    from types import SimpleNamespace

    checks = iter([True, False, True])
    stopped = []
    started = []
    monkeypatch.setattr(remote, "gw_vivo", lambda: next(checks))
    monkeypatch.setattr(remote, "estado", lambda **changes: {"gateway_listen": "127.0.0.1"})
    monkeypatch.setattr(remote, "detener", lambda name: stopped.append(name))
    monkeypatch.setattr(remote.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        remote,
        "lanzar",
        lambda *args, **kwargs: started.append(args[0]) or SimpleNamespace(poll=lambda: None),
    )
    monkeypatch.setattr(
        remote,
        "http_status",
        lambda url, headers=None: 401 if url.endswith("/identity") or headers is None else 200,
    )
    remote.arrancar_gateway("new-token-at-least-16", "ninguno")
    assert stopped == ["gateway"]
    assert started == ["gateway"]
