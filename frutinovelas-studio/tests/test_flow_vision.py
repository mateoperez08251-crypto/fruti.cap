import json

import httpx
import pytest
from tests.conftest import png_bytes

from frutinovelas.flow_vision import (
    PromptLocation,
    VisionClient,
    VisionConnection,
    connect_interactively,
    load_connection,
    save_connection,
)
from frutinovelas.services.flow_transport import FlowError


def client_for(handler):
    return VisionClient("https://qwen.example/v1", "private-test-key", transport=httpx.MockTransport(handler))


def test_models_uses_given_base_path_and_auth():
    def handler(request):
        assert str(request.url) == "https://qwen.example/v1/models"
        assert request.headers["authorization"] == "Bearer private-test-key"
        return httpx.Response(200, json={"data": [{"id": "actual-model"}]})
    client = client_for(handler)
    try:
        assert client.models() == ["actual-model"]
    finally:
        client.close()


@pytest.mark.parametrize("status", [400, 401, 403, 422, 302, 500])
def test_failures_never_follow_redirect_retry_or_leak_body(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private-test-key provider secret", headers={"location": "https://other.example"})
    client = client_for(handler)
    try:
        with pytest.raises(FlowError) as error:
            client.models()
        assert "private-test-key" not in str(error.value)
        assert "provider secret" not in str(error.value)
        assert str(status) in str(error.value)
        assert "consulta visual" not in str(error.value)
        if status in (400, 422):
            assert "consulta del catálogo" in str(error.value)
            assert "No se envió ningún modelo ni imagen" in str(error.value)
            assert "temporal" not in str(error.value)
        assert len(calls) == 1
    finally:
        client.close()


def test_locator_only_sends_image_and_fixed_task_and_accepts_bounded_result():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "actual-model"
        assert "tools" not in body
        assert body["stream"] is False
        assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
        answer = {"state": "found", "box": [0.1, 0.5, 0.9, 0.8], "confidence": 0.95, "blocker": "none"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})
    client = client_for(handler)
    try:
        assert client.locate_prompt(png_bytes(), "actual-model").box == [0.1, 0.5, 0.9, 0.8]
    finally:
        client.close()


@pytest.mark.parametrize("change", [
    {"box": [-0.1, 0.2, 0.8, 0.5]}, {"box": [0.2, 0.2, 1.1, 0.5]},
    {"box": [0.8, 0.2, 0.2, 0.5]}, {"box": [0.2, 0.2, 0.2, 0.5]},
    {"box": [0.2, 0.3]}, {"box": None}, {"confidence": 0.89},
    {"confidence": float("nan")}, {"action": "click"}, {"prompt": "invented text"},
    {"state": "blocked"}, {"blocker": "captcha"}, {"box": [True, 0.2, 0.8, 0.5]},
])
def test_unusable_or_executable_results_are_rejected(change):
    result = {"state": "found", "box": [0.1, 0.2, 0.8, 0.5], "confidence": 0.95, "blocker": "none"}
    result.update(change)
    with pytest.raises(ValueError):
        PromptLocation.model_validate(result)


@pytest.mark.parametrize("answer", ["```json\n{}\n```", "not JSON", '{"state":"found"}', None])
def test_invalid_model_reply_does_not_become_an_action(answer):
    client = client_for(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": answer}}]}))
    try:
        with pytest.raises(FlowError, match="localización visual válida"):
            client.locate_prompt(png_bytes(), "actual-model")
    finally:
        client.close()


def test_blockers_and_absent_inputs_have_no_coordinates():
    for state, blocker in [("blocked", "captcha"), ("not_found", "none")]:
        result = PromptLocation(state=state, box=None, confidence=0.95, blocker=blocker)
        assert result.box is None


def test_invalid_capture_is_rejected_before_network():
    client = client_for(lambda request: pytest.fail("Invalid image must not be sent"))
    try:
        with pytest.raises(FlowError):
            client.locate_prompt(b"invalid", "actual-model")
    finally:
        client.close()


def test_local_connection_is_encrypted_and_round_trips(data_dir):
    connection = VisionConnection(base_url="https://qwen.example/v1/", model="actual-model", api_key="private-test-key")
    save_connection(connection)
    path = data_dir / "flow" / "vision.credential"
    assert b"private-test-key" not in path.read_bytes()
    assert b"qwen.example" not in path.read_bytes()
    assert load_connection() == connection
    assert "private-test-key" not in repr(connection)


def test_failed_connect_does_not_replace_previous_connection(data_dir, monkeypatch):
    existing = VisionConnection(base_url="https://qwen.example/v1", model="actual-model", api_key="old-key")
    save_connection(existing)
    monkeypatch.setenv("FRUTINOVELAS_FLOW_VISION_API_KEY", "wrong-key")
    monkeypatch.setattr(VisionClient, "models", lambda self: (_ for _ in ()).throw(FlowError("Denied")))
    with pytest.raises(FlowError):
        connect_interactively("https://new.example/v1")
    assert load_connection() == existing


def test_connect_uses_published_model_without_assuming_its_identity(data_dir, monkeypatch, capsys):
    monkeypatch.setenv("FRUTINOVELAS_FLOW_VISION_API_KEY", "private-test-key")
    monkeypatch.setattr(VisionClient, "models", lambda self: ["server-model-alias"])
    connect_interactively("https://qwen.example/v1")
    assert load_connection().model == "server-model-alias"
    assert "private-test-key" not in capsys.readouterr().out


def test_unknown_model_cannot_replace_saved_connection(data_dir, monkeypatch):
    monkeypatch.setenv("FRUTINOVELAS_FLOW_VISION_API_KEY", "private-test-key")
    monkeypatch.setattr(VisionClient, "models", lambda self: ["server-model-alias"])
    with pytest.raises(FlowError, match="no está publicado"):
        connect_interactively("https://qwen.example/v1", "assumed-model")
    assert not (data_dir / "flow" / "vision.credential").exists()


def test_connection_command_prompts_for_key_without_echoing_it(data_dir, monkeypatch, capsys):
    from frutinovelas.flow_agent import main

    monkeypatch.delenv("FRUTINOVELAS_FLOW_VISION_API_KEY", raising=False)
    monkeypatch.setattr("builtins.input", lambda message: "https://qwen.example/v1")
    monkeypatch.setattr("getpass.getpass", lambda message: "private-test-key")
    monkeypatch.setattr(VisionClient, "models", lambda self: ["server-model-alias"])
    assert main(["vision-connect"]) == 0
    assert load_connection().api_key == "private-test-key"
    assert "private-test-key" not in capsys.readouterr().out


@pytest.mark.parametrize("key", ["private-test-key\r\n", "x" * 8193])
def test_invalid_key_is_never_sent_or_printed(data_dir, monkeypatch, key):
    monkeypatch.setenv("FRUTINOVELAS_FLOW_VISION_API_KEY", key)
    monkeypatch.setattr(VisionClient, "models", lambda self: pytest.fail("Invalid key must not be used"))
    with pytest.raises(FlowError) as error:
        connect_interactively("https://qwen.example/v1")
    assert key not in str(error.value)
