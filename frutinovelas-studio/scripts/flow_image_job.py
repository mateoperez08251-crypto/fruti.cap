"""One explicit Flow image request: new project, reference, generation and download.

Run with My Content's Python. Requests and presets belong outside Git. A request ID
is never submitted twice; interrupted submissions need inspection, not blind retries.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

try:
    from scripts import flow_mycontent_browser as bridge
except ModuleNotFoundError:
    import flow_mycontent_browser as bridge


def read_request(path):
    request = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    request_id = str(UUID(request["request_id"]))
    prompt = request.get("prompt")
    if not prompt:
        preset = json.loads(Path(request["preset_path"]).read_text(encoding="utf-8-sig"))
        scene = request.get("scene", "")
        if not isinstance(scene, str) or not scene.strip():
            raise ValueError("La escena debe ser explícita.")
        prompt = preset["style"] + "\n\nEscena: " + scene
        reference = request.get("reference", preset.get("reference"))
    else:
        reference = request.get("reference")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Falta un prompt literal.")
    if reference and not Path(reference).is_file():
        raise ValueError("No existe la referencia.")
    return {"request_id": request_id, "prompt": prompt, "reference": reference,
            "aspect_ratio": "9:16", "model": "Nano Banana 2.1", "outputs": 1}


def load_job(path, request):
    if not path.exists():
        return {"request": request, "state": "new"}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state["request"] != request:
        raise ValueError("Este request_id ya corresponde a otra solicitud; no se sobrescribe.")
    if state["state"] in ("creating_project", "sending"):
        raise ValueError("Resultado incierto. Revisa el proyecto antes de volver a enviar.")
    return state


@contextmanager
def job_lock(path):
    # Exclusive creation also protects against two separately launched bot processes.
    lock = path.with_suffix(".lock")
    with lock.open("x", encoding="utf-8") as stream:
        stream.write("Flow image job in progress")
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


@contextmanager
def download_browser(browser, manifest):
    from playwright.sync_api import BrowserType

    original = BrowserType.launch_persistent_context
    lookup = browser.buscar_navegador

    def launch(self, **kwargs):
        kwargs["accept_downloads"] = True
        return original(self, **kwargs)

    browser.buscar_navegador = lambda name="auto": (
        ("chromium", manifest["executable"]) if name == "chromium" else lookup(name)
    )
    try:
        # Local to this bot process; My Content's source and defaults stay intact.
        with patch.object(BrowserType, "launch_persistent_context", launch):
            with browser.abrir(manifest["profile"], navegador="chromium", headless=False) as context:
                yield context
    finally:
        browser.buscar_navegador = lookup


def image_settings(page):
    from playwright.sync_api import expect

    close = page.get_by_role("button", name="Close", exact=True)
    if close.count() == 1 and close.is_visible():
        close.click()
    agent = page.get_by_role("button", name="Agent", exact=True)
    if agent.get_attribute("aria-pressed") == "true":
        agent.click()
    expect(agent).to_have_attribute("aria-pressed", "false")
    trigger = page.get_by_role("button", name="Settings trigger", exact=True)
    trigger.click()
    for name in (re.compile(r"Image$"), re.compile(r"9:16$"), "x1"):
        control = page.get_by_role("radio", name=name, exact=True)
        control.click()
        expect(control).to_have_attribute("aria-checked", "true")
    # Verify actual model, without changing or substituting it.
    if "Nano Banana 2.1" not in page.locator("body").inner_text():
        raise ValueError("Nano Banana 2.1 no está disponible; no se generó.")
    page.keyboard.press("Escape")
    expect(trigger).to_contain_text("Nano Banana 2.1")
    expect(trigger).to_contain_text("x1")


def attach_reference(page, reference):
    from playwright.sync_api import expect

    if not reference:
        return
    page.get_by_role("button", name="Add ingredients to the prompt box", exact=True).click()
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="Upload media", exact=True).click()
    chooser.value.set_files(reference)
    option = page.get_by_role("option").filter(has_text=Path(reference).name)
    expect(option).to_be_enabled(timeout=60000)
    option.click()
    # A single uploaded image is attached immediately in the observed Flow UI.
    expect(page.get_by_role("button", name="Settings trigger", exact=True)).to_be_visible()


def submit_once(page, state, path):
    if state["state"] != "configured":
        raise ValueError("La solicitud no está preparada o ya se envió.")
    editor = page.get_by_role("textbox", name="What do you want to create?", exact=True)
    editor.fill(state["request"]["prompt"])
    if editor.inner_text().strip() != state["request"]["prompt"].strip():
        raise ValueError("Flow alteró el texto; envío cancelado.")
    state["state"] = "sending"
    bridge.save_manifest(path, state)
    page.get_by_role("button", name="Start generation", exact=True).click()
    state["state"] = "submitted"
    bridge.save_manifest(path, state)


def download_result(page, state, path, timeout=180):
    images = page.locator('img[alt="Tile displaying a user\'s image"]')
    deadline = time.monotonic() + timeout
    reference = state["request"]["reference"]
    while time.monotonic() < deadline:
        for index in range(images.count()):
            image = images.nth(index)
            tile = image.locator('xpath=ancestor::*[.//button[@aria-label="More options"]][1]')
            if reference and Path(reference).name in tile.inner_text():
                continue
            if not image.evaluate("e=>e.complete && e.naturalWidth>0"):
                continue
            image.hover()
            tile.get_by_role("button", name="More options", exact=True).click()
            page.get_by_role("menuitem").filter(has_text=re.compile(r"Download$")).hover()
            with page.expect_download(timeout=60000) as download:
                page.get_by_text("Original size", exact=True).click()
            output = path.with_suffix(".png")
            download.value.save_as(str(output))
            state.update(state="downloaded", output=str(output))
            bridge.save_manifest(path, state)
            return
        page.wait_for_timeout(1500)
    raise TimeoutError("La imagen sigue sin estar disponible. Reutiliza el mismo request_id, sin reenviar.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        request = read_request(args.request)
        browser, connection_path, manifest = bridge.prepare(args.source)
        root = connection_path.parent / "image_jobs"
        if root.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
            raise ValueError("Los trabajos y prompts deben guardarse fuera de Git.")
        root.mkdir(parents=True, exist_ok=True)
        path = root / (request["request_id"] + ".json")
        with job_lock(path):
            state = load_job(path, request)
            if state["state"] == "downloaded" and Path(state["output"]).is_file():
                print(json.dumps({key: state[key] for key in ("state", "project_url", "output")}))
                return 0
            with download_browser(browser, manifest) as context:
                page = context.new_page()
                if state["state"] == "new":
                    page.goto(bridge.FLOW_URL, wait_until="domcontentloaded", timeout=60000)
                    state["state"] = "creating_project"
                    bridge.save_manifest(path, state)
                    page.get_by_role("button", name="New project", exact=True).click()
                    page.wait_for_url("**/project/**", timeout=45000)
                    state.update(state="project_created", project_url=page.url)
                    bridge.save_manifest(path, state)
                else:
                    page.goto(state["project_url"], wait_until="domcontentloaded", timeout=60000)
                if not bridge.flow_page(page.url) or not page.url.startswith("https://flow.google.com/project/"):
                    raise ValueError("No se pudo abrir el proyecto de esta solicitud.")
                if state["state"] == "project_created":
                    # Only automatic before any upload; partial preparation requires inspection.
                    state["state"] = "preparing"
                    bridge.save_manifest(path, state)
                    attach_reference(page, request["reference"])
                    image_settings(page)  # Upload can reset x1 to x4; configure last.
                    state["state"] = "configured"
                    bridge.save_manifest(path, state)
                    submit_once(page, state, path)
                elif state["state"] not in ("submitted", "downloaded"):
                    raise ValueError("Preparación incompleta. Revisa el proyecto; no se repetirá automáticamente.")
                download_result(page, state, path)
            print(json.dumps({key: state[key] for key in ("state", "project_url", "output")}))
        return 0
    except Exception as error:
        print(json.dumps({"state": "needs_attention", "detail": str(error)}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
