"""Chromium executor for Studio's Flow queue, using My Content's browser module.

Run with My Content's Python (it provides Playwright). Studio decides *what* to
generate; this bot only executes one claimed job at a time:

1. ``POST /flow/browser/claim``: Studio records ``submitting`` before any click.
2. Same story key -> open its recorded Flow project. New key -> ``New project``
   and report the URL to Studio *before* uploading or submitting.
3. Attach references, then configure type/ratio/model/x1 (upload can reset x1).
4. Write the prompt literally, journal ``sending``, press Start generation once.
5. Wait for a tile that did not exist before submission, download it at original
   size and upload it to Studio, which verifies and assigns it to the shot.

A local journal (outside Git) decides reconciliation after a crash: before
``sending`` -> provably not submitted; ``sending`` -> uncertain (human check);
``submitted`` -> recover the download without resubmitting.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

try:
    from scripts import flow_mycontent_browser as bridge
except ModuleNotFoundError:  # Executed as a plain script by My Content's Python.
    import flow_mycontent_browser as bridge

BEFORE_SEND = ("claimed", "project_ready", "preparing", "configured")


class ControlsMissing(RuntimeError):
    """A required Flow control was not found; nothing was submitted."""


class Uncertain(RuntimeError):
    """Flow may have received the request; never resubmit automatically."""


# --- Studio API ---------------------------------------------------------------------

class StudioAPI:
    def __init__(self, base_url, key, timeout=60):
        self.base = base_url.rstrip("/") + "/api/v1/flow/browser"
        self.key, self.timeout = key, timeout
        # Loopback only: proxies from the environment must not see the bot key.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _send(self, path, data=None, content_type="application/json"):
        request = urllib.request.Request(self.base + path, data=data, method="POST",
                                         headers={"X-Fruti-Flow-Bot": self.key, "Content-Type": content_type})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except ValueError:
                pass
            raise RuntimeError(f"Studio rechazó la operación ({error.code}): {detail}") from None

    def claim(self):
        return self._send("/claim", b"{}")

    def event(self, job_id, event, error="", project_url=None):
        body = {"event": event, "error": error[:1000]}
        if project_url:
            body["project_url"] = project_url
        return self._send(f"/jobs/{job_id}/event", json.dumps(body, ensure_ascii=False).encode("utf-8"))

    def upload(self, job_id, path):
        boundary = uuid.uuid4().hex
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{Path(path).name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode()
        body = head + Path(path).read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        return self._send(f"/jobs/{job_id}/result", body, f"multipart/form-data; boundary={boundary}")


# --- Journal ------------------------------------------------------------------------

class Journal:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, job_id):
        return self.root / f"{uuid.UUID(job_id)}.json"

    def load(self, job_id):
        path = self.path(job_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def save(self, job_id, value):
        bridge.save_manifest(self.path(job_id), value)


def write_references(job, folder):
    """Materialize Studio's frozen references and verify their hashes."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, ref in enumerate(job.get("references", [])):
        raw = base64.b64decode(ref["content_base64"], validate=True)
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ControlsMissing("Una referencia no coincide con su huella; no se envió.")
        suffix = ".png" if raw.startswith(b"\x89PNG") else ".jpg" if raw.startswith(b"\xff\xd8") else ".webp"
        path = folder / f"ref-{index + 1}-{ref['sha256'][:12]}{suffix}"
        path.write_bytes(raw)
        paths.append(path)
    return paths


def same_text(typed, expected):
    normalize = lambda value: value.replace("\r\n", "\n").replace("\r", "\n").strip()
    return normalize(typed) == normalize(expected)


# --- One job ------------------------------------------------------------------------

def submit(api, journal, page, job, workdir):
    job_id = job["request_id"]
    state = {"request_id": job_id, "kind": job["kind"], "state": "claimed",
             "flow_project_key": job["flow_project_key"], "project_url": job.get("flow_project_url")}
    journal.save(job_id, state)
    try:
        references = write_references(job, workdir / job_id)
        url = page.open_project(state["project_url"])
        if not state["project_url"]:
            # New story: bind the project before any upload or submission.
            api.event(job_id, "project", project_url=url)
        state.update(state="project_ready", project_url=url)
        journal.save(job_id, state)
        state["state"] = "preparing"
        journal.save(job_id, state)
        page.attach(references)
        page.configure(job)  # After attaching: an upload can switch x1 to x4.
        state["known_results"] = sorted(page.results(job["kind"]))
        state["state"] = "configured"
        journal.save(job_id, state)
        page.write_prompt(job["prompt"])
    except Exception as error:  # Nothing was sent: provably safe to release.
        state.update(state="stopped", error=str(error))
        journal.save(job_id, state)
        api.event(job_id, "not_submitted", f"No se envió: {error}")
        return "not_submitted"
    state["state"] = "sending"
    journal.save(job_id, state)
    try:
        page.start_generation()
    except Exception as error:
        api.event(job_id, "uncertain", f"Clic de envío sin confirmar: {error}")
        return "uncertain"
    state["state"] = "submitted"
    journal.save(job_id, state)
    api.event(job_id, "submitted")
    return recover(api, journal, page, job, workdir)


def recover(api, journal, page, job, workdir, timeout=None):
    job_id = job["request_id"]
    state = journal.load(job_id)
    if not state or state.get("state") not in ("submitted", "downloaded"):
        api.event(job_id, "uncertain", "No hay diario de envío confirmado; revisa Flow manualmente.")
        return "uncertain"
    if state["state"] == "submitted":
        page.open_project(state["project_url"])
        handle = page.wait_new_result(job["kind"], set(state.get("known_results", [])), timeout)
        if handle is None:
            return "waiting"  # Still generating: try again later, never resubmit.
        api.event(job_id, "downloading")
        output = workdir / job_id / ("result.mp4" if job["kind"] == "video" else "result.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        page.download(handle, output)
        state.update(state="downloaded", output=str(output))
        journal.save(job_id, state)
    try:
        api.upload(job_id, state["output"])
    except RuntimeError as error:
        state.update(state="rejected", error=str(error))
        journal.save(job_id, state)
        api.event(job_id, "uncertain", f"Studio no aceptó la descarga: {error}")
        return "rejected"
    state["state"] = "uploaded"
    journal.save(job_id, state)
    return "completed"


def reconcile(api, journal, page, job, workdir):
    state = journal.load(job["request_id"]) or {}
    current = state.get("state")
    if current in BEFORE_SEND or current == "stopped":
        api.event(job["request_id"], "not_submitted", state.get("error") or "El bot se detuvo antes de enviar.")
        return "not_submitted"
    if current in ("submitted", "downloaded"):
        api.event(job["request_id"], "submitted")
        return recover(api, journal, page, job, workdir)
    # Missing journal or "sending": Flow may have the request. A human decides.
    api.event(job["request_id"], "uncertain", "Envío sin confirmar. Revisa el proyecto Flow y concilia en Studio.")
    return "uncertain"


def run_once(api, journal, page_factory, workdir):
    job = api.claim()
    action = job.get("action")
    if action in ("idle", "blocked"):
        return action, job.get("detail", "")
    with page_factory() as page:
        if action == "submit":
            return submit(api, journal, page, job, workdir), job["request_id"]
        if action == "recover":
            return recover(api, journal, page, job, workdir), job["request_id"]
        if action == "reconcile":
            return reconcile(api, journal, page, job, workdir), job["request_id"]
    raise RuntimeError("Acción desconocida de Studio.")


# --- Playwright page (observed English Flow UI) -------------------------------------

class FlowPage:
    def __init__(self, page, timeout=600):
        self.page, self.timeout = page, timeout

    def _one(self, locator, what):
        if locator.count() != 1:
            raise ControlsMissing(f"No se encontró un control único: {what}.")
        return locator

    def open_project(self, url):
        if url:
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        else:
            self.page.goto(bridge.FLOW_URL, wait_until="domcontentloaded", timeout=60000)
            self._one(self.page.get_by_role("button", name="New project", exact=True), "New project").click()
            self.page.wait_for_url("**/project/**", timeout=45000)
        if not self.page.url.startswith("https://flow.google.com/project/"):
            raise ControlsMissing("No se abrió un proyecto de Flow.")
        return self.page.url

    def attach(self, references):
        from playwright.sync_api import expect
        for reference in references:
            self._one(self.page.get_by_role("button", name="Add ingredients to the prompt box", exact=True),
                      "Add ingredients").click()
            with self.page.expect_file_chooser() as chooser:
                self._one(self.page.get_by_role("button", name="Upload media", exact=True), "Upload media").click()
            chooser.value.set_files(str(reference))
            option = self.page.get_by_role("option").filter(has_text=Path(reference).name)
            expect(option).to_be_enabled(timeout=60000)
            option.click()

    def configure(self, job):
        from playwright.sync_api import expect
        close = self.page.get_by_role("button", name="Close", exact=True)
        if close.count() == 1 and close.is_visible():
            close.click()
        agent = self._one(self.page.get_by_role("button", name="Agent", exact=True), "Agent")
        if agent.get_attribute("aria-pressed") == "true":
            agent.click()  # Agent mode would rewrite the literal prompt.
        expect(agent).to_have_attribute("aria-pressed", "false")
        trigger = self._one(self.page.get_by_role("button", name="Settings trigger", exact=True), "Settings trigger")
        trigger.click()
        kind = "Video" if job["kind"] == "video" else "Image"
        names = [re.compile(kind + "$"), re.compile(re.escape(job["aspect_ratio"]) + "$"), "x1"]
        if job["kind"] == "video":
            # Not yet observed with a real run: exact labels must exist or we stop.
            names.append(re.compile(rf"^{int(job['duration_seconds'])}\s?s$"))
        for name in names:
            control = self._one(self.page.get_by_role("radio", name=name, exact=True), str(name))
            control.click()
            expect(control).to_have_attribute("aria-checked", "true")
        if job["model"] not in self.page.locator("body").inner_text():
            raise ControlsMissing(f"{job['model']} no está disponible; no se sustituye el modelo.")
        self.page.keyboard.press("Escape")
        expect(trigger).to_contain_text(job["model"])
        expect(trigger).to_contain_text("x1")

    def _tiles(self, kind):
        selector = "video" if kind == "video" else 'img[alt="Tile displaying a user\'s image"]'
        return self.page.locator(selector)

    def results(self, kind):
        tiles = self._tiles(kind)
        return {tiles.nth(i).get_attribute("src") or "" for i in range(tiles.count())}

    def write_prompt(self, prompt):
        editor = self._one(self.page.get_by_role("textbox", name="What do you want to create?", exact=True), "prompt")
        editor.fill(prompt)
        if not same_text(editor.inner_text(), prompt):
            raise ControlsMissing("Flow alteró el texto del prompt.")
        self._one(self.page.get_by_role("button", name="Start generation", exact=True), "Start generation")

    def start_generation(self):
        self.page.get_by_role("button", name="Start generation", exact=True).click()

    def wait_new_result(self, kind, known, timeout=None):
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            tiles = self._tiles(kind)
            for i in range(tiles.count()):
                tile = tiles.nth(i)
                source = tile.get_attribute("src") or ""
                if not source or source in known:
                    continue
                ready = "e=>e.readyState>=3" if kind == "video" else "e=>e.complete && e.naturalWidth>0"
                if tile.evaluate(ready):
                    return tile
            self.page.wait_for_timeout(2000)
        return None

    def download(self, tile, output):
        tile.hover()
        box = tile.locator('xpath=ancestor::*[.//button[@aria-label="More options"]][1]')
        self._one(box.get_by_role("button", name="More options", exact=True), "More options").click()
        self.page.get_by_role("menuitem").filter(has_text=re.compile(r"Download$")).hover()
        original = self.page.get_by_text("Original size", exact=True)
        with self.page.expect_download(timeout=120000) as download:
            if original.count():
                original.click()
            else:
                self.page.get_by_role("menuitem").filter(has_text=re.compile(r"Download$")).click()
        download.value.save_as(str(output))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path, help="Carpeta de My Content")
    parser.add_argument("--studio", default="http://127.0.0.1:" + os.environ.get("FRUTINOVELAS_API_PORT", "8765"))
    parser.add_argument("--once", action="store_true", help="Procesa una sola acción y termina")
    parser.add_argument("--poll", type=float, default=15)
    args = parser.parse_args(argv)
    key = os.environ.pop("FRUTI_FLOW_BOT_KEY", "")
    if not key:
        print("Falta la credencial local del bot. Usa iniciar_flow_bot.cmd.", file=sys.stderr)
        return 2
    try:
        from scripts.flow_image_job import download_browser
    except ModuleNotFoundError:
        from flow_image_job import download_browser
    from contextlib import contextmanager

    browser, connection_path, manifest = bridge.prepare(args.source)
    root = connection_path.parent
    if root.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise SystemExit("El diario del bot debe quedar fuera de Git.")
    journal, workdir = Journal(root / "bot_jobs"), root / "bot_files"
    lock = root / "bot.lock"
    try:
        lock.open("x", encoding="utf-8").close()  # One executor per profile.
    except FileExistsError:
        print("Ya hay un bot Flow en ejecución (bot.lock).", file=sys.stderr)
        return 1

    @contextmanager
    def page_factory():
        with download_browser(browser, manifest) as context:
            page = context.new_page()
            try:
                yield FlowPage(page)
            finally:
                page.close()

    api = StudioAPI(args.studio, key)
    try:
        while True:
            try:
                result, detail = run_once(api, journal, page_factory, workdir)
                print(json.dumps({"result": result, "detail": detail}, ensure_ascii=False), flush=True)
            except Exception as error:  # Studio offline or browser closed: wait, never resubmit.
                print(json.dumps({"result": "error", "detail": str(error)}, ensure_ascii=False), flush=True)
                result = "error"
            if args.once:
                return 0 if result not in ("error", "uncertain", "rejected") else 1
            time.sleep(args.poll if result in ("idle", "waiting", "blocked", "error") else 1)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
