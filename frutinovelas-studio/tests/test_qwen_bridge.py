import json

import pytest

from frutinovelas.flow_vision import VisionConnection
from frutinovelas.routes import qwen_bridge as bridge
from frutinovelas.services.flow_transport import FlowError

PATH = "/api/v1/qwen/v1"
KEY = "private-qwen-test-key"
HEADERS = {"Authorization": "Bearer " + KEY}


@pytest.fixture
def provider(monkeypatch):
    connection = VisionConnection(base_url="https://qwen.example/v1", model="real-model", api_key=KEY)
    monkeypatch.setattr(bridge, "load_connection", lambda: connection)
    calls = []
    result = {"id": "chat-123", "model": "real-model", "object": "chat.completion", "created": 10,
              "choices": [{"index": 0, "message": {"role": "assistant", "content": "Texto literal con tildes: acción.\n"}, "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}}
    class Client:
        def __init__(self, url, key, **kwargs):
            assert url == connection.base_url and key == KEY
        def _request(self, method, path, body):
            calls.append(body)
            assert body["stream"] is False
            assert "stream_options" not in body
            return result
        def close(self):
            pass
    monkeypatch.setattr(bridge, "VisionClient", Client)
    return calls, result


def test_stream_adapter_preserves_text_tools_and_usage(client, provider):
    calls, result = provider
    tool = {"id": "call-1", "type": "function", "function": {"name": "Snapshot", "arguments": '{"x":"á"}'}}
    result["choices"][0]["message"]["tool_calls"] = [tool]
    result["choices"][0]["finish_reason"] = "tool_calls"
    body = {"model": "real-model", "stream": True, "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": "Texto original"}], "tools": [{"type": "function", "function": {"name": "Snapshot"}}]}
    response = client.post(PATH + "/chat/completions", headers=HEADERS, json=body)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [event.removeprefix("data: ") for event in response.text.strip().split("\n\n")]
    assert events[-1] == "[DONE]"
    delta = json.loads(events[0])["choices"][0]["delta"]
    assert delta["content"] == result["choices"][0]["message"]["content"]
    assert delta["tool_calls"] == [{**tool, "index": 0}]
    assert json.loads(events[1])["choices"][0]["finish_reason"] == "tool_calls"
    assert json.loads(events[2])["usage"] == result["usage"]
    assert len(calls) == 1
    assert calls[0]["messages"] == body["messages"]
    assert calls[0]["tools"] == body["tools"]


def test_non_streaming_returns_unmodified_response(client, provider):
    _, result = provider
    response = client.post(PATH + "/chat/completions", headers=HEADERS, json={"model": "real-model", "messages": [{"role": "user", "content": "Hola"}]})
    assert response.json() == result


def test_no_secret_or_upstream_calls_in_model_catalog(client, provider):
    calls, _ = provider
    assert client.get(PATH + "/models").status_code == 401
    response = client.get(PATH + "/models", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "real-model"
    assert KEY not in response.text and not calls


@pytest.mark.parametrize("body", [{}, {"model": "wrong", "messages": [{}]}, {"model": "real-model", "messages": [{}], "stream": "true"}])
def test_invalid_requests_never_reach_provider(client, provider, body):
    calls, _ = provider
    assert client.post(PATH + "/chat/completions", headers=HEADERS, json=body).status_code == 422
    assert not calls


def test_origin_is_restricted_even_with_key(client, provider):
    assert client.get(PATH + "/models", headers={**HEADERS, "Origin": "https://untrusted.example"}).status_code == 403


def test_upstream_failure_is_not_retried(client, provider, monkeypatch):
    calls = []
    def fail(self, *args):
        calls.append(args)
        raise FlowError("El servidor no respondió.")
    monkeypatch.setattr(bridge.VisionClient, "_request", fail)
    response = client.post(PATH + "/chat/completions", headers=HEADERS, json={"model": "real-model", "messages": [{}], "stream": True})
    assert response.status_code == 502 and len(calls) == 1
    assert KEY not in response.text
