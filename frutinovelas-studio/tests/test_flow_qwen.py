import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.test_flow import generate, initial, job

from conftest import png_bytes
from frutinovelas.db import session_factory
from frutinovelas.flow_worker import FlowWorker
from frutinovelas.models import FlowJob
from frutinovelas.services import flow_qwen as qwen
from frutinovelas.services.flow_transport import FlowError, local_secret


@pytest.fixture
def pending(client, monkeypatch):
    monkeypatch.setattr(qwen, "status", lambda: {"configured": True, "base_url": "https://qwen.example/v1", "model": "test", "detail": "ready"})
    monkeypatch.setattr(qwen, "load_connection", lambda: SimpleNamespace(base_url="https://qwen.example/v1", model="test", api_key="test-key"))
    payload, _ = initial(client)
    identifier = generate(client, payload)[0]["id"]
    FlowWorker().tick()
    assert job(client, identifier)["state"] == "awaiting_import"
    return identifier


def start(client, identifier, **changes):
    return client.post(f"/api/v1/flow/jobs/{identifier}/execute-qwen", json={
        "request_id": str(uuid4()), "authorized_desktop": True, "confirmed_not_started": True, **changes})


def test_enqueue_preserves_prompt_deduplicates_and_requires_local_consent(client, pending):
    original = job(client, pending)["snapshot"]
    assert start(client, pending, authorized_desktop=False).status_code == 409
    assert start(client, pending, confirmed_not_started=False).status_code == 409
    request = str(uuid4())
    first = start(client, pending, request_id=request)
    assert first.status_code == 202, first.text
    assert start(client, pending, request_id=request).status_code == 202
    assert start(client, pending).status_code == 409
    assert job(client, pending)["snapshot"] == original
    assert job(client, pending)["result_metadata"]["executor"] == "qwen"
    # The original manual/UIA worker must not turn it back into awaiting_import.
    FlowWorker().tick()
    assert job(client, pending)["state"] == "queued"


def test_successful_executor_downloads_validates_and_imports_without_manual_step(client, pending):
    assert start(client, pending).status_code == 202
    calls = []
    async def execute(task, report, cancelled, touched):
        assert not cancelled()
        assert task["prompt"] == job(client, pending)["snapshot"]["prompt"]
        calls.append(task)
        touched()
        report(3, "Descargando")
        Path(task["output_path"]).write_bytes(png_bytes(size=(63, 112)))
    worker = qwen.QwenFlowWorker(execute=execute)
    worker.tick()
    result = job(client, pending)
    assert result["state"] == "completed", result
    assert result["result_asset_id"] and result["result_sha256"]
    assert result["result_metadata"]["qwen_step"] == 3
    worker.tick()
    assert len(calls) == 1


def test_failure_after_input_is_uncertain_and_is_not_replayed(client, pending):
    start(client, pending)
    calls = []
    async def execute(task, report, cancelled, touched):
        calls.append(task)
        touched()
        raise FlowError("Se perdió la respuesta después del clic.")
    worker = qwen.QwenFlowWorker(execute=execute)
    worker.tick()
    result = job(client, pending)
    assert result["state"] == "unknown" and not result["remote_stopped"]
    worker.tick()
    assert len(calls) == 1


def test_preflight_failure_is_definitive_without_a_desktop_action(client, pending):
    start(client, pending)
    async def execute(task, report, cancelled, touched):
        raise FlowError("Windows-MCP no respondió antes de tocar la ventana.")
    qwen.QwenFlowWorker(execute=execute).tick()
    result = job(client, pending)
    assert result["state"] == "failed" and result["remote_stopped"]


def test_recovery_does_not_repeat_a_generation(client, pending):
    start(client, pending)
    with session_factory()() as session:
        row = session.get(FlowJob, pending)
        row.state = "running"
        session.commit()
    qwen.QwenFlowWorker().recover()
    assert job(client, pending)["state"] == "unknown"


def test_mcp_cannot_start_desktop_execution(client, pending, monkeypatch):
    monkeypatch.setenv("FRUTINOVELAS_MCP_ACCESS_MODE", "read_write")
    from frutinovelas.config import reset_settings_cache
    reset_settings_cache()
    response = client.post(f"/api/v1/flow/jobs/{pending}/execute-qwen", headers={"X-Fruti-Flow-Key": local_secret("mcp")},
        json={"request_id": str(uuid4()), "authorized_desktop": True, "confirmed_not_started": True})
    assert response.status_code == 403


def test_changed_qwen_destination_does_not_receive_the_desktop(client, pending, monkeypatch):
    start(client, pending)
    monkeypatch.setattr(qwen, "load_connection", lambda: SimpleNamespace(base_url="https://other.example", model="test"))
    calls = []
    async def execute(*args):
        calls.append(args)
    qwen.QwenFlowWorker(execute=execute).tick()
    assert not calls
    assert job(client, pending)["state"] == "failed"


@pytest.mark.parametrize("step,expected", [(1, True), (2, False)])
def test_only_proven_first_focus_failure_can_be_reclassified(client, pending, step, expected):
    start(client, pending)
    with session_factory()() as session:
        row = session.get(FlowJob, pending)
        row.state = "unknown"
        row.result_metadata = {**row.result_metadata, "qwen_step": step,
            "qwen_message": "Qwen ejecuta App; preparando la toma."}
        session.commit()
        assert qwen.classify_legacy_focus_failure(session, row) is expected
    result = job(client, pending)
    assert result["state"] == ("failed" if expected else "unknown")
    if expected:
        assert result["remote_stopped"]


def test_nested_failures_keep_safe_cause_without_leaking_unknown_exception_details():
    group = ExceptionGroup("transport", [FlowError("El control se pausó."), RuntimeError("private-key")])
    assert qwen.failure_message(group) == "El control se pausó."
    assert "private-key" not in qwen.failure_message(RuntimeError("private-key"))


def test_prompt_cannot_be_rewritten_and_generate_cannot_be_repeated():
    task = {"prompt": "  Imagen literal.\nCon tildes: acción.", "output_path": "C:/output.png", "reference_paths": [], "aspect_ratio": "9:16"}
    with pytest.raises(FlowError):
        qwen.guarded_arguments("Type", {"text": "Imagen mejorada"}, task, False)
    assert qwen.guarded_arguments("Type", {"text": task["prompt"], "press_enter": True}, task, False) == {
        "text": task["prompt"], "press_enter": False, "clear": True}
    with pytest.raises(FlowError):
        qwen.guarded_arguments("FlowSubmit", {"label": 12}, task, True)
    with pytest.raises(FlowError):
        qwen.guarded_arguments("PowerShell", {"command": "arbitrary"}, task, False)
    with pytest.raises(FlowError):
        qwen.guarded_arguments("Shortcut", {"shortcut": "win+r"}, task, False)


@pytest.mark.asyncio
@pytest.mark.parametrize("repeat_submit", [False, True])
async def test_model_mcp_boundary_uses_fresh_observations_and_one_submit(tmp_path, monkeypatch, repeat_submit):
    import mcp
    import mcp.client.stdio

    output = tmp_path / "result.png"
    task = {"prompt": " Literal con acción.\n", "output_path": str(output), "reference_paths": [],
            "aspect_ratio": "9:16", "qwen_base_url": "https://qwen.example/v1", "qwen_model": "test"}
    monkeypatch.setattr(qwen, "load_connection", lambda: SimpleNamespace(base_url=task["qwen_base_url"], model="test", api_key="private"))
    calls, queries = [], []
    actions = iter([("Type", {"text": task["prompt"]}), ("FlowSubmit", {"label": 13}),
                    ("FlowSubmit", {"label": 13}) if repeat_submit else ("FlowFinish", {})])
    class Model:
        def __init__(self, *args, **kwargs):
            pass
        def close(self):
            pass
        def _request(self, method, path, body):
            assert body["stream"] is False and body["parallel_tool_calls"] is False
            assert any(c.get("type") == "image_url" for c in body["messages"][-1]["content"])
            queries.append(body)
            name, arguments = next(actions)
            return {"choices": [{"message": {"tool_calls": [{"function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}
    monkeypatch.setattr(qwen, "VisionClient", Model)
    class Desktop:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def initialize(self):
            pass
        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name=n, description="Control", input_schema={"type": "object"})
                                          for n in ("App", "Snapshot", "Click", "Type")])
        async def call_tool(self, name, args):
            calls.append((name, args))
            if name == "Click":
                output.write_bytes(png_bytes())
            return SimpleNamespace(is_error=False, content=[SimpleNamespace(type="text", text="UserFLEX observado"),
                SimpleNamespace(type="image", mime_type="image/png", data=base64.b64encode(png_bytes()).decode())])
    @asynccontextmanager
    async def transport(*args, **kwargs):
        yield None, None
    monkeypatch.setattr(mcp, "ClientSession", Desktop)
    monkeypatch.setattr(mcp.client.stdio, "stdio_client", transport)
    if repeat_submit:
        with pytest.raises(FlowError, match="Ya se intentó Generar"):
            await qwen.desktop_execute(task, lambda *a, **kw: None, lambda: False, lambda: None)
    else:
        await qwen.desktop_execute(task, lambda *a, **kw: None, lambda: False, lambda: None)
    assert [name for name, _ in calls] == ["Snapshot", "Type", "Snapshot", "Click", "Snapshot"]
    assert calls[1][1]["text"] == task["prompt"]
    assert len(queries) == 3
