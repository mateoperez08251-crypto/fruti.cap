"""Open Google Flow using My Content's existing browser module and Python.

This entry opens a normal browser for manual sign-in, never automates credentials
or imports My Content accounts, queues or cookies. It runs with its existing
Playwright installation, independently of Studio's Python environment.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

FLOW_URL = "https://flow.google.com/"


def data_directory():
    configured = os.environ.get("FRUTINOVELAS_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    base = Path(os.environ["LOCALAPPDATA"]) if os.name == "nt" else Path.home() / ".local/share"
    return base / "frutinovelas-studio"


def load_browser(source):
    path = Path(source).resolve() / "bot" / "navegador.py"
    if not path.is_file():
        raise ValueError("No se encontró bot/navegador.py de My Content.")
    spec = importlib.util.spec_from_file_location("fruti_mycontent_browser", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "abrir_normal", None)) or not callable(getattr(module, "_ejecutable_login", None)):
        raise ValueError("El módulo del navegador de My Content no tiene la interfaz esperada.")
    return module


def save_manifest(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="flow-browser-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def installed_chromium():
    base = (Path(os.environ["LOCALAPPDATA"]) / "ms-playwright" if os.name == "nt" else
            Path.home() / ".cache/ms-playwright")
    candidates = []
    for folder in base.glob("chromium-*"):
        revision = folder.name.removeprefix("chromium-")
        if not revision.isdecimal():
            continue
        executable = folder / ("chrome-win64/chrome.exe" if os.name == "nt" else "chrome-linux/chrome")
        if executable.is_file():
            candidates.append((int(revision), executable))
    return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else None


def prepare(source, root=None):
    root = Path(root or data_directory()).resolve()
    source = Path(source).resolve()
    browser = load_browser(source)
    installed = installed_chromium()
    if installed:
        name, executable = "chromium", str(installed)
        # Normal manual sign-in does not use the Playwright protocol. Reuse the
        # installed browser even when its Python package expects another build.
        # The change is local to this separately loaded module, never My Content.
        browser._ejecutable_login = lambda *_: (name, executable)
    else:
        name, executable = browser._ejecutable_login("chromium")
    if name != "chromium" or not Path(executable).is_file():
        raise ValueError("No se encontró el Chromium instalado para el bot.")
    profile = root / "flow" / "google_browser" / "profile"
    if source == profile or source in profile.parents:
        raise ValueError("El perfil Flow debe estar fuera del repositorio My Content.")
    manifest = {"source": str(source), "python": sys.executable, "browser": name,
                "executable": str(executable), "profile": str(profile), "url": FLOW_URL,
                "state": "configured", "automation_ready": False}
    path = root / "flow" / "google_browser" / "connection.json"
    if path.is_file():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous.get("profile") == manifest["profile"] and previous.get("source") == manifest["source"]:
            for key in ("owned_project_url", "project_create_attempted", "owned_storyboard_url", "controls_verified", "verified_settings"):
                if key in previous:
                    manifest[key] = previous[key]
            last_url = previous.get("project_url", "")
            if "/tool/" in urlsplit(last_url).path and flow_page(last_url):
                manifest.setdefault("owned_storyboard_url", last_url)
    return browser, path, manifest


def flow_page(url):
    parsed = urlsplit(url)
    return parsed.scheme == "https" and (parsed.hostname == "flow.google.com" or
           parsed.hostname == "labs.google" and parsed.path.startswith("/fx/"))


def inspect_flow(browser, path, manifest, new_project=False, screen=None):
    # The executable binding is local to this imported browser module. It keeps
    # using My Content's profile locking and context lifecycle with installed Chromium.
    executable = manifest["executable"]
    original_lookup = browser.buscar_navegador
    browser.buscar_navegador = lambda name="auto": ("chromium", executable) if name == "chromium" else original_lookup(name)
    with browser.abrir(manifest["profile"], navegador="chromium", headless=False) as context:
        candidates = [page for page in context.pages if flow_page(page.url)]
        page = candidates[0] if candidates else context.new_page()
        if not candidates:
            page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3500)
        login = page.get_by_role("link", name=re.compile(r"^(sign in|iniciar sesi[oó]n|acceder)$", re.I))
        if not flow_page(page.url) or any(login.nth(index).is_visible() for index in range(login.count())):
            manifest["state"] = "login_required"
            save_manifest(path, manifest)
            raise ValueError("Flow requiere iniciar sesión manualmente. No se capturó la pantalla de acceso.")
        if page.locator('input[type="password"]:visible').count():
            raise ValueError("El acceso aún no está completo. No se inspeccionan campos de contraseña.")
        if new_project:
            owned = manifest.get("owned_project_url")
            if owned:
                if not flow_page(owned) or not urlsplit(owned).path.startswith("/project/"):
                    raise ValueError("La URL del proyecto del bot no es válida.")
                page.goto(owned, wait_until="domcontentloaded", timeout=60000)
            else:
                if manifest.get("project_create_attempted"):
                    raise ValueError("Hubo un intento previo de crear proyecto sin confirmación. Comprueba Flow antes de repetirlo.")
                create = page.get_by_role("button", name=re.compile(r"Proyecto nuevo", re.I))
                if create.count() != 1 or not create.is_visible():
                    raise ValueError("No hay un único botón Proyecto nuevo verificable.")
                manifest["project_create_attempted"] = True
                save_manifest(path, manifest)
                create.click()
                page.wait_for_url("**/project/**", timeout=45000)
                manifest["owned_project_url"] = page.url
                save_manifest(path, manifest)
            page.wait_for_timeout(2500)
        if screen in ("settings", "video-settings"):
            page.get_by_role("button", name="Botón de configuración", exact=True).click()
            if screen == "video-settings":
                page.get_by_role("radio", name=re.compile(r"Video$", re.I)).click()
            page.wait_for_timeout(500)
        elif screen == "storyboard" and manifest.get("owned_storyboard_url"):
            target = manifest["owned_storyboard_url"]
            if not flow_page(target) or not target.startswith(manifest["owned_project_url"] + "/tool/"):
                raise ValueError("La herramienta no pertenece al proyecto de prueba.")
            page.goto(target, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
        elif screen in ("tools", "templates", "storyboard"):
            page.get_by_role("link", name=re.compile(r"Herramientas", re.I)).click()
            page.wait_for_timeout(1800)
            if screen in ("templates", "storyboard"):
                page.get_by_role("radio", name="Plantillas", exact=True).click()
                page.wait_for_timeout(1300)
                if screen == "storyboard":
                    page.get_by_text("Storyboard Studio", exact=True).click()
                    page.wait_for_timeout(3500)
                    if "/tool/" in urlsplit(page.url).path:
                        manifest["owned_storyboard_url"] = page.url
                        save_manifest(path, manifest)
        if screen == "configure-image":
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
            from frutinovelas.services.flow_browser_controls import FlowBrowserSettings, prepare_settings
            manifest["verified_settings"] = prepare_settings(page, FlowBrowserSettings())
            manifest["controls_verified"] = True
            save_manifest(path, manifest)
        controls = page.locator('button, a, input:not([type="password"]), textarea, [contenteditable="true"], [role="button"], [role="combobox"]').evaluate_all("""elements => elements.filter(el => el.getClientRects().length).map(el => ({
          tag: el.tagName, role: el.getAttribute('role'), text: (el.innerText || '').slice(0,180),
          label: el.getAttribute('aria-label'), placeholder: el.getAttribute('placeholder'),
          type: el.getAttribute('type'), href: el.tagName === 'A' ? el.getAttribute('href') : null,
          editable: el.getAttribute('contenteditable'), pressed: el.getAttribute('aria-pressed'),
          checked: el.getAttribute('aria-checked'), state: el.getAttribute('data-state')
        }))""")
        controls = [control for control in controls if "accounts.google.com" not in (control.get("href") or "")]
        apps = []
        import time
        deadline = time.monotonic() + (45 if screen == "storyboard" else 0)
        while True:
            for frame in page.frames:
                inner = urlsplit(frame.url.removeprefix("blob:"))
                if not inner.hostname or not inner.hostname.endswith(".scf.usercontent.goog"):
                    continue
                try:
                    text = frame.locator("body").inner_text(timeout=1000)
                    if not text.strip():
                        continue
                    app_controls = frame.locator(
                    'button, input:not([type="password"]), textarea, select, [contenteditable="true"], [role="button"], [role="radio"]').evaluate_all("""els => els.filter(e => e.getClientRects().length).map(e => ({
                    tag:e.tagName,role:e.getAttribute('role'),text:(e.innerText||'').slice(0,120),
                    label:e.getAttribute('aria-label'),placeholder:e.getAttribute('placeholder'),
                    type:e.getAttribute('type'),checked:e.getAttribute('aria-checked'),
                    options:e.tagName==='SELECT' ? [...e.options].map(o=>({text:o.text,value:o.value})):null
                    }))""")
                    # Flow also hosts a hidden compiler iframe on this domain.
                    # Its script text is not the rendered Storyboard application.
                    if not app_controls:
                        continue
                    apps.append({"text": text[:16000], "controls": app_controls})
                except Exception:
                    continue  # Flow replaces its sandboxed iframe while loading.
            if apps or time.monotonic() >= deadline:
                break
            page.wait_for_timeout(500)
        result = {"url": page.url, "title": page.title(), "controls": controls,
                  "apps": apps,
                  "frames": [{"name": frame.name, "kind": "flow" if flow_page(frame.url) else "embedded"} for frame in page.frames],
                  "pages": [{"url": item.url} for item in context.pages],
                  "text": page.locator("body").inner_text()[:14000]}
        inspection = path.parent / "inspection.json"
        save_manifest(inspection, result)
        page.screenshot(path=str(path.parent / "inspection.png"), full_page=False)
        manifest["state"] = "flow_inspected"
        manifest["project_url"] = page.url
        save_manifest(path, manifest)
        print(json.dumps(result, ensure_ascii=True), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--inspect-project", action="store_true")
    parser.add_argument("--screen", choices=("settings", "tools", "video-settings", "templates", "storyboard", "configure-image"))
    args = parser.parse_args(argv)
    try:
        browser, path, manifest = prepare(args.source)
        if args.check:
            save_manifest(path, manifest)
            print("Motor My Content y Chromium comprobados. Conexión local preparada; sesión Google sin verificar.")
            return 0
        if args.inspect or args.inspect_project:
            inspect_flow(browser, path, manifest, new_project=args.inspect_project, screen=args.screen)
            return 0
        if not args.login:
            parser.error("Usa --check o --login.")
        manifest["state"] = "opening"
        save_manifest(path, manifest)
        def opened(*_):
            manifest["state"] = "manual_login"
            manifest["helper_pid"] = os.getpid()
            save_manifest(path, manifest)
            print("Google Flow abierto con el motor de My Content. Inicia sesión tú mismo y cierra su ventana al terminar.", flush=True)
        browser.abrir_normal(manifest["profile"], FLOW_URL, navegador="chromium", al_abrir=opened)
        manifest["state"] = "closed_unverified"
        save_manifest(path, manifest)
        print("Ventana cerrada. El perfil se conserva localmente; falta comprobar Flow y su rutina de generación.")
        return 0
    except Exception:
        print("No se pudo preparar o abrir Chromium. Comprueba el Python y el módulo de navegador de My Content.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
