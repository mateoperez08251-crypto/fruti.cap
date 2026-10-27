import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import flow_mycontent_browser as bridge


@pytest.fixture(autouse=True)
def isolated_browser_lookup(monkeypatch):
    monkeypatch.setattr(bridge, "installed_chromium", lambda: None)


def test_reuses_browser_module_without_importing_application_or_accounts(tmp_path):
    source = tmp_path / "my content"
    (source / "bot").mkdir(parents=True)
    (source / "bot/navegador.py").write_text("def abrir_normal(*args, **kwargs): pass\ndef _ejecutable_login(*args): return ('chromium', __file__)\n", encoding="utf-8")
    browser, path, manifest = bridge.prepare(source, tmp_path / "private-data")
    assert callable(browser.abrir_normal)
    assert manifest["url"] == "https://flow.google.com/"
    assert manifest["automation_ready"] is False
    assert source not in Path(manifest["profile"]).parents
    assert not Path(manifest["profile"]).exists()
    bridge.save_manifest(path, manifest)
    assert json.loads(path.read_text(encoding="utf-8"))["source"] == str(source.resolve())


def test_missing_module_fails_without_creating_a_profile(tmp_path):
    with pytest.raises(ValueError, match="bot/navegador.py"):
        bridge.prepare(tmp_path / "missing", tmp_path / "data")
    assert not (tmp_path / "data").exists()


def test_manual_signin_uses_existing_chromium_without_downloading_another_build(tmp_path, monkeypatch):
    source = tmp_path / "my content"
    (source / "bot").mkdir(parents=True)
    (source / "bot/navegador.py").write_text("def abrir_normal(*args, **kwargs): pass\ndef _ejecutable_login(*args): raise RuntimeError('different Playwright build')\n", encoding="utf-8")
    executable = tmp_path / "chrome.exe"
    executable.write_bytes(b"existing")
    monkeypatch.setattr(bridge, "installed_chromium", lambda: executable)
    browser, _, manifest = bridge.prepare(source, tmp_path / "private")
    assert manifest["executable"] == str(executable)
    assert browser._ejecutable_login("chromium") == ("chromium", str(executable))


def test_login_opens_only_flow_with_separate_profile_and_does_not_claim_authentication(tmp_path, monkeypatch):
    path = tmp_path / "connection.json"
    calls = []
    def open_browser(profile, url, **kwargs):
        calls.append((profile, url, kwargs["navegador"]))
        kwargs["al_abrir"]("chromium", "chrome.exe")
        assert json.loads(path.read_text())["state"] == "manual_login"
    manifest = {"profile": str(tmp_path / "profile"), "automation_ready": False}
    monkeypatch.setattr(bridge, "prepare", lambda *args: (SimpleNamespace(abrir_normal=open_browser), path, manifest))
    assert bridge.main(["--source", str(tmp_path), "--login"]) == 0
    assert calls == [(str(tmp_path / "profile"), bridge.FLOW_URL, "chromium")]
    assert json.loads(path.read_text())["state"] == "closed_unverified"
    assert json.loads(path.read_text())["automation_ready"] is False
