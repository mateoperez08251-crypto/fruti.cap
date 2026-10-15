"""Actualiza solo un checkout limpio de main; no requiere instalar dependencias."""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

EXPECTED_REMOTES = {
    "https://github.com/mateoperez08251-crypto/fruti.cap",
    "https://github.com/mateoperez08251-crypto/fruti.cap.git",
    "git@github.com:mateoperez08251-crypto/fruti.cap.git",
    "git@github.com:mateoperez08251-crypto/fruti.cap",
    "ssh://git@github.com/mateoperez08251-crypto/fruti.cap.git",
    "ssh://git@github.com/mateoperez08251-crypto/fruti.cap",
}
GIT_STATES = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "REBASE_HEAD",
    "BISECT_LOG",
    "rebase-merge",
    "rebase-apply",
    "sequencer",
    "index.lock",
    "HEAD.lock",
)
PORT_DEFAULTS = {"FRUTINOVELAS_API_PORT": 8765, "FRUTINOVELAS_MCP_PORT": 8766}
HOST_NAMES = ("FRUTINOVELAS_API_HOST", "FRUTINOVELAS_MCP_HOST")


class UpdateError(Exception):
    """Error legible; nunca contiene stderr de Git ni URLs de credenciales."""


def git(repo: Path, *args: str, timeout: float = 15, check: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"})
    try:
        result = subprocess.run(  # noqa: S603 - argumentos internos separados, sin shell
            ["git", "-c", "credential.interactive=false", "-c", f"core.hooksPath={os.devnull}", *args],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise UpdateError("Instala Git y vuelve a abrir una terminal antes de actualizar.") from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(
            "Git excedio el tiempo limite. No se forzo la actualizacion; revisa git status."
        ) from exc
    except OSError as exc:
        raise UpdateError("No se pudo ejecutar Git en la carpeta del programa.") from exc
    if check and result.returncode:
        raise UpdateError(
            "Git no completo la operacion. Revisa git status y la conexion/autenticacion de GitHub."
        )
    return result


def git_path(repo: Path, name: str) -> Path:
    value = Path(git(repo, "rev-parse", "--git-path", name).stdout.strip())
    return value if value.is_absolute() else repo / value


def connection_settings(app: Path) -> dict[str, str]:
    """Lee solo puertos/interfaces; no carga ni muestra tokens de .env."""
    values = {}
    env_file = app / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                match = re.match(
                    r"\s*(?:export\s+)?(FRUTINOVELAS_(?:API|MCP)_(?:PORT|HOST))\s*=\s*(.*?)\s*$", line
                )
                if match:
                    values[match[1]] = match[2].split("#", 1)[0].strip().strip("\"'")
        except (OSError, UnicodeError) as exc:
            raise UpdateError("No se pudo comprobar la configuracion local de conexion en .env.") from exc
    for name in (*PORT_DEFAULTS, *HOST_NAMES):
        if name in os.environ:
            values[name] = os.environ[name]
    return values


def configured_ports(app: Path) -> set[int]:
    values = connection_settings(app)
    ports = set(PORT_DEFAULTS.values())
    for name, default in PORT_DEFAULTS.items():
        raw = values.get(name, str(default))
        try:
            port = int(raw)
        except ValueError as exc:
            raise UpdateError(f"{name} debe contener un puerto numerico antes de actualizar.") from exc
        if not 1 <= port <= 65535:
            raise UpdateError(f"{name} esta fuera del rango de puertos permitido.")
        ports.add(port)
    return ports


def check_stopped(app: Path) -> None:
    settings = connection_settings(app)
    hosts = {"127.0.0.1", "::1"}
    hosts.update(
        settings[name] for name in HOST_NAMES if settings.get(name) not in {None, "", "0.0.0.0", "::"}
    )
    for port in sorted(configured_ports(app)):
        for host in sorted(hosts):
            try:
                with socket.create_connection((host, port), timeout=0.25):
                    pass
            except OSError:
                continue
            raise UpdateError(
                f"El puerto local {port} esta ocupado. Cierra Studio y su MCP antes de actualizar o iniciar. "
                "No se cerrara ningun proceso automaticamente."
            )


def preflight(repo: Path, app: Path) -> str:
    root = Path(git(repo, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if root != repo.resolve():
        raise UpdateError("Esta carpeta no es la raiz esperada del checkout de Fruti.cap.")
    branch = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if branch.returncode or branch.stdout.strip() != "main":
        raise UpdateError(
            "La actualizacion automatica requiere la rama main. Conserva y revisa tu rama actual."
        )
    origins = git(repo, "remote", "get-url", "--all", "origin").stdout.splitlines()
    if len(origins) != 1 or origins[0].rstrip("/") not in EXPECTED_REMOTES:
        raise UpdateError(
            "origin no coincide con mateoperez08251-crypto/fruti.cap. No se cambiara el remoto."
        )
    for name in GIT_STATES:
        if git_path(repo, name).exists():
            raise UpdateError("Hay una operacion o bloqueo de Git en curso. Terminala antes de actualizar.")
    if git(
        repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"
    ).stdout:
        raise UpdateError(
            "Hay cambios locales o archivos nuevos sin seguimiento. Guardalos/revisalos antes de actualizar. "
            "No se usa reset, clean ni stash."
        )
    check_stopped(app)
    return git(repo, "rev-parse", "--verify", "HEAD").stdout.strip()


def update(repo: Path, app: Path) -> bool:
    """Devuelve True solo si el checkout avanza; un fallo nunca habilita el arranque."""
    before = preflight(repo, app)
    lock = git_path(repo, "fruti-update.lock")
    try:
        with lock.open("x", encoding="ascii") as stream:
            stream.write(str(os.getpid()))
    except FileExistsError as exc:
        raise UpdateError("Ya hay otra actualizacion o un bloqueo anterior (fruti-update.lock).") from exc
    try:
        print("Comprobando main en GitHub...", flush=True)
        git(
            repo,
            "fetch",
            "--no-tags",
            "--no-recurse-submodules",
            "origin",
            "refs/heads/main:refs/remotes/origin/main",
            timeout=45,
        )
        target = git(repo, "rev-parse", "--verify", "refs/remotes/origin/main^{commit}").stdout.strip()
        if preflight(repo, app) != before:
            raise UpdateError("El checkout cambio durante la comprobacion. Se cancelo la actualizacion.")
        if before == target:
            print("Ya tienes la ultima version publicada en main.", flush=True)
            return False
        ancestor = git(repo, "merge-base", "--is-ancestor", before, target, check=False)
        if ancestor.returncode:
            raise UpdateError(
                "main tiene commits locales o un historial diferente. Se requiere revisar la fusion manualmente; "
                "no se reescribira el historial."
            )
        git(
            repo,
            "-c",
            "merge.autostash=false",
            "merge",
            "--ff-only",
            "--no-edit",
            "--no-overwrite-ignore",
            target,
            timeout=45,
        )
        if git(repo, "rev-parse", "HEAD").stdout.strip() != target:
            raise UpdateError("No se pudo confirmar la version final. Revisa git status antes de iniciar.")
        print(f"Codigo actualizado de {before[:8]} a {target[:8]} (fast-forward).", flush=True)
        return True
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock.unlink()


def run_visible(args: list[str], app: Path, *, timeout: int | None = 600) -> int:
    try:
        return subprocess.run(args, cwd=app, timeout=timeout, check=False).returncode  # noqa: S603 - comandos internos
    except FileNotFoundError as exc:
        raise UpdateError(
            f"No se encontro {Path(args[0]).name}. Instala los requisitos del programa."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(
            "La instalacion o compilacion excedio el tiempo limite. El programa no se inicio."
        ) from exc


def start(app: Path) -> int:
    check_stopped(app)
    try:
        node = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError(
            "Instala Node.js 24 LTS (recomendado) o 22.13+ de la rama 22 y vuelve a abrir este archivo."
        ) from exc
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\s*", node.stdout)
    major, minor, _ = tuple(map(int, version.groups())) if version else (0, 0, 0)
    if node.returncode or not ((major == 22 and minor >= 13) or major == 24 or major >= 26):
        raise UpdateError(
            "Se recomienda Node.js 24 LTS; tambien se admite 22.13+ de la rama 22 o >=26. No 23/25."
        )
    if subprocess.run(
        [sys.executable, "-m", "uv", "--version"], cwd=app, capture_output=True, timeout=15, check=False
    ).returncode:
        if run_visible([sys.executable, "-m", "pip", "install", "uv"], app):
            raise UpdateError("No se pudo instalar uv. El programa no se inicio.")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    commands = (
        [sys.executable, "-m", "uv", "sync", "--frozen", "--link-mode", "copy"],
        [npm, "--prefix", "frontend", "ci"],
        [npm, "--prefix", "frontend", "run", "build"],
    )
    for command in commands:
        if run_visible(command, app):
            raise UpdateError(
                "Fallo la preparacion del programa. Corrige el error anterior y vuelve a iniciar."
            )
    if run_visible([sys.executable, "-m", "uv", "run", "--frozen", "frutinovelas-api"], app, timeout=None):
        raise UpdateError(
            "La API termino con un error. Revisa el mensaje anterior antes de volver a iniciar."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--launch", action="store_true", help="Actualizar y despues iniciar el programa")
    mode.add_argument("--start-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    app = Path(__file__).resolve().parent.parent
    repo = app.parent
    try:
        if args.start_only:
            return start(app)
        if args.launch and os.environ.get("FRUTINOVELAS_AUTO_UPDATE", "1").lower() in {"0", "false", "no"}:
            print("Actualizacion automatica desactivada; se abrira el codigo local.", flush=True)
        else:
            update(repo, app)
        if args.launch:
            # El script puede haberse actualizado: cargar la version nueva antes de preparar dependencias.
            return run_visible(
                [sys.executable, str(app / "scripts" / "safe_update.py"), "--start-only"], app, timeout=None
            )
        return 0
    except (UpdateError, OSError, subprocess.TimeoutExpired) as exc:
        message = str(exc) if isinstance(exc, UpdateError) else "No se pudo completar la operacion local."
        print(f"Actualizacion/inicio detenido: {message}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Operacion cancelada. Revisa git status si estaba actualizando.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
