# -*- coding: utf-8 -*-
"""Genera notebooks/Hunyuan3D-2.1_i23d_pbr_local.ipynb con los parámetros oficiales
verificados en gradio_app.py / textureGenPipeline.py / README de Tencent-Hunyuan/Hunyuan3D-2.1."""
import json

cells = []


def md(src: str):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": src.strip("\n").splitlines(keepends=True)})


def py(src: str):
    cells.append({
        "cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
        "source": src.strip("\n").splitlines(keepends=True),
    })


md(r"""
# Hunyuan3D 2.1 — Image to 3D con texturas PBR (100% local)

Notebook local para generación **Image-to-3D** con **Hunyuan3D-2.1** (Tencent) usando la **API oficial**
(`hy3dshape` + `hy3dpaint` del repo [Tencent-Hunyuan/Hunyuan3D-2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)).
**Todos los parámetros son los por defecto verbatim del `gradio_app.py` oficial** (demo de Tencent).

| Etapa | Modelo (HuggingFace, auto-descarga) | VRAM |
|---|---|---|
| 1. Geometría | `tencent/Hunyuan3D-2.1` → `hunyuan3d-dit-v2-1` (3.3B) | ~10 GB |
| 2. Textura PBR | `tencent/Hunyuan3D-2.1` → `hunyuan3d-paintpbr-v2-1` (2B) + `facebook/dinov2-giant` | ~21 GB |

> La demo oficial mantiene ambos modelos en memoria → **29 GB VRAM**. Este notebook **libera el
> modelo de forma antes de pintar**, por lo que cabe en GPUs de **21–24 GB** (3090/4090/A5000+).
>
> Requisitos oficiales: **Python 3.10**, **PyTorch 2.5.1+cu124**, NVIDIA GPU, ~30 GB de disco.
> Licencia: *Tencent Hunyuan Community License* (uso académico/no comercial).

**Pipeline (flujo real del `gradio_app.py`):**
```text
imagen (PIL) → [rembg opcional] → Hunyuan3DDiTFlowMatchingPipeline (DiT flow-matching)
  → export_to_trimesh → white_mesh.obj
→ Hunyuan3DPaintPipeline (SD2.1 multiview + DINOv2 + RealESRGAN + bake)
  → textured_mesh.obj + albedo/metallic/roughness (.jpg)
→ create_glb_with_pbr_materials → textured_mesh.glb
```
""")

md(r"""
## PASO 1 — Instalación única (PowerShell, fuera del notebook)

> Solo la **primera vez**. **No uses el `.venv` de frutinovelas-studio** (es el de la app: Python 3.12 sin torch).
> `uv` ya está instalado (0.11.x); si lo prefieres, sustituye `uv venv/uv pip` por `python -m venv`/`pip`.

```powershell
# 1) Clonar el repo oficial
git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git D:\Hunyuan3D-2.1
cd D:\Hunyuan3D-2.1

# 2) venv dedicado (Python 3.10, versión testada por Tencent)
uv venv .venv --python 3.10
.\.venv\Scripts\Activate

# 3) PyTorch 2.5.1 + cu124 (combinación probada)
uv pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124

# 4) Dependencias completas del repo
uv pip install -r requirements.txt
uv pip install jupyterlab ipykernel        # para correr ESTE notebook dentro del venv
```

**5) Rasterizador CUDA** — es un `CUDAExtension` (`.cpp` + `.cu`): **requiere CUDA Toolkit 12.x con `nvcc`
en PATH + Visual Studio Build Tools (C++)**. Ajusta la versión de CUDA a la tuya:

```powershell
$env:PATH = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4\bin;" + $env:PATH
cd D:\Hunyuan3D-2.1\hy3dpaint\custom_rasterizer
uv pip install -e .
```

**6) DifferentiableRenderer** — el script oficial `compile_mesh_painter.sh` es simplemente
`c++ -O3 -shared -std=c++11 -fPIC $(python -m pybind11 --includes) mesh_inpaint_processor.cpp -o ...pyd`.
En **Windows (Git Bash)**:

```bash
cd /d/Hunyuan3D-2.1/hy3dpaint/DifferentiableRenderer
g++ -O3 -Wall -shared -std=c++11 -fPIC $(python -m pybind11 --includes) mesh_inpaint_processor.cpp -o mesh_inpaint_processor.pyd
```

```powershell
# 7) RealESRGAN (peso MANUAL, obligatorio)
New-Item -ItemType Directory -Force hy3dpaint\ckpt | Out-Null
Invoke-WebRequest "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth" -OutFile hy3dpaint\ckpt\RealESRGAN_x4plus.pth

# 8) Jupyter desde dentro del venv
jupyter lab
```

**Pesos que se descargan SOLOS la primera vez** (HuggingFace, sin token):
| Peso | Origen |
|---|---|
| DiT v2.1 (3.3B) | `tencent/Hunyuan3D-2.1/hunyuan3d-dit-v2-1` (≈7 GB) |
| Paint PBR (2B, incluye base SD 2.1) | `tencent/Hunyuan3D-2.1/hunyuan3d-paintpbr-v2-1` (≈8 GB) |
| DINOv2-giant | `facebook/dinov2-giant` (≈5 GB) |
| RealESRGAN | GitHub (punto 7, manual) |

> ⚠️ Si algún paquete de `requirements.txt` (p. ej. `tb_nightly`, `pymeshlab==2022.2.post3`) no tiene rueda
> para tu sistema, es opcional para inferencia: instálalo por separado con la última versión disponible.
""")
py(r"""
import os

# ══════════════════ TUS AJUSTES ══════════════════
# Ruta del clone del repo oficial (PASO 1)
HY3D_REPO = r"D:\Hunyuan3D-2.1"

# Imagen de entrada (PNG/JPG). RGBA (fondo transparente) = mejor resultado.
IMAGE_PATH = r"D:\fruti.cap\frutinovelas-studio\notebooks\input_image.png"

# Carpeta de salida (se crea sola)
SAVE_DIR = os.path.join(HY3D_REPO, "save_dir_notebook")

# ── Modelo (valores por defecto oficiales del gradio_app.py / README) ──
MODEL_ID = "tencent/Hunyuan3D-2.1"
SHAPE_SUBFOLDER = "hunyuan3d-dit-v2-1"   # Image-to-Shape 3.3B
DEVICE = "cuda"

# ── Generación de forma (defaults oficiales de _gen_shape) ──
SEED = 1234
NUM_INFERENCE_STEPS = 50     # modo rápido: 30 · turbo: 5
GUIDANCE_SCALE = 7.5         # modo rápido: 5.0
OCTREE_RESOLUTION = 256      # Low=196 · Standard=256 · High=384
NUM_CHUNKS = 200000          # modo rápido: 8000 (memoria en el decode de tetraedros)
REMOVE_BACKGROUND = True     # rembg (U²-Net) si la imagen no tiene canal alfa

# ── Simplificación geométrica opcional (el gradio usa FaceReducer antes de pintar) ──
REDUCE_FACES = False         # True = reduce caras antes de texturizar
TARGET_FACES = 500_000       # solo si REDUCE_FACES=True

# ── Textura PBR (defaults oficiales: gradio_app + README de hy3dpaint) ──
RUN_PAINT = True
PAINT_MAX_NUM_VIEW = 8       # 6–12 · usa 6 si tienes 24 GB justos
PAINT_RESOLUTION = 768       # 512 o 768 · 512 ahorra VRAM y tiempo
USE_REMESH = True            # re-mallado automático del mesh
SAVE_GLB_IN_PIPELINE = False # ruta oficial: False + create_glb_with_pbr_materials

# ── Comprobaciones ──
assert os.path.isdir(HY3D_REPO), \
    f"❌ HY3D_REPO no existe: {HY3D_REPO}\n   Ejecuta el PASO 1 (clonar el repo)."
assert os.path.isfile(os.path.join(HY3D_REPO, "gradio_app.py")), \
    f"❌ {HY3D_REPO} no parece el repo de Hunyuan3D-2.1 (falta gradio_app.py)."

_img_ok = os.path.exists(IMAGE_PATH)
print("Config ✓")
print(f"  repo     : {HY3D_REPO}")
print(f"  imagen   : {IMAGE_PATH}   {'✓' if _img_ok else '❗ FALTA — guarda tu imagen en esa ruta'}")
print(f"  forma    : {MODEL_ID}/{SHAPE_SUBFOLDER} @ {DEVICE}")
print(f"  steps/cfg: {NUM_INFERENCE_STEPS} / {GUIDANCE_SCALE} | octree {OCTREE_RESOLUTION} | chunks {NUM_CHUNKS} | seed {SEED}")
print(f"  paint    : run={RUN_PAINT} | views={PAINT_MAX_NUM_VIEW} | res={PAINT_RESOLUTION}")
print(f"  salida   : {SAVE_DIR}")
if not _img_ok:
    raise FileNotFoundError("Coloca una imagen en IMAGE_PATH antes de continuar.")
""")

py(r"""
import gc
import os
import sys
import time
try:
    import torch
except ImportError:
    raise SystemExit("❌ Este notebook debe correr con el venv del PASO 1 (Python 3.10 + torch 2.5.1+cu124).\n   Interpreter actual: " + sys.executable)

# Importar igual que en README + gradio_app.py: raíz del repo + paquetes
sys.path.insert(0, HY3D_REPO)
sys.path.insert(0, os.path.join(HY3D_REPO, "hy3dshape"))
sys.path.insert(0, os.path.join(HY3D_REPO, "hy3dpaint"))

print(f"python : {sys.executable}")
print(f"torch  : {torch.__version__} | cuda: {torch.cuda.is_available()}", end="")
if torch.cuda.is_available():
    gi = torch.cuda.get_device_properties(0)
    print(f" | GPU {gi.name} ({gi.total_memory / 2 ** 30:.1f} GB VRAM)")
else:
    print("\n❌ Sin GPU: Hunyuan3D 2.1 requiere NVIDIA GPU (usar CUDA).")

# Pre-chequeo de dependencias de la textura (marcan ✖ sin romper la forma)
realesrgan_ok = os.path.isfile(os.path.join(HY3D_REPO, "hy3dpaint", "ckpt", "RealESRGAN_x4plus.pth"))
try:
    import custom_rasterizer  # noqa: F401
    rasterizer_ok = True
except Exception as e:
    rasterizer_ok = False
    print("⚠  custom_rasterizer no importable (necesario para pintar):", repr(e)[:160])
try:
    from DifferentiableRenderer.mesh_inpaint_processor import meshVerticeInpaint  # noqa: F401
    renderer_ok = True
except Exception as e:
    renderer_ok = False
    print("⚠  mesh_inpaint_processor no importable (necesario para pintar):", repr(e)[:160])

print(f"custom_rasterizer      : {'✓' if rasterizer_ok else '✖ (PASO 1, punto 5)'}")
print(f"mesh_inpaint_processor : {'✓' if renderer_ok else '✖ (PASO 1, punto 6)'}")
print(f"RealESRGAN ckpt        : {'✓' if realesrgan_ok else '✖ (PASO 1, punto 7)'}")
if RUN_PAINT and not (rasterizer_ok and renderer_ok and realesrgan_ok):
    print("\n⚠  RUN_PAINT=True pero faltan dependencias de pintura. Completa primero el PASO 1.")
""")
py(r"""
import time
from IPython.display import display
from PIL import Image

t0 = time.time()
image = Image.open(IMAGE_PATH)

# Lógica oficial del gradio: aplicar rembg si se marcó o si la imagen no tiene alfa
if REMOVE_BACKGROUND or image.mode == "RGB":
    from hy3dshape.rembg import BackgroundRemover
    _rmbg = BackgroundRemover()
    try:
        image = _rmbg(image.convert("RGB"))
    finally:
        del _rmbg
        gc.collect()

print(f"Imagen lista: {image.size} {image.mode}  ({time.time() - t0:.1f}s)")
display(image)
""")

py(r"""
from hy3dshape import Hunyuan3DDiTFlowMatchingPipeline
from hy3dshape.pipelines import export_to_trimesh

t0 = time.time()
i23d_worker = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
    MODEL_ID,
    subfolder=SHAPE_SUBFOLDER,
    use_safetensors=False,   # el repo oficial usa *.bin
    device=DEVICE,
)
print(f"Shape pipeline listo en {time.time() - t0:.0f}s (la 1ª vez descarga ~7 GB de HF).")
""")

py(r"""
import trimesh

t0 = time.time()
generator = torch.Generator()
generator = generator.manual_seed(int(SEED))
outputs = i23d_worker(
    image=image,
    num_inference_steps=NUM_INFERENCE_STEPS,
    guidance_scale=GUIDANCE_SCALE,
    generator=generator,
    octree_resolution=OCTREE_RESOLUTION,
    num_chunks=NUM_CHUNKS,
    output_type="mesh",
)
white_mesh = export_to_trimesh(outputs)[0]
del outputs
gc.collect()

# Simplificación opcional (FaceReducer oficial)
if REDUCE_FACES:
    from hy3dshape import FaceReducer
    white_mesh = FaceReducer()(white_mesh, TARGET_FACES)

os.makedirs(SAVE_DIR, exist_ok=True)
white_obj = os.path.join(SAVE_DIR, "white_mesh.obj")
white_glb = os.path.join(SAVE_DIR, "white_mesh.glb")
white_mesh.export(white_obj)
white_mesh.export(white_glb)

t_shape = time.time() - t0
print(f"Forma: {white_mesh.vertices.shape[0]} vertices / {white_mesh.faces.shape[0]} caras — {t_shape:.0f}s")
print(f"Guardado: {white_obj}")
print(f"Guardado: {white_glb}")
""")

py(r"""
# El gradio oficial mantiene AMBOS modelos en VRAM (~29 GB).
# Aquí se libera la memoria de la forma para que la textura (~21 GB) quepa en 24 GB.
del i23d_worker
gc.collect()
torch.cuda.empty_cache()
free, total = torch.cuda.mem_get_info()
print(f"VRAM libre tras liberar la forma: {free / 2 ** 30:.1f} / {total / 2 ** 30:.1f} GB")
""")
py(r"""
from hy3dpaint.textureGenPipeline import Hunyuan3DPaintPipeline, Hunyuan3DPaintConfig

t0 = time.time()
conf = Hunyuan3DPaintConfig(max_num_view=PAINT_MAX_NUM_VIEW, resolution=PAINT_RESOLUTION)
conf.realesrgan_ckpt_path = os.path.join(HY3D_REPO, "hy3dpaint", "ckpt", "RealESRGAN_x4plus.pth")
conf.multiview_cfg_path = os.path.join(HY3D_REPO, "hy3dpaint", "cfgs", "hunyuan-paint-pbr.yaml")
conf.custom_pipeline = os.path.join(HY3D_REPO, "hy3dpaint", "hunyuanpaintpbr")
conf.device = DEVICE
tex_pipeline = Hunyuan3DPaintPipeline(conf)
print(f"Paint (PBR) pipeline listo en {time.time() - t0:.0f}s (la 1ª vez descarga pesos PBR + DINOv2).")

t0 = time.time()
textured_obj = os.path.join(SAVE_DIR, "textured_mesh.obj")
output_path = tex_pipeline(
    mesh_path=white_obj,           # OBJ blanco de la celda anterior
    image_path=image,              # misma imagen (tras rembg)
    output_mesh_path=textured_obj,
    use_remesh=USE_REMESH,
    save_glb=SAVE_GLB_IN_PIPELINE,
)
print(f"Textura PBR aplicada en {time.time() - t0:.0f}s")
print("Salida:", output_path)
""")

py(r"""
from hy3dpaint.convert_utils import create_glb_with_pbr_materials

# El gradio oficial convierte el OBJ texturizado a GLB con estos mapas PBR
textures = {
    "albedo":    textured_obj.replace(".obj", ".jpg"),
    "metallic":  textured_obj.replace(".obj", "_metallic.jpg"),
    "roughness": textured_obj.replace(".obj", "_roughness.jpg"),
}
for k, v in textures.items():
    assert os.path.isfile(v), f"Falta el mapa {k}: {v}"

textured_glb = os.path.join(SAVE_DIR, "textured_mesh.glb")
create_glb_with_pbr_materials(textured_obj, textures, textured_glb)

textured_mesh = trimesh.load(textured_obj)
print(f"Malla texturizada: {textured_mesh.vertices.shape[0]} vert / {textured_mesh.faces.shape[0]} caras")
print(f"GLB final: {textured_glb} ({os.path.getsize(textured_glb) / 2 ** 20:.0f} MB)")
print("\nArchivos generados:")
for f in sorted(os.listdir(SAVE_DIR)):
    p = os.path.join(SAVE_DIR, f)
    if os.path.isfile(p):
        print(f"  {f:26s} {os.path.getsize(p) / 2 ** 20:8.1f} MB")
""")

py(r"""
# Vista 3D opcional en el notebook (pythreejs, incluido en requirements.txt)
try:
    import pythreejs as p3d
    scene = p3d.Scene(
        bg=0xf0f0f0,
        camera=p3d.PerspectiveCamera(up=[0, 0, 1], position=[2.0, 2.0, 2.0], fov=30),
        objects=[
            p3d.Mesh(geometry=p3d.BufferGeometry.from_trimesh(white_mesh)),
            p3d.AxesHelper(1.2),
        ],
        lights=[p3d.DirectionalLight(color=0xffffff, intensity=1.5, position=[2, 3, 2]),
                p3d.AmbientLight(color=0xffffff, intensity=0.7)],
    )
    display(p3d.Output(), scene)
except Exception as e:
    print("Vista 3D no disponible (pythreejs sin instalar?). Abre textured_mesh.glb en:")
    print("  - El Explorador de Windows 11 (vista 3D) | Blender | Spline/Model Viewer")
    print("   :::", repr(e)[:200])
""")

md(r"""
## Solución de problemas

| Síntoma | Causa / solución |
|---|---|
| `ModuleNotFoundError: custom_rasterizer` | PASO 1-punto 5 (nvcc en PATH + MSVC Build Tools; `uv pip install -e .`) |
| `ImportError ... mesh_inpaint_processor` | PASO 1-punto 6 (compilar el renderer; el `.pyd` queda junto al `.cpp`) |
| `FileNotFoundError ... RealESRGAN_x4plus.pth` | PASO 1-punto 7 (peso manual) |
| `CUDA out of memory` en la **forma** | `OCTREE_RESOLUTION=196`, `NUM_CHUNKS=8000`, `NUM_INFERENCE_STEPS=30` |
| `CUDA out of memory` en el **paint** | `PAINT_MAX_NUM_VIEW=6`, `PAINT_RESOLUTION=512`; verifica la celda "libera VRAM" |
| Falla compilar `rasterizer_gpu.cu` | CUDA Toolkit 12.x en PATH + Visual Studio 2019/2022 (C++) |
| Baja la 1ª vez | ~20 GB desde HF; quedan cacheados en `~/.cache/huggingface` |
| Artes en el resultado | Otro `SEED`; imagen centrada con poco fondo; `REMOVE_BACKGROUND=True` |
| `bash: command not found` | Usa Git Bash (incluye `g++`/MinGW) o el comando `g++` manual del PASO 1 |

> **Licencia**: pesos con *Tencent Hunyuan Community License* — revisión del archivo LICENSE del repo antes de uso comercial.
> **Limpieza**: `tmp_hy3d/` (gradio_app.py, README, requirements) solo sirvió para verificar esta API; se puede borrar.
""")

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = r"D:\fruti.cap\frutinovelas-studio\notebooks\Hunyuan3D-2.1_i23d_pbr_local.ipynb"
with open(out, "w", encoding="utf-8", newline="\n") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
print(f"OK: {len(cells)} celdas -> {out}")

