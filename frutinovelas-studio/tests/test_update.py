"""El actualizador nunca descarta archivos ni reescribe el historial local."""

from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "safe_update.py"
spec = importlib.util.spec_from_file_location("safe_update", SCRIPT)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, files, message="Cambio de prueba"):
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", "--all")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Fruti Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.invalid")
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "-b", "main")
    commit(upstream, {"frutinovelas-studio/app.txt": "version uno", ".gitignore": ".env\nprivate/\n"})
    remote = tmp_path / "origin.git"
    git(tmp_path, "clone", "--bare", str(upstream), str(remote))
    git(upstream, "remote", "add", "origin", str(remote))
    repo = tmp_path / "working"
    git(tmp_path, "clone", str(remote), str(repo))
    monkeypatch.setattr(updater, "EXPECTED_REMOTES", {str(remote)})
    monkeypatch.setattr(updater, "check_stopped", lambda app: None)
    return repo, repo / "frutinovelas-studio", upstream


def publish(upstream, files):
    result = commit(upstream, files)
    git(upstream, "push", "origin", "main")
    return result


def test_fast_forward_preserves_ignored_configuration(checkout):
    repo, app, upstream = checkout
    (app / ".env").write_text("PRIVATE_TOKEN=kept-local\n")
    target = publish(upstream, {"frutinovelas-studio/app.txt": "version dos"})
    assert updater.update(repo, app) is True
    assert git(repo, "rev-parse", "HEAD") == target
    assert (app / "app.txt").read_text() == "version dos"
    assert (app / ".env").read_text() == "PRIVATE_TOKEN=kept-local\n"
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".git" / "fruti-update.lock").exists()
    assert updater.update(repo, app) is False


@pytest.mark.parametrize("kind", ["modified", "staged", "untracked"])
def test_preserves_all_local_changes(checkout, kind):
    repo, app, upstream = checkout
    publish(upstream, {"frutinovelas-studio/app.txt": "remoto"})
    path = app / ("nuevo.txt" if kind == "untracked" else "app.txt")
    path.write_text("trabajo local")
    if kind == "staged":
        git(repo, "add", str(path))
    before = git(repo, "rev-parse", "HEAD")
    status = git(repo, "status", "--porcelain")
    with pytest.raises(updater.UpdateError, match="cambios locales"):
        updater.update(repo, app)
    assert path.read_text() == "trabajo local"
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "status", "--porcelain") == status


@pytest.mark.parametrize("branch", ["otra", "detached"])
def test_does_not_change_branch(checkout, branch):
    repo, app, _ = checkout
    git(repo, "checkout", "--detach") if branch == "detached" else git(repo, "checkout", "-b", branch)
    before = git(repo, "rev-parse", "HEAD")
    with pytest.raises(updater.UpdateError, match="rama main"):
        updater.update(repo, app)
    assert git(repo, "rev-parse", "HEAD") == before


def test_wrong_remote_does_not_leak_credentials(checkout):
    repo, app, _ = checkout
    git(repo, "remote", "set-url", "origin", "https://user:private-secret@example.invalid/other.git")
    with pytest.raises(updater.UpdateError, match="origin no coincide") as caught:
        updater.update(repo, app)
    assert "private-secret" not in str(caught.value)
    assert "example.invalid" not in str(caught.value)


@pytest.mark.parametrize("marker", ["MERGE_HEAD", "index.lock", "rebase-merge", "CHERRY_PICK_HEAD"])
def test_git_operation_blocks_update(checkout, marker):
    repo, app, _ = checkout
    path = repo / ".git" / marker
    path.mkdir() if marker == "rebase-merge" else path.write_text("preservar")
    with pytest.raises(updater.UpdateError, match="Git en curso"):
        updater.update(repo, app)
    assert path.exists()


@pytest.mark.parametrize("diverged", [False, True])
def test_local_commits_are_not_rewritten(checkout, diverged):
    repo, app, upstream = checkout
    local_head = commit(repo, {"frutinovelas-studio/local.txt": "commit local"})
    if diverged:
        publish(upstream, {"frutinovelas-studio/remoto.txt": "commit remoto"})
    with pytest.raises(updater.UpdateError, match="commits locales"):
        updater.update(repo, app)
    assert git(repo, "rev-parse", "HEAD") == local_head
    assert (app / "local.txt").read_text() == "commit local"


def test_ignored_file_is_not_overwritten_by_incoming_tracked_file(checkout):
    repo, app, upstream = checkout
    path = app / "private" / "notes.txt"
    path.parent.mkdir()
    path.write_text("datos privados")
    remote_path = upstream / "frutinovelas-studio" / "private" / "notes.txt"
    remote_path.parent.mkdir()
    remote_path.write_text("archivo remoto")
    git(upstream, "add", "-f", str(remote_path))
    git(upstream, "commit", "-m", "Archivo nuevo")
    git(upstream, "push", "origin", "main")
    before = git(repo, "rev-parse", "HEAD")
    with pytest.raises(updater.UpdateError):
        updater.update(repo, app)
    assert path.read_text() == "datos privados"
    assert git(repo, "rev-parse", "HEAD") == before


def test_network_failure_releases_only_own_lock(checkout, monkeypatch):
    repo, app, _ = checkout
    before = git(repo, "rev-parse", "HEAD")
    real_git = updater.git

    def failing_git(repo, *args, **kwargs):
        if args[0] == "fetch":
            raise updater.UpdateError("Sin conexion")
        return real_git(repo, *args, **kwargs)

    monkeypatch.setattr(updater, "git", failing_git)
    with pytest.raises(updater.UpdateError, match="Sin conexion"):
        updater.update(repo, app)
    assert git(repo, "rev-parse", "HEAD") == before
    assert not (repo / ".git" / "fruti-update.lock").exists()
    lock = repo / ".git" / "fruti-update.lock"
    lock.write_text("otro proceso")
    with pytest.raises(updater.UpdateError, match="otra actualizacion"):
        updater.update(repo, app)
    assert lock.read_text() == "otro proceso"


def test_changes_during_fetch_abort_merge(checkout, monkeypatch):
    repo, app, upstream = checkout
    publish(upstream, {"frutinovelas-studio/app.txt": "remoto"})
    before = git(repo, "rev-parse", "HEAD")
    real_git = updater.git

    def changing_git(repo, *args, **kwargs):
        result = real_git(repo, *args, **kwargs)
        if args[0] == "fetch":
            (app / "app.txt").write_text("edicion concurrente")
        return result

    monkeypatch.setattr(updater, "git", changing_git)
    with pytest.raises(updater.UpdateError, match="cambios locales"):
        updater.update(repo, app)
    assert git(repo, "rev-parse", "HEAD") == before
    assert (app / "app.txt").read_text() == "edicion concurrente"


def test_active_listener_blocks_update(tmp_path, monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        monkeypatch.setenv("FRUTINOVELAS_API_PORT", str(port))
        # A developer may have Studio running on a default port. Exercise this
        # listener only; configured_ports is covered independently below.
        monkeypatch.setattr(updater, "configured_ports", lambda app: {port})
        with pytest.raises(updater.UpdateError, match=f"puerto local {port}"):
            updater.check_stopped(tmp_path)


def test_ports_read_dotenv_and_environment_without_loading_tokens(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        'FRUTINOVELAS_API_PORT="9020" # custom\nFRUTINOVELAS_MCP_PORT=9021\nSECRET=private\n'
    )
    monkeypatch.setenv("FRUTINOVELAS_API_PORT", "9030")
    monkeypatch.delenv("FRUTINOVELAS_MCP_PORT", raising=False)
    assert updater.configured_ports(tmp_path) == {8765, 8766, 9030, 9021}


def test_explicit_bind_interface_is_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("FRUTINOVELAS_API_HOST", "192.0.2.4")
    hosts = []

    def connect(address, **kwargs):
        hosts.append(address[0])
        if address[0] == "192.0.2.4":
            return socket.socket()
        raise OSError("no listener")

    monkeypatch.setattr(updater.socket, "create_connection", connect)
    with pytest.raises(updater.UpdateError, match="ocupado"):
        updater.check_stopped(tmp_path)
    assert "192.0.2.4" in hosts


def test_git_timeout_redacts_command_and_stderr(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(["git", "https://private-secret@github.com"], 45)

    monkeypatch.setattr(updater.subprocess, "run", timeout)
    with pytest.raises(updater.UpdateError, match="tiempo limite") as caught:
        updater.git(tmp_path, "fetch")
    assert "private-secret" not in str(caught.value)


def test_failed_update_never_installs_or_starts(monkeypatch):
    monkeypatch.delenv("FRUTINOVELAS_AUTO_UPDATE", raising=False)
    monkeypatch.setattr(updater.sys.stdin, "isatty", lambda: False)

    def fail(*args):
        raise updater.UpdateError("cambios locales")

    monkeypatch.setattr(updater, "update", fail)
    monkeypatch.setattr(updater, "run_visible", lambda *args, **kwargs: pytest.fail("No debe iniciar"))
    assert updater.main(["--launch"]) == 1


def test_auto_update_can_be_disabled(monkeypatch):
    monkeypatch.setenv("FRUTINOVELAS_AUTO_UPDATE", "0")
    monkeypatch.setattr(updater, "update", lambda *args: pytest.fail("No debe actualizar"))
    commands = []
    monkeypatch.setattr(
        updater, "run_visible", lambda command, *args, **kwargs: commands.append(command) or 0
    )
    assert updater.main(["--launch"]) == 0
    assert len(commands) == 1
    assert commands[0][-1] == "--start-only"


def test_start_syncs_locked_dependencies_and_npm_before_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "check_stopped", lambda app: None)
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="v22.13.0\n"),
    )
    commands = []
    monkeypatch.setattr(
        updater, "run_visible", lambda command, *args, **kwargs: commands.append(command) or 0
    )
    assert updater.start(tmp_path) == 0
    assert commands[0][-4:] == ["sync", "--frozen", "--link-mode", "copy"]
    assert commands[1][-1] == "ci"
    assert commands[2][-1] == "build"
    assert commands[3][-3:] == ["run", "--frozen", "frutinovelas-api"]


def test_build_failure_does_not_start_api(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "check_stopped", lambda app: None)
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="v22.13.0\n"),
    )
    commands = []

    def run(command, *args, **kwargs):
        commands.append(command)
        return int(command[-1] == "build")

    monkeypatch.setattr(updater, "run_visible", run)
    with pytest.raises(updater.UpdateError, match="preparacion"):
        updater.start(tmp_path)
    assert len(commands) == 3


def test_api_failure_gets_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "check_stopped", lambda app: None)
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="v22.13.0\n"),
    )
    monkeypatch.setattr(
        updater, "run_visible", lambda command, *args, **kwargs: int(command[-1] == "frutinovelas-api")
    )
    with pytest.raises(updater.UpdateError, match="API termino"):
        updater.start(tmp_path)


@pytest.mark.parametrize("version", ["v22.12.0", "v23.9.0", "v25.0.0", "v20.19.0", "invalid"])
def test_node_versions_incompatible_with_lockfile_stop_before_install(tmp_path, monkeypatch, version):
    monkeypatch.setattr(updater, "check_stopped", lambda app: None)
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=version),
    )
    monkeypatch.setattr(updater, "run_visible", lambda *args, **kwargs: pytest.fail("No debe instalar"))
    with pytest.raises(updater.UpdateError, match="Node.js 24 LTS"):
        updater.start(tmp_path)


@pytest.mark.parametrize("version", ["v22.13.0", "v22.20.0", "v24.0.0", "v26.0.0"])
def test_node_versions_supported_by_lockfile_can_launch(tmp_path, monkeypatch, version):
    monkeypatch.setattr(updater, "check_stopped", lambda app: None)
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=version),
    )
    monkeypatch.setattr(updater, "run_visible", lambda *args, **kwargs: 0)
    assert updater.start(tmp_path) == 0
