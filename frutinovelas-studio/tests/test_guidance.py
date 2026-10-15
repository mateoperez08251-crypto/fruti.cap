import json

import pytest

from frutinovelas.guidance import get_guidance, guidance_catalog, read_guide
from frutinovelas.mcp_server import create_server


@pytest.mark.parametrize("task", ["story", "image", "animation", "review"])
@pytest.mark.parametrize("preset", ["general", "frutinovelas"])
def test_task_guidance_keeps_story_separate(task, preset):
    context = get_guidance(task, preset)
    names = {guide["name"] for guide in context["guides"]}
    assert f"skill-{task}" in names
    assert "example-story" not in names
    assert ("preferences" in names) == (preset == "frutinovelas")
    assert all(guide["content"] for guide in context["guides"])
    assert "no entrenan" in context["persistence"]


def test_story_requires_explicit_opt_in():
    context = get_guidance(include_example_story=True)
    story = next(guide for guide in context["guides"] if guide["name"] == "example-story")
    assert "Mano izquierda de Darío" in story["content"]
    with pytest.raises(ValueError):
        get_guidance(preset="general", include_example_story=True)


def test_guides_are_allowlisted_and_links_work_over_mcp():
    for entry in guidance_catalog():
        assert read_guide(entry["name"])
    with pytest.raises(ValueError):
        read_guide("../../pyproject.toml")
    assert "frutinovelas://guides/models" in read_guide("skill-animation")


@pytest.mark.asyncio
async def test_mcp_exposes_guidance_resources_and_portable_prompt():
    server = create_server()
    tool = await server.call_tool("get_directing_guidance", {"task": "image", "preset": "general"})
    assert not tool.is_error
    resources = await server.read_resource("frutinovelas://guides")
    catalog = json.loads(next(iter(resources)).content)
    assert any(entry["name"] == "skill-image" for entry in catalog)
    resource = await server.read_resource("frutinovelas://guides/director-core")
    assert "cualquier escena" in next(iter(resource)).content
    prompt = await server.get_prompt(
        "direct_scene",
        {"request": "A realistic dog crossing a wet street", "task": "animation", "preset": "general"},
    )
    text = prompt.messages[0].content.text
    assert "A realistic dog crossing a wet street" in text
    assert "Identidades y objetos del arco de la heladería" not in text
    assert "Preferencias del preset frutinovelas" not in text
