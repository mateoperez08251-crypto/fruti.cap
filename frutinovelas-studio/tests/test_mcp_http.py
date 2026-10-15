"""Exercise the documented local HTTP endpoint with a real MCP client."""

import asyncio
import json
import socket
import sys

import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from frutinovelas.mcp_server import main


@pytest.mark.parametrize("args", [
    ["--host", "0.0.0.0"], ["--host", "192.168.1.5"], ["--host", "example.com"],
    ["--port", "0"], ["--port", "65536"], ["--port", "invalid"],
])
def test_cli_rejects_public_bind_and_invalid_ports(args):
    with pytest.raises(SystemExit) as error:
        main(["--transport", "streamable-http", *args])
    assert error.value.code == 2


@pytest.mark.asyncio
async def test_real_http_endpoint_tools_resources_and_dns_rebinding_protection():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "frutinovelas.mcp_server", "--transport", "streamable-http",
        "--port", str(port), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(20), httpx2.AsyncClient(trust_env=False, timeout=5) as client:
            url = f"http://127.0.0.1:{port}/mcp"
            while True:
                assert process.returncode is None, "MCP server exited before initialization"
                try:
                    await client.get(f"http://127.0.0.1:{port}/")
                    break
                except httpx2.ConnectError:
                    await asyncio.sleep(0.05)
            blocked = await client.post(url, headers={"Host": "untrusted.example"}, json={})
            assert blocked.status_code == 421
            async with streamable_http_client(url, http_client=client) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert {tool.name for tool in tools.tools} == {
                        "get_directing_guidance", "prepare_h3_prompt", "prepare_image_prompt", "review_h3_prompt",
                    }
                    result = await session.call_tool("get_directing_guidance", {"task": "image", "preset": "general"})
                    assert not result.is_error
                    context = json.loads(result.content[0].text)
                    assert all(guide["name"] != "example-story" for guide in context["guides"])
                    resource = await session.read_resource("frutinovelas://guides")
                    assert "skill-image" in resource.contents[0].text
                    prompt = await session.get_prompt("direct_scene", {"request": "A dog crossing the street", "preset": "general"})
                    assert "A dog crossing the street" in prompt.messages[0].content.text
    finally:
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()
