"""El modal exporta configuración utilizable y diagnostica MCP sin ejecutar herramientas."""

import asyncio
import os
import shlex
import socket
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest

from frutinovelas.config import Settings, get_settings, reset_settings_cache
from frutinovelas.mcp_server import main
from frutinovelas.services.mcp_connection import (
    connection_info,
    connection_status,
    local_address,
    shell_command,
)


def test_configuration_uses_actual_runtime_without_exporting_any_token(client, monkeypatch, tmp_path):
    directory = tmp_path / "Studio de Ana's ñ con espacios"
    directory.mkdir()
    monkeypatch.chdir(directory)
    settings = get_settings()
    settings.api_token = "private-studio-api-secret"
    settings.mcp_token = "unused-private-mcp-secret"
    settings.mcp_backend_token = "unused-private-backend-secret"
    settings.comfyui_token = "private-gateway-secret"
    settings.api_port = 9005
    settings.mcp_port = 9006
    response = client.get("/api/v1/mcp/connection")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["local_url"] == "http://127.0.0.1:9006/mcp"
    assert data["authentication"] == "bearer"
    assert data["api_token_configured"] is True
    entry = data["claude_desktop_config"]["mcpServers"]["frutinovelas"]
    assert entry["command"] == str(Path(sys.executable).absolute())
    assert entry["args"] == ["-m", "frutinovelas.mcp_server", "--directory", str(directory), "--transport", "stdio"]
    assert entry["env"] == {"FRUTINOVELAS_API_PORT": "9005"}
    assert "secret" not in response.text
    assert "--port" in data["http_command"] and "9006" in data["http_command"]
    assert "--api-port" in data["http_command"] and "9005" in data["http_command"]


def test_api_cli_port_is_exported_before_the_app_and_server_start(data_dir, monkeypatch, tmp_path):
    import uvicorn

    from frutinovelas import api as api_module

    settings = get_settings()
    settings.api_host = "127.0.0.1"
    settings.api_port = 8765
    app = object()
    exported = []
    runs = []

    def create_app():
        assert settings.api_host == "localhost"
        exported.append(connection_info())
        return app

    monkeypatch.setattr(api_module, "create_app", create_app)
    monkeypatch.setattr(api_module, "_port_in_use", lambda *_args: False)
    monkeypatch.setattr(api_module, "frontend_dir", lambda: tmp_path)
    monkeypatch.setattr(uvicorn, "run", lambda application, **options: runs.append((application, options)))

    assert api_module.main(["--host", "localhost", "--port", "9425", "--no-browser"]) == 0
    assert runs == [(app, {"host": "localhost", "port": 9425, "log_level": "info"})]
    assert len(exported) == 1
    entry = exported[0].claude_desktop_config.mcpServers["frutinovelas"]
    assert entry.env["FRUTINOVELAS_API_PORT"] == "9425"
    assert "--api-port" in exported[0].http_command and "9425" in exported[0].http_command


def test_generated_desktop_command_finds_the_installed_module_from_another_directory(data_dir, monkeypatch, tmp_path):
    studio = tmp_path / "Studio con espacios"
    studio.mkdir()
    elsewhere = tmp_path / "Otra carpeta"
    elsewhere.mkdir()
    monkeypatch.chdir(studio)
    entry = connection_info().claude_desktop_config.mcpServers["frutinovelas"]
    result = subprocess.run(
        [entry.command, *entry.args, "--help"],
        cwd=elsewhere,
        env={**os.environ, **entry.env},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--directory" in result.stdout and "streamable-http" in result.stdout


def test_directory_loads_same_dotenv_and_configured_port_before_mcp_starts(data_dir, monkeypatch, tmp_path):
    studio = tmp_path / "Studio de Ana ñ"
    studio.mkdir()
    (studio / ".env").write_text(
        "FRUTINOVELAS_MCP_PORT=9326\nFRUTINOVELAS_API_PORT=9325\nFRUTINOVELAS_API_TOKEN=from-local-env\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for key in ("FRUTINOVELAS_MCP_PORT", "FRUTINOVELAS_API_PORT", "FRUTINOVELAS_API_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    # A setting cached by an earlier invocation must not hide the selected directory's .env.
    assert get_settings().api_token is None
    calls = []

    class Server:
        def run(self, **options):
            calls.append(options)
            assert Path.cwd() == studio
            assert get_settings().api_token == "from-local-env"
            assert get_settings().api_port == 9325

    monkeypatch.setattr("frutinovelas.mcp_server.create_server", Server)
    assert main(["--directory", str(studio), "--transport", "streamable-http"]) == 0
    assert calls == [{"transport": "streamable-http", "host": "127.0.0.1", "port": 9326,
                      "streamable_http_path": "/mcp", "stateless_http": True}]


def test_mcp_cli_api_port_overrides_the_selected_directory_configuration(data_dir, monkeypatch, tmp_path):
    studio = tmp_path / "Studio con puerto distinto"
    studio.mkdir()
    (studio / ".env").write_text("FRUTINOVELAS_API_PORT=8765\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FRUTINOVELAS_API_PORT", raising=False)
    calls = []

    class Server:
        def run(self, **options):
            calls.append(options)
            assert Path.cwd() == studio
            assert get_settings().api_port == 9425

    monkeypatch.setattr("frutinovelas.mcp_server.create_server", Server)
    assert main([
        "--directory", str(studio), "--transport", "streamable-http",
        "--host", "127.0.0.1", "--port", "9426", "--api-port", "9425",
    ]) == 0
    assert calls == [{"transport": "streamable-http", "host": "127.0.0.1", "port": 9426,
                      "streamable_http_path": "/mcp", "stateless_http": True}]
    assert (studio / ".env").read_text(encoding="utf-8") == "FRUTINOVELAS_API_PORT=8765\n"


def test_missing_directory_is_rejected_before_start(data_dir, tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["--directory", str(tmp_path / "missing")])
    assert error.value.code == 2


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.2", "example.com", "https://example.com/mcp"])
def test_connection_info_cannot_probe_a_remote_host(host):
    with pytest.raises(ValueError, match="loopback"):
        local_address(Settings(_env_file=None, FRUTINOVELAS_MCP_HOST=host))


def test_ipv6_url_and_shell_arguments_preserve_paths():
    assert local_address(Settings(_env_file=None, FRUTINOVELAS_MCP_HOST="::1", FRUTINOVELAS_MCP_PORT=8767))[2] == "http://[::1]:8767/mcp"
    arguments = ["/opt/Studio de Ana's/python", "--directory", "/tmp/a $b; & ' ñ"]
    assert shlex.split(shell_command(arguments, windows=False)) == arguments
    assert shell_command([r"C:\Ana's Studio\python.exe", "$HOME; Get-ChildItem"], windows=True) == (
        "& 'C:\\Ana''s Studio\\python.exe' '$HOME; Get-ChildItem'"
    )


@pytest.mark.asyncio
async def test_real_protocol_diagnostic_checks_frutinovelas_without_calling_generation(data_dir, monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setenv("FRUTINOVELAS_MCP_PORT", str(port))
    reset_settings_cache()
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "frutinovelas.mcp_server", "--transport", "streamable-http", "--port", str(port),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(20), httpx2.AsyncClient(trust_env=False, timeout=2) as client:
            while True:
                assert process.returncode is None, "MCP exited before the diagnostic"
                try:
                    await client.get(f"http://127.0.0.1:{port}/")
                    break
                except (httpx2.ConnectError, httpx2.ConnectTimeout):
                    await asyncio.sleep(0.05)
            result = await connection_status()
        assert result.state == "ready", result.model_dump()
        assert result.server_name == "FRUTINOVELAS Prompts"
        assert result.tools_count >= 45
        assert result.local_url == f"http://127.0.0.1:{port}/mcp"
        assert result.checked_at
    finally:
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()


@pytest.mark.asyncio
async def test_protocol_error_never_reports_ready_or_exposes_server_text(data_dir, monkeypatch):
    @asynccontextmanager
    async def broken_transport(*_args, **_kwargs):
        raise RuntimeError("private-server-text-secret")
        yield  # pragma: no cover

    monkeypatch.setattr("mcp.client.streamable_http.streamable_http_client", broken_transport)
    result = await connection_status()
    assert result.state == "unreachable"
    assert result.server_name is None and result.tools_count is None
    assert "private-server-text-secret" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_another_mcp_server_is_not_reported_as_frutinovelas(data_dir, monkeypatch):
    @asynccontextmanager
    async def transport(*_args, **_kwargs):
        yield (None, None)

    class Session:
        def __init__(self, *_streams):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def initialize(self):
            return SimpleNamespace(server_info=SimpleNamespace(name="Otro MCP"))

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name="get_directing_guidance")])

        async def call_tool(self, *_args, **_kwargs):
            raise AssertionError("A diagnostic must never execute tools")

    monkeypatch.setattr("mcp.client.streamable_http.streamable_http_client", transport)
    monkeypatch.setattr("mcp.ClientSession", Session)
    result = await connection_status()
    assert result.state == "incompatible"
    assert result.server_name == "Otro MCP"
    assert result.tools_count == 1


def test_invalid_config_returns_actionable_error_instead_of_contacting_other_hosts(client):
    get_settings().mcp_host = "example.com"
    response = client.get("/api/v1/mcp/connection")
    assert response.status_code == 503
    assert "loopback" in response.json()["detail"]
