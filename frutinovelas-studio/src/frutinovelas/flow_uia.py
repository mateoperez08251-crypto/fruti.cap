"""UI Automation adapter. All selectors come from a locally verified profile.

No built-in Userflex selectors are claimed: its runtime/UI are not available in CI.
No global mouse/keyboard, cookies, browser debugging, screenshots or shell commands.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from functools import wraps
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from frutinovelas.services.flow_transport import FlowError, FlowIntervention


def uia_thread(function):
    """Initialize COM on each Windows worker thread, not just the import thread."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        if os.name != "nt":
            return function(*args, **kwargs)
        if "comtypes" not in sys.modules:
            sys.coinit_flags = 0  # UIA uses the multithreaded apartment in this dedicated agent.
        import comtypes
        comtypes.CoInitializeEx(0)
        try:
            return function(*args, **kwargs)
        finally:
            comtypes.CoUninitialize()
    return wrapped


class Selector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control_type: str = Field(min_length=1, max_length=80)
    auto_id: str | None = Field(default=None, max_length=300)
    title: str | None = Field(default=None, max_length=300)
    window_title: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def identifiable(self):
        if not self.auto_id and not self.title:
            raise ValueError("Cada selector necesita auto_id o título exacto observado.")
        return self


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["invoke", "set_text", "select"]
    selector: Selector
    source: Literal["literal", "prompt", "reference_0", "reference_1", "reference_2", "aspect_ratio", "duration_seconds", "output_path"] = "literal"
    value: str = Field(default="", max_length=500)


class Mode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aspect_ratios: list[Literal["9:16", "16:9", "1:1"]] = Field(min_length=1)
    durations: list[float] = Field(default_factory=list, max_length=20)
    reference_count: int = Field(default=0, ge=0, le=3)
    prepare: list[Action] = Field(default_factory=list, max_length=30)
    submit: Selector
    busy: Selector
    completed: Selector
    save: list[Action] = Field(min_length=1, max_length=15)

    @model_validator(mode="after")
    def validate_actions(self):
        if not any(a.operation == "set_text" and a.source == "prompt" for a in self.prepare):
            raise ValueError("La preparación debe escribir el prompt mediante un control accesible.")
        for i in range(self.reference_count):
            if not any(a.operation == "set_text" and a.source == f"reference_{i}" for a in self.prepare):
                raise ValueError("Falta una acción para cargar cada referencia declarada.")
        if not any(a.operation == "set_text" and a.source == "output_path" for a in self.save):
            raise ValueError("La descarga debe usar Guardar como con una ruta de salida por solicitud.")
        if any(a.selector == self.submit for a in self.prepare + self.save):
            raise ValueError("El botón de generación solo puede invocarse en la etapa submit.")
        return self


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executable: Path
    window_title_contains: str = Field(min_length=2, max_length=200)
    automation_authorized: bool = False
    flow_marker: Selector
    authenticated_marker: Selector
    ready_marker: Selector
    blockers: list[Selector] = Field(min_length=1, max_length=20)
    modes: dict[Literal["image", "video"], Mode]
    timeout_seconds: int = Field(default=900, ge=30, le=7200)


class UIADriver:
    def __init__(self, profile_path: Path):
        self.profile_path = profile_path
        self.profile = Profile.model_validate_json(profile_path.read_text(encoding="utf-8"))
        self.profile_hash = hashlib.sha256(profile_path.read_bytes()).hexdigest()
        self.bound_processes = None
        self.bound_handle = None

    def _windows(self):
        if os.name != "nt":
            raise FlowError("Este controlador requiere Windows con una sesión de escritorio abierta.")
        try:
            import psutil
            from pywinauto import Desktop
        except ImportError as exc:
            raise FlowError("Instala el extra flow-agent en Windows.") from exc
        expected = self.profile.executable.resolve(strict=True)
        processes = []
        for proc in psutil.process_iter(["pid", "exe"]):
            try:
                if proc.info["exe"] and Path(proc.info["exe"]).resolve() == expected:
                    processes.append(proc)
            except (psutil.Error, OSError):
                continue
        pids = {p.pid for p in processes}
        identity = tuple(sorted((p.pid, p.create_time()) for p in processes))
        if self.bound_processes is not None and identity != self.bound_processes:
            raise FlowError("La aplicación se reinició o cambió de proceso. No se reasignará este trabajo.")
        for proc in processes:
            try:
                pids.update(c.pid for c in proc.children(recursive=True))
            except psutil.Error:
                pass
        windows = [w for w in Desktop(backend="uia").windows() if w.process_id() in pids and w.is_visible()]
        return processes, windows

    def _window(self, title=None):
        _, windows = self._windows()
        selected = [w for w in windows if (w.window_text() == title if title else self.profile.window_title_contains in w.window_text())]
        if len(selected) != 1:
            raise FlowError("La ventana autorizada no está abierta o hay varias coincidencias. Selecciona una sola.")
        if title is None and self.bound_handle is not None and selected[0].handle != self.bound_handle:
            raise FlowError("La ventana cambió desde el inicio del trabajo. Se requiere reconciliación.")
        return selected[0]

    def bind(self):
        window = self._window()
        processes, _ = self._windows()
        self.bound_processes = tuple(sorted((p.pid, p.create_time()) for p in processes))
        self.bound_handle = window.handle

    def find(self, selector, optional=False):
        window = self._window(selector.window_title)
        # No title regexes/indices/coordinates: a selector must resolve uniquely inside the approved process tree.
        criteria = {"control_type": selector.control_type}
        if selector.auto_id:
            criteria["auto_id"] = selector.auto_id
        if selector.title:
            criteria["title"] = selector.title
        matches = [w for w in window.descendants(**criteria) if w.is_visible()]
        if not matches and optional:
            return None
        if len(matches) != 1:
            raise FlowError("Un control no existe o es ambiguo. Revisa el perfil local de accesibilidad.")
        return matches[0]

    def check_blockers(self):
        for selector in self.profile.blockers:
            if self.find(selector, optional=True) is not None:
                raise FlowIntervention("Flow requiere intervención: verificación humana, cuota o rechazo. Se pausó el controlador.")

    def verify(self):
        if not self.profile.automation_authorized:
            raise FlowError("Falta autorización local para la automatización de este programa.")
        self.check_blockers()
        for selector in (self.profile.flow_marker, self.profile.authenticated_marker, self.profile.ready_marker):
            if not self.find(selector).is_enabled():
                raise FlowError("Flow no está preparado o la autenticación no puede verificarse.")
        return True

    def validated(self):
        marker = self.profile_path.with_suffix(".verified.json")
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            return value == {"profile_sha256": self.profile_hash,
                             "executable_sha256": self._executable_hash()}
        except (OSError, ValueError):
            return False

    def _executable_hash(self):
        with self.profile.executable.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    @uia_thread
    def mark_verified(self):
        self.verify()
        marker = self.profile_path.with_suffix(".verified.json")
        marker.write_text(json.dumps({"profile_sha256": self.profile_hash,
                                     "executable_sha256": self._executable_hash()}), encoding="utf-8")

    @uia_thread
    def status(self):
        result = {"available": False, "window_open": False, "flow_available": None,
                  "authentication": "unknown", "modes": {}, "remote_cancel_supported": False,
                  "detail": "Perfil sin verificar; ejecuta verify-profile en Windows."}
        try:
            self._window()
            result["window_open"] = True
            result["flow_available"] = self.find(self.profile.flow_marker, optional=True) is not None
            if self.find(self.profile.authenticated_marker, optional=True) is not None:
                result["authentication"] = "verified_by_control"
            if self.validated():
                self.verify()
                result.update(available=True, detail="Controlador UIA configurado. La compatibilidad requiere una prueba real.",
                              modes={kind: {"aspect_ratios": m.aspect_ratios, "durations": m.durations,
                                            "reference_count": m.reference_count} for kind, m in self.profile.modes.items()})
        except Exception:
            result["detail"] = "No se pudieron verificar los controles. Revisa el perfil y la ventana en Windows."
        return result

    @uia_thread
    def focus(self):
        self._window().set_focus()

    def validate_request(self, payload):
        if not self.validated():
            raise FlowError("El perfil o el ejecutable cambió. Vuelve a verificarlo localmente.")
        mode = self.profile.modes.get(payload["kind"])
        if mode is None or payload["aspect_ratio"] not in mode.aspect_ratios:
            raise FlowError("Modo o formato no verificado para esta interfaz.")
        if payload["kind"] == "video" and payload["duration_seconds"] not in mode.durations:
            raise FlowError("La duración solicitada no está verificada para este modo Flow.")
        if len(payload["references"]) != mode.reference_count:
            raise FlowError("El perfil necesita exactamente la cantidad configurada de referencias; no se omitirán imágenes.")
        return mode

    def actions(self, actions, values):
        for action in actions:
            self.check_blockers()
            element = self.find(action.selector)
            if not element.is_enabled():
                raise FlowError("Un control está deshabilitado. No se continuará.")
            if action.operation == "invoke":
                element.invoke()
            elif action.operation == "select":
                element.select()
            else:
                value = action.value if action.source == "literal" else values.get(action.source)
                if value is None:
                    raise FlowError("Falta el valor de un control requerido.")
                element.set_edit_text(str(value))


@uia_thread
def inspect_application(executable: Path):
    """Local diagnostic: no passwords, edit contents, command lines or session storage."""
    if os.name != "nt":
        raise FlowError("Ejecuta el diagnóstico en Windows.")
    import psutil
    from pywinauto import Desktop
    executable = executable.resolve(strict=True)
    matches = []
    for process in psutil.process_iter(["pid", "exe", "name"]):
        try:
            if process.info["exe"] and Path(process.info["exe"]).resolve() == executable:
                matches.append(process)
        except (psutil.Error, OSError):
            continue
    pids = {p.pid for p in matches}
    names = set()
    for process in matches:
        try:
            children = process.children(recursive=True)
            pids.update(c.pid for c in children)
            names.update(c.name() for c in children)
        except psutil.Error:
            pass
    evidence = {"app_asar_present": (executable.parent / "resources" / "app.asar").is_file(),
                "webview2_child": any("msedgewebview2" in n.lower() for n in names),
                "child_process_names": sorted(names)}
    windows = []
    for window in Desktop(backend="uia").windows():
        if window.process_id() not in pids:
            continue
        controls = []
        for element in window.descendants()[:400]:
            info = element.element_info
            kind = info.control_type
            # Only expose names of actionable, non-edit controls. Never Values.
            title = info.name if kind in ("Button", "TabItem", "MenuItem", "ComboBox", "CheckBox") else ""
            controls.append({"control_type": kind, "auto_id": info.automation_id,
                             "title": title[:200], "framework_id": info.framework_id})
        windows.append({"title": window.window_text()[:200], "pid": window.process_id(), "controls": controls})
    return {"evidence": evidence, "windows": windows,
            "conclusion": "Indicios locales; app.asar sugiere Electron, un proceso msedgewebview2 sugiere WebView2. No prueban acceso CDP ni autorización contractual."}
