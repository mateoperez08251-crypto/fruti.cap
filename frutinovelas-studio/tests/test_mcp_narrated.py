from uuid import uuid4

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from frutinovelas.mcp_flow import register_narrated_tools


@pytest.fixture
def tools():
    catalog, calls = {}, []

    class Server:
        def tool(self, **kwargs):
            def register(function):
                catalog[function.__name__] = function
                return function
            return register

    def request(*args):
        calls.append(args)
        return {"video": {"id": "v", "revision": 3, "state": "draft", "error": "", "shots": [{
            "start_seconds": 0, "end_seconds": 8, "media_mode": "static", "image_prompt": "SECRETO literal",
            "image_asset_id": "a", "flow_image_job_id": "j"}]},
            "jobs": [{"id": "j", "kind": "image", "state": "queued", "shot": 0, "error": "",
                      "snapshot": {"prompt": "SECRETO literal"}}]}

    register_narrated_tools(Server(), None, None, request=request)
    return catalog, calls


def test_send_uses_request_id_and_summary_hides_prompts(tools):
    catalog, calls = tools
    request_id = uuid4()
    video = uuid4()
    result = catalog["narrated_send_to_flow"](video, 2, request_id, clip_seconds=8)
    method, path, body = calls[0]
    assert (method, path) == ("POST", f"{video}/flow")
    assert body == {"expected_revision": 2, "request_id": str(request_id), "clip_seconds": 8, "automatic_approval": False}
    assert "SECRETO" not in str(result)
    assert result["jobs"] == [{"id": "j", "shot": 0, "kind": "image", "state": "queued", "error": None}]
    assert result["shots"][0]["image"] is True


def test_select_version_and_render_respect_read_only(tools, monkeypatch):
    from frutinovelas.config import get_settings
    catalog, calls = tools
    video = uuid4()
    catalog["narrated_select_version"](video, 3, 0, None)
    assert calls[-1][2] == {"expected_revision": 3, "shot_index": 0, "job_id": None}
    monkeypatch.setattr(get_settings(), "mcp_access_mode", "read_only")
    with pytest.raises(ToolError):
        catalog["narrated_render"](video, 3)
    assert calls[-1][1] != f"{video}/render"
