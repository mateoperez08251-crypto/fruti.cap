"""Comprobaciones sin red para el túnel MCP público optativo."""
from pathlib import Path

from scripts.public_mcp_tunnel import commands, public_mcp_url


def test_extracts_complete_https_mcp_url_from_cloudflared_log():
    assert public_mcp_url("2026 INF https://quiet-cloud.trycloudflare.com listo") == (
        "https://quiet-cloud.trycloudflare.com/mcp"
    )
    assert public_mcp_url("http://127.0.0.1:8766/mcp") is None
    assert public_mcp_url("https://example.com/mcp") is None


def test_origin_remains_loopback_and_host_header_is_rewritten():
    mcp, cloud = commands(Path("/tmp/fruti studio"), 8767, 8765, "cloudflared")
    assert mcp[mcp.index("--host") + 1] == "127.0.0.1"
    assert mcp[mcp.index("--port") + 1] == "8767"
    assert mcp[mcp.index("--api-port") + 1] == "8765"
    assert cloud == [
        "cloudflared", "tunnel", "--url", "http://127.0.0.1:8767",
        "--http-host-header", "127.0.0.1:8767",
    ]
