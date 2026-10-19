# @title 9C · Consultar cola, cancelar pendientes o interrumpir el activo
# Ejecuta primero la celda 8. Consulta es la opción segura al ejecutar todo.
# Reutiliza GW y AUTH: es la API nativa de ComfyUI detrás del gateway Bearer.
# No imprime tokens, prompts, workflows ni respuestas completas del servidor.
# Si otra celda bloquea el kernel esperando un render, detén solo esa celda
# antes de ejecutar esta: detener Python no cancela el render de ComfyUI.
ACCION_COLA = "consultar"  # @param ["consultar", "cancelar seleccionados", "cancelar todos los pendientes", "interrumpir activo"]
IDS_PENDIENTES = ""  # @param {type:"string"}
# IDs completos separados por comas o espacios; nunca índices de posición.

import re

import requests


def gestionar_cola(accion, ids_texto="", *, contexto=None, transporte=None, confirmar=input):
    """Gestiona exclusivamente la cola de ComfyUI; no modifica la base de Studio."""
    ctx = globals() if contexto is None else contexto
    http = requests if transporte is None else transporte
    base, auth = ctx.get("GW"), ctx.get("AUTH")
    if not isinstance(base, str) or not isinstance(auth, dict) or not auth.get("Authorization"):
        raise ValueError("Ejecuta primero la celda 8 para configurar GW y AUTH.")
    base, auth = base.rstrip("/"), dict(auth)
    acciones = {"consultar", "cancelar seleccionados", "cancelar todos los pendientes", "interrumpir activo"}
    if accion not in acciones:
        raise ValueError("Acción de cola no válida.")

    def pedir(method, ruta, payload=None):
        try:
            kwargs = {"headers": auth, "timeout": 20, "allow_redirects": False}
            if payload is not None:
                kwargs["json"] = payload
            response = http.request(method, base + ruta, **kwargs)
        except requests.RequestException:
            raise RuntimeError("Fallo de conexión o timeout. Resultado incierto si era una escritura; consulta la cola antes de repetir.") from None
        if response.status_code in (401, 403):
            raise RuntimeError("Gateway: acceso rechazado. Revisa la configuración de la celda 8.")
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"Gateway/ComfyUI: HTTP {response.status_code}. Consulta el estado antes de repetir.")
        if method == "POST":
            return None  # ComfyUI devuelve 200 con cuerpo vacío.
        try:
            return response.json()
        except ValueError:
            raise RuntimeError("Respuesta no JSON; comprueba el gateway de la celda 8.") from None

    def cola():
        data = pedir("GET", "/queue")
        result = {}
        for key in ("queue_running", "queue_pending"):
            items = data.get(key) if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise RuntimeError("Respuesta de cola no válida; no se hará ningún cambio.")
            ids = []
            for item in items:
                if (not isinstance(item, (list, tuple)) or len(item) < 2
                        or not isinstance(item[1], str)
                        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item[1])):
                    raise RuntimeError("Trabajo de cola no válido; no se hará ningún cambio.")
                ids.append(item[1])
            result[key] = ids
        return result

    def mostrar(data):
        for key, label in (("queue_running", "Activos"), ("queue_pending", "Pendientes")):
            print(f"{label}: {len(data[key])}")
            for pid in data[key]:
                print("  " + pid)

    actual = cola()
    mostrar(actual)
    if accion == "consultar":
        return actual
    if accion.startswith("cancelar"):
        if accion == "cancelar seleccionados":
            elegidos = list(dict.fromkeys(ids_texto.replace(",", " ").split()))
            if not elegidos or not set(elegidos) <= set(actual["queue_pending"]):
                raise ValueError("Indica IDs completos que estén pendientes. No se aceptan activos ni IDs desconocidos.")
        else:
            elegidos = actual["queue_pending"][:]
        if not elegidos:
            print("No hay pendientes que cancelar.")
            return actual
        print("Se eliminarán solo estos pendientes:", ", ".join(elegidos))
        print("No interrumpe el activo. Los trabajos enviados después de esta consulta se conservan.")
        if confirmar("Escribe CANCELAR para confirmar: ").strip() != "CANCELAR":
            print("Operación cancelada; no se envió ningún cambio.")
            return actual
        nuevos = cola()
        if not set(elegidos) <= set(nuevos["queue_pending"]):
            raise RuntimeError("La cola cambió (un trabajo pudo empezar). Consulta de nuevo; no se envió ningún cambio.")
        # Eliminar IDs es seguro aunque alguno empiece tras consultar: /queue
        # solo elimina pendientes, jamás interrumpe un render ni borra historial.
        pedir("POST", "/queue", {"delete": elegidos})
        print("Solicitud de eliminación enviada. Estado observado ahora:")
    else:
        activos = actual["queue_running"]
        if not activos:
            print("No hay trabajo activo que interrumpir.")
            return actual
        if len(activos) != 1:
            raise RuntimeError("Hay varios activos; no se enviará una interrupción ambigua.")
        # La versión fijada en esta libreta soporta /interrupt con prompt_id.
        # No usar {}: sería una interrupción global y podría afectar al siguiente.
        identidad = pedir("GET", "/frutinovelas/identity")
        if (not isinstance(identidad, dict)
                or identidad.get("comfyui_commit") != "3541246a9c997f4b8c32f9f88f3c985d02021c79"):
            raise RuntimeError("No se confirmó la versión con interrupción por ID. No se enviará una interrupción global.")
        pid = activos[0]
        print("Interrumpir el render puede perder su progreso. Los pendientes continuarán automáticamente.")
        if confirmar(f"Escribe INTERRUMPIR {pid} para confirmar: ").strip() != f"INTERRUMPIR {pid}":
            print("Operación cancelada; no se envió ningún cambio.")
            return actual
        if cola()["queue_running"] != activos:
            raise RuntimeError("El trabajo activo cambió. Consulta de nuevo; no se envió la interrupción.")
        pedir("POST", "/interrupt", {"prompt_id": pid})
        print("Interrupción solicitada; puede tardar hasta que el nodo atienda la señal. Estado observado ahora:")
    final = cola()
    mostrar(final)
    print("La respuesta HTTP no garantiza que el render ya haya terminado; vuelve a consultar.")
    return final


try:
    _ = gestionar_cola(ACCION_COLA, IDS_PENDIENTES)
except (RuntimeError, ValueError) as exc:
    print(str(exc))
except (EOFError, KeyboardInterrupt):
    print("Celda detenida. Si ya se envió una solicitud, consulta la cola antes de repetir.")
