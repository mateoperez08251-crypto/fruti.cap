"""Diagnostic export tests; Windows UIA is represented by metadata-only doubles."""
import json
import sys
from types import SimpleNamespace

import pytest

from frutinovelas import flow_agent, flow_uia
from frutinovelas.services.flow_transport import FlowError


@pytest.mark.parametrize("file_output", [False, True])
def test_inspection_preserves_exact_unicode_through_console_and_utf8_file(data_dir, monkeypatch, tmp_path, capsys, file_output):
    document = {"executable": "C:\\Aplicación\\UserFlex.exe", "windows": [
        {"title": "Prueba", "controls": [{"title": "Iniciar generación", "label": "¿Qué imaginas?"}]}]}
    calls = []

    def inspect(executable, **kwargs):
        calls.append((executable, kwargs))
        return document

    monkeypatch.setattr(flow_agent, "inspect_application", inspect)
    executable = tmp_path / "UserFlex.exe"
    output = tmp_path / "diagnostico.json"
    args = ["inspect", "--executable", str(executable), "--include-edit-labels"]
    if file_output:
        args += ["--output", str(output)]
    assert flow_agent.main(args) == 0
    stdout = capsys.readouterr().out
    if file_output:
        serialized = output.read_text(encoding="utf-8")
        assert "Iniciar generación" in serialized
    else:
        assert stdout.isascii(), "Legacy PowerShell must not reinterpret accented selector names"
        serialized = stdout
    assert json.loads(serialized) == document
    assert calls == [(executable, {"include_edit_labels": True})]


@pytest.mark.parametrize("directory", [True, False])
def test_inspection_rejects_a_directory_or_non_executable_before_loading_uia(monkeypatch, tmp_path, directory):
    monkeypatch.setattr(flow_uia, "os", SimpleNamespace(name="nt"))
    path = tmp_path if directory else tmp_path / "profile.json"
    if not directory:
        path.write_text("{}")
    with pytest.raises(FlowError, match="archivo .exe"):
        flow_uia.inspect_application.__wrapped__(path)


@pytest.mark.parametrize("include,password,status,expected_name", [
    (False, False, None, ""),
    (True, False, "included", "Instrucción de imagen"),
    (True, True, "password_omitted", ""),
    (True, None, "password_omitted", ""),
    (True, "unavailable", "unavailable", ""),
])
def test_edit_labels_are_opt_in_and_fail_closed_for_password_or_unknown_controls(include, password, status, expected_name):
    class Metadata:
        @property
        def CurrentIsPassword(self):
            if password == "unavailable":
                raise RuntimeError("Detached control")
            return password

        @property
        def CurrentName(self):
            assert include and password is False
            return "Instrucción de imagen"

        def __getattr__(self, name):
            raise AssertionError(f"Values, text patterns and other content must not be read: {name}")

    class Info:
        control_type = "Edit"
        automation_id = "prompt"
        framework_id = "Chrome"

        @property
        def element(self):
            assert include
            return Metadata()

        @property
        def name(self):
            raise AssertionError("Password status must be checked before reading an edit name")

    result = flow_uia._diagnostic_control(Info(), include_edit_labels=include)
    assert result["title"] == expected_name
    assert result.get("edit_label_status") == status


def test_inspection_reports_scope_and_hierarchy_without_reading_other_apps(monkeypatch, tmp_path):
    executable = tmp_path / "UserFlex.exe"
    executable.touch()
    own = SimpleNamespace(pid=11, info={"exe": str(executable)}, children=lambda recursive: [])
    other = SimpleNamespace(pid=99, info={"exe": str(tmp_path / "Other.exe")})
    root = SimpleNamespace(runtime_id=(1,))
    group = SimpleNamespace(control_type="Group", automation_id="canvas", framework_id="Chrome", runtime_id=(2,), parent=root)
    button = SimpleNamespace(control_type="Button", automation_id="", framework_id="Chrome", name="Iniciar generación",
                             runtime_id=(3,), parent=group)
    own_window = SimpleNamespace(process_id=lambda: 11, window_text=lambda: "UserFlex",
                                 descendants=lambda: [SimpleNamespace(element_info=group), SimpleNamespace(element_info=button)])
    # An unrelated window deliberately has no methods for reading title or descendants.
    other_window = SimpleNamespace(process_id=lambda: 99)
    monkeypatch.setattr(flow_uia, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(process_iter=lambda _: [own, other], Error=RuntimeError))
    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(
        Desktop=lambda backend: SimpleNamespace(windows=lambda: [own_window, other_window])))
    result = flow_uia.inspect_application.__wrapped__(executable)
    assert result["executable"] == str(executable.resolve())
    assert result["matched_processes"] == 1
    assert len(result["windows"]) == 1
    assert result["windows"][0]["controls_truncated"] is False
    controls = result["windows"][0]["controls"]
    assert controls[0]["parent_index"] is None
    assert controls[1]["parent_index"] == controls[0]["index"]
    assert controls[1]["title"] == "Iniciar generación"
