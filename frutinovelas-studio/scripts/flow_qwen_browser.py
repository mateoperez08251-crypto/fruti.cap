"""Qwen controls Chromium through observed DOM elements, not a fixed click script."""
import base64
import json
import re
from urllib.parse import urlsplit

OBSERVE = """() => {
 document.querySelectorAll('[data-fruti-qwen]').forEach(e=>e.removeAttribute('data-fruti-qwen'));
 return [...document.querySelectorAll('button,a,input,textarea,select,[role="button"],[role="menuitem"],[role="radio"],[role="tab"],[role="option"],[role="combobox"],[role="switch"],[contenteditable="true"],img')]
 .filter(e=>e.getClientRects().length || e.matches('input[type="file"]')).slice(0,250)
 .map((e,id)=>{e.setAttribute('data-fruti-qwen',String(id)); return {
 id,tag:e.tagName,role:e.getAttribute('role'),type:e.getAttribute('type'),
 text:(e.getAttribute('aria-label')||e.innerText||e.getAttribute('alt')||'').slice(0,180),
 checked:e.getAttribute('aria-checked'),pressed:e.getAttribute('aria-pressed'),
 src:e.tagName==='IMG'?(e.currentSrc||e.src):undefined,
 width:e.naturalWidth,height:e.naturalHeight};});
}"""


def project_url(url):
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname == "flow.google.com" and parsed.path.startswith("/project/")


def sources(page):
    return page.locator("img").evaluate_all("els=>els.map(e=>e.currentSrc||e.src).filter(Boolean)")


def execute(api, journal, adapter, job, workdir):
    # Imported lazily to support both script entry and test imports.
    try:
        from scripts.flow_browser_bot import same_text, write_references
    except ModuleNotFoundError:
        from flow_browser_bot import same_text, write_references
    page = adapter.page
    identifier = job["request_id"]
    state = journal.load(identifier)
    if state and state.get("executor") != "browser_qwen":
        raise RuntimeError("Este trabajo pertenece al bot anterior; no se cambia de ejecutor.")
    if state and state["state"] in ("sending", "unconfirmed"):
        api.event(identifier, "uncertain", "Qwen no repetirá un envío incierto. Revisa Flow.")
        return "uncertain"
    if state and state["state"] == "downloaded":
        api.upload_qwen(identifier, state["output"], state["preview"])
        state["state"] = "uploaded"
        journal.save(identifier, state)
        return "completed"
    if job["action"] != "submit" and not state:
        api.event(identifier, "uncertain", "Falta el diario Qwen; no se vuelve a generar.")
        return "uncertain"
    state = state or {"executor": "browser_qwen", "state": "claimed", "history": [],
                      "project_url": job.get("flow_project_url"), "known_results": []}
    folder = workdir / identifier
    folder.mkdir(parents=True, exist_ok=True)
    references = write_references(job, folder) if job["action"] == "submit" else []
    submitted = state["state"] == "submitted"
    if submitted and job["action"] == "reconcile":
        api.event(identifier, "submitted")
    journal.save(identifier, state)
    preview = folder / "selected-preview.png"
    output = folder / "result.png"
    selected = False
    editor = None
    touched = False
    try:
        page.goto(state.get("project_url") or "https://flow.google.com/", wait_until="domcontentloaded")
        for _ in range(100):
            url = page.url
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.hostname != "flow.google.com":
                raise RuntimeError("Flow requiere acceso manual o salió de su página.")
            if page.locator('input[type="password"]:visible').count():
                raise RuntimeError("Completa el acceso manualmente.")
            login = page.get_by_role("link", name=re.compile(r"^(sign in|iniciar sesión|acceder)$", re.I))
            if any(login.nth(i).is_visible() for i in range(login.count())):
                raise RuntimeError("Completa el acceso manualmente antes de enviar capturas.")
            if project_url(url):
                if state.get("project_url") and state["project_url"].split("?")[0] != url.split("?")[0]:
                    raise RuntimeError("Qwen salió del proyecto asignado a esta historia.")
                if not state.get("project_url"):
                    api.event(identifier, "project", project_url=url)
                    state["project_url"] = url
                    journal.save(identifier, state)
            elements = page.evaluate(OBSERVE)
            shot = base64.b64encode(page.screenshot(type="png", full_page=False)).decode("ascii")
            observation = json.dumps({"elements": [{k: v for k, v in e.items() if k != "src"} for e in elements], "submitted": submitted,
                                      "selected_result": selected}, ensure_ascii=False)
            decision = api.qwen(identifier, observation[:24000], shot, state["history"][-30:])
            name, args = decision["action"], decision["arguments"]
            element = None
            if "target" in args:
                element = next((e for e in elements if e["id"] == args["target"]), None)
                if element is None:
                    raise RuntimeError("Qwen eligió un elemento que no aparece en la observación actual.")
                target = page.locator(f'[data-fruti-qwen="{args["target"]}"]')
                if target.count() != 1:
                    raise RuntimeError("El control cambió desde la observación.")
            if name == "stop":
                raise RuntimeError("Qwen pidió detenerse para revisar Flow.")
            elif name == "wait":
                page.wait_for_timeout(5000)
            elif name == "scroll":
                page.mouse.wheel(0, args["pixels"])
            elif name == "escape":
                page.keyboard.press("Escape")
            elif name == "hover":
                target.hover()
            elif name == "click":
                if re.search(r"generat|generar|crear imagen|retry|reintentar|regener", element["text"], re.I):
                    raise RuntimeError("El envío requiere generate; nunca un clic genérico.")
                touched = True
                target.click()
            elif name in ("fill_prompt", "upload_references", "select"):
                if submitted or not state.get("project_url"):
                    raise RuntimeError("Solo se prepara la imagen antes del envío y dentro de su proyecto.")
                if name == "fill_prompt":
                    target.fill(job["prompt"])
                    target.press("End")
                    target.press("Space")
                    target.press("Backspace")
                    editor = target.element_handle()
                    if not same_text(editor.evaluate("e=>e.value??e.innerText"), job["prompt"]):
                        raise RuntimeError("El editor no conserva el prompt literal.")
                    state["prompt_ready"] = True
                elif name == "upload_references":
                    files = [str(path) for path in references]
                    if element.get("type") == "file":
                        target.set_input_files(files)
                    else:
                        with page.expect_file_chooser(timeout=15000) as chooser:
                            target.click()
                        chooser.value.set_files(files)
                    state["references_ready"] = True
                    page.wait_for_timeout(2000)
                else:
                    target.select_option(args["value"])
            elif name == "generate":
                if submitted or not state.get("project_url") or not state.get("prompt_ready") or (references and not state.get("references_ready")):
                    raise RuntimeError("El envío ya ocurrió o faltan prompt/referencias.")
                if editor is None or not same_text(editor.evaluate("e=>e.value??e.innerText"), job["prompt"]):
                    raise RuntimeError("El prompt cambió antes de generar.")
                state["known_results"] = sources(page)
                state["state"] = "sending"
                journal.save(identifier, state)  # Write intent before any possible submission.
                touched = True
                target.click()
                submitted = True
                state["state"] = "submitted"
                journal.save(identifier, state)
                api.event(identifier, "submitted")
            elif name == "select_result":
                if not submitted or element["tag"] != "IMG" or not element.get("src") or element["src"] in state["known_results"]:
                    raise RuntimeError("La imagen seleccionada no es un resultado nuevo posterior al envío.")
                if not element.get("width") or not element.get("height"):
                    raise RuntimeError("La imagen todavía no terminó de cargar.")
                target.screenshot(path=str(preview), type="png")
                selected = True
                state["selected_source"] = element["src"]
            elif name == "download":
                if not submitted or not selected:
                    raise RuntimeError("Selecciona primero el resultado nuevo de esta generación.")
                if not re.search(r"download|descargar|original|guardar", element["text"], re.I):
                    raise RuntimeError("El elemento elegido no identifica una descarga.")
                with page.expect_download(timeout=60000) as pending:
                    target.click()
                pending.value.save_as(str(output))
                state.update(state="downloaded", output=str(output), preview=str(preview))
                journal.save(identifier, state)
                api.event(identifier, "downloading")
                api.upload_qwen(identifier, output, preview)
                state["state"] = "uploaded"
                journal.save(identifier, state)
                return "completed"
            else:
                raise RuntimeError("Acción Qwen desconocida.")
            state["history"].append(name + " " + json.dumps(args, ensure_ascii=False))
            journal.save(identifier, state)
            page.wait_for_timeout(400)
        raise RuntimeError("Qwen alcanzó el límite de acciones; revisa Flow.")
    except Exception as exc:
        # Generic navigation can potentially trigger a page action: never silently replay it.
        uncertain = submitted or touched or state["state"] == "sending"
        state.update(state="unconfirmed" if uncertain else "stopped", error=str(exc)[:500])
        journal.save(identifier, state)
        api.event(identifier, "uncertain" if uncertain else "not_submitted", str(exc)[:500])
        return "uncertain" if uncertain else "not_submitted"
