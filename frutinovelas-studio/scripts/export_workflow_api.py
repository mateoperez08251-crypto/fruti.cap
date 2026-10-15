"""Exporta un flujo de interfaz ComfyUI a formato API usando el propio frontend.

Abre la interfaz del ComfyUI en marcha con Chromium sin ventana, carga el JSON de
interfaz y llama a ``app.graphToPrompt()``: es exactamente lo que hace el menú
*Workflow → Export (API)*. Así se resuelven subgrafos, widgets dinámicos y
entradas que la conversión manual no puede adivinar.

Uso::

    python export_workflow_api.py --comfy http://127.0.0.1:8188 \
        --ui flujo.ui.json --out flujo.api.json

Requiere ``playwright`` y Chromium (``python -m playwright install --with-deps chromium``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

JS_FIND_APP = """
() => {
  const a = window.app || (window.comfyAPI && window.comfyAPI.app && window.comfyAPI.app.app);
  return !!(a && a.graph && typeof a.graphToPrompt === 'function' && typeof a.loadGraphData === 'function');
}
"""

JS_EXPORT = """
async ({workflow, required}) => {
  const a = window.app || window.comfyAPI.app.app;
  const LG = window.LiteGraph || (window.comfyAPI && window.comfyAPI.litegraph && window.comfyAPI.litegraph.LiteGraph);
  const missing = [];
  if (LG && LG.registered_node_types) {
    for (const t of required) { if (!LG.registered_node_types[t]) missing.push(t); }
  }
  if (missing.length) { return {error: 'Nodos no registrados en el frontend: ' + missing.join(', ')}; }
  await a.loadGraphData(workflow, true, false);
  await new Promise(r => setTimeout(r, 1500));
  const p = await a.graphToPrompt();
  return {output: p.output};
}
"""


def export_api(comfy_url: str, ui_workflow: dict, timeout_s: float = 180.0) -> dict:
    from playwright.sync_api import sync_playwright

    required = sorted(
        {
            n["type"]
            for n in ui_workflow.get("nodes", [])
            if n.get("type") not in ("Note", "MarkdownNote", "Reroute", "PrimitiveNode")
            and "-" not in str(n.get("type"))  # los UUID de subgrafos se resuelven en el frontend
        }
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.goto(comfy_url.rstrip("/") + "/", wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
            page.wait_for_function(JS_FIND_APP, timeout=int(timeout_s * 1000))
            # Margen para que las extensiones registren todos los nodos.
            page.wait_for_timeout(3000)
            result = page.evaluate(JS_EXPORT, {"workflow": ui_workflow, "required": required})
        finally:
            browser.close()
    if not isinstance(result, dict) or result.get("error"):
        raise RuntimeError((result or {}).get("error") or "La exportación no devolvió resultado.")
    output = result.get("output")
    if not isinstance(output, dict) or not output:
        raise RuntimeError("graphToPrompt devolvió un grafo vacío.")
    return output


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Exporta un flujo de interfaz ComfyUI a formato API")
    ap.add_argument("--comfy", default="http://127.0.0.1:8188")
    ap.add_argument("--ui", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args(argv)

    ui = json.loads(Path(args.ui).read_text(encoding="utf-8"))
    if not (isinstance(ui, dict) and isinstance(ui.get("nodes"), list)):
        print("ERROR: el archivo no es un JSON de interfaz ComfyUI (falta 'nodes').", file=sys.stderr)
        return 2
    api = export_api(args.comfy, ui, args.timeout)
    out = Path(args.out)
    tmp = out.with_suffix(out.suffix + ".partial")
    tmp.write_text(json.dumps(api, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    print(f"API exportada: {out} ({len(api)} nodos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
