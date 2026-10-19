"""Offline tests: execute the actual embedded cell, never contact a runtime."""
import ast
import importlib.util
import json
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
NAME = "FRUTINOVELAS_ComfyUI_Imagenes_H3_Colab.ipynb"
COMMIT = "3541246a9c997f4b8c32f9f88f3c985d02021c79"
SECRET = "test-secret-must-never-be-printed"


def queue(active=("active-1",), pending=("pending-1", "pending-2")):
    return {"queue_running": [[0, pid, {"private_prompt": SECRET}] for pid in active],
            "queue_pending": [[i + 1, pid, {"private_prompt": SECRET}] for i, pid in enumerate(pending)]}


class Response:
    def __init__(self, data=None, status=200):
        self.data, self.status_code = data, status

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class FakeHTTP:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert kwargs["headers"]["Authorization"] == "Bearer " + SECRET
        assert kwargs["timeout"] == 20
        assert kwargs["allow_redirects"] is False
        assert url.startswith("http://127.0.0.1:8189/")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def posts(self):
        return [(url.rsplit("/", 1)[-1], kw["json"]) for method, url, kw in self.calls if method == "POST"]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Real network access is forbidden in queue tests")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)


@pytest.fixture
def run():
    nb = json.loads((ROOT / "notebooks" / NAME).read_text(encoding="utf-8"))
    cell = next(c for c in nb["cells"] if c["id"] == "fruti-queue-controls")
    namespace = {}
    exec(compile("".join(cell["source"]), "queue-cell", "exec"), namespace)

    def invoke(fake, action="consultar", ids="", confirm=lambda _: "", context=None):
        context = context if context is not None else {"GW": "http://127.0.0.1:8189/", "AUTH": {"Authorization": "Bearer " + SECRET}}
        return namespace["gestionar_cola"](action, ids, contexto=context, transporte=fake, confirmar=confirm)
    return invoke


def test_consult_only_and_no_secrets(run, capsys):
    fake = FakeHTTP(Response(queue()))
    assert run(fake)["queue_pending"] == ["pending-1", "pending-2"]
    assert not fake.posts
    assert SECRET not in capsys.readouterr().out


@pytest.mark.parametrize("action,ids,expected", [
    ("cancelar seleccionados", "pending-2, pending-2", ["pending-2"]),
    ("cancelar todos los pendientes", "", ["pending-1", "pending-2"]),
])
def test_delete_pending_snapshot_only(run, action, ids, expected):
    fake = FakeHTTP(Response(queue()), Response(queue(pending=("pending-1", "pending-2", "new"))),
                    Response(ValueError("empty POST body")), Response(queue(pending=("new",))))
    run(fake, action, ids, lambda _: "CANCELAR")
    assert fake.posts == [("queue", {"delete": expected})]


@pytest.mark.parametrize("ids", ["", "active-1", "unknown", "pending-1,unknown"])
def test_invalid_selection_never_writes(run, ids):
    fake = FakeHTTP(Response(queue()))
    with pytest.raises(ValueError):
        run(fake, "cancelar seleccionados", ids, lambda _: "CANCELAR")
    assert not fake.posts


def test_pending_started_during_confirmation(run):
    fake = FakeHTTP(Response(queue()), Response(queue(active=("pending-1",), pending=("pending-2",))))
    with pytest.raises(RuntimeError, match="cola cambió"):
        run(fake, "cancelar todos los pendientes", confirm=lambda _: "CANCELAR")
    assert not fake.posts


@pytest.mark.parametrize("action", ["cancelar todos los pendientes", "interrumpir activo"])
def test_decline_confirmation(run, action):
    fake = FakeHTTP(Response(queue()), Response({"comfyui_commit": COMMIT}))
    run(fake, action, confirm=lambda _: "no")
    assert not fake.posts


def test_targeted_interrupt(run):
    fake = FakeHTTP(Response(queue()), Response({"comfyui_commit": COMMIT}), Response(queue()),
                    Response(ValueError("empty POST body")), Response(queue(active=())))
    run(fake, "interrumpir activo", confirm=lambda _: "INTERRUMPIR active-1")
    assert fake.posts == [("interrupt", {"prompt_id": "active-1"})]


@pytest.mark.parametrize("active", [(), ("next-job",)])
def test_active_changed_never_interrupts(run, active):
    fake = FakeHTTP(Response(queue()), Response({"comfyui_commit": COMMIT}), Response(queue(active=active)))
    with pytest.raises(RuntimeError, match="activo cambió"):
        run(fake, "interrumpir activo", confirm=lambda _: "INTERRUMPIR active-1")
    assert not fake.posts


def test_unknown_version_never_uses_global_interrupt(run):
    fake = FakeHTTP(Response(queue()), Response({"comfyui_commit": "other"}))
    with pytest.raises(RuntimeError, match="versión"):
        run(fake, "interrumpir activo", confirm=lambda _: "INTERRUMPIR active-1")
    assert not fake.posts


@pytest.mark.parametrize("action", ["interrumpir activo", "cancelar todos los pendientes"])
def test_empty_queue_no_write(run, action):
    fake = FakeHTTP(Response(queue(active=(), pending=())))
    run(fake, action)
    assert not fake.posts


@pytest.mark.parametrize("response", [
    Response(status=401), Response(status=403), Response(status=302), Response(status=503),
    Response(ValueError(SECRET)), Response({}), Response({"queue_running": [], "queue_pending": [[0]]}),
    requests.Timeout(SECRET), requests.ConnectionError(SECRET),
])
def test_failure_is_sanitized_and_no_write(run, response):
    fake = FakeHTTP(response)
    with pytest.raises(RuntimeError) as exc:
        run(fake)
    assert SECRET not in str(exc.value)
    assert not fake.posts


def test_post_timeout_no_retry(run):
    fake = FakeHTTP(Response(queue()), Response(queue()), requests.Timeout(SECRET))
    with pytest.raises(RuntimeError, match="Resultado incierto"):
        run(fake, "cancelar todos los pendientes", confirm=lambda _: "CANCELAR")
    assert len(fake.posts) == 1


def test_missing_configuration(run):
    fake = FakeHTTP()
    with pytest.raises(ValueError, match="celda 8"):
        run(fake, context={})
    assert not fake.calls


def test_existing_notebooks_and_generator():
    spec = importlib.util.spec_from_file_location("builder", ROOT / "scripts/build_colab_notebook.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    generated_cell = next(c for c in builder.build("colab")["cells"] if c["id"] == "fruti-queue-controls")
    for path in (ROOT / "notebooks" / NAME, ROOT.parent / NAME):
        nb = json.loads(path.read_text(encoding="utf-8"))
        assert nb["nbformat"] == 4
        ids = [c["id"] for c in nb["cells"]]
        assert len(ids) == len(set(ids))
        assert next(c for c in nb["cells"] if c["id"] == "fruti-queue-controls") == generated_cell
        for cell in nb["cells"]:
            if cell["cell_type"] == "code":
                source = "".join(cell["source"])
                if not source.startswith("%%"):
                    ast.parse(source)
