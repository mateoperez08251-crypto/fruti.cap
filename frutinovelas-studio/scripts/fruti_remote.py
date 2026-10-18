#!/usr/bin/env python3
"""FRUTINOVELAS · ComfyUI remoto por comandos (RunPod o cualquier Linux con GPU NVIDIA).

Prepara ComfyUI v0.40.0 con el flujo H3 del usuario, exporta y valida los flujos API,
y lo publica detrás del gateway con token para que FRUTINOVELAS Studio (en el PC)
lo use. Todo se maneja desde la terminal del pod::

    python3 scripts/fruti_remote.py setup          # primera vez: instala, descarga, arranca
    fruti status                                    # (tras setup existe el atajo «fruti»)
    fruti token --mostrar
    fruti test --modo i2va --segundos 5
    fruti logs comfyui -f
    fruti stop
    fruti start                                     # tras reanudar el pod

Rutas (cambiables con FRUTI_BASE / FRUTI_MODELS_DIR): ``/workspace/ComfyUI``,
``/workspace/FRUTINOVELAS_models``, ``/workspace/FRUTINOVELAS_data``.
ComfyUI escucha solo en 127.0.0.1; hacia fuera solo sale el gateway (8189) con token.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# --------------------------------------------------------------------------- constantes
VERSION = "1.2.0"
KIT_DIR = Path(__file__).resolve().parents[1]
BASE = Path(os.environ.get("FRUTI_BASE", "/workspace"))
COMFY_DIR = BASE / "ComfyUI"
DATA_DIR = BASE / "FRUTINOVELAS_data"
MODELS_DIR = Path(os.environ.get("FRUTI_MODELS_DIR", str(BASE / "FRUTINOVELAS_models")))
API_DIR = DATA_DIR / "workflows" / "api"
LOG_DIR = DATA_DIR / "logs"
SECRETS_DIR = DATA_DIR / "secrets"
TESTS_DIR = DATA_DIR / "tests"
CONFIG_FILE = DATA_DIR / "config.json"
STATE_FILE = DATA_DIR / "estado.json"
PIDS_FILE = DATA_DIR / "pids.json"
IDENTITY_FILE = DATA_DIR / "identity.json"
INFORME_FILE = DATA_DIR / "informe_exportacion.json"
TOKEN_FILE = SECRETS_DIR / "gateway_token.txt"
# Disco del contenedor (se borra al reiniciar el pod): marca de pip y sesión de procesos.
PIP_MARKER = Path.home() / ".frutinovelas_pip_ok"
SESSION_FILE = Path("/tmp/frutinovelas_session")

COMFY_REPO = "https://github.com/Comfy-Org/ComfyUI.git"
COMFY_TAG = "v0.40.0"
COMFY_COMMIT = "3541246a9c997f4b8c32f9f88f3c985d02021c79"
TEMPLATES_COMMIT = "3e89967349dd95fa68ce3b36966f41d642af8ea7"
CLOUDFLARED_VERSION = "2026.10.0"
COMFY_PORT = 8188
GATEWAY_PORT = 8189
LOCAL = f"http://127.0.0.1:{COMFY_PORT}"
GW = f"http://127.0.0.1:{GATEWAY_PORT}"
UA = f"FRUTINOVELAS-remote/{VERSION}"
H3_PROFILE_KEY = "h3_equilibrado_9x16"
UI_PATH = KIT_DIR / "workflows" / "H3_EQUILIBRADO_9x16_INICIO_FINAL.ui.json"
NOMBRES_QWEN = {
    "qwen2512_t2i": "QWEN_2512_T2I.api.json",
    "qwen_edit2511_fp8mixed": "QWEN_EDIT_2511.api.json",
    "qwen_edit2511_bf16": "QWEN_EDIT_2511.api.json",
}
LOADER_FIELD = {
    "diffusion_models": ("UNETLoader", "unet_name"),
    "text_encoders": ("CLIPLoader", "clip_name"),
    "vae": ("VAELoader", "vae_name"),
    "loras": ("LoraLoaderModelOnly", "lora_name"),
}

sys.path.insert(0, str(KIT_DIR / "scripts"))
sys.path.insert(0, str(KIT_DIR / "src"))
import validate_workflows as vw  # noqa: E402
from frutinovelas.services.voice_workflow import (  # noqa: E402
    VOICE_WORKFLOW, derive_voice_workflow, validate_voice_node_info, validate_voice_workflow,
)


# --------------------------------------------------------------------------- utilidades
def say(msg: str = "") -> None:
    print(msg, flush=True)


def ok(msg: str) -> None:
    say(f"✅ {msg}")


def warn(msg: str) -> None:
    say(f"⚠️  {msg}")


def fail(msg: str) -> None:
    say(f"❌ {msg}")
    raise SystemExit(1)


def titulo(msg: str) -> None:
    say(f"\n── {msg} " + "─" * max(0, 60 - len(msg)))


def run(cmd: str, cwd: Path | None = None) -> str:
    say(f"$ {cmd}")
    r = subprocess.run(cmd, shell=True, cwd=cwd, text=True, capture_output=True)
    if r.returncode != 0:
        say(r.stdout[-3000:])
        say(r.stderr[-3000:])
        fail(f"Falló: {cmd}")
    return r.stdout


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def load_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def ensure_dirs() -> None:
    for d in (DATA_DIR, API_DIR, LOG_DIR, SECRETS_DIR, TESTS_DIR, MODELS_DIR, DATA_DIR / "comfy_input",
              DATA_DIR / "comfy_output", DATA_DIR / "workflows" / "templates", DATA_DIR / "bin"):
        d.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS_DIR, 0o700)


def http_status(url: str, headers: dict | None = None, timeout: float = 5.0) -> int | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


def http_json(url: str, timeout: float = 60.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def tail(path: Path, n: int = 60) -> None:
    if path.exists():
        say("\n".join(path.read_text(errors="replace").splitlines()[-n:]))


def requests_mod():
    try:
        import requests

        return requests
    except ImportError:
        fail("Falta 'requests'. Ejecuta primero: fruti install")


# --------------------------------------------------------------------------- estado
DEFAULT_CFG = {
    "perfil_video": "h3_balanced_default",
    "voces_personajes": False,
    "qwen21": True,
    "qwen_t2i": False,
    "qwen_edit": "no",
    "acceso": "runpod_proxy" if os.environ.get("RUNPOD_POD_ID") else "quick",
    "verificar_sha256": True,
}


def cfg() -> dict:
    return {**DEFAULT_CFG, **(load_json(CONFIG_FILE, {}) or {})}


def aplicar_flags(a: argparse.Namespace) -> dict:
    c = cfg()
    if getattr(a, "perfil", None):
        c["perfil_video"] = a.perfil
    if getattr(a, "voces_personajes", None):
        c["voces_personajes"] = a.voces_personajes == "si"
    if getattr(a, "qwen21", None):
        c["qwen21"] = a.qwen21 == "si"
    if getattr(a, "qwen_t2i", None):
        c["qwen_t2i"] = a.qwen_t2i == "si"
    if getattr(a, "qwen_edit", None):
        c["qwen_edit"] = a.qwen_edit
    if getattr(a, "acceso", None):
        c["acceso"] = a.acceso
    if getattr(a, "sin_sha256", False):
        c["verificar_sha256"] = False
    ensure_dirs()
    save_json(CONFIG_FILE, c)
    return c


def estado(**cambios) -> dict:
    datos = load_json(STATE_FILE, {}) or {}
    if cambios:
        datos.update(cambios)
        save_json(STATE_FILE, datos)
    return datos


def session_id() -> str:
    if not SESSION_FILE.exists():
        SESSION_FILE.write_text(uuid.uuid4().hex)
    return SESSION_FILE.read_text().strip()


def procs() -> dict:
    """PIDs de esta sesión del contenedor; tras reiniciar el pod se descartan los viejos."""
    p = load_json(PIDS_FILE, {}) or {}
    if p.get("_session") != session_id():
        p = {"_session": session_id()}
        save_json(PIDS_FILE, p)
        if STATE_FILE.exists():
            estado(public_url=None, gateway_listen=None)
    return p


def guardar_proc(nombre: str, pid: int | None) -> None:
    p = procs()
    if pid is None:
        p.pop(nombre, None)
    else:
        p[nombre] = pid
    save_json(PIDS_FILE, p)


def vivo(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def lanzar(nombre: str, cmd: list[str], log: Path, cwd: Path | None = None, env: dict | None = None) -> subprocess.Popen:
    """Proceso en su propia sesión: sobrevive al cierre de la terminal SSH."""
    with open(log, "ab") as fh:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,  # noqa: S603 - argv construido por el kit, sin shell
                             start_new_session=True)
    guardar_proc(nombre, p.pid)
    return p


def detener(nombre: str) -> bool:
    pid = procs().get(nombre)
    if not (pid and vivo(pid)):
        guardar_proc(nombre, None)
        return False
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    for _ in range(30):
        if not vivo(pid):
            break
        time.sleep(0.5)
    else:
        try:
            os.killpg(int(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    guardar_proc(nombre, None)
    return True


# --------------------------------------------------------------------------- kit
def manifest() -> dict:
    return load_json(KIT_DIR / "config" / "models_manifest.lock.json")


def profile() -> dict:
    return vw.load_profile(KIT_DIR / "config" / "workflow_profiles.json", H3_PROFILE_KEY)


def perfiles_activos(c: dict) -> list[str]:
    out = [c["perfil_video"]]
    if c.get("voces_personajes", False):
        out.append("h3_voice_references")
    if c.get("qwen21", True):
        out.append("qwen21_bf16")
    if c["qwen_t2i"]:
        out.append("qwen2512_t2i")
    if c["qwen_edit"] != "no":
        out.append({"fp8mixed": "qwen_edit2511_fp8mixed", "bf16": "qwen_edit2511_bf16"}[c["qwen_edit"]])
    return out


def componentes(c: dict) -> list[str]:
    m = manifest()
    vistos: list[str] = []
    for perfil in perfiles_activos(c):
        for comp in m["profiles"][perfil]["components"]:
            if comp not in vistos:
                vistos.append(comp)
    return vistos


def ruta_local(comp: dict) -> Path:
    return MODELS_DIR / "hf" / comp["repo_id"].replace("/", "__") / comp["path"]


def verificar_kit() -> None:
    for p in (UI_PATH, KIT_DIR / "config" / "models_manifest.lock.json", KIT_DIR / "config" / "workflow_profiles.json",
              KIT_DIR / "scripts" / "export_workflow_api.py", KIT_DIR / "scripts" / "comfy_gateway.py",
              KIT_DIR / "src" / "frutinovelas" / "services" / "voice_workflow.py"):
        if not p.exists():
            fail(f"Kit incompleto: falta {p}")
    sha = hashlib.sha256(UI_PATH.read_bytes()).hexdigest()
    if sha != profile()["workflow_ui_sha256"]:
        fail(f"El flujo H3 del kit no coincide con el original (SHA-256 {sha[:12]}…).")


def instalar_atajo() -> None:
    destino = Path("/usr/local/bin/fruti")
    contenido = f'#!/usr/bin/env bash\nexec "{sys.executable}" "{Path(__file__).resolve()}" "$@"\n'
    try:
        if not destino.exists() or destino.read_text() != contenido:
            destino.write_text(contenido)
            destino.chmod(0o755)
    except OSError:
        pass


# --------------------------------------------------------------------------- doctor
def cmd_doctor(a=None) -> None:
    titulo("Diagnóstico")
    c = cfg()
    ensure_dirs()
    gpu = sh("nvidia-smi --query-gpu=name,memory.total,compute_cap,driver_version --format=csv,noheader,nounits")
    if not gpu:
        fail("No hay GPU visible (nvidia-smi). Crea el pod con GPU.")
    name, vram_mb, cc, drv = [x.strip() for x in gpu.splitlines()[0].split(",")]
    vram = float(vram_mb) / 1024
    ram = int(Path("/proc/meminfo").read_text().split("MemTotal:")[1].split()[0]) / 1024 / 1024
    disk = shutil.disk_usage(MODELS_DIR)
    torch_info = sh(f'{sys.executable} -c "import torch;print(torch.__version__, \'CUDA\', torch.version.cuda, '
                    f'torch.cuda.is_available())"') or "no disponible"
    m = manifest()
    pendiente = sum(m["components"][k]["size"] for k in componentes(c)
                    if not (ruta_local(m["components"][k]).exists()
                            and ruta_local(m["components"][k]).stat().st_size == m["components"][k]["size"]))
    say(f"GPU      {name} · {vram:.1f} GB VRAM · compute {cc} · driver {drv}")
    say(f"RAM      {ram:.1f} GB")
    say(f"Disco    {disk.free / 1e9:.1f} GB libres en {MODELS_DIR}")
    say(f"Python   {sys.version.split()[0]} ({sys.executable})")
    say(f"PyTorch  {torch_info}")
    say(f"FFmpeg   {'sí' if shutil.which('ffprobe') else 'no (se instala con fruti install)'}")
    say(f"Pod      {os.environ.get('RUNPOD_POD_ID') or '(no es RunPod)'}")
    say(f"Perfiles {', '.join(perfiles_activos(c))} · acceso {c['acceso']}")
    say(f"Descarga pendiente: {pendiente / 1e9:.1f} GB")
    avisos = []
    if vram < 40:
        avisos.append("VRAM < 40 GB: H3 puede fallar por memoria o ir muy lento (requisito no verificado).")
    if ram < 50:
        avisos.append("RAM < 50 GB: la carga de modelos puede fallar.")
    if disk.free < pendiente + 15e9:
        avisos.append("Disco insuficiente para los modelos seleccionados (+15 GB de margen).")
    try:
        if float(cc) < 10.0:
            avisos.append("GPU anterior a Blackwell: el encoder NVFP4 AWQ puede ir más lento o no ser compatible (no verificado).")
    except ValueError:
        pass
    if c["acceso"] == "runpod_proxy" and not os.environ.get("RUNPOD_POD_ID"):
        avisos.append("acceso=runpod_proxy pero RUNPOD_POD_ID no existe: usa --acceso quick.")
    for x in avisos:
        warn(x)
    estado(diagnostico={"gpu": name, "vram_gb": round(vram, 1), "compute_cap": cc, "ram_gb": round(ram, 1),
                        "disco_libre_gb": round(disk.free / 1e9, 1), "torch": torch_info})
    ok("Diagnóstico terminado" + (" con avisos" if avisos else ""))


# --------------------------------------------------------------------------- install
def cmd_install(a=None) -> None:
    titulo("Instalación de ComfyUI (versión fijada)")
    ensure_dirs()
    verificar_kit()
    if not (COMFY_DIR / ".git").is_dir():
        COMFY_DIR.mkdir(parents=True, exist_ok=True)
        run(f"git init -q {COMFY_DIR}")
        run(f"git -C {COMFY_DIR} remote add origin {COMFY_REPO}")
    if sh(f"git -C {COMFY_DIR} rev-parse HEAD") != COMFY_COMMIT:
        run(f"git -C {COMFY_DIR} fetch -q --depth 1 origin {COMFY_COMMIT}")
        run(f"git -C {COMFY_DIR} checkout -q --force {COMFY_COMMIT}")
    say(f"ComfyUI {COMFY_TAG} · commit {sh(f'git -C {COMFY_DIR} rev-parse HEAD')}")
    if not PIP_MARKER.exists() or PIP_MARKER.read_text().strip() != COMFY_COMMIT:
        run(f"{sys.executable} -m pip install -q -r requirements.txt", cwd=COMFY_DIR)
        run(f'{sys.executable} -m pip install -q -U "huggingface_hub[hf_xet]" playwright pillow requests aiohttp')
        run(f"{sys.executable} -m playwright install --with-deps chromium")
        PIP_MARKER.write_text(COMFY_COMMIT)
    else:
        say("Dependencias ya instaladas en este contenedor.")
    if not shutil.which("ffprobe"):
        run("apt-get update -qq && apt-get install -y -qq ffmpeg")
    import importlib.metadata as md

    for paquete in ("torch", "comfyui-frontend-package", "comfy-kitchen", "aiohttp", "huggingface_hub", "playwright"):
        try:
            say(f"  {paquete} {md.version(paquete)}")
        except md.PackageNotFoundError:
            say(f"  {paquete} (no instalado)")
    instalar_atajo()
    estado(comfyui_commit=COMFY_COMMIT)
    ok("Instalación lista (sin SageAttention ni xformers)")


# --------------------------------------------------------------------------- models
def sha256_archivo(path: Path, size: int) -> str:
    h = hashlib.sha256()
    leido, siguiente = 0, 0.1
    with open(path, "rb") as f:
        while bloque := f.read(16 * 1024 * 1024):
            h.update(bloque)
            leido += len(bloque)
            if leido / size >= siguiente:
                print(f"    sha256 {leido / size:4.0%}", end="\r", flush=True)
                siguiente += 0.1
    print(" " * 30, end="\r")
    return h.hexdigest()


def verificar_modelo(comp: dict, path: Path, con_sha: bool) -> tuple[bool, str]:
    st = path.stat()
    if st.st_size != comp["size"]:
        return False, f"tamaño {st.st_size} ≠ {comp['size']}"
    if not con_sha:
        return True, "tamaño correcto (SHA-256 desactivado)"
    marca = path.with_name(path.name + ".sha256ok")
    clave = f"{st.st_size}:{int(st.st_mtime)}:{comp['sha256']}"
    if marca.exists() and marca.read_text() == clave:
        return True, "SHA-256 correcto (ya verificado)"
    digest = sha256_archivo(path, comp["size"])
    if digest != comp["sha256"]:
        return False, f"SHA-256 {digest} ≠ {comp['sha256']}"
    marca.write_text(clave)
    return True, "SHA-256 correcto"


def cmd_models(a=None) -> None:
    titulo("Modelos (revisiones fijadas, verificación de tamaño y SHA-256)")
    c = cfg()
    ensure_dirs()
    m = manifest()
    os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        fail("Falta huggingface_hub. Ejecuta primero: fruti install")
    token = (os.environ.get("HF_TOKEN") or "").strip() or None
    keys = componentes(c)
    falta = sum(m["components"][k]["size"] for k in keys if not ruta_local(m["components"][k]).exists())
    if shutil.disk_usage(MODELS_DIR).free < falta + 5e9:
        fail(f"No hay espacio: faltan {falta / 1e9:.1f} GB. Amplía el volumen o desactiva perfiles opcionales.")
    for k in keys:
        comp = m["components"][k]
        path = ruta_local(comp)
        nombre = Path(comp["path"]).name
        say(f"• {nombre} ({comp['size'] / 1e9:.2f} GB)")
        motivo = ""
        if path.exists():
            good, motivo = verificar_modelo(comp, path, c["verificar_sha256"])
            if not good:
                warn(f"{motivo} → se vuelve a descargar")
                path.unlink()
        if not path.exists():
            t0 = time.time()
            hf_hub_download(repo_id=comp["repo_id"], filename=comp["path"], revision=m["repos"][comp["repo_id"]],
                            local_dir=MODELS_DIR / "hf" / comp["repo_id"].replace("/", "__"), token=token)
            say(f"    descargado en {time.time() - t0:.0f} s")
            good, motivo = verificar_modelo(comp, path, c["verificar_sha256"])
            if not good:
                path.unlink(missing_ok=True)
                fail(f"{nombre}: {motivo}")
        say(f"    ✓ {motivo}")
        enlace = COMFY_DIR / "models" / comp["dest"] / nombre
        enlace.parent.mkdir(parents=True, exist_ok=True)
        if enlace.is_symlink() and enlace.resolve() != path.resolve():
            enlace.unlink()
        if not enlace.exists() and not enlace.is_symlink():
            enlace.symlink_to(path)
    estado(modelos={k: m["components"][k]["sha256"] for k in keys})
    ok(f"Modelos listos y enlazados en {COMFY_DIR / 'models'}")


# --------------------------------------------------------------------------- start
def comfy_vivo() -> bool:
    return http_status(LOCAL + "/system_stats", timeout=3) == 200


def gw_vivo() -> bool:
    return http_status(GW + "/healthz", timeout=3) == 200


def arrancar_comfy() -> tuple[dict, dict]:
    titulo("ComfyUI (127.0.0.1:8188, no expuesto)")
    if not (COMFY_DIR / "main.py").exists():
        fail("ComfyUI no está instalado. Ejecuta: fruti install")
    if not comfy_vivo():
        p = lanzar("comfyui", [sys.executable, "main.py", "--listen", "127.0.0.1", "--port", str(COMFY_PORT),
                               "--disable-auto-launch", "--output-directory", str(DATA_DIR / "comfy_output"),
                               "--input-directory", str(DATA_DIR / "comfy_input")],
                   LOG_DIR / "comfyui.log", cwd=COMFY_DIR)
        t0 = time.time()
        while not comfy_vivo():
            if p.poll() is not None:
                tail(LOG_DIR / "comfyui.log")
                fail("ComfyUI se cerró al arrancar (log arriba).")
            if time.time() - t0 > 900:
                fail("ComfyUI no respondió en 15 minutos. Revisa: fruti logs comfyui")
            time.sleep(3)
        say(f"Arrancado en {time.time() - t0:.0f} s")
    else:
        say("Ya estaba en marcha")
    stats = http_json(LOCAL + "/system_stats", 30)
    object_info = http_json(LOCAL + "/object_info", 300)
    save_json(DATA_DIR / "object_info.json", object_info)
    say(f"Versión ComfyUI: {stats.get('system', {}).get('comfyui_version')}")
    ui = load_json(UI_PATH)
    faltan = sorted({n["type"] for n in ui["nodes"] if n["type"] not in ("Note", "MarkdownNote")} - set(object_info))
    if faltan:
        fail(f"Nodos ausentes en este ComfyUI: {faltan}")
    m = manifest()
    sin_ver = []
    for k in componentes(cfg()):
        comp = m["components"][k]
        clase, campo = LOADER_FIELD[comp["dest"]]
        spec = (object_info.get(clase, {}).get("input", {}).get("required", {}) or {}).get(campo)
        if Path(comp["path"]).name not in (vw.combo_options(spec) or []):
            sin_ver.append(f"{clase}.{campo}: {Path(comp['path']).name}")
    if sin_ver:
        fail("ComfyUI no ve estos modelos: " + "; ".join(sin_ver) + ". Ejecuta: fruti models")
    ok("Nodos del flujo H3 y modelos presentes")
    return stats, object_info


def exportar(ui_path: Path, out_path: Path) -> dict:
    r = subprocess.run([sys.executable, str(KIT_DIR / "scripts" / "export_workflow_api.py"), "--comfy", LOCAL,  # noqa: S603 - script local y argv, sin shell
                        "--ui", str(ui_path), "--out", str(out_path)], capture_output=True, text=True)
    say("  " + r.stdout.strip())
    if r.returncode != 0:
        say(r.stderr[-4000:])
        fail(f"No se pudo exportar {ui_path.name}")
    return load_json(out_path)


def exportar_y_validar(object_info: dict, forzar: bool) -> dict:
    titulo("Exportación API automática y validación")
    c = cfg()
    m = manifest()
    prof = profile()
    clave = {"commit": COMFY_COMMIT, "ui_sha256": prof["workflow_ui_sha256"], "perfiles": perfiles_activos(c),
             "kit": VERSION}
    previo = load_json(INFORME_FILE)
    esperados = set(prof["workflow_api_files"].values()) | {
        NOMBRES_QWEN[p] for p in perfiles_activos(c) if p in NOMBRES_QWEN
    }
    if c.get("qwen21", True):
        esperados.update({"QWEN_21_T2I.api.json", "QWEN_21_EDIT.api.json"})
    if c.get("voces_personajes", False):
        esperados.add(VOICE_WORKFLOW)
    if not forzar and cache_exportacion_valida(previo, clave, esperados, object_info):
        say("Flujos API ya exportados para esta versión y perfiles (usa --reexportar para repetir).")
        return previo

    informe = {"generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "clave": clave, "flujos": {}}
    ui = load_json(UI_PATH)
    crudo = exportar(UI_PATH, DATA_DIR / "workflows" / "H3_export_crudo.api.json")
    say(f"  Nodos de interfaz que no van a la API (las notas son normales): {vw.ui_nodes_missing_in_api(ui, crudo) or 'ninguno'}")
    say(f"  Nodo 28 (duración): {crudo.get('28', {}).get('inputs')}")
    errores_totales: list[str] = []
    overrides = m["profiles"][c["perfil_video"]]["loader_overrides"]
    for modo, grafo in (("fl2va", crudo), ("i2va", vw.derive_i2va(crudo, prof))):
        r1 = vw.check_profile(grafo, prof, modo)
        final, cambios = vw.apply_loader_overrides(grafo, overrides)
        r2 = vw.validate_api_graph(final, object_info)
        errores = r1["errors"] + r2["errors"]
        avisos = r1["warnings"] + r2["warnings"]
        for x in avisos:
            say(f"  [{modo}] aviso: {x}")
        for x in errores:
            say(f"  [{modo}] ERROR: {x}")
        for x in cambios:
            say(f"  [{modo}] perfil {c['perfil_video']}: {x}")
        nombre = prof["workflow_api_files"][modo]
        if not errores:
            destino = API_DIR / nombre
            save_json(destino, final)
            informe["flujos"][nombre] = {"modo": modo, "nodos": len(final), "cambios_perfil": cambios, "avisos": avisos,
                                         "sha256": hashlib.sha256(destino.read_bytes()).hexdigest()}
            ok(f"{nombre} ({len(final)} nodos)")
        errores_totales += errores

    if c.get("voces_personajes", False):
        # Derivar siempre de FL2VA completo; las muestras reales se conectan en Studio.
        base_voz, cambios = vw.apply_loader_overrides(crudo, overrides)
        unet = Path(m["components"]["h3_diffusion_ref2va_pruned_int8"]["path"]).name
        try:
            validate_voice_node_info(object_info)
            voz = derive_voice_workflow(base_voz, unet)
            rv = vw.validate_api_graph(voz, object_info)
        except ValueError as exc:
            rv = {"errors": [str(exc)], "warnings": []}
        for x in rv["warnings"]:
            say(f"  [voces] aviso: {x}")
        for x in rv["errors"]:
            say(f"  [voces] ERROR: {x}")
        if not rv["errors"]:
            destino = API_DIR / VOICE_WORKFLOW
            save_json(destino, voz)
            informe["flujos"][VOICE_WORKFLOW] = {
                "modo": "ref2va", "perfil": "h3_voice_references", "nodos": len(voz),
                "cambios_perfil": cambios, "avisos": rv["warnings"],
                "sha256": hashlib.sha256(destino.read_bytes()).hexdigest(),
            }
            ok(f"{VOICE_WORKFLOW} ({len(voz)} nodos; muestras por personaje desde Studio)")
        errores_totales += rv["errors"]

    if c.get("qwen21", True):
        from frutinovelas.services.qwen21_workflow import WORKFLOWS, build_graph

        api_q = build_graph()
        rq = vw.validate_api_graph(api_q, object_info)
        errores_totales += rq["errors"]
        for error in rq["errors"]:
            say(f"  [qwen21_bf16] ERROR: {error}")
        if not rq["errors"]:
            for filename in WORKFLOWS:
                destino = API_DIR / filename
                save_json(destino, api_q)
                informe["flujos"][filename] = {"perfil": "qwen21_bf16", "nodos": len(api_q),
                    "cambios_perfil": [], "avisos": rq["warnings"],
                    "sha256": hashlib.sha256(destino.read_bytes()).hexdigest()}
                ok(f"{filename} (BF16, 1152×2048, 40 pasos)")

    for perfil in perfiles_activos(c):
        plantilla = m["profiles"][perfil].get("template")
        if not plantilla:
            continue
        local = DATA_DIR / "workflows" / "templates" / Path(plantilla).name
        if not local.exists():
            url = f"https://raw.githubusercontent.com/Comfy-Org/workflow_templates/{TEMPLATES_COMMIT}/{plantilla}"
            r = requests_mod().get(url, timeout=60, headers={"User-Agent": UA})
            r.raise_for_status()
            local.write_bytes(r.content)
        api_q = exportar(local, DATA_DIR / "workflows" / (local.stem + ".api.json"))
        api_q, cambios = vw.apply_loader_overrides(api_q, m["profiles"][perfil]["loader_overrides"])
        rq = vw.validate_api_graph(api_q, object_info)
        for x in rq["warnings"]:
            say(f"  [{perfil}] aviso: {x}")
        for x in rq["errors"]:
            say(f"  [{perfil}] ERROR: {x}")
        if not rq["errors"]:
            destino = API_DIR / NOMBRES_QWEN[perfil]
            save_json(destino, api_q)
            informe["flujos"][destino.name] = {"perfil": perfil, "nodos": len(api_q), "cambios_perfil": cambios,
                                               "avisos": rq["warnings"],
                                               "sha256": hashlib.sha256(destino.read_bytes()).hexdigest()}
            ok(f"{destino.name} ({len(api_q)} nodos)")
        errores_totales += rq["errors"]

    if errores_totales:
        informe["clave"] = None  # obliga a repetir la exportación la próxima vez
    save_json(INFORME_FILE, informe)
    if errores_totales:
        fail(f"{len(errores_totales)} error(es) de validación (detalle arriba). Esos flujos no se publican.")
    return informe


def cache_exportacion_valida(informe: dict | None, clave: dict, esperados: set[str], object_info: dict) -> bool:
    """Reutilizar solo archivos íntegros y compatibles con el servidor de ahora."""
    if (not isinstance(informe, dict) or informe.get("clave") != clave
            or not isinstance(informe.get("flujos"), dict) or set(informe["flujos"]) != esperados):
        return False
    for nombre, datos in informe["flujos"].items():
        path = API_DIR / nombre
        try:
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != datos.get("sha256"):
                return False
            graph = json.loads(body)
            if nombre == VOICE_WORKFLOW:
                validate_voice_node_info(object_info)
                validate_voice_workflow(graph)
            if vw.validate_api_graph(graph, object_info)["errors"]:
                return False
        except (OSError, ValueError, TypeError, AttributeError):
            return False
    return True


def obtener_token() -> tuple[str, str]:
    tok = (os.environ.get("FRUTI_GATEWAY_TOKEN") or "").strip()
    origen = "variable FRUTI_GATEWAY_TOKEN"
    if not tok and TOKEN_FILE.exists():
        tok, origen = TOKEN_FILE.read_text().strip(), str(TOKEN_FILE)
    if not tok:
        tok, origen = secrets.token_urlsafe(32), "generado ahora"
    if len(tok) < 16:
        fail("El token del gateway debe tener al menos 16 caracteres.")
    if not TOKEN_FILE.exists() or TOKEN_FILE.read_text().strip() != tok:
        TOKEN_FILE.write_text(tok)
    os.chmod(TOKEN_FILE, 0o600)
    return tok, origen


def escribir_identidad(stats: dict, informe: dict) -> dict:
    c = cfg()
    m = manifest()
    previo = load_json(IDENTITY_FILE, {}) or {}
    ident = {
        "servicio": "frutinovelas-comfyui-remote",
        "plataforma": "runpod" if os.environ.get("RUNPOD_POD_ID") else "linux",
        "kit_version": VERSION,
        "comfyui_version": stats.get("system", {}).get("comfyui_version"),
        "comfyui_commit": COMFY_COMMIT,
        "python": stats.get("system", {}).get("python_version"),
        "pytorch": stats.get("system", {}).get("pytorch_version"),
        "gpu": [{"nombre": d.get("name"), "vram_total": d.get("vram_total")} for d in stats.get("devices", [])],
        "perfil_video": c["perfil_video"],
        "perfiles": perfiles_activos(c),
        "modelos": {k: {"archivo": Path(m["components"][k]["path"]).name, "sha256": m["components"][k]["sha256"]}
                    for k in componentes(c)},
        "workflows": {n: d["sha256"] for n, d in informe["flujos"].items()},
        "workflow_ui_sha256": profile()["workflow_ui_sha256"],
        "estado_compatibilidad": previo.get("estado_compatibilidad", "pendiente_prueba_real"),
        "pruebas": previo.get("pruebas", {}),
        "actualizado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    # Una prueba de otros pesos o flujos no certifica la configuración actual.
    if any(previo.get(k) != ident[k] for k in ("comfyui_commit", "perfiles", "workflows", "modelos")):
        ident["estado_compatibilidad"] = "pendiente_prueba_real"
        ident["pruebas"] = {}
    save_json(IDENTITY_FILE, ident)
    return ident


def registrar_prueba(nombre: str, resultado: dict) -> None:
    ident = load_json(IDENTITY_FILE, {}) or {}
    ident.setdefault("pruebas", {})[nombre] = resultado
    ident["estado_compatibilidad"] = (
        "prueba_real_ok" if all(v.get("ok") for v in ident["pruebas"].values()) else "prueba_real_fallida"
    )
    save_json(IDENTITY_FILE, ident)


def arrancar_gateway(token: str, acceso: str) -> None:
    titulo("Gateway con token (puerto 8189)")
    listen = "0.0.0.0" if acceso == "runpod_proxy" else "127.0.0.1"
    if gw_vivo() and (estado().get("gateway_listen") != listen or
                     http_status(GW + "/frutinovelas/identity", {"Authorization": f"Bearer {token}"}) == 401):
        detener("gateway")
        time.sleep(1)
    if not gw_vivo():
        env = dict(os.environ, FRUTI_GATEWAY_TOKEN_FILE=str(TOKEN_FILE))
        env.pop("FRUTI_GATEWAY_TOKEN", None)
        p = lanzar("gateway", [sys.executable, str(KIT_DIR / "scripts" / "comfy_gateway.py"), "--listen", listen,
                               "--port", str(GATEWAY_PORT), "--upstream", LOCAL, "--workflows-dir", str(API_DIR),
                               "--identity-file", str(IDENTITY_FILE)], LOG_DIR / "gateway.log", env=env)
        estado(gateway_listen=listen)
        for _ in range(40):
            if gw_vivo():
                break
            if p.poll() is not None:
                tail(LOG_DIR / "gateway.log")
                fail("El gateway se cerró (log arriba).")
            time.sleep(0.5)
    if http_status(GW + "/system_stats") != 401:
        fail("El gateway no rechaza peticiones sin token.")
    if http_status(GW + "/system_stats", {"Authorization": f"Bearer {token}"}) != 200:
        fail("El gateway no reenvía a ComfyUI.")
    ok(f"Gateway en {listen}:{GATEWAY_PORT} (sin token → 401, con token → 200)")


def acceso_publico(token: str, acceso: str) -> str | None:
    titulo(f"Acceso público ({acceso})")
    url = None
    if acceso == "ninguno":
        say("Sin acceso público: solo accesible dentro de la máquina.")
        estado(public_url=None)
        return None
    if acceso == "runpod_proxy":
        pod = os.environ.get("RUNPOD_POD_ID")
        if not pod:
            fail("RUNPOD_POD_ID no existe: no estás en RunPod. Usa --acceso quick.")
        url = f"https://{pod}-{GATEWAY_PORT}.proxy.runpod.net"
    else:
        cf = DATA_DIR / "bin" / "cloudflared"
        if not cf.exists():
            urllib.request.urlretrieve(
                f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/cloudflared-linux-amd64", cf)
            cf.chmod(0o755)
        previo = estado().get("public_url")
        pid = procs().get("cloudflared")
        if pid and vivo(pid) and previo:
            url = previo
        elif acceso == "quick":
            log = LOG_DIR / "cloudflared.log"
            log.write_text("")
            lanzar("cloudflared", [str(cf), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{GATEWAY_PORT}"], log)
            for _ in range(90):
                mt = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", log.read_text(errors="replace"))
                if mt:
                    url = mt.group(0)
                    break
                time.sleep(1)
            if not url:
                tail(log)
                fail("No se obtuvo la URL del Quick Tunnel (log arriba).")
        else:
            cf_token, host = os.environ.get("CF_TUNNEL_TOKEN"), os.environ.get("CF_TUNNEL_HOSTNAME")
            if not (cf_token and host):
                fail("Para --acceso named define CF_TUNNEL_TOKEN y CF_TUNNEL_HOSTNAME.")
            lanzar("cloudflared", [str(cf), "tunnel", "--no-autoupdate", "run"], LOG_DIR / "cloudflared.log",
                   env=dict(os.environ, TUNNEL_TOKEN=cf_token))
            url = "https://" + host.removeprefix("https://").rstrip("/")
    estado(public_url=url)
    for _ in range(60):
        if http_status(url + "/healthz", timeout=10) == 200:
            break
        time.sleep(2)
    else:
        if acceso == "runpod_proxy":
            fail(f"{url} no responde. En RunPod: Edit Pod → Expose HTTP Ports → añade {GATEWAY_PORT}. "
                 "El pod se reinicia; después ejecuta: fruti start")
        fail(f"{url} no responde. Revisa: fruti logs cloudflared")
    if http_status(url + "/system_stats", timeout=30) != 401:
        detener("cloudflared")
        fail("⚠️ El acceso público NO exige token. Revisa la configuración antes de continuar.")
    if http_status(url + "/system_stats", {"Authorization": f"Bearer {token}"}, timeout=30) != 200:
        fail("El acceso público no llega a ComfyUI con el token.")
    ok("Acceso público verificado (sin token → 401, con token → 200)")
    return url


def imprimir_conexion(url: str | None, token: str, informe: dict) -> None:
    conexion = {
        "formato": "frutinovelas.conexion_comfyui",
        "version": 1,
        "comfyui_url": url,
        "autenticacion": "Authorization: Bearer <token>",
        "token": "NO INCLUIDO: fruti token --mostrar",
        "acceso": cfg()["acceso"],
        "flujos": sorted(informe["flujos"]),
        "creado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_json(DATA_DIR / "conexion_frutinovelas.json", conexion)
    say("\n" + "═" * 72)
    say("  FRUTINOVELAS · datos de conexión para el programa")
    say(f"  URL:    {url or '(sin acceso público)'}")
    say(f"  Token:  …{token[-4:]}   (verlo completo: fruti token --mostrar)")
    say(f"  Flujos: {', '.join(conexion['flujos'])}")
    say("═" * 72)
    say("En tu PC (PowerShell, dentro de frutinovelas-studio):")
    say('  $env:FRUTI_COMFY_TOKEN = "PEGA_EL_TOKEN"')
    say(f"  uv run python scripts/check_colab_connection.py --url {url or 'https://...'}")
    say("Primera prueba real en el pod:  fruti test --modo i2va --segundos 5")


def cmd_start(a) -> None:
    c = aplicar_flags(a)
    ensure_dirs()
    verificar_kit()
    if not PIP_MARKER.exists() or PIP_MARKER.read_text().strip() != COMFY_COMMIT:
        say("Dependencias ausentes en este contenedor (¿pod reanudado?): se reinstalan.")
        cmd_install()
    instalar_atajo()
    stats, object_info = arrancar_comfy()
    informe = exportar_y_validar(object_info, getattr(a, "reexportar", False))
    token, origen = obtener_token()
    say(f"Token del gateway: {origen} · termina en …{token[-4:]}")
    escribir_identidad(stats, informe)
    arrancar_gateway(token, c["acceso"])
    url = acceso_publico(token, c["acceso"])
    imprimir_conexion(url, token, informe)


def cmd_setup(a) -> None:
    aplicar_flags(a)
    cmd_doctor()
    cmd_install()
    cmd_models()
    cmd_start(a)


# --------------------------------------------------------------------------- status / token / logs / stop
def cmd_status(a) -> None:
    titulo("Estado")
    c = cfg()
    p = procs()
    for nombre in ("comfyui", "gateway", "cloudflared"):
        pid = p.get(nombre)
        say(f"  {nombre:12} {'en marcha (pid ' + str(pid) + ')' if pid and vivo(pid) else 'parado'}")
    say(f"  ComfyUI local  {'responde' if comfy_vivo() else 'no responde'}")
    say(f"  Gateway local  {'responde' if gw_vivo() else 'no responde'}")
    url = estado().get("public_url")
    if url:
        st = http_status(url + "/healthz", timeout=10)
        say(f"  Público        {url} → {'OK' if st == 200 else st}")
    if comfy_vivo():
        q = http_json(LOCAL + "/queue", 10)
        say(f"  Cola           {len(q.get('queue_running', []))} en curso · {len(q.get('queue_pending', []))} pendientes")
    gpu = sh("nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader")
    if gpu:
        say(f"  GPU            {gpu}")
    ident = load_json(IDENTITY_FILE, {}) or {}
    say(f"  Perfiles       {', '.join(perfiles_activos(c))} · acceso {c['acceso']}")
    say(f"  Compatibilidad {ident.get('estado_compatibilidad', '¿?')}")
    for nombre, res in (ident.get("pruebas") or {}).items():
        say(f"    prueba {nombre}: {'OK' if res.get('ok') else 'FALLÓ'} · {res}")


def cmd_token(a) -> None:
    if not TOKEN_FILE.exists():
        fail("Aún no hay token. Ejecuta: fruti start")
    tok = TOKEN_FILE.read_text().strip()
    if a.mostrar:
        say(tok)
        say("\n⚠️ No lo compartas. Puedes limpiar la pantalla con: clear")
    else:
        say(f"Token guardado en {TOKEN_FILE} (termina en …{tok[-4:]}). Para verlo: fruti token --mostrar")
    if a.regenerar:
        TOKEN_FILE.write_text(secrets.token_urlsafe(32))
        detener("gateway")
        ok("Token regenerado. Ejecuta 'fruti start' y actualiza el token en el programa.")


def cmd_logs(a) -> None:
    path = LOG_DIR / f"{a.servicio}.log"
    if not path.exists():
        fail(f"No hay log de {a.servicio} todavía.")
    if a.f:
        os.execvp("tail", ["tail", "-n", str(a.n), "-f", str(path)])
    tail(path, a.n)


def cmd_stop(a) -> None:
    titulo("Deteniendo procesos")
    for nombre in ("cloudflared", "gateway", "comfyui"):
        say(f"  {nombre}: {'detenido' if detener(nombre) else 'no estaba en marcha'}")
    estado(public_url=None, gateway_listen=None)
    ok("Procesos detenidos. Para no pagar GPU: detén el pod en RunPod (el volumen sigue cobrando).")


# --------------------------------------------------------------------------- test
def cmd_test(a) -> None:
    requests = requests_mod()
    from PIL import Image, ImageDraw

    if not TOKEN_FILE.exists() or not gw_vivo():
        fail("El servicio no está en marcha. Ejecuta: fruti start")
    auth = {"Authorization": f"Bearer {TOKEN_FILE.read_text().strip()}", "User-Agent": UA}
    prof = profile()

    def imagen(path: Path, c1, c2, texto):
        w, h = 576, 1024
        img = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(img)
        for y in range(h):
            t = y / (h - 1)
            d.line([(0, y), (w, y)], fill=tuple(int(x + (z - x) * t) for x, z in zip(c1, c2, strict=True)))
        d.ellipse([w // 2 - 120, h // 2 - 120, w // 2 + 120, h // 2 + 120], fill=(230, 40, 70))
        d.text((40, 60), texto, fill=(255, 255, 255))
        img.save(path)
        return path

    def subir(path: Path) -> str:
        with open(path, "rb") as f:
            r = requests.post(GW + "/upload/image", headers=auth, files={"image": (path.name, f, "image/png")},
                              data={"type": "input", "overwrite": "true"}, timeout=120)
        r.raise_for_status()
        j = r.json()
        return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]

    def encolar(grafo: dict) -> str:
        pid = str(uuid.uuid4())
        r = requests.post(GW + "/prompt", headers=auth, timeout=120,
                          json={"prompt": grafo, "prompt_id": pid, "client_id": "frutinovelas-remote"})
        if r.status_code != 200 or r.json().get("node_errors"):
            say(r.text[:4000])
            fail("ComfyUI rechazó el trabajo")
        return pid

    def esperar(pid: str) -> dict:
        t0 = time.time()
        while time.time() - t0 < 3 * 3600:
            h = requests.get(f"{GW}/history/{pid}", headers=auth, timeout=60).json()
            st = h.get(pid, {}).get("status", {})
            if st.get("completed") or st.get("status_str") in ("success", "error"):
                say(f"\n  terminado en {time.time() - t0:.0f} s · {st.get('status_str')}")
                if st.get("status_str") != "success":
                    for msg in st.get("messages", []):
                        say(f"    {msg}")
                    fail("El trabajo terminó con error (más detalle: fruti logs comfyui)")
                return h[pid]
            print(f"  generando… {time.time() - t0:.0f} s", end="\r", flush=True)
            time.sleep(10)
        fail("La prueba superó el tiempo límite")

    def descargar(entrada: dict) -> list[Path]:
        rutas = []
        for salida in entrada.get("outputs", {}).values():
            for valor in salida.values():
                for item in valor if isinstance(valor, list) else []:
                    if isinstance(item, dict) and item.get("filename"):
                        r = requests.get(GW + "/view", headers=auth, timeout=600, params={
                            "filename": item["filename"], "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output")})
                        r.raise_for_status()
                        destino = TESTS_DIR / item["filename"]
                        destino.write_bytes(r.content)
                        rutas.append(destino)
        return rutas

    modos = ["i2va", "fl2va"] if a.modo == "ambos" else ([] if a.modo == "ninguno" else [a.modo])
    for modo in modos:
        frames, seg = vw.quantize_frames(a.segundos, prof["duration_rule"])
        titulo(f"Prueba H3 {modo}: {a.segundos} s → {frames} frames ({seg:.3f} s reales)")
        base = load_json(API_DIR / prof["workflow_api_files"][modo])
        if base is None:
            fail(f"No existe el flujo {prof['workflow_api_files'][modo]}. Ejecuta: fruti start")
        valores = {"start_image": subir(imagen(TESTS_DIR / "inicio.png", (250, 170, 60), (120, 40, 90), "INICIO")),
                   "positive_prompt": a.prompt, "seed": a.semilla, "duration": float(a.segundos),
                   "filename_prefix": f"video/FRUTINOVELAS_PRUEBA_{modo.upper()}"}
        if modo == "fl2va":
            valores["end_image"] = subir(imagen(TESTS_DIR / "final.png", (60, 40, 140), (20, 160, 150), "FINAL"))
        t0 = time.time()
        salidas = descargar(esperar(encolar(vw.materialize(base, prof, valores))))
        videos = [p for p in salidas if p.suffix.lower() in (".mp4", ".webm", ".mov")]
        if not videos:
            fail(f"No se encontró vídeo en las salidas: {salidas}")
        r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",  # noqa: S603 - argv sin shell
                            "stream=codec_type,width,height,nb_read_frames:format=duration", "-of", "json", str(videos[0])],
                           capture_output=True, text=True)
        info = json.loads(r.stdout or "{}")
        v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
        audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        good = str(v.get("nb_read_frames")) == str(frames)
        say(f"  {videos[0]} · {v.get('width')}x{v.get('height')} · {v.get('nb_read_frames')} frames · "
            f"{float(info.get('format', {}).get('duration', 0)):.2f} s · audio={'sí' if audio else 'no'}")
        if not good:
            warn(f"Frames esperados: {frames}")
        registrar_prueba(f"h3_{modo}", {"ok": good, "segundos": a.segundos, "frames": v.get("nb_read_frames"),
                                 "tiempo_s": round(time.time() - t0), "fecha": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        (ok if good else warn)(f"Prueba {modo} terminada. Descarga el vídeo con: runpodctl send {videos[0]}")

    if a.qwen:
        ruta = API_DIR / ("QWEN_21_T2I.api.json" if cfg().get("qwen21", True) else "QWEN_2512_T2I.api.json")
        if not ruta.exists():
            fail("Activa Qwen: fruti start --qwen-t2i si (antes: fruti models --qwen-t2i si)")
        titulo(f"Prueba {ruta.name}")
        t0 = time.time()
        imgs = descargar(esperar(encolar(load_json(ruta))))
        registrar_prueba("qwen21_bf16" if cfg().get("qwen21", True) else "qwen2512_t2i", {"ok": bool(imgs), "tiempo_s": round(time.time() - t0)})
        for p in imgs:
            ok(f"Imagen: {p}")


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    opciones = argparse.ArgumentParser(add_help=False)
    opciones.add_argument("--perfil", choices=["h3_balanced_default", "h3_quality_bf16_optional"])
    opciones.add_argument("--voces-personajes", choices=["si", "no"],
                          help="añade H3 Ref2VA para generar diálogo con muestras de voz guardadas")
    opciones.add_argument("--qwen21", choices=["si", "no"], help="Qwen 2.1 BF16 (predeterminado)")
    opciones.add_argument("--qwen-t2i", choices=["si", "no"])
    opciones.add_argument("--qwen-edit", choices=["no", "fp8mixed", "bf16"])
    opciones.add_argument("--acceso", choices=["runpod_proxy", "quick", "named", "ninguno"])
    opciones.add_argument("--sin-sha256", action="store_true", help="solo comprobar tamaños (más rápido)")

    ap = argparse.ArgumentParser(prog="fruti", description="FRUTINOVELAS · ComfyUI remoto por comandos")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", parents=[opciones], help="todo: diagnóstico, instalación, modelos y arranque")
    s.add_argument("--reexportar", action="store_true")
    sub.add_parser("doctor", help="diagnóstico de GPU, RAM y disco")
    sub.add_parser("install", help="instala ComfyUI fijado y dependencias")
    sub.add_parser("models", parents=[opciones], help="descarga y verifica modelos")
    s = sub.add_parser("start", parents=[opciones], help="arranca ComfyUI, valida flujos, gateway y acceso público")
    s.add_argument("--reexportar", action="store_true", help="repite la exportación API aunque ya exista")
    sub.add_parser("status", help="estado de los servicios")
    s = sub.add_parser("token", help="token del gateway")
    s.add_argument("--mostrar", action="store_true")
    s.add_argument("--regenerar", action="store_true")
    s = sub.add_parser("test", help="prueba real de generación")
    s.add_argument("--modo", choices=["i2va", "fl2va", "ambos", "ninguno"], default="i2va")
    s.add_argument("--segundos", type=int, default=5, choices=range(4, 16), metavar="4-15")
    s.add_argument("--prompt", default="Una fresa sonriente camina por un mercado colorido al atardecer, cámara estable, luz cálida.")
    s.add_argument("--semilla", type=int, default=42)
    s.add_argument("--qwen", action="store_true", help="también prueba el perfil Qwen activo")
    s = sub.add_parser("logs", help="muestra logs")
    s.add_argument("servicio", choices=["comfyui", "gateway", "cloudflared"])
    s.add_argument("-n", type=int, default=80)
    s.add_argument("-f", action="store_true", help="seguir en directo (Ctrl+C para salir)")
    sub.add_parser("stop", help="detiene ComfyUI, gateway y túnel")

    a = ap.parse_args(argv)
    if a.cmd == "models":
        aplicar_flags(a)
    handlers = {"setup": cmd_setup, "doctor": cmd_doctor, "install": cmd_install, "models": cmd_models,
                "start": cmd_start, "status": cmd_status, "token": cmd_token, "test": cmd_test, "logs": cmd_logs,
                "stop": cmd_stop}
    handlers[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
