import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from scripts import flow_browser_bot as bot
from tests.test_flow_browser_bot import ClientAPI, connect_browser, dispatch, factory, narrated

from frutinovelas.services import flow_browser_qwen as qwen
from frutinovelas.services.flow_transport import FlowError


def picture(color, size=(90, 160), fmt="PNG"):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=fmt)
    return output.getvalue()


def test_identity_rejects_resized_reencoded_reference_and_wrong_download():
    reference = picture("red")
    copied = picture("red", (180, 320), "JPEG")
    with pytest.raises(FlowError, match="referencia"):
        qwen.verify_result(io.BytesIO(copied), io.BytesIO(copied), [io.BytesIO(reference)])
    with pytest.raises(FlowError, match="no coincide"):
        qwen.verify_result(io.BytesIO(picture("blue")), io.BytesIO(reference), [])
    qwen.verify_result(io.BytesIO(picture("blue")), io.BytesIO(picture("blue", (45, 80))), [io.BytesIO(reference)])


@pytest.mark.parametrize("name,args", [("PowerShell", {}), ("click", {"target": True}),
                                      ("fill_prompt", {"target": 1, "text": "changed"}), ("scroll", {"pixels": 1001})])
def test_model_cannot_add_scripts_change_prompt_or_escape_schema(monkeypatch, name, args):
    monkeypatch.setattr(qwen, "load_connection", lambda: SimpleNamespace(base_url="https://example.test", api_key="private", model="test"))
    class Model:
        def __init__(self, *a, **kw): pass
        def close(self): pass
        def _request(self, *a):
            return {"choices": [{"message": {"tool_calls": [{"function": {"name": name, "arguments": json.dumps(args)}}]}}]}
    monkeypatch.setattr(qwen, "VisionClient", Model)
    with pytest.raises(FlowError, match="válida"):
        qwen.decide(SimpleNamespace(snapshot={}), "page", base64.b64encode(picture("white")).decode(), [])


class AgentAPI(ClientAPI):
    def qwen(self, identifier, observation, screenshot, history):
        return self._check(self.client.post(f"/api/v1/flow/browser/jobs/{identifier}/qwen", headers=self.headers,
            json={"observation": observation, "screenshot": screenshot, "history": history}))

    def upload_qwen(self, identifier, path, preview):
        return self._check(self.client.post(f"/api/v1/flow/browser/jobs/{identifier}/result", headers=self.headers,
            files={"file": ("result.png", Path(path).read_bytes(), "image/png"),
                   "preview": ("preview.png", Path(preview).read_bytes(), "image/png")}))


class NativePage:
    def __init__(self, downloaded="blue"):
        self.page = self
        self.url = "https://flow.google.com/project/owned"
        self.sent = 0
        self.downloaded = downloaded
        self.text = ""
    def goto(self, *a, **kw): pass
    def wait_for_timeout(self, *a): pass
    def get_by_role(self, *a, **kw): return SimpleNamespace(count=lambda: 0)
    def screenshot(self, **kw): return picture("white")
    def evaluate(self, code):
        return [{"id": n, "tag": "IMG" if n in (4, 5) else "BUTTON", "text": "Generate" if n == 3 else "Download" if n == 6 else "control",
                 "type": "file" if n == 2 else None,
                 "src": "reference" if n == 4 else "generated", "width": 90, "height": 160} for n in range(7)]
    def expect_download(self, **kw):
        page = self
        class Pending:
            value = SimpleNamespace(save_as=lambda path: Path(path).write_bytes(picture(page.downloaded)))
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return Pending()
    def locator(self, selector):
        page = self
        class Target:
            def count(self): return 0 if 'password' in selector else 1
            def evaluate_all(self, *a): return ["reference"]
            def fill(self, text): page.text = text
            def press(self, *a): pass
            def element_handle(self): return self
            def evaluate(self, *a): return page.text
            def set_input_files(self, paths): page.attached = paths
            def click(self):
                if selector == '[data-fruti-qwen="3"]':
                    page.sent += 1
            def screenshot(self, path, **kw): Path(path).write_bytes(picture("blue"))
        return Target()


@pytest.mark.parametrize("selected,downloaded,expected", [(5, "blue", "completed"),
    (4, "blue", "uncertain"), (5, "red", "uncertain")])
def test_agent_controls_browser_and_imports_only_selected_new_image(client, tmp_path, monkeypatch, selected, downloaded, expected):
    reference = client.post("/api/v1/assets", files={"file": ("ref.png", picture("red"), "image/png")}).json()
    video = narrated(client, references=[{"asset_id": reference["id"], "role": "identity"}])
    connect_browser(client)
    identifier = dispatch(client, video)["jobs"][0]["id"]
    decisions = iter([( "fill_prompt", 1), ("upload_references", 2), ("generate", 3), ("select_result", selected), ("download", 6)])
    def decide(*a):
        action, target = next(decisions)
        return {"action": action, "arguments": {"target": target}}
    monkeypatch.setattr(qwen, "decide", decide)
    page = NativePage(downloaded)
    journal = bot.Journal(tmp_path / "journal")
    result, _ = bot.run_once(AgentAPI(client), journal, factory(page), tmp_path / "files", qwen=True)
    assert result == expected
    assert page.sent == 1
    assert page.text == " Fruta «ñ» bajo el sol.\r\n"
    job = client.get(f"/api/v1/flow/jobs/{identifier}").json()
    assert job["state"] == ("completed" if expected == "completed" else "unknown")
    if expected != "completed":
        assert not job["result_asset_id"]
        result, _ = bot.run_once(AgentAPI(client), journal, factory(page), tmp_path / "files", qwen=True)
        assert result == "uncertain" and page.sent == 1


def test_restart_after_submit_recovers_without_generating_again(client, tmp_path, monkeypatch):
    connect_browser(client)
    identifier = dispatch(client, narrated(client))["jobs"][0]["id"]
    decisions = iter([("fill_prompt", 1), ("generate", 3), ("select_result", 5), ("download", 6)])
    def decide(*a):
        action, target = next(decisions)
        return {"action": action, "arguments": {"target": target}}
    monkeypatch.setattr(qwen, "decide", decide)
    api = AgentAPI(client)
    query = api.qwen
    calls = 0
    class Crash(BaseException):
        pass
    def interrupted(*args):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise Crash()
        return query(*args)
    api.qwen = interrupted
    page = NativePage()
    journal = bot.Journal(tmp_path / "journal")
    with pytest.raises(Crash):
        bot.run_once(api, journal, factory(page), tmp_path / "files", qwen=True)
    assert journal.load(identifier)["state"] == "submitted"
    api.qwen = query
    result, _ = bot.run_once(api, journal, factory(page), tmp_path / "files", qwen=True)
    assert result == "completed" and page.sent == 1


def test_images_only_claim_does_not_reserve_queued_video(client):
    from frutinovelas.db import session_factory
    from frutinovelas.models import FlowJob
    connect_browser(client)
    identifier = dispatch(client, narrated(client))["jobs"][0]["id"]
    with session_factory()() as session:
        session.get(FlowJob, identifier).kind = "video"
        session.commit()
    api = AgentAPI(client)
    result = client.post('/api/v1/flow/browser/claim', headers=api.headers, json={"images_only": True})
    assert result.json()["action"] == "idle"
    assert client.get(f'/api/v1/flow/jobs/{identifier}').json()["state"] == "queued"


def test_qwen_route_requires_bot_credential(client):
    from uuid import uuid4
    response = client.post(f"/api/v1/flow/browser/jobs/{uuid4()}/qwen", json={
        "observation": "page", "screenshot": "abc", "history": []})
    assert response.status_code == 401
