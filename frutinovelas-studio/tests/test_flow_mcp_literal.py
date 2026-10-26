from uuid import uuid4

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from frutinovelas.mcp_flow import register_flow_tools


@pytest.fixture
def tools():
    catalog, calls = {}, []

    class Server:
        def tool(self, **kwargs):
            def register(function):
                catalog[function.__name__] = function
                return function
            return register

    register_flow_tools(Server(), None, None, request=lambda *args: calls.append(args) or [])
    return catalog, calls


@pytest.mark.parametrize("name", ["flow_submit_image", "flow_submit_video", "flow_generate_scene"])
@pytest.mark.parametrize("prompt", [None, "", " \n\t", "a" * 24001])
def test_missing_or_invalid_text_never_sends(tools, name, prompt):
    catalog, calls = tools
    with pytest.raises(ToolError, match="prompt explícito"):
        catalog[name](uuid4(), uuid4(), uuid4(), 1, uuid4(), prompt=prompt)
    assert calls == []


@pytest.mark.parametrize("name,field", [
    ("flow_submit_image", "prompts"), ("flow_submit_video", "video_prompts"),
])
def test_literal_text_is_preserved(tools, name, field):
    catalog, calls = tools
    scene = uuid4()
    literal = '  ¡Darío dice: «Sí, aquí»!\r\nNo añadir música.\t '
    catalog[name](uuid4(), uuid4(), scene, 1, uuid4(), prompt=literal)
    assert calls[0][2][field] == {str(scene): literal}


def test_image_video_requires_both_prompts(tools):
    catalog, calls = tools
    with pytest.raises(ToolError):
        catalog["flow_generate_scene"](uuid4(), uuid4(), uuid4(), 1, uuid4(),
                                       generation_mode="image_video", prompt="Imagen literal")
    assert not calls


def test_chapter_rejects_missing_scene_before_sending(tools):
    catalog, calls = tools
    first, second = str(uuid4()), str(uuid4())
    with pytest.raises(ToolError):
        catalog["flow_generate_chapter"](uuid4(), uuid4(), {first: 1, second: 1}, uuid4(),
                                         prompts={first: "Texto literal"})
    assert not calls


def test_image_video_keeps_both_texts(tools):
    catalog, calls = tools
    scene = uuid4()
    catalog["flow_generate_scene"](uuid4(), uuid4(), scene, 1, uuid4(),
                                   generation_mode="image_video", prompt=" Imagen\n", video_prompt=" Vídeo\r\n")
    body = calls[0][2]
    assert body["prompts"] == {str(scene): " Imagen\n"}
    assert body["video_prompts"] == {str(scene): " Vídeo\r\n"}
    assert body["automatic_approval"] is False
