"""Genera ``notebooks/FRUTINOVELAS_ComfyUI_Imagenes_H3_Colab.ipynb``.

RunPod no usa libreta: se maneja por comandos con ``scripts/fruti_remote.py``.

La libreta es autocontenida: incrusta (visibles, sin base64) los scripts del kit,
el manifiesto de modelos, los perfiles y el flujo H3 del usuario sin modificar.
Se regenera siempre con este script::

    uv run python scripts/build_colab_notebook.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

UI_FILE = ROOT / "workflows" / "H3_EQUILIBRADO_9x16_INICIO_FINAL.ui.json"
EMBEDDED = [
    ("scripts/validate_workflows.py", ROOT / "scripts" / "validate_workflows.py"),
    ("scripts/export_workflow_api.py", ROOT / "scripts" / "export_workflow_api.py"),
    ("scripts/comfy_gateway.py", ROOT / "scripts" / "comfy_gateway.py"),
    ("config/models_manifest.lock.json", ROOT / "config" / "models_manifest.lock.json"),
    ("config/workflow_profiles.json", ROOT / "config" / "workflow_profiles.json"),
]

# --------------------------------------------------------------------------- celdas
INTRO = """# 🍓 FRUTINOVELAS · ComfyUI en Colab (H3 + imágenes Qwen)

Esta libreta prepara **ComfyUI v0.40.0** con tu flujo **H3 EQUILIBRADO 9:16 (inicio / inicio+final)** y lo publica
de forma segura para que **FRUTINOVELAS Studio** (que corre en tu PC) lo use como motor de generación.

**Qué hace, en orden**

| Celda | Acción |
|---|---|
| 1 | Configuración (perfil, Drive, túnel) |
| 1.1–1.6 | Escribe los archivos del kit (scripts, manifiesto, perfiles y tu flujo exacto) |
| 2 | Diagnóstico de GPU, VRAM, RAM y disco |
| 3 | Instala ComfyUI fijado al commit `3541246` + dependencias |
| 4–5 | Plan de modelos y descarga verificada (tamaño + SHA-256, revisiones fijadas) |
| 6 | Prepara los flujos (tu H3 + plantillas Qwen opcionales) |
| 7 / 7B | Arranca ComfyUI, **exporta a formato API automáticamente** y valida contra el servidor real |
| 8 | Gateway con token + túnel Cloudflare |
| 9 / 9B | Datos de conexión para el programa (URL) y token (paso privado) |
| 10 | Pruebas reales opcionales (H3 5 s solo-inicio / inicio+final, Qwen) |
| 11 | Guardar en Drive y detener procesos |

**Antes de empezar**

1. *Entorno de ejecución → Cambiar tipo de entorno* → **GPU** (recomendado A100 80 GB, H100 o G4 con RAM alta).
2. Panel 🔑 **Secretos** (barra izquierda), todos opcionales:
   - `HF_TOKEN`: token de lectura de Hugging Face (evita límites de descarga).
   - `FRUTI_GATEWAY_TOKEN`: token fijo del gateway (≥ 16 caracteres). Si no existe se genera uno.
   - `CF_TUNNEL_TOKEN` y `CF_TUNNEL_HOSTNAME`: solo si usas un túnel con nombre de Cloudflare (URL estable).
3. Ejecuta las celdas **una a una, en orden**. Las celdas 10 y 11 tienen casillas desactivadas por defecto.

> ⚠️ **Avisos importantes**
> - Las [condiciones de Colab](https://research.google.com/colaboratory/faq.html) restringen en el plan gratuito el uso principal mediante interfaces web remotas y los proxies remotos. Se recomienda **plan de pago con saldo de cómputo**. Esta libreta **no** usa autoclic ni trucos anti-inactividad: mantén la pestaña abierta.
> - Un *Quick Tunnel* de Cloudflare es para pruebas: la URL cambia en cada sesión.
> - Requisitos de VRAM/RAM de H3 **no verificados** por FRUTINOVELAS. Hasta que la celda 10 termine con éxito, la compatibilidad real es **pendiente de prueba**.
> - Nunca compartas el token ni guardes la libreta con la salida de la celda 9B visible.
"""

CONFIG_HEAD_COLAB = r'''# @title 1 · Configuración
PERFIL_VIDEO = "h3_balanced_default"  # @param ["h3_balanced_default", "h3_quality_bf16_optional"]
ACTIVAR_QWEN_2512_T2I = False  # @param {type:"boolean"}
QWEN_EDIT_2511 = "no"  # @param ["no", "fp8mixed", "bf16"]
USAR_DRIVE = True  # @param {type:"boolean"}
GUARDAR_MODELOS_EN_DRIVE = False  # @param {type:"boolean"}
VERIFICAR_SHA256 = True  # @param {type:"boolean"}
MODO_TUNEL = "quick"  # @param ["quick", "named", "ninguno"]

import json
import os
import signal
import sys
import time
from pathlib import Path

PLATAFORMA = "colab"
BASE_DIR = Path("/content")
KIT_DIR = BASE_DIR / "FRUTINOVELAS_kit"
COMFY_DIR = BASE_DIR / "ComfyUI"
DATA_DIR = BASE_DIR / "FRUTINOVELAS_data"
MODELS_DIR = BASE_DIR / "FRUTINOVELAS_models"
DRIVE_ROOT = Path("/content/drive/MyDrive/FRUTINOVELAS")

IN_COLAB = "google.colab" in sys.modules
if USAR_DRIVE and IN_COLAB:
    from google.colab import drive

    if not Path("/content/drive/MyDrive").is_dir():
        drive.mount("/content/drive")
    DRIVE_ROOT.mkdir(parents=True, exist_ok=True)
if GUARDAR_MODELOS_EN_DRIVE:
    if not (USAR_DRIVE and IN_COLAB):
        raise SystemExit("GUARDAR_MODELOS_EN_DRIVE necesita USAR_DRIVE activado.")
    MODELS_DIR = DRIVE_ROOT / "models"
    print("⚠️ Los modelos (≈40 GB o más) se guardarán en tu Drive. Comprueba que tienes espacio.")
# Carpeta que sobrevive al cierre de la sesión (token, conexión, copias de cada sesión).
PERSIST_DIR = DRIVE_ROOT if (USAR_DRIVE and IN_COLAB) else None
# El entorno de Colab se borra al desconectar: la marca de dependencias vive con él.
PIP_MARKER = COMFY_DIR / ".frutinovelas_pip_ok"
'''

CONFIG_COMMON = r'''
NOTEBOOK_VERSION = "1.1.0"
COMFY_REPO = "https://github.com/Comfy-Org/ComfyUI.git"
COMFY_TAG = "v0.40.0"
COMFY_COMMIT = "3541246a9c997f4b8c32f9f88f3c985d02021c79"
TEMPLATES_COMMIT = "3e89967349dd95fa68ce3b36966f41d642af8ea7"
CLOUDFLARED_VERSION = "2026.10.0"
COMFY_PORT = 8188
GATEWAY_PORT = 8189
UA = f"FRUTINOVELAS-{PLATAFORMA}/{NOTEBOOK_VERSION}"
H3_PROFILE_KEY = "h3_equilibrado_9x16"
API_DIR = DATA_DIR / "workflows" / "api"
LOG_DIR = DATA_DIR / "logs"
UI_PATH = KIT_DIR / "workflows" / "H3_EQUILIBRADO_9x16_INICIO_FINAL.ui.json"

for d in [KIT_DIR / "scripts", KIT_DIR / "config", KIT_DIR / "workflows" / "templates", KIT_DIR / "bin",
          DATA_DIR / "workflows", API_DIR, DATA_DIR / "secrets", DATA_DIR / "tests",
          DATA_DIR / "comfy_input", DATA_DIR / "comfy_output", LOG_DIR, MODELS_DIR] + ([PERSIST_DIR] if PERSIST_DIR else []):
    d.mkdir(parents=True, exist_ok=True)
os.chmod(DATA_DIR / "secrets", 0o700)


def secreto(nombre):
    """Lee un secreto de Colab sin mostrarlo. Devuelve None si no existe o no hay permiso."""
    try:
        from google.colab import userdata

        valor = userdata.get(nombre)
        return valor.strip() if valor else None
    except Exception:
        return (os.environ.get(nombre) or "").strip() or None


STATE_FILE = DATA_DIR / "estado.json"
PIDS_FILE = DATA_DIR / "pids.json"


def estado(**cambios):
    """Estado persistente de la sesión (sin secretos)."""
    datos = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    datos.update(cambios)
    STATE_FILE.write_text(json.dumps(datos, ensure_ascii=False, indent=2))
    return datos


# Los PID solo valen dentro del mismo contenedor: /tmp se borra al reiniciar el pod o el entorno.
SESSION_FILE = Path("/tmp/frutinovelas_session")
if not SESSION_FILE.exists():
    import uuid

    SESSION_FILE.write_text(uuid.uuid4().hex)
SESSION_ID = SESSION_FILE.read_text().strip()
PROCS = json.loads(PIDS_FILE.read_text()) if PIDS_FILE.exists() else {}
if PROCS.get("_session") != SESSION_ID:
    PROCS = {"_session": SESSION_ID}
    if STATE_FILE.exists():
        estado(public_url=None, gateway_listen=None)


def guardar_pids():
    PIDS_FILE.write_text(json.dumps(PROCS, indent=2))


def vivo(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def cargar_kit():
    """Carga manifiesto, perfil H3 y el validador (recargado para que la celda sea repetible)."""
    import importlib

    if str(KIT_DIR / "scripts") not in sys.path:
        sys.path.insert(0, str(KIT_DIR / "scripts"))
    import validate_workflows

    importlib.reload(validate_workflows)
    manifest = json.loads((KIT_DIR / "config" / "models_manifest.lock.json").read_text())
    profile = validate_workflows.load_profile(KIT_DIR / "config" / "workflow_profiles.json", H3_PROFILE_KEY)
    return manifest, profile, validate_workflows


PERFILES_ACTIVOS = [PERFIL_VIDEO]
if ACTIVAR_QWEN_2512_T2I:
    PERFILES_ACTIVOS.append("qwen2512_t2i")
if QWEN_EDIT_2511 != "no":
    PERFILES_ACTIVOS.append({"fp8mixed": "qwen_edit2511_fp8mixed", "bf16": "qwen_edit2511_bf16"}[QWEN_EDIT_2511])

estado(perfiles=PERFILES_ACTIVOS, modo_tunel=MODO_TUNEL, notebook_version=NOTEBOOK_VERSION)
print("Perfiles de modelos:", ", ".join(PERFILES_ACTIVOS))
print("Modelos en:", MODELS_DIR)
print("Plataforma:", PLATAFORMA)
print("Persistencia:", PERSIST_DIR or "ninguna (todo se borra al cerrar la sesión)")
print("Túnel:", MODO_TUNEL)
print("Secretos detectados:", ", ".join(n for n in ["HF_TOKEN", "FRUTI_GATEWAY_TOKEN", "CF_TUNNEL_TOKEN", "CF_TUNNEL_HOSTNAME"] if secreto(n)) or "ninguno")
'''

CELL_DIAG = r'''# @title 2 · Diagnóstico del entorno
import platform
import shutil
import subprocess

MANIFEST, PROFILE, vw = cargar_kit()


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


gpu_line = sh("nvidia-smi --query-gpu=name,memory.total,compute_cap,driver_version --format=csv,noheader,nounits")
if not gpu_line:
    raise SystemExit("❌ No hay GPU. Colab: Entorno de ejecución → Cambiar tipo → GPU. RunPod: crea el pod con GPU.")
gpu_name, vram_mb, compute_cap, driver = [x.strip() for x in gpu_line.splitlines()[0].split(",")]
vram_gb = float(vram_mb) / 1024
ram_gb = int(open("/proc/meminfo").read().split("MemTotal:")[1].split()[0]) / 1024 / 1024
disk = shutil.disk_usage(MODELS_DIR)

try:
    import torch

    torch_info = f"{torch.__version__} · CUDA {torch.version.cuda} · disponible={torch.cuda.is_available()}"
except Exception as exc:
    torch_info = f"no disponible ({exc})"


def componentes_activos():
    vistos = []
    for perfil in PERFILES_ACTIVOS:
        for comp in MANIFEST["profiles"][perfil]["components"]:
            if comp not in vistos:
                vistos.append(comp)
    return vistos


def ruta_local(comp_key):
    c = MANIFEST["components"][comp_key]
    return MODELS_DIR / "hf" / c["repo_id"].replace("/", "__") / c["path"]


pendiente = sum(MANIFEST["components"][k]["size"] for k in componentes_activos()
                if not (ruta_local(k).exists() and ruta_local(k).stat().st_size == MANIFEST["components"][k]["size"]))

print(f"GPU:     {gpu_name} · {vram_gb:.1f} GB VRAM · compute {compute_cap} · driver {driver}")
print(f"RAM:     {ram_gb:.1f} GB")
print(f"Disco:   {disk.free / 1e9:.1f} GB libres en {MODELS_DIR}")
print(f"Python:  {platform.python_version()}")
print(f"PyTorch: {torch_info}")
print(f"FFmpeg:  {'sí' if shutil.which('ffmpeg') else 'no'}")
print(f"Descarga pendiente: {pendiente / 1e9:.1f} GB")

avisos = []
if vram_gb < 40:
    avisos.append("VRAM < 40 GB: H3 puede fallar por memoria o ir muy lento (requisito no verificado).")
if ram_gb < 50:
    avisos.append("RAM < 50 GB: activa 'RAM alta' si tu plan lo permite; la carga de modelos puede fallar.")
if disk.free < pendiente + 15e9:
    avisos.append("Disco insuficiente para los modelos seleccionados (+15 GB de margen).")
try:
    if float(compute_cap) < 10.0:
        avisos.append("GPU anterior a Blackwell: el encoder NVFP4 AWQ puede ir más lento o no ser compatible (no verificado).")
except ValueError:
    pass
for a in avisos:
    print("⚠️", a)
estado(diagnostico={"gpu": gpu_name, "vram_gb": round(vram_gb, 1), "compute_cap": compute_cap,
                    "ram_gb": round(ram_gb, 1), "disco_libre_gb": round(disk.free / 1e9, 1), "torch": torch_info})
print("✅ Diagnóstico terminado" + (" con avisos" if avisos else ""))
'''

CELL_INSTALL = r'''# @title 3 · Instalar ComfyUI (versión fijada) y dependencias
import subprocess


def run(cmd, cwd=None):
    print("$", cmd)
    r = subprocess.run(cmd, shell=True, cwd=cwd, text=True, capture_output=True)
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        raise RuntimeError(f"Falló: {cmd}")
    return r.stdout


if not (COMFY_DIR / ".git").is_dir():
    COMFY_DIR.mkdir(parents=True, exist_ok=True)
    run(f"git init -q {COMFY_DIR}")
    run(f"git -C {COMFY_DIR} remote add origin {COMFY_REPO}")
actual = subprocess.run(f"git -C {COMFY_DIR} rev-parse HEAD", shell=True, capture_output=True, text=True).stdout.strip()
if actual != COMFY_COMMIT:
    run(f"git -C {COMFY_DIR} fetch -q --depth 1 origin {COMFY_COMMIT}")
    run(f"git -C {COMFY_DIR} checkout -q --force {COMFY_COMMIT}")
print("ComfyUI en commit", run(f"git -C {COMFY_DIR} rev-parse HEAD").strip(), f"({COMFY_TAG})")

import shutil

if not PIP_MARKER.exists() or PIP_MARKER.read_text().strip() != COMFY_COMMIT:
    run(f"{sys.executable} -m pip install -q -r requirements.txt", cwd=COMFY_DIR)
    run(f'{sys.executable} -m pip install -q -U "huggingface_hub[hf_xet]" playwright pillow requests aiohttp')
    run(f"{sys.executable} -m playwright install --with-deps chromium")
    PIP_MARKER.write_text(COMFY_COMMIT)
else:
    print("Dependencias ya instaladas para este commit.")
if not shutil.which("ffprobe"):
    run("apt-get update -qq && apt-get install -y -qq ffmpeg")

import importlib.metadata as md

for paquete in ["torch", "comfyui-frontend-package", "comfy-kitchen", "aiohttp", "huggingface_hub", "playwright"]:
    try:
        print(f"  {paquete} {md.version(paquete)}")
    except md.PackageNotFoundError:
        print(f"  {paquete} (no instalado)")
estado(comfyui_commit=COMFY_COMMIT)
print("✅ Instalación lista (no se instalan SageAttention ni xformers)")
'''

CELL_PLAN = r'''# @title 4 · Plan de modelos (manifiesto con revisiones fijadas)
MANIFEST, PROFILE, vw = cargar_kit()
print(f"{'componente':40} {'GB':>7}  estado")
total = 0
for k in componentes_activos():
    c = MANIFEST["components"][k]
    p = ruta_local(k)
    if p.exists() and p.stat().st_size == c["size"]:
        st = "presente"
    elif p.exists():
        st = "incompleto"
    else:
        st = "por descargar"
        total += c["size"]
    print(f"{Path(c['path']).name[:40]:40} {c['size'] / 1e9:7.2f}  {st}")
libre = shutil.disk_usage(MODELS_DIR).free
print(f"\nPor descargar: {total / 1e9:.1f} GB · libre en destino: {libre / 1e9:.1f} GB")
if libre < total + 5e9:
    raise SystemExit("❌ No hay espacio suficiente. Desactiva perfiles opcionales o usa un entorno con más disco.")
print("✅ Hay espacio suficiente")
'''

CELL_DOWNLOAD = r'''# @title 5 · Descargar y verificar modelos
import hashlib

os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
from huggingface_hub import hf_hub_download

HF_TOKEN = secreto("HF_TOKEN")


def sha256_archivo(path, size):
    h = hashlib.sha256()
    leido, siguiente = 0, 0.1
    with open(path, "rb") as f:
        while bloque := f.read(16 * 1024 * 1024):
            h.update(bloque)
            leido += len(bloque)
            if leido / size >= siguiente:
                print(f"    sha256 {leido / size:4.0%}", end="\r")
                siguiente += 0.1
    print(" " * 30, end="\r")
    return h.hexdigest()


def verificar(c, path):
    st = path.stat()
    if st.st_size != c["size"]:
        return False, f"tamaño {st.st_size} ≠ {c['size']}"
    if not VERIFICAR_SHA256:
        return True, "tamaño correcto (SHA-256 desactivado)"
    marca = path.with_name(path.name + ".sha256ok")
    clave = f"{st.st_size}:{int(st.st_mtime)}:{c['sha256']}"
    if marca.exists() and marca.read_text() == clave:
        return True, "SHA-256 correcto (ya verificado)"
    digest = sha256_archivo(path, c["size"])
    if digest != c["sha256"]:
        return False, f"SHA-256 {digest} ≠ {c['sha256']}"
    marca.write_text(clave)
    return True, "SHA-256 correcto"


for k in componentes_activos():
    c = MANIFEST["components"][k]
    rev = MANIFEST["repos"][c["repo_id"]]
    path = ruta_local(k)
    nombre = Path(c["path"]).name
    print(f"• {nombre} ({c['size'] / 1e9:.2f} GB)")
    if path.exists():
        ok, motivo = verificar(c, path)
        if not ok:
            print("    ⚠️", motivo, "→ se vuelve a descargar")
            path.unlink()
    if not path.exists():
        t0 = time.time()
        hf_hub_download(repo_id=c["repo_id"], filename=c["path"], revision=rev,
                        local_dir=MODELS_DIR / "hf" / c["repo_id"].replace("/", "__"), token=HF_TOKEN)
        print(f"    descargado en {time.time() - t0:.0f} s")
        ok, motivo = verificar(c, path)
        if not ok:
            path.unlink(missing_ok=True)
            raise RuntimeError(f"{nombre}: {motivo}")
    print("    ✅", motivo)
    enlace = COMFY_DIR / "models" / c["dest"] / nombre
    enlace.parent.mkdir(parents=True, exist_ok=True)
    if enlace.is_symlink() and enlace.resolve() != path.resolve():
        enlace.unlink()
    if not enlace.exists() and not enlace.is_symlink():
        enlace.symlink_to(path)
estado(modelos={k: MANIFEST["components"][k]["sha256"] for k in componentes_activos()})
print("✅ Modelos listos y enlazados en", COMFY_DIR / "models")
'''

CELL_WORKFLOWS = r'''# @title 6 · Preparar flujos (tu H3 + plantillas Qwen opcionales)
import requests

ui = json.loads(UI_PATH.read_text(encoding="utf-8"))
print("Flujo H3:", UI_PATH.name, "·", vw.detect_format(ui), "·", len(ui["nodes"]), "nodos")
if vw.detect_format(ui) != "ui":
    raise SystemExit("❌ El flujo H3 no tiene formato de interfaz.")

TEMPLATES = {}
for perfil in PERFILES_ACTIVOS:
    plantilla = MANIFEST["profiles"][perfil].get("template")
    if not plantilla:
        continue
    destino = KIT_DIR / "workflows" / "templates" / Path(plantilla).name
    if not destino.exists():
        url = f"https://raw.githubusercontent.com/Comfy-Org/workflow_templates/{TEMPLATES_COMMIT}/{plantilla}"
        r = requests.get(url, timeout=60, headers={"User-Agent": UA})
        r.raise_for_status()
        destino.write_bytes(r.content)
    datos = json.loads(destino.read_text(encoding="utf-8"))
    if vw.detect_format(datos) != "ui":
        raise SystemExit(f"❌ {destino.name} no es un flujo de interfaz.")
    TEMPLATES[perfil] = destino
    print("Plantilla:", destino.name, "·", len(datos["nodes"]), "nodos")
print("✅ Flujos preparados")
'''

CELL_START = r'''# @title 7 · Arrancar ComfyUI y comprobar nodos y modelos
import subprocess

import requests

LOCAL = f"http://127.0.0.1:{COMFY_PORT}"


def comfy_vivo():
    try:
        return requests.get(LOCAL + "/system_stats", timeout=3).ok
    except Exception:
        return False


def cola_log(path, n=60):
    if path.exists():
        print("\n".join(path.read_text(errors="replace").splitlines()[-n:]))


if not comfy_vivo():
    log = open(LOG_DIR / "comfyui.log", "ab")
    p = subprocess.Popen(
        [sys.executable, "main.py", "--listen", "127.0.0.1", "--port", str(COMFY_PORT), "--disable-auto-launch",
         "--output-directory", str(DATA_DIR / "comfy_output"), "--input-directory", str(DATA_DIR / "comfy_input")],
        cwd=COMFY_DIR, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    PROCS["comfyui"] = p.pid
    guardar_pids()
    t0 = time.time()
    while not comfy_vivo():
        if p.poll() is not None:
            cola_log(LOG_DIR / "comfyui.log")
            raise RuntimeError("ComfyUI se cerró al arrancar (log arriba).")
        if time.time() - t0 > 900:
            raise RuntimeError("ComfyUI no respondió en 15 minutos.")
        time.sleep(3)
    print(f"ComfyUI arrancado en {time.time() - t0:.0f} s")
else:
    print("ComfyUI ya estaba en marcha")

STATS = requests.get(LOCAL + "/system_stats", timeout=30).json()
OBJECT_INFO = requests.get(LOCAL + "/object_info", timeout=300).json()
(DATA_DIR / "object_info.json").write_text(json.dumps(OBJECT_INFO))
print("Versión ComfyUI:", STATS.get("system", {}).get("comfyui_version"))

faltan = sorted({n["type"] for n in ui["nodes"] if n["type"] not in ("Note", "MarkdownNote")} - set(OBJECT_INFO))
if faltan:
    raise SystemExit(f"❌ Nodos ausentes en este ComfyUI: {faltan}")
print("✅ Todos los nodos del flujo H3 existen")

LOADER_FIELD = {"diffusion_models": ("UNETLoader", "unet_name"), "text_encoders": ("CLIPLoader", "clip_name"),
                "vae": ("VAELoader", "vae_name"), "loras": ("LoraLoaderModelOnly", "lora_name")}
sin_ver = []
for k in componentes_activos():
    c = MANIFEST["components"][k]
    clase, campo = LOADER_FIELD[c["dest"]]
    spec = (OBJECT_INFO.get(clase, {}).get("input", {}).get("required", {}) or {}).get(campo)
    opciones = vw.combo_options(spec) or []
    if Path(c["path"]).name not in opciones:
        sin_ver.append(f"{clase}.{campo}: {Path(c['path']).name}")
if sin_ver:
    raise SystemExit("❌ ComfyUI no ve estos modelos: " + "; ".join(sin_ver))
print("✅ ComfyUI ve todos los modelos seleccionados")
'''

CELL_EXPORT = r'''# @title 7B · Exportar a formato API (automático) y validar
import hashlib
import subprocess

MANIFEST, PROFILE, vw = cargar_kit()


def exportar(ui_path, out_path):
    r = subprocess.run([sys.executable, str(KIT_DIR / "scripts" / "export_workflow_api.py"), "--comfy", LOCAL,
                        "--ui", str(ui_path), "--out", str(out_path)], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr[-4000:])
        raise RuntimeError(f"No se pudo exportar {ui_path.name}")
    return json.loads(out_path.read_text(encoding="utf-8"))


def sha_json(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


INFORME = {"generado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "comfyui_commit": COMFY_COMMIT, "flujos": {}}
crudo = exportar(UI_PATH, DATA_DIR / "workflows" / "H3_export_crudo.api.json")
omitidos = vw.ui_nodes_missing_in_api(ui, crudo)
print("Nodos de la interfaz que no van a la API (las notas son normales):", omitidos or "ninguno")
print("Nodo 28 (duración):", crudo.get("28", {}).get("inputs"))
print("Nodo 29 (fórmula):", {k: v for k, v in crudo.get("29", {}).get("inputs", {}).items() if k != "expression"})

overrides = MANIFEST["profiles"][PERFIL_VIDEO]["loader_overrides"]
variantes = {"fl2va": crudo, "i2va": vw.derive_i2va(crudo, PROFILE)}
errores_totales = []
for modo, grafo in variantes.items():
    r1 = vw.check_profile(grafo, PROFILE, modo)
    grafo_final, cambios = vw.apply_loader_overrides(grafo, overrides)
    r2 = vw.validate_api_graph(grafo_final, OBJECT_INFO)
    errores = r1["errors"] + r2["errors"]
    avisos = r1["warnings"] + r2["warnings"]
    nombre = PROFILE["workflow_api_files"][modo]
    for a in avisos:
        print(f"  [{modo}] aviso:", a)
    for e in errores:
        print(f"  [{modo}] ERROR:", e)
    for cbio in cambios:
        print(f"  [{modo}] perfil {PERFIL_VIDEO}:", cbio)
    if not errores:
        destino = API_DIR / nombre
        destino.write_text(json.dumps(grafo_final, ensure_ascii=False, indent=2), encoding="utf-8")
        INFORME["flujos"][nombre] = {"modo": modo, "nodos": len(grafo_final), "sha256": sha_json(destino),
                                     "cambios_perfil": cambios, "avisos": avisos}
        print(f"✅ {nombre} ({len(grafo_final)} nodos)")
    errores_totales += errores

NOMBRES_QWEN = {"qwen2512_t2i": "QWEN_2512_T2I.api.json", "qwen_edit2511_fp8mixed": "QWEN_EDIT_2511.api.json",
                "qwen_edit2511_bf16": "QWEN_EDIT_2511.api.json"}
for perfil, plantilla in TEMPLATES.items():
    api_q = exportar(plantilla, DATA_DIR / "workflows" / (plantilla.stem + ".api.json"))
    api_q, cambios = vw.apply_loader_overrides(api_q, MANIFEST["profiles"][perfil]["loader_overrides"])
    rq = vw.validate_api_graph(api_q, OBJECT_INFO)
    for a in rq["warnings"]:
        print(f"  [{perfil}] aviso:", a)
    for e in rq["errors"]:
        print(f"  [{perfil}] ERROR:", e)
    if not rq["errors"]:
        destino = API_DIR / NOMBRES_QWEN[perfil]
        destino.write_text(json.dumps(api_q, ensure_ascii=False, indent=2), encoding="utf-8")
        INFORME["flujos"][destino.name] = {"perfil": perfil, "nodos": len(api_q), "sha256": sha_json(destino),
                                           "cambios_perfil": cambios, "avisos": rq["warnings"]}
        print(f"✅ {destino.name} ({len(api_q)} nodos)")
    errores_totales += rq["errors"]

(DATA_DIR / "informe_exportacion.json").write_text(json.dumps(INFORME, ensure_ascii=False, indent=2))
if errores_totales:
    raise SystemExit(f"❌ {len(errores_totales)} error(es) de validación (detalle arriba). No se publican esos flujos.")
print("✅ Flujos API exportados y validados contra este ComfyUI:", ", ".join(INFORME["flujos"]))
'''

CELL_GATEWAY = r'''# @title 8 · Gateway con token + acceso público (túnel Cloudflare o proxy RunPod)
import re
import secrets as _secrets
import subprocess
import urllib.request

import requests

TOKEN_FILE = DATA_DIR / "secrets" / "gateway_token.txt"
TOKEN_PERSIST = PERSIST_DIR / "secrets" / "gateway_token.txt" if PERSIST_DIR else None
token, origen = secreto("FRUTI_GATEWAY_TOKEN"), "secreto FRUTI_GATEWAY_TOKEN"
if not token and TOKEN_FILE.exists():
    token, origen = TOKEN_FILE.read_text().strip(), "guardado en esta máquina"
if not token and TOKEN_PERSIST and TOKEN_PERSIST.exists():
    token, origen = TOKEN_PERSIST.read_text().strip(), f"guardado en {PERSIST_DIR}"
if not token:
    token, origen = _secrets.token_urlsafe(32), "generado ahora"
if len(token) < 16:
    raise SystemExit("❌ El token del gateway debe tener al menos 16 caracteres.")
TOKEN_FILE.write_text(token)
os.chmod(TOKEN_FILE, 0o600)
if TOKEN_PERSIST and origen == "generado ahora":
    TOKEN_PERSIST.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PERSIST.write_text(token)
    os.chmod(TOKEN_PERSIST, 0o600)
GATEWAY_TOKEN = token
AUTH = {"Authorization": f"Bearer {GATEWAY_TOKEN}", "User-Agent": UA}
print("Token del gateway:", origen, "· termina en …" + GATEWAY_TOKEN[-4:])


def escribir_identidad(extra=None):
    ident = {
        "servicio": f"frutinovelas-comfyui-{PLATAFORMA}",
        "plataforma": PLATAFORMA,
        "notebook_version": NOTEBOOK_VERSION,
        "comfyui_version": STATS.get("system", {}).get("comfyui_version"),
        "comfyui_commit": COMFY_COMMIT,
        "python": STATS.get("system", {}).get("python_version"),
        "pytorch": STATS.get("system", {}).get("pytorch_version"),
        "gpu": [{"nombre": d.get("name"), "vram_total": d.get("vram_total")} for d in STATS.get("devices", [])],
        "perfil_video": PERFIL_VIDEO,
        "perfiles": PERFILES_ACTIVOS,
        "modelos": {k: {"archivo": Path(MANIFEST["components"][k]["path"]).name, "sha256": MANIFEST["components"][k]["sha256"]}
                    for k in componentes_activos()},
        "workflows": {n: d["sha256"] for n, d in INFORME["flujos"].items()},
        "workflow_ui_sha256": PROFILE["workflow_ui_sha256"],
        "estado_compatibilidad": "pendiente_prueba_real",
        "actualizado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    anterior = DATA_DIR / "identity.json"
    if anterior.exists():
        viejo = json.loads(anterior.read_text())
        ident["pruebas"] = viejo.get("pruebas", {})
        ident["estado_compatibilidad"] = viejo.get("estado_compatibilidad", ident["estado_compatibilidad"])
    ident.update(extra or {})
    anterior.write_text(json.dumps(ident, ensure_ascii=False, indent=2))
    return ident


IDENTIDAD = escribir_identidad()
GW = f"http://127.0.0.1:{GATEWAY_PORT}"


def gw_vivo():
    try:
        return requests.get(GW + "/healthz", timeout=3).ok
    except Exception:
        return False


# Con el proxy de RunPod el gateway debe escuchar en todas las interfaces; sigue exigiendo token.
# ComfyUI (8188) se queda siempre en 127.0.0.1 y nunca se expone.
GATEWAY_LISTEN = "0.0.0.0" if MODO_TUNEL == "runpod_proxy" else "127.0.0.1"
if gw_vivo() and estado().get("gateway_listen") != GATEWAY_LISTEN and PROCS.get("gateway"):
    try:
        os.killpg(int(PROCS.pop("gateway")), signal.SIGTERM)
    except ProcessLookupError:
        pass
    time.sleep(1)
if not gw_vivo():
    env = dict(os.environ, FRUTI_GATEWAY_TOKEN_FILE=str(TOKEN_FILE))
    env.pop("FRUTI_GATEWAY_TOKEN", None)
    p = subprocess.Popen([sys.executable, str(KIT_DIR / "scripts" / "comfy_gateway.py"), "--listen", GATEWAY_LISTEN,
                          "--port", str(GATEWAY_PORT), "--upstream", LOCAL, "--workflows-dir", str(API_DIR),
                          "--identity-file", str(DATA_DIR / "identity.json")],
                         env=env, stdout=open(LOG_DIR / "gateway.log", "ab"), stderr=subprocess.STDOUT, start_new_session=True)
    PROCS["gateway"] = p.pid
    guardar_pids()
    estado(gateway_listen=GATEWAY_LISTEN)
    for _ in range(40):
        if gw_vivo():
            break
        if p.poll() is not None:
            cola_log(LOG_DIR / "gateway.log")
            raise RuntimeError("El gateway se cerró (log arriba).")
        time.sleep(0.5)
assert requests.get(GW + "/system_stats", timeout=10).status_code == 401, "El gateway debería rechazar peticiones sin token"
assert requests.get(GW + "/system_stats", headers=AUTH, timeout=10).ok, "El gateway no reenvía a ComfyUI"
print("✅ Gateway local OK (sin token → 401, con token → 200)")

CF_BIN = KIT_DIR / "bin" / "cloudflared"
PUBLIC_URL = None
if MODO_TUNEL == "runpod_proxy":
    pod = os.environ.get("RUNPOD_POD_ID")
    if not pod:
        raise SystemExit("❌ RUNPOD_POD_ID no está definido: el modo runpod_proxy solo funciona dentro de un pod de RunPod.")
    PUBLIC_URL = f"https://{pod}-{GATEWAY_PORT}.proxy.runpod.net"
elif MODO_TUNEL in ("quick", "named"):
    if not CF_BIN.exists():
        url = f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/cloudflared-linux-amd64"
        urllib.request.urlretrieve(url, CF_BIN)
        os.chmod(CF_BIN, 0o755)
    print(subprocess.run([str(CF_BIN), "--version"], capture_output=True, text=True).stdout.strip())
    previo = estado().get("public_url")
    cf_pid = PROCS.get("cloudflared")
    if cf_pid and vivo(cf_pid) and previo:
        PUBLIC_URL = previo
        print("Túnel ya activo")
    elif MODO_TUNEL == "quick":
        cf_log = LOG_DIR / "cloudflared.log"
        cf_log.write_text("")
        p = subprocess.Popen([str(CF_BIN), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{GATEWAY_PORT}"],
                             stdout=open(cf_log, "ab"), stderr=subprocess.STDOUT, start_new_session=True)
        PROCS["cloudflared"] = p.pid
        guardar_pids()
        for _ in range(90):
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", cf_log.read_text(errors="replace"))
            if m:
                PUBLIC_URL = m.group(0)
                break
            time.sleep(1)
        if not PUBLIC_URL:
            cola_log(cf_log)
            raise RuntimeError("No se obtuvo la URL del Quick Tunnel (log arriba).")
    else:
        cf_token, host = secreto("CF_TUNNEL_TOKEN"), secreto("CF_TUNNEL_HOSTNAME")
        if not (cf_token and host):
            raise SystemExit("❌ Para MODO_TUNEL='named' define CF_TUNNEL_TOKEN y CF_TUNNEL_HOSTNAME.")
        env = dict(os.environ, TUNNEL_TOKEN=cf_token)
        p = subprocess.Popen([str(CF_BIN), "tunnel", "--no-autoupdate", "run"], env=env,
                             stdout=open(LOG_DIR / "cloudflared.log", "ab"), stderr=subprocess.STDOUT, start_new_session=True)
        PROCS["cloudflared"] = p.pid
        guardar_pids()
        PUBLIC_URL = "https://" + host.removeprefix("https://").rstrip("/")

if PUBLIC_URL:
    publico_ok = False
    for _ in range(60):
        try:
            if requests.get(PUBLIC_URL + "/healthz", timeout=10, headers={"User-Agent": UA}).ok:
                publico_ok = True
                break
        except Exception:
            pass
        time.sleep(2)
    if not publico_ok:
        if MODO_TUNEL == "runpod_proxy":
            raise RuntimeError(f"{PUBLIC_URL} no responde. En RunPod: Edit Pod → Expose HTTP Ports → añade {GATEWAY_PORT} "
                               "(el pod se reinicia; vuelve a ejecutar desde la celda 1).")
        raise RuntimeError(f"{PUBLIC_URL} no responde. Revisa {LOG_DIR / 'cloudflared.log'}")
    r = requests.get(PUBLIC_URL + "/system_stats", headers=AUTH, timeout=30)
    if not r.ok:
        raise RuntimeError(f"El acceso público responde {r.status_code} con token.")
    if requests.get(PUBLIC_URL + "/system_stats", headers={"User-Agent": UA}, timeout=30).status_code != 401:
        raise RuntimeError("⚠️ El acceso público NO exige token. Detén el pod y revisa la configuración.")
    print("✅ Acceso público verificado (sin token → 401, con token → 200)")
estado(public_url=PUBLIC_URL)
print("URL pública:", PUBLIC_URL or "(sin acceso público: solo accesible dentro de la máquina)")
'''

CELL_CONNECTION = r'''# @title 9 · Datos de conexión para FRUTINOVELAS Studio (sin secretos)
DESCARGAR_ARCHIVO = False  # @param {type:"boolean"}
conexion = {
    "formato": "frutinovelas.conexion_comfyui",
    "version": 1,
    "comfyui_url": PUBLIC_URL,
    "autenticacion": "Authorization: Bearer <token>",
    "token": "NO INCLUIDO: cópialo desde la celda 9B y pégalo en el programa",
    "plataforma": PLATAFORMA,
    "tunel": MODO_TUNEL,
    "flujos": sorted(INFORME["flujos"]),
    "identidad": {k: IDENTIDAD[k] for k in ("comfyui_version", "comfyui_commit", "perfil_video", "workflow_ui_sha256")},
    "creado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "aviso": {"quick": "La URL de un Quick Tunnel cambia en cada sesión.",
              "runpod_proxy": "La URL depende del ID del pod: se mantiene mientras uses el mismo pod."}.get(MODO_TUNEL, ""),
}
ruta_conexion = DATA_DIR / "conexion_frutinovelas.json"
ruta_conexion.write_text(json.dumps(conexion, ensure_ascii=False, indent=2))
if PERSIST_DIR:
    (PERSIST_DIR / "conexion_frutinovelas.json").write_text(ruta_conexion.read_text())
print("═" * 70)
print("  URL de ComfyUI para el programa:")
print("   ", PUBLIC_URL)
print("  Flujos publicados:", ", ".join(conexion["flujos"]))
print("═" * 70)
print("Archivo:", ruta_conexion)
if DESCARGAR_ARCHIVO and IN_COLAB:
    from google.colab import files

    files.download(str(ruta_conexion))
'''

CELL_TOKEN = r'''# @title 9B · Token del gateway (paso privado)
MOSTRAR_TOKEN = False  # @param {type:"boolean"}
if MOSTRAR_TOKEN:
    print(GATEWAY_TOKEN)
    print("\n⚠️ Cópialo al programa y después borra la salida de esta celda (⋮ → Borrar salida).")
else:
    print("Marca MOSTRAR_TOKEN y vuelve a ejecutar para ver el token. Termina en …" + GATEWAY_TOKEN[-4:])
'''

CELL_TESTS = r'''# @title 10 · Pruebas reales opcionales (usan GPU y tiempo)
PROBAR_H3_SOLO_INICIO = False  # @param {type:"boolean"}
PROBAR_H3_INICIO_FINAL = False  # @param {type:"boolean"}
PROBAR_QWEN_2512 = False  # @param {type:"boolean"}
PROMPT_PRUEBA = "Una fresa sonriente camina por un mercado colorido al atardecer, cámara estable, luz cálida."  # @param {type:"string"}
SEGUNDOS = 5  # @param {type:"slider", min:4, max:15, step:1}
SEMILLA = 42  # @param {type:"integer"}

import subprocess
import uuid

import requests
from IPython.display import Image as IPImage
from IPython.display import Video, display
from PIL import Image, ImageDraw

MANIFEST, PROFILE, vw = cargar_kit()


def imagen_prueba(path, c1, c2, texto):
    w, h = 576, 1024
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    d.ellipse([w // 2 - 120, h // 2 - 120, w // 2 + 120, h // 2 + 120], fill=(230, 40, 70))
    d.text((40, 60), texto, fill=(255, 255, 255))
    img.save(path)
    return path


def subir(path):
    with open(path, "rb") as f:
        r = requests.post(GW + "/upload/image", headers=AUTH, files={"image": (path.name, f, "image/png")},
                          data={"type": "input", "overwrite": "true"}, timeout=120)
    r.raise_for_status()
    j = r.json()
    return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]


def encolar(grafo):
    pid = str(uuid.uuid4())
    r = requests.post(GW + "/prompt", headers=AUTH, timeout=120,
                      json={"prompt": grafo, "prompt_id": pid, "client_id": "frutinovelas-colab"})
    if r.status_code != 200 or r.json().get("node_errors"):
        print(r.text[:4000])
        raise RuntimeError("ComfyUI rechazó el trabajo")
    return pid


def esperar(pid, limite_s=3 * 3600):
    t0 = time.time()
    while time.time() - t0 < limite_s:
        h = requests.get(f"{GW}/history/{pid}", headers=AUTH, timeout=60).json()
        if pid in h:
            entrada = h[pid]
            st = entrada.get("status", {})
            if st.get("completed") or st.get("status_str") in ("success", "error"):
                print(f"  terminado en {time.time() - t0:.0f} s · {st.get('status_str')}")
                if st.get("status_str") != "success":
                    for msg in st.get("messages", []):
                        print("   ", msg)
                    raise RuntimeError("El trabajo terminó con error")
                return entrada
        print(f"  generando… {time.time() - t0:.0f} s", end="\r")
        time.sleep(10)
    raise TimeoutError("La prueba superó el tiempo límite")


def descargar_salidas(entrada):
    rutas = []
    for salida in entrada.get("outputs", {}).values():
        for valor in salida.values():
            if not isinstance(valor, list):
                continue
            for item in valor:
                if isinstance(item, dict) and item.get("filename"):
                    r = requests.get(GW + "/view", headers=AUTH, timeout=600, params={
                        "filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
                    r.raise_for_status()
                    destino = DATA_DIR / "tests" / item["filename"]
                    destino.write_bytes(r.content)
                    rutas.append(destino)
    return rutas


def ffprobe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                        "stream=codec_type,width,height,r_frame_rate,nb_read_frames:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


def registrar(nombre, resultado):
    ident = json.loads((DATA_DIR / "identity.json").read_text())
    ident.setdefault("pruebas", {})[nombre] = resultado
    if all(v.get("ok") for v in ident["pruebas"].values()):
        ident["estado_compatibilidad"] = "prueba_real_ok"
    (DATA_DIR / "identity.json").write_text(json.dumps(ident, ensure_ascii=False, indent=2))


def prueba_h3(modo):
    frames, seg = vw.quantize_frames(SEGUNDOS, PROFILE["duration_rule"])
    print(f"▶ H3 {modo}: {SEGUNDOS} s pedidos → {frames} frames ({seg:.3f} s reales)")
    base = json.loads((API_DIR / PROFILE["workflow_api_files"][modo]).read_text())
    valores = {"start_image": subir(imagen_prueba(DATA_DIR / "tests" / "inicio.png", (250, 170, 60), (120, 40, 90), "INICIO")),
               "positive_prompt": PROMPT_PRUEBA, "seed": int(SEMILLA), "duration": float(SEGUNDOS),
               "filename_prefix": f"video/FRUTINOVELAS_PRUEBA_{modo.upper()}"}
    if modo == "fl2va":
        valores["end_image"] = subir(imagen_prueba(DATA_DIR / "tests" / "final.png", (60, 40, 140), (20, 160, 150), "FINAL"))
    t0 = time.time()
    salidas = descargar_salidas(esperar(encolar(vw.materialize(base, PROFILE, valores))))
    videos = [p for p in salidas if p.suffix.lower() in (".mp4", ".webm", ".mov")]
    if not videos:
        raise RuntimeError(f"No se encontró vídeo en las salidas: {salidas}")
    info = ffprobe(videos[0])
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    print(f"  {videos[0].name}: {v.get('width')}x{v.get('height')} · {v.get('nb_read_frames')} frames · "
          f"{float(info.get('format', {}).get('duration', 0)):.2f} s · audio={'sí' if audio else 'no'}")
    ok = str(v.get("nb_read_frames")) == str(frames)
    if not ok:
        print(f"  ⚠️ Frames esperados {frames}")
    registrar(f"h3_{modo}", {"ok": ok, "segundos": SEGUNDOS, "frames": v.get("nb_read_frames"),
                             "tiempo_s": round(time.time() - t0), "fecha": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    display(Video(str(videos[0]), embed=True, width=288))


if PROBAR_H3_SOLO_INICIO:
    prueba_h3("i2va")
if PROBAR_H3_INICIO_FINAL:
    prueba_h3("fl2va")
if PROBAR_QWEN_2512:
    ruta_q = API_DIR / "QWEN_2512_T2I.api.json"
    if not ruta_q.exists():
        raise SystemExit("Activa ACTIVAR_QWEN_2512_T2I en la celda 1 y repite las celdas 4–8.")
    print("▶ Qwen-Image-2512 con los valores de la plantilla oficial")
    t0 = time.time()
    imgs = descargar_salidas(esperar(encolar(json.loads(ruta_q.read_text()))))
    registrar("qwen2512_t2i", {"ok": bool(imgs), "tiempo_s": round(time.time() - t0)})
    for p in imgs:
        display(IPImage(filename=str(p), width=320))
if not (PROBAR_H3_SOLO_INICIO or PROBAR_H3_INICIO_FINAL or PROBAR_QWEN_2512):
    print("Ninguna prueba marcada. Recomendado: PROBAR_H3_SOLO_INICIO con 5 s.")
'''

CELL_FINISH = r'''# @title 11 · Guardar copia de la sesión y (opcional) detener procesos
DETENER_PROCESOS = False  # @param {type:"boolean"}
import shutil

if PERSIST_DIR:
    sesion = PERSIST_DIR / "sesiones" / time.strftime("%Y%m%d_%H%M%S")
    (sesion / "workflows_api").mkdir(parents=True, exist_ok=True)
    for nombre in ["identity.json", "conexion_frutinovelas.json", "informe_exportacion.json", "estado.json"]:
        if (DATA_DIR / nombre).exists():
            shutil.copy2(DATA_DIR / nombre, sesion / nombre)
    for p in API_DIR.glob("*.api.json"):
        shutil.copy2(p, sesion / "workflows_api" / p.name)
    shutil.copytree(LOG_DIR, sesion / "logs", dirs_exist_ok=True)
    if any((DATA_DIR / "tests").iterdir()):
        shutil.copytree(DATA_DIR / "tests", sesion / "pruebas", dirs_exist_ok=True)
    print("✅ Guardado en", sesion, "(sin secretos)")
else:
    print("Sin almacenamiento persistente: no se guarda nada fuera del entorno.")

if DETENER_PROCESOS:
    for nombre in ["cloudflared", "gateway", "comfyui"]:
        pid = PROCS.get(nombre)
        if pid and vivo(pid):
            try:
                os.killpg(int(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(20):
                if not vivo(pid):
                    break
                time.sleep(0.5)
            print(f"Detenido: {nombre}")
        PROCS.pop(nombre, None)
    guardar_pids()
    estado(public_url=None)
    print("✅ Procesos detenidos. Colab: desconecta el entorno. RunPod: detén el pod (el volumen sigue cobrando aunque esté parado).")
else:
    print("Los procesos siguen en marcha. Marca DETENER_PROCESOS para pararlos.")
'''

STEPS_MD = """## Conectar FRUTINOVELAS Studio (en tu PC)

1. Copia la **URL** de la celda 9 y el **token** de la celda 9B.
2. Comprueba la conexión desde el PC (PowerShell, dentro de `frutinovelas-studio`):

   ```powershell
   $env:FRUTI_COMFY_TOKEN = "PEGA_AQUI_EL_TOKEN"
   uv run python scripts/check_colab_connection.py --url {url_ejemplo}
   ```

   Descarga los flujos API exportados a `workflows/api/` y verifica sus SHA-256.
3. En el programa: **Conexiones → ComfyUI** → pega URL y token → **Probar** → **Importar flujo**.
4. {reconexion}
"""

STEPS_VARS = {
    "colab": {
        "url_ejemplo": "https://XXXX.trycloudflare.com",
        "reconexion": "Si Colab se desconecta: vuelve a ejecutar las celdas 1–9 (el token guardado en Drive se reutiliza; "
        "la URL del Quick Tunnel cambia).",
    },
}

PLATFORMS = {
    "colab": {
        "out": ROOT / "notebooks" / "FRUTINOVELAS_ComfyUI_Imagenes_H3_Colab.ipynb",
        "kit": "/content/FRUTINOVELAS_kit",
        "intro": INTRO,
        "config_head": CONFIG_HEAD_COLAB,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "A100", "machine_shape": "hm", "toc_visible": True},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
    },
}


# --------------------------------------------------------------------------- utilidades
def lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": lines(text)}


def code(text: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": lines(text.rstrip("\n"))}


def writefile_cell(rel: str, src: Path, kit: str) -> dict:
    content = src.read_text(encoding="utf-8").replace("\r\n", "\n")
    return code(f"%%writefile {kit}/{rel}\n{content}")


def ui_cell() -> dict:
    data = UI_FILE.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    expected = json.loads((ROOT / "config" / "workflow_profiles.json").read_text(encoding="utf-8"))["profiles"][0][
        "workflow_ui_sha256"
    ]
    if sha != expected:
        raise SystemExit(f"El flujo H3 no coincide con el perfil: {sha} ≠ {expected}")
    text = data.decode("utf-8")
    if "\r" in text or "'''" in text or text.endswith("\\"):
        raise SystemExit("El flujo no se puede incrustar como cadena literal sin alterarlo.")
    body = (
        "# @title 1.6 · Tu flujo H3 (copia exacta; se verifica con SHA-256)\n"
        "import hashlib\n\n"
        f"UI_SHA256 = \"{sha}\"\n"
        f"UI_TEXT = r'''{text}'''\n"
        "datos = UI_TEXT.encode(\"utf-8\")\n"
        "if hashlib.sha256(datos).hexdigest() != UI_SHA256:\n"
        "    raise SystemExit(\"❌ El flujo incrustado no coincide con el original (SHA-256).\")\n"
        "UI_PATH.write_bytes(datos)\n"
        "print(\"✅ Flujo H3 escrito sin cambios:\", UI_PATH, \"·\", UI_SHA256[:12])\n"
    )
    return code(body)


def build(platform: str) -> dict:
    p = PLATFORMS[platform]
    cells = [md(p["intro"]), md("## 1 · Configuración"), code(p["config_head"] + CONFIG_COMMON),
             md("### 1.1–1.6 · Archivos del kit\nScripts y configuración del repositorio FRUTINOVELAS Studio, escritos tal cual. "
                "No hace falta tocarlos.")]
    for rel, src in EMBEDDED:
        cells.append(writefile_cell(rel, src, p["kit"]))
    cells.append(ui_cell())
    cells += [
        md("## 2 · Diagnóstico"), code(CELL_DIAG),
        md("## 3 · Instalación"), code(CELL_INSTALL),
        md("## 4–5 · Modelos"), code(CELL_PLAN), code(CELL_DOWNLOAD),
        md("## 6 · Flujos"), code(CELL_WORKFLOWS),
        md("## 7 · ComfyUI"), code(CELL_START), code(CELL_EXPORT),
        md("## 8 · Conexión segura"), code(CELL_GATEWAY),
        md("## 9 · Datos para el programa"), code(CELL_CONNECTION), code(CELL_TOKEN),
        md(STEPS_MD.format(**STEPS_VARS[platform])),
        md("## 10 · Pruebas reales (opcional)"), code(CELL_TESTS),
        md("## 11 · Cierre"), code(CELL_FINISH),
    ]
    for i, c in enumerate(cells):
        c["id"] = f"fruti-{i:02d}"
    return {"nbformat": 4, "nbformat_minor": 5, "metadata": p["metadata"], "cells": cells}


def main() -> int:
    for platform, p in PLATFORMS.items():
        nb = build(platform)
        p["out"].parent.mkdir(parents=True, exist_ok=True)
        p["out"].write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"Libreta generada: {p['out']} ({len(nb['cells'])} celdas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
