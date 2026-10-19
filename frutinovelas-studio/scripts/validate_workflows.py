"""Validación y utilidades de grafos ComfyUI para FRUTINOVELAS.

Sin dependencias externas: lo usan la libreta Colab, las pruebas y el programa.

- Detecta si un JSON es de interfaz (``nodes``/``links``) o de API.
- Valida un grafo API contra ``/object_info`` real: clases, entradas obligatorias,
  enlaces, opciones de combos (incluidos los nombres de modelos instalados) y rangos.
- Comprueba un perfil FRUTINOVELAS (IDs, clases y valores esperados).
- Deriva la variante solo-inicio (I2VA) eliminando de verdad ``last_frame``.
- Materializa un trabajo sobre una COPIA del grafo cambiando solo campos mapeados.

Uso por línea de órdenes::

    python validate_workflows.py H3_USUARIO_INICIO_FINAL.api.json \
        --object-info object_info.json --profiles workflow_profiles.json --mode fl2va
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

# Entradas de LoadImage cuyo valor se sustituye en cada trabajo: no deben exigir
# que el placeholder exista en el servidor.
PLACEHOLDER_INPUTS = {("LoadImage", "image")}


# --------------------------------------------------------------------------- formato
def detect_format(data: Any) -> str:
    """Devuelve ``"ui"``, ``"api"`` o ``"unknown"``."""
    if isinstance(data, dict) and isinstance(data.get("nodes"), list) and "links" in data:
        return "ui"
    if isinstance(data, dict) and data and all(
        isinstance(v, dict) and "class_type" in v and isinstance(v.get("inputs"), dict) for v in data.values()
    ):
        return "api"
    return "unknown"


def is_link(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], int)
        and not isinstance(value[1], bool)
    )


def combo_options(spec: Any) -> list | None:
    """Opciones de un input combo en cualquiera de los formatos de /object_info."""
    if not isinstance(spec, (list, tuple)) or not spec:
        return None
    first = spec[0]
    if isinstance(first, list):
        return first
    if first == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        opts = spec[1].get("options")
        return list(opts) if isinstance(opts, (list, tuple)) else None
    return None


def _input_specs(info: dict) -> tuple[dict, dict]:
    inp = info.get("input") or {}
    return dict(inp.get("required") or {}), dict(inp.get("optional") or {})


# --------------------------------------------------------------------------- validación
def validate_api_graph(graph: dict, object_info: dict | None = None) -> dict:
    """Valida un grafo API. Devuelve ``{"errors": [...], "warnings": [...]}``."""
    errors: list[str] = []
    warnings: list[str] = []

    if detect_format(graph) != "api":
        return {"errors": ["El JSON no tiene formato API (se esperaba {id: {class_type, inputs}})."], "warnings": []}

    for node_id, node in graph.items():
        ctype = node["class_type"]
        inputs = node["inputs"]
        info = (object_info or {}).get(ctype) if object_info is not None else None
        if object_info is not None and info is None:
            errors.append(f"Nodo {node_id}: la clase '{ctype}' no existe en este ComfyUI (nodo ausente).")
            continue

        for name, value in inputs.items():
            if is_link(value):
                src_id = str(value[0])
                src = graph.get(src_id)
                if src is None:
                    errors.append(f"Nodo {node_id}.{name}: enlace a nodo inexistente {src_id}.")
                    continue
                if object_info is not None:
                    src_info = object_info.get(src["class_type"])
                    if src_info is not None:
                        n_out = len(src_info.get("output") or [])
                        if value[1] < 0 or value[1] >= n_out:
                            errors.append(
                                f"Nodo {node_id}.{name}: salida {value[1]} fuera de rango en {src_id} ({src['class_type']})."
                            )

        if info is None:
            continue
        required, optional = _input_specs(info)
        for name in required:
            if name not in inputs:
                # Native Qwen 2.1 declares an Autogrow group with min=0.
                # Text-to-image legitimately has no images.image_N inputs.
                if ctype == "TextEncodeQwenImage21" and name == "images":
                    continue
                # Los inputs dinámicos (Autogrow/DynamicCombo) se serializan con
                # claves con punto; si existe alguna con ese prefijo, se acepta.
                if any(k.startswith(name + ".") for k in inputs):
                    continue
                errors.append(f"Nodo {node_id} ({ctype}): falta la entrada obligatoria '{name}'.")
        all_specs = {**required, **optional}
        for name, value in inputs.items():
            if is_link(value) or name not in all_specs:
                continue
            spec = all_specs[name]
            opts = combo_options(spec)
            if opts is not None:
                if value not in opts:
                    msg = f"Nodo {node_id} ({ctype}).{name}: valor '{value}' no está entre las opciones del servidor."
                    if (ctype, name) in PLACEHOLDER_INPUTS:
                        warnings.append(msg + " (placeholder: el programa lo sustituye al subir la imagen)")
                    else:
                        errors.append(msg)
                continue
            if isinstance(spec, (list, tuple)) and spec and spec[0] in ("INT", "FLOAT"):
                cfg = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    lo, hi = cfg.get("min"), cfg.get("max")
                    if lo is not None and value < lo:
                        errors.append(f"Nodo {node_id} ({ctype}).{name}: {value} < mínimo {lo}.")
                    if hi is not None and value > hi:
                        errors.append(f"Nodo {node_id} ({ctype}).{name}: {value} > máximo {hi}.")
                else:
                    errors.append(f"Nodo {node_id} ({ctype}).{name}: se esperaba número y llegó {value!r}.")

    outputs = [nid for nid, n in graph.items() if n["class_type"] in ("SaveVideo", "SaveImage", "SaveAnimatedWEBP", "SaveWEBM")]
    if not outputs:
        warnings.append("No se encontró ningún nodo de guardado conocido (SaveVideo/SaveImage).")
    return {"errors": errors, "warnings": warnings}


# --------------------------------------------------------------------------- perfiles
def load_profile(profiles_path: str | Path, key: str) -> dict:
    data = json.loads(Path(profiles_path).read_text(encoding="utf-8"))
    for p in data.get("profiles", []):
        if p.get("key") == key:
            return p
    raise KeyError(f"Perfil '{key}' no encontrado en {profiles_path}")


def _iter_mapping_refs(mapping: dict):
    for field, ref in mapping.items():
        if ref is None:
            continue
        refs = ref if isinstance(ref, list) else [ref]
        for r in refs:
            if isinstance(r, dict) and "node_id" in r:
                yield field, r


def check_profile(graph: dict, profile: dict, mode: str) -> dict:
    """Comprueba que el grafo API corresponde al perfil y al modo (fl2va/i2va)."""
    errors: list[str] = []
    warnings: list[str] = []
    mapping = profile["mapping"]
    disabled_nodes: set[str] = set()
    if mode == "i2va":
        dis = profile["modes"]["i2va"]["end_image_disable"]
        disabled_nodes = {str(n) for n in dis.get("remove_nodes", [])}

    for field, ref in _iter_mapping_refs(mapping):
        nid = str(ref["node_id"])
        if nid in disabled_nodes:
            if nid in graph:
                errors.append(f"Modo {mode}: el nodo {nid} ({field}) debería haberse eliminado.")
            continue
        node = graph.get(nid)
        if node is None:
            errors.append(f"Mapeo '{field}': el nodo {nid} no existe en el grafo API.")
            continue
        want = ref.get("class_type")
        if want and node["class_type"] != want:
            errors.append(f"Mapeo '{field}': el nodo {nid} es '{node['class_type']}', se esperaba '{want}'.")
        if field != "outputs" and ref.get("input") and ref["input"] not in node["inputs"]:
            errors.append(f"Mapeo '{field}': el nodo {nid} no tiene la entrada '{ref['input']}'.")

    for nid, expected in (profile.get("expected_values") or {}).items():
        if nid in disabled_nodes:
            continue
        node = graph.get(nid)
        if node is None:
            errors.append(f"Valor esperado: falta el nodo {nid}.")
            continue
        for k, v in expected.items():
            if k == "class_type":
                if node["class_type"] != v:
                    errors.append(f"Nodo {nid}: clase '{node['class_type']}' ≠ esperada '{v}'.")
                continue
            got = node["inputs"].get(k)
            if is_link(got):
                warnings.append(f"Nodo {nid}.{k}: está enlazado; no se compara con {v!r}.")
            elif got != v and not (isinstance(got, (int, float)) and isinstance(v, (int, float)) and float(got) == float(v)):
                errors.append(f"Nodo {nid}.{k}: {got!r} ≠ esperado {v!r}.")

    start = mapping.get("start_image")
    h3_id = str(mapping["positive_prompt"]["node_id"])
    h3 = graph.get(h3_id)
    if h3 is not None:
        ff = h3["inputs"].get("first_frame")
        if not (is_link(ff) and start and str(ff[0]) == str(start["node_id"])):
            errors.append(f"first_frame del nodo {h3_id} no está enlazado al LoadImage inicial.")
        lf = h3["inputs"].get("last_frame")
        if mode == "fl2va":
            end = mapping.get("end_image")
            if not (is_link(lf) and end and str(lf[0]) == str(end["node_id"])):
                errors.append(f"last_frame del nodo {h3_id} no está enlazado al LoadImage final.")
        elif mode == "i2va" and lf is not None:
            errors.append(f"Modo i2va: last_frame del nodo {h3_id} sigue presente.")
    return {"errors": errors, "warnings": warnings}


def derive_i2va(graph: dict, profile: dict) -> dict:
    """Copia del grafo sin imagen final: elimina el input y los nodos indicados.

    No duplica la imagen inicial ni inyecta una imagen vacía.
    """
    g = copy.deepcopy(graph)
    dis = profile["modes"]["i2va"]["end_image_disable"]
    if dis.get("strategy") != "remove_link":
        raise ValueError(f"Estrategia no soportada: {dis.get('strategy')}")
    consumer = g.get(str(dis["consumer"]["node_id"]))
    if consumer is None:
        raise ValueError("El nodo consumidor de la imagen final no existe en el grafo.")
    consumer["inputs"].pop(dis["consumer"]["input"], None)
    for nid in dis.get("remove_nodes", []):
        nid = str(nid)
        still_used = [
            other_id
            for other_id, other in g.items()
            if other_id != nid and any(is_link(v) and str(v[0]) == nid for v in other["inputs"].values())
        ]
        if still_used:
            raise ValueError(f"No se puede eliminar el nodo {nid}: lo usan también {still_used}.")
        g.pop(nid, None)
    return g


def apply_loader_overrides(graph: dict, overrides: dict[str, str]) -> tuple[dict, list[str]]:
    """Sustituye nombres de pesos exactos (perfil alternativo explícito)."""
    g = copy.deepcopy(graph)
    changes: list[str] = []
    if not overrides:
        return g, changes
    for nid, node in g.items():
        for k, v in node["inputs"].items():
            if isinstance(v, str) and v in overrides:
                node["inputs"][k] = overrides[v]
                changes.append(f"Nodo {nid} ({node['class_type']}).{k}: {v} → {overrides[v]}")
    return g, changes


# --------------------------------------------------------------------------- duración
def quantize_frames(seconds: float, rule: dict) -> tuple[int, float]:
    """Réplica de la fórmula del nodo de duración: frames efectivos y segundos reales."""
    fps = int(rule["fps"])
    step = int(rule["grid_step"])
    offset = int(rule["grid_offset"])
    min_frames = int(rule.get("min_frames", offset))
    base = max(min_frames, round(float(seconds) * fps))  # round() de Python, igual que simpleeval
    frames = base + (offset - base % step) % step
    return frames, frames / fps


# --------------------------------------------------------------------------- materializar
def materialize(graph: dict, profile: dict, values: dict) -> dict:
    """Copia del grafo con los campos mapeados sustituidos. Nada más se toca.

    ``values`` admite: start_image, end_image, positive_prompt, seed, duration,
    width, height, steps, filename_prefix.
    """
    g = copy.deepcopy(graph)
    mapping = profile["mapping"]
    for field, value in values.items():
        if value is None:
            continue
        ref = mapping.get(field)
        if ref is None:
            raise KeyError(f"El perfil no mapea el campo '{field}'.")
        refs = ref if isinstance(ref, list) else [ref]
        for r in refs:
            node = g.get(str(r["node_id"]))
            if node is None:
                raise KeyError(f"Campo '{field}': el nodo {r['node_id']} no está en el grafo.")
            if r.get("class_type") and node["class_type"] != r["class_type"]:
                raise ValueError(f"Campo '{field}': clase inesperada {node['class_type']}.")
            if r["input"] not in node["inputs"]:
                raise KeyError(f"Campo '{field}': el nodo {r['node_id']} no tiene '{r['input']}'.")
            if is_link(node["inputs"][r["input"]]):
                raise ValueError(f"Campo '{field}': la entrada está enlazada y no se puede fijar.")
            node["inputs"][r["input"]] = value
    return g


def ui_nodes_missing_in_api(ui: dict, api: dict) -> list[str]:
    """Nodos de la interfaz que no aparecen en la API (las notas son normales)."""
    out = []
    for n in ui.get("nodes", []):
        if str(n["id"]) not in api:
            out.append(f"{n['id']} ({n.get('type')})")
    return out


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Valida grafos ComfyUI para FRUTINOVELAS")
    ap.add_argument("graph")
    ap.add_argument("--object-info")
    ap.add_argument("--profiles")
    ap.add_argument("--profile-key", default="h3_equilibrado_9x16")
    ap.add_argument("--mode", choices=["fl2va", "i2va"])
    args = ap.parse_args(argv)

    data = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    fmt = detect_format(data)
    print(f"Formato: {fmt}")
    if fmt != "api":
        print("ERROR: se necesita la exportación API (Workflow → Export (API)).")
        return 2
    oi = json.loads(Path(args.object_info).read_text(encoding="utf-8")) if args.object_info else None
    rep = validate_api_graph(data, oi)
    if args.profiles and args.mode:
        prof = load_profile(args.profiles, args.profile_key)
        r2 = check_profile(data, prof, args.mode)
        rep["errors"] += r2["errors"]
        rep["warnings"] += r2["warnings"]
    for w in rep["warnings"]:
        print("AVISO:", w)
    for e in rep["errors"]:
        print("ERROR:", e)
    print("OK" if not rep["errors"] else f"{len(rep['errors'])} error(es)")
    return 0 if not rep["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
