"""Agent tests use a fake UIA surface, real journal, HTTP authentication and media files."""
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import png_bytes
from frutinovelas.flow_agent import AgentRunner, Journal, create_agent_app
from frutinovelas.flow_uia import Action, Mode, Selector
from frutinovelas.mcp_flow import BearerMiddleware
from frutinovelas.mcp_server import create_server
from frutinovelas.services.flow_transport import (
    FlowClient,
    FlowError,
    FlowIntervention,
    FlowRejected,
    local_secret,
)


def payload(journal):
    return {"request_id": str(uuid4()), "expected_agent_id": journal.identity, "kind": "image",
            "prompt": "Fruta bajo la lluvia", "references": [], "aspect_ratio": "9:16", "duration_seconds": None}


class FakeDriver:
    """Test double, deliberately not named Userflex and never used in production."""
    def __init__(self, fail_invoke=False):
        self.invocations = 0
        self.fail_invoke = fail_invoke
        self.profile = SimpleNamespace(timeout_seconds=30)
        self.mode = SimpleNamespace(prepare="prepare", busy="busy", completed="complete", submit="submit", save="save")

    def status(self):
        return {"available": True, "modes": {"image": {}}, "authentication": "verified_by_control"}

    def validate_request(self, _payload):
        return self.mode

    def verify(self):
        return True

    def bind(self):
        pass

    def check_blockers(self):
        pass

    def find(self, selector, optional=False):
        if selector == "submit":
            return self
        if selector == "complete" and self.invocations:
            return self
        return None

    def is_enabled(self):
        return True

    def invoke(self):
        self.invocations += 1
        if self.fail_invoke:
            raise RuntimeError("lost response after click")

    def actions(self, actions, values):
        if actions == "save":
            from pathlib import Path
            Path(values["output_path"]).write_bytes(png_bytes())


def test_journal_idempotence_and_single_global_lane(tmp_path):
    first = Journal(tmp_path)
    p = payload(first)
    assert first.submit(p)["state"] == "queued"
    second = Journal(tmp_path)
    assert first.identity == second.identity
    assert second.submit(p)["id"] == p["request_id"]
    with pytest.raises(FlowError):
        second.submit({**p, "prompt": "Different"})
    with pytest.raises(FlowError):
        second.submit(payload(second))
    assert second.cancel(p["request_id"])["remote_stopped"] is True
    assert first.submit(payload(first))["state"] == "queued"


def test_crash_after_invoke_never_repeats_submission(data_dir, tmp_path):
    j = Journal(tmp_path)
    p = payload(j)
    j.submit(p)
    driver = FakeDriver(fail_invoke=True)
    runner = AgentRunner(j, driver)
    runner.execute(j.claim())
    assert driver.invocations == 1
    assert j.get(p["request_id"])["state"] == "unknown"
    Journal(tmp_path).recover()
    assert j.claim() is None
    assert j.submit(p)["state"] == "unknown"
    assert j.cancel(p["request_id"])["remote_stopped"] is False
    with pytest.raises(FlowError):
        j.submit(payload(j))


@pytest.mark.parametrize("after_submit", [False, True])
def test_human_verification_or_quota_pauses_remaining_scenes(data_dir, tmp_path, after_submit):
    class BlockedDriver(FakeDriver):
        def verify(self):
            if not after_submit:
                self.check_blockers()

        def check_blockers(self):
            raise FlowIntervention("Cuota agotada o verificación humana.")

    j = Journal(tmp_path)
    p = payload(j)
    j.submit(p)
    driver = BlockedDriver()
    AgentRunner(j, driver).execute(j.claim())
    row = j.get(p["request_id"])
    assert row["state"] == "blocked"
    assert bool(row["remote_stopped"]) is not after_submit
    assert driver.invocations == int(after_submit)
    Journal(tmp_path).recover()
    assert j.claim() is None
    with pytest.raises(FlowError):
        j.submit(payload(j))


@pytest.mark.parametrize("state", ["preparing", "submitting", "running", "saving"])
def test_restart_preserves_uncertain_reservation(tmp_path, state):
    j = Journal(tmp_path)
    p = payload(j)
    j.submit(p)
    j.set(p["request_id"], state)
    fresh = Journal(tmp_path)
    fresh.recover()
    assert fresh.get(p["request_id"])["state"] == "unknown"
    assert fresh.claim() is None
    with pytest.raises(FlowError):
        fresh.submit(payload(fresh))


def test_real_agent_http_journal_media_completion_and_corrupt_download(data_dir, tmp_path, monkeypatch):
    j = Journal(tmp_path)
    driver = FakeDriver()
    headers = {"Authorization": "Bearer " + local_secret("agent")}
    with TestClient(create_agent_app(j, driver, start_runner=False)) as c:
        assert c.get("/status").status_code == 401
        assert c.get("/status", headers={**headers, "Origin": "http://localhost"}).status_code == 403
        assert c.get("/status", headers={**headers, "Host": "evil.example"}).status_code == 403
        p = payload(j)
        r = c.post("/jobs", json=p, headers=headers)
        assert r.status_code == 200, r.text
        assert c.post("/jobs", json=p, headers=headers).json()["id"] == p["request_id"]
        runner = AgentRunner(j, driver)
        monkeypatch.setattr(runner.stop, "wait", lambda *_: None)
        runner.execute(j.claim())
        finished = c.get(f"/jobs/{p['request_id']}", headers=headers)
        assert finished.json()["state"] == "completed"
        assert driver.invocations == 1
        assert c.get(f"/jobs/{p['request_id']}/content", headers=headers).content == png_bytes()
        j.result_path(p["request_id"]).write_bytes(b"corrupted")
        assert c.get(f"/jobs/{p['request_id']}/content", headers=headers).status_code == 409
        assert "prompt" not in c.get(f"/jobs/{p['request_id']}", headers=headers).json()


def test_agent_rejects_identity_and_arbitrary_actions(data_dir, tmp_path):
    j = Journal(tmp_path)
    headers = {"Authorization": "Bearer " + local_secret("agent")}
    with TestClient(create_agent_app(j, FakeDriver(), start_runner=False)) as c:
        p = payload(j)
        assert c.post("/jobs", json={**p, "expected_agent_id": str(uuid4())}, headers=headers).status_code == 409
        assert c.post("/jobs", json={**p, "shell": "anything"}, headers=headers).status_code == 422
        assert c.post("/jobs", json={**p, "url": "http://external"}, headers=headers).status_code == 422
        assert c.post("/click", json={"x": 1, "y": 1}, headers=headers).status_code == 404


def test_agent_reports_missing_profile_as_unknown_window(data_dir, tmp_path):
    headers = {"Authorization": "Bearer " + local_secret("agent")}
    with TestClient(create_agent_app(Journal(tmp_path), start_runner=False)) as c:
        result = c.get("/status", headers=headers)
        assert result.status_code == 200
        assert result.json()["profile_configured"] is False
        assert result.json()["window_open"] is None
        assert result.json()["available"] is False


def test_transport_preserves_uncertainty_for_journal_conflicts(data_dir):
    client = FlowClient()
    client.close()
    client.client = httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(
        lambda request: httpx.Response(409, json={"detail": "Existing uncertain work"})))
    try:
        with pytest.raises(FlowError) as raised:
            client.request("POST", "jobs", {})
        assert not isinstance(raised.value, FlowRejected)
    finally:
        client.close()


def test_unverified_selector_profiles_are_rejected():
    with pytest.raises(ValueError):
        Selector(control_type="Button")
    selector = Selector(control_type="Button", title="Observed button")
    with pytest.raises(ValueError):
        Mode(aspect_ratios=["9:16"], prepare=[], submit=selector, busy=selector, completed=selector,
             save=[Action(operation="invoke", selector=selector)])


@pytest.mark.asyncio
async def test_flow_mcp_catalog_is_opt_in_and_has_no_desktop_escape_hatch():
    public = await create_server().list_tools()
    private = await create_server(include_flow=True).list_tools()
    assert not any(t.name.startswith("flow_") for t in public)
    names = {t.name for t in private}
    assert {"flow_generate_scene", "flow_generate_chapter", "flow_import_result", "flow_cancel_job"} <= names
    for tool in private:
        if tool.name.startswith("flow_"):
            schema = json.dumps(tool.input_schema)
            assert '"executable"' not in schema and '"selector"' not in schema and '"shell"' not in schema


def test_http_mcp_rejects_unauthenticated_tool_discovery():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    app = Starlette(routes=[Route("/mcp", lambda _: JSONResponse({"tools": ["flow_get_status"]}))])
    with TestClient(BearerMiddleware(app, "private-token")) as c:
        assert c.get("/mcp").status_code == 401
        assert c.get("/mcp", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/mcp", headers={"Authorization": "Bearer private-token"}).status_code == 200
