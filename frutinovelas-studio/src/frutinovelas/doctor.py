"""Diagnóstico de FRUTINOVELAS Studio.

Revisa dependencias, almacenamiento y conexiones sin modificar el entorno de
ComfyUI ni descargar nada. Nunca muestra tokens ni credenciales.

Uso::

    frutinovelas-doctor
    python -m frutinovelas.doctor --json
    python -m frutinovelas.doctor --comfy-url http://127.0.0.1:8188
    python -m frutinovelas.doctor --skip-comfy

Código de salida: 0 si no hay fallos bloqueantes, 1 si los hay.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

OK = "ok"
WARN = "aviso"
FAIL = "falla"
INFO = "info"

_LABELS = {OK: "[ OK  ]", WARN: "[AVISO]", FAIL: "[FALLA]", INFO: "[INFO ]"}

REQUIRED_PYTHON = (3, 12)

# Distribuciones obligatorias según pyproject.toml.
REQUIRED_PACKAGES = (
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    "sqlalchemy",
    "alembic",
    "httpx",
    "websockets",
    "python-multipart",
    "Pillow",
    "platformdirs",
    "mcp",
)

# Módulos de arranque declarados en [project.scripts].
PROGRAM_MODULES = {
    "frutinovelas.api": "API y interfaz web",
    "frutinovelas.worker": "Coordinador de la cola",
    "frutinovelas.mcp_server": "Servidor MCP",
}

MIN_FREE_GB = 5.0


@dataclass
class Check:
    group: str
    name: str
    status: str
    detail: str
    hint: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- utilidades


def mask_url(url: str) -> str:
    """Oculta usuario, contraseña y query (donde suelen viajar tokens)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<url no válida>"
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    if parts.username or parts.password:
        host = f"***@{host}"
    query = "***" if parts.query else ""
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def _run_version(executable: str) -> tuple[str | None, str | None]:
    """Devuelve (primera línea de -version, error)."""
    resolved = shutil.which(executable)
    if resolved is None and Path(executable).is_file():
        resolved = executable
    if resolved is None:
        return None, "no encontrado"
    try:
        proc = subprocess.run(  # noqa: S603 - lista de argumentos, shell=False
            [resolved, "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"no se pudo ejecutar: {exc}"
    if proc.returncode != 0:
        return None, f"terminó con código {proc.returncode}"
    first = (proc.stdout or proc.stderr).strip().splitlines()
    return (first[0] if first else resolved), None


# --------------------------------------------------------------------------- comprobaciones


def _project_venv_python() -> Path | None:
    """Python del .venv del proyecto si este archivo vive en el repositorio."""
    root = Path(__file__).resolve().parents[2]
    exe = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return exe if exe.is_file() else None


def _using_project_venv() -> bool:
    venv_py = _project_venv_python()
    if venv_py is None:
        return sys.prefix != sys.base_prefix
    return Path(sys.prefix).resolve() == venv_py.parents[1].resolve()


def check_python() -> list[Check]:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    out: list[Check] = []
    if (v.major, v.minor) == REQUIRED_PYTHON:
        out.append(Check("Sistema", "Python", OK, f"{ver} ({sys.executable})"))
    else:
        out.append(
            Check(
                "Sistema",
                "Python",
                FAIL,
                f"{ver}; se requiere {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}",
                hint="Crea el entorno con: py -3.12 -m venv .venv",
            )
        )
    venv_py = _project_venv_python()
    if _using_project_venv():
        out.append(Check("Sistema", "Entorno", OK, "entorno virtual del proyecto"))
    else:
        hint = (
            f"Ejecuta con: {venv_py} -m frutinovelas.doctor"
            if venv_py
            else "Crea el entorno del proyecto y ejecuta uv sync --extra dev."
        )
        out.append(
            Check(
                "Sistema",
                "Entorno",
                FAIL,
                "estás usando el Python del sistema, no el entorno .venv del proyecto",
                hint=hint + " (en VS Code: Ctrl+Shift+P > 'Python: Select Interpreter' > .venv)",
            )
        )
    return out


def check_packages() -> list[Check]:
    out: list[Check] = []
    missing: list[str] = []
    for dist in REQUIRED_PACKAGES:
        try:
            version = metadata.version(dist)
        except metadata.PackageNotFoundError:
            missing.append(dist)
            out.append(Check("Paquetes", dist, FAIL, "no instalado"))
        else:
            out.append(Check("Paquetes", dist, OK, version))
    if missing:
        hint = (
            r"Ejecuta: .\.venv\Scripts\uv.exe sync --extra dev"
            if _using_project_venv()
            else "Probablemente ya están en .venv: usa el Python del entorno (ver 'Entorno' arriba)."
        )
        out.append(
            Check("Paquetes", "Resumen", FAIL, f"faltan {len(missing)}: {', '.join(missing)}", hint=hint)
        )
    return out


def check_program_modules() -> list[Check]:
    out: list[Check] = []
    for module, label in PROGRAM_MODULES.items():
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if found:
            out.append(Check("Programa", label, OK, module))
        else:
            out.append(
                Check(
                    "Programa",
                    label,
                    WARN,
                    f"{module} todavía no está implementado",
                    hint="El comando correspondiente no arrancará hasta que exista este módulo.",
                )
            )
    return out


def check_settings() -> tuple[list[Check], Any]:
    try:
        from frutinovelas.config import Settings
    except Exception as exc:  # pragma: no cover - depende del entorno
        return [Check("Configuración", "Carga", FAIL, f"no se pudo importar config: {exc}")], None
    try:
        settings = Settings()
    except Exception as exc:
        return [
            Check(
                "Configuración",
                "Variables",
                FAIL,
                f"valores no válidos: {exc.__class__.__name__}",
                hint="Revisa tu .env frente a .env.example.",
            )
        ], None
    env_file = Path(".env")
    checks = [
        Check(
            "Configuración",
            "Archivo .env",
            INFO,
            f"usado: {env_file.resolve()}" if env_file.is_file() else "no hay .env en esta carpeta; se usan valores por defecto",
        ),
        Check("Configuración", "API", INFO, f"{settings.api_host}:{settings.api_port}"),
        Check("Configuración", "MCP", INFO, f"{settings.mcp_host}:{settings.mcp_port}"),
    ]
    for name, host in (("API", settings.api_host), ("MCP", settings.mcp_host)):
        if host not in ("127.0.0.1", "localhost", "::1"):
            token = settings.api_token if name == "API" else settings.mcp_token
            if not token:
                checks.append(
                    Check(
                        "Configuración",
                        f"Seguridad {name}",
                        WARN,
                        f"{name} escucha en {host} sin token",
                        hint=f"Define FRUTINOVELAS_{name}_TOKEN o usa 127.0.0.1.",
                    )
                )
    return checks, settings


def check_storage(settings: Any) -> list[Check]:
    out: list[Check] = []
    try:
        data_dir = Path(settings.resolved_data_dir)
        settings.ensure_dirs()
    except OSError as exc:
        return [
            Check(
                "Almacenamiento",
                "Directorio de datos",
                FAIL,
                f"no se pudo crear: {exc}",
                hint="Ajusta FRUTINOVELAS_DATA_DIR a una carpeta con permisos de escritura.",
            )
        ]
    probe = data_dir / "tmp" / f".doctor-{uuid.uuid4().hex}"
    try:
        probe.write_text("prueba ñ", encoding="utf-8")
        ok = probe.read_text(encoding="utf-8") == "prueba ñ"
    except OSError as exc:
        out.append(Check("Almacenamiento", "Escritura", FAIL, f"{data_dir}: {exc}"))
        return out
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
    out.append(
        Check(
            "Almacenamiento",
            "Directorio de datos",
            OK if ok else FAIL,
            str(data_dir),
            data={"path": str(data_dir)},
        )
    )
    usage = shutil.disk_usage(data_dir)
    free_gb = usage.free / 1024**3
    out.append(
        Check(
            "Almacenamiento",
            "Espacio libre",
            OK if free_gb >= MIN_FREE_GB else WARN,
            f"{free_gb:.1f} GB libres",
            hint=None if free_gb >= MIN_FREE_GB else "Los videos y montajes ocupan bastante; libera espacio.",
            data={"free_bytes": usage.free},
        )
    )
    return out


def check_sqlite(settings: Any) -> list[Check]:
    version = sqlite3.sqlite_version
    tmp_root = Path(settings.tmp_dir) if settings is not None else Path(tempfile.gettempdir())
    tmp_root.mkdir(parents=True, exist_ok=True)
    db = tmp_root / f".doctor-{uuid.uuid4().hex}.sqlite3"
    try:
        con = sqlite3.connect(db, timeout=5)
        try:
            mode = con.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            con.execute("PRAGMA foreign_keys=ON")
            fk = con.execute("PRAGMA foreign_keys").fetchone()[0]
            con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            con.commit()
        finally:
            con.close()
    except sqlite3.Error as exc:
        return [Check("Base de datos", "SQLite", FAIL, f"{version}: {exc}")]
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(f"{db}{suffix}").unlink(missing_ok=True)
            except OSError:
                pass
    if str(mode).lower() != "wal":
        return [
            Check(
                "Base de datos",
                "SQLite",
                WARN,
                f"{version}; WAL no disponible (modo {mode})",
                hint="Evita guardar los datos en una carpeta de red o sincronizada.",
            )
        ]
    return [Check("Base de datos", "SQLite", OK, f"{version}, WAL y claves foráneas {'activas' if fk else 'inactivas'}")]


def check_ffmpeg(settings: Any) -> list[Check]:
    out: list[Check] = []
    pairs = (
        ("FFmpeg", getattr(settings, "ffmpeg_path", "ffmpeg"), "FFMPEG_PATH"),
        ("FFprobe", getattr(settings, "ffprobe_path", "ffprobe"), "FFPROBE_PATH"),
    )
    for label, exe, env in pairs:
        line, err = _run_version(exe)
        if err:
            out.append(
                Check(
                    "Multimedia",
                    label,
                    FAIL,
                    f"'{exe}' {err}",
                    hint=f"Instala FFmpeg (winget install Gyan.FFmpeg) o define {env} con la ruta completa.",
                )
            )
        else:
            out.append(Check("Multimedia", label, OK, line or exe))
    return out


def check_comfyui(url: str, timeout: float) -> list[Check]:
    import httpx

    shown = mask_url(url)
    endpoint = url.rstrip("/") + "/system_stats"
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=timeout)) as client:
            resp = client.get(endpoint)
    except httpx.HTTPError as exc:
        return [
            Check(
                "ComfyUI",
                "Conexión",
                WARN,
                f"{shown} no responde ({exc.__class__.__name__})",
                hint="Arranca ComfyUI o actualiza COMFYUI_BASE_URL (p. ej. si el túnel de Colab cambió).",
            )
        ]
    if resp.status_code in (401, 403):
        return [Check("ComfyUI", "Conexión", WARN, f"{shown} exige autenticación (HTTP {resp.status_code})")]
    if resp.status_code != 200:
        return [Check("ComfyUI", "Conexión", WARN, f"{shown} respondió HTTP {resp.status_code}")]
    try:
        stats = resp.json()
    except ValueError:
        return [Check("ComfyUI", "Conexión", WARN, f"{shown} respondió algo que no es JSON; ¿es ComfyUI?")]

    system = stats.get("system", {}) if isinstance(stats, dict) else {}
    version = system.get("comfyui_version") or "versión no informada"
    out = [Check("ComfyUI", "Conexión", OK, f"{shown} — ComfyUI {version}")]
    for dev in stats.get("devices", []) if isinstance(stats, dict) else []:
        name = dev.get("name", "dispositivo")
        total = dev.get("vram_total") or 0
        free = dev.get("vram_free") or 0
        if total:
            detail = f"{name} — VRAM {free / 1024**3:.1f} / {total / 1024**3:.1f} GB libres"
        else:
            detail = name
        out.append(Check("ComfyUI", "GPU", INFO, detail))
    return out


def check_api_port(settings: Any) -> list[Check]:
    host, port = settings.api_host, settings.api_port
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    try:
        with socket.create_connection((probe_host, port), timeout=1.5):
            busy = True
    except OSError:
        busy = False
    if busy:
        return [Check("Programa", "Puerto API", INFO, f"{probe_host}:{port} ya está en uso (¿API en marcha?)")]
    return [Check("Programa", "Puerto API", OK, f"{probe_host}:{port} libre")]


# --------------------------------------------------------------------------- ejecución


def run_checks(*, comfy_url: str | None = None, skip_comfy: bool = False, comfy_timeout: float = 5.0) -> list[Check]:
    checks: list[Check] = []
    checks += check_python()
    checks += check_packages()
    settings_checks, settings = check_settings()
    checks += settings_checks
    if settings is not None:
        checks += check_storage(settings)
    checks += check_sqlite(settings)
    checks += check_ffmpeg(settings)
    if skip_comfy:
        checks.append(Check("ComfyUI", "Conexión", INFO, "omitida (--skip-comfy)"))
    else:
        url = comfy_url or (settings.comfyui_base_url if settings is not None else "http://127.0.0.1:8188")
        checks += check_comfyui(url, comfy_timeout)
    checks += check_program_modules()
    if settings is not None:
        checks += check_api_port(settings)
    return checks


def summarize(checks: list[Check]) -> dict[str, int]:
    counts = {OK: 0, WARN: 0, FAIL: 0, INFO: 0}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1
    return counts


def render_text(checks: list[Check]) -> str:
    lines = ["FRUTINOVELAS Studio — diagnóstico", ""]
    group = None
    for c in checks:
        if c.group != group:
            if group is not None:
                lines.append("")
            lines.append(c.group)
            group = c.group
        lines.append(f"  {_LABELS[c.status]} {c.name}: {c.detail}")
        if c.hint and c.status in (WARN, FAIL):
            lines.append(f"           -> {c.hint}")
    counts = summarize(checks)
    lines += [
        "",
        f"Resultado: {counts[OK]} correctas, {counts[WARN]} avisos, {counts[FAIL]} fallos.",
    ]
    lines.append("Listo para continuar." if counts[FAIL] == 0 else "Corrige los fallos antes de continuar.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="frutinovelas-doctor",
        description="Revisa dependencias, almacenamiento y conexión de FRUTINOVELAS Studio.",
    )
    p.add_argument("--json", action="store_true", help="salida en JSON (sin secretos)")
    p.add_argument("--comfy-url", help="URL de ComfyUI a probar en lugar de COMFYUI_BASE_URL")
    p.add_argument("--skip-comfy", action="store_true", help="no intentar conectar con ComfyUI")
    p.add_argument("--timeout", type=float, default=5.0, help="segundos de espera para ComfyUI (5)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    checks = run_checks(comfy_url=args.comfy_url, skip_comfy=args.skip_comfy, comfy_timeout=args.timeout)
    counts = summarize(checks)
    if args.json:
        payload = {"summary": counts, "checks": [asdict(c) for c in checks]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(checks))
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
