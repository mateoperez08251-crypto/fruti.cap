import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "qwen_desktop_setup", Path(__file__).resolve().parents[1] / "scripts/configurar_qwen_escritorio.py"
)
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)


def test_full_desktop_catalog_local_transport_and_existing_approvals(tmp_path):
    python = tmp_path / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    entries = setup.server_entries(tmp_path, "C:/Tools/uvx.exe")
    desktop = entries["windows-desktop-qwen"]
    assert "--tools" not in desktop["args"] and "--exclude-tools" not in desktop["args"]
    assert desktop["args"][-2:] == ["--transport", "stdio"]
    assert "autoApprove" not in desktop
    assert desktop["env"]["ANONYMIZED_TELEMETRY"] == "false"
    assert str(python) == entries["frutinovelas-studio"]["command"]


def test_merge_preserves_private_data_and_other_servers():
    current = {"other": {"private": "untouched"}, "mcpServers": {"other-server": {"token": "private"}}}
    result = setup.merge_servers(current, {"desktop": {"command": "uvx"}})
    assert result["other"] == current["other"]
    assert result["mcpServers"]["other-server"] == current["mcpServers"]["other-server"]
    assert "desktop" not in current["mcpServers"]


def test_install_backs_up_original_and_is_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    original = b'{"mcpServers":{},"keep":"literal"}\r\n'
    settings.write_bytes(original)
    entries = {"desktop": {"command": "uvx"}}
    backup = setup.install(settings, entries)
    assert backup.read_bytes() == original
    after = settings.read_bytes()
    assert json.loads(after)["keep"] == "literal"
    assert setup.install(settings, entries) is None
    assert settings.read_bytes() == after
    assert len(list(tmp_path.glob("*.bak"))) == 1


@pytest.mark.parametrize("body", [b"invalid json", b"[]", b'{"mcpServers":[]}'])
def test_invalid_settings_are_not_replaced(tmp_path, body):
    path = tmp_path / "settings.json"
    path.write_bytes(body)
    with pytest.raises(ValueError):
        setup.install(path, {"desktop": {"command": "uvx"}})
    assert path.read_bytes() == body


def test_conflicting_entry_preserved(tmp_path):
    path = tmp_path / "settings.json"
    original = b'{"mcpServers":{"desktop":{"command":"original"}}}'
    path.write_bytes(original)
    with pytest.raises(ValueError, match="No se sobrescribió"):
        setup.install(path, {"desktop": {"command": "different"}})
    assert path.read_bytes() == original
