"""Explicit, observed Google Flow generation settings. Never presses Generate."""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit


class FlowControlError(ValueError):
    pass


@dataclass(frozen=True)
class FlowBrowserSettings:
    kind: str = "image"
    aspect_ratio: str = "9:16"
    outputs: int = 1
    model: str = "Nano Banana 2.1"
    duration_seconds: int | None = None
    resolution: str | None = None
    video_input: str | None = None

    def __post_init__(self):
        if self.kind not in ("image", "video"):
            raise FlowControlError("El tipo debe ser imagen o video.")
        if self.aspect_ratio not in ("16:9", "4:3", "1:1", "3:4", "9:16"):
            raise FlowControlError("Formato no admitido por el adaptador Flow.")
        if type(self.outputs) is not int or not 1 <= self.outputs <= 4:
            raise FlowControlError("La cantidad de salidas debe ser de 1 a 4.")
        if not isinstance(self.model, str) or not self.model.strip():
            raise FlowControlError("Selecciona un modelo explícito.")
        if self.kind == "image" and any(value is not None for value in (self.duration_seconds, self.resolution, self.video_input)):
            raise FlowControlError("La duración y resolución de video no se aplican a una imagen.")
        if self.kind == "video":
            if type(self.duration_seconds) is not int or not 1 <= self.duration_seconds <= 60:
                raise FlowControlError("El video necesita una duración explícita.")
            if not self.resolution or self.video_input not in ("Fotogramas", "Ingredientes"):
                raise FlowControlError("Selecciona resolución y modo de entrada del video.")


def unique(locator, name):
    if locator.count() != 1 or not locator.is_visible() or not locator.is_enabled():
        raise FlowControlError("No hay un único control disponible para " + name + ". No se generó contenido.")
    return locator


def checked(page, locator, name):
    locator = unique(locator, name)
    if locator.get_attribute("aria-checked") != "true":
        locator.click()
    deadline = time.monotonic() + 4
    while locator.get_attribute("aria-checked") != "true":
        if time.monotonic() >= deadline:
            raise FlowControlError("Flow no confirmó la selección de " + name + ". No se generó contenido.")
        page.wait_for_timeout(100)


def prepare_settings(page, settings: FlowBrowserSettings):
    parsed = urlsplit(page.url)
    if parsed.scheme != "https" or parsed.hostname != "flow.google.com" or not parsed.path.startswith("/project/"):
        raise FlowControlError("Solo se configura la pestaña del proyecto Google Flow.")
    if page.locator('input[type="password"]:visible').count():
        raise FlowControlError("Completa el acceso manualmente antes de configurar Flow.")
    unique(page.get_by_role("button", name="Botón de configuración", exact=True), "configuración").click()
    checked(page, page.get_by_role("radio", name=re.compile(r"Imagen$" if settings.kind == "image" else r"Video$", re.I)), settings.kind)
    checked(page, page.get_by_role("radio", name=re.compile(r"(?:^|\s)" + re.escape(settings.aspect_ratio) + r"$")), settings.aspect_ratio)
    checked(page, page.get_by_role("radio", name="x" + str(settings.outputs), exact=True), "cantidad de salidas")
    family = unique(page.get_by_role("button", name="Seleccionar familia de modelos", exact=True), "modelo")
    label = " ".join(family.inner_text().split())
    if not re.search(re.escape(settings.model) + r"(?=\s|$)", label):
        raise FlowControlError("El modelo visible no coincide con el solicitado. No se sustituirá automáticamente ni se generará contenido.")
    if settings.kind == "video":
        checked(page, page.get_by_role("radio", name=re.compile(re.escape(settings.video_input) + r"$")), settings.video_input)
        checked(page, page.get_by_role("radio", name=re.compile(r"^" + re.escape(settings.resolution) + r"(?:\s|$)")), settings.resolution)
        checked(page, page.get_by_role("radio", name=re.compile(r"^" + str(settings.duration_seconds) + r"\s*s$")), "duración")
    page.keyboard.press("Escape")
    agent = unique(page.get_by_role("button", name="Agente", exact=True), "modo de instrucciones literales")
    if agent.get_attribute("aria-pressed") == "true":
        agent.click()
    if agent.get_attribute("aria-pressed") != "false":
        raise FlowControlError("No se pudo confirmar que el agente de Flow esté desactivado.")
    return {**asdict(settings), "agent_enabled": False, "verified": True, "submitted": False}
