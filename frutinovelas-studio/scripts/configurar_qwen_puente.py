"""Switch only the existing Qwen provider to Studio's loopback SSE bridge."""
from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from frutinovelas.config import get_settings
from frutinovelas.flow_vision import load_connection
from frutinovelas.services.flow_transport import FlowError


def update(data, kind, remote, local, model):
    updated = copy.deepcopy(data)
    if kind == "providers":
        settings = updated.get("providers", {}).get("openai-compatible", {}).get("settings")
        if not isinstance(settings, dict) or settings.get("baseUrl", "").rstrip("/") not in (remote, local):
            raise ValueError("El proveedor actual no corresponde al Qwen configurado. No se modificó.")
        settings["baseUrl"], settings["model"] = local, model
    elif kind == "global":
        if updated.get("openAiBaseUrl", "").rstrip("/") not in (remote, local):
            raise ValueError("La configuración antigua apunta a otro proveedor. No se modificó.")
        updated["openAiBaseUrl"] = local
        for mode in ("plan", "act"):
            if updated.get(mode + "ModeApiProvider") == "openai":
                updated[mode + "ModeOpenAiModelId"] = model
    else:
        raise ValueError("Configuración desconocida.")
    return updated


def install(data_dir, remote, local, model):
    prepared = []
    for relative, kind in (("settings/providers.json", "providers"), ("globalState.json", "global")):
        path = data_dir / relative
        if not path.is_file():
            continue
        original = path.read_bytes()
        current = json.loads(original.decode("utf-8-sig"))
        result = update(current, kind, remote, local, model)
        if current != result:
            prepared.append((path, original, result))
    # Validate all inputs before replacing either file; abort on concurrent changes.
    for path, original, _ in prepared:
        if path.read_bytes() != original:
            raise ValueError("Cline cambió su configuración. No se sobrescribió.")
    for path, original, result in prepared:
        fd, name = tempfile.mkstemp(prefix="qwen-bridge-", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o600)
            if path.read_bytes() != original:
                raise ValueError("Cline cambió su configuración. No se sobrescribió.")
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
            backup = path.with_name(path.name + "." + stamp + ".bak")
            with backup.open("xb") as stream:
                stream.write(original)
            backup.chmod(0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return len(prepared)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".cline/data")
    args = parser.parse_args()
    try:
        connection = load_connection()
        local = f"http://127.0.0.1:{get_settings().api_port}/api/v1/qwen/v1"
        count = install(args.data_dir, connection.base_url.rstrip("/"), local, connection.model)
    except (OSError, ValueError, FlowError):
        print("No se pudo activar el puente. Comprueba la conexión de Qwen y que Cline use ese mismo proveedor. Se conservan las copias previas.")
        return 1
    print(f"Configuraciones actualizadas: {count}. Copias anteriores conservadas. Claves y herramientas sin cambios.")
    print("URL Cline:", local)
    print("Modelo:", connection.model)
    print("Mantén Studio abierto y recarga la configuración del proveedor en Cline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
