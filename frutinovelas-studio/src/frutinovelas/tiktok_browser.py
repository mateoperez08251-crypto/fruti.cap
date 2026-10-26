"""TikTok browser operator for Cline's local MCP (independent of My Content).

Only completed FRUTINOVELAS chapter renders may be uploaded. All browser work runs
on one dedicated thread so the persistent Playwright context never changes thread.
No arbitrary paths, URLs, cookie exports, credentials or shell tools are exposed.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.models import ChapterRender

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center"
SUCCESS = re.compile(
    r"(tu v[ií]deo se ha publicado|v[ií]deo publicado correctamente|"
    r"your video has been posted|video published successfully)",
    re.I,
)
POST_BUTTON = re.compile(r"^(publicar|post)$", re.I)
CAPTION_SELECTORS = (
    'div.public-DraftEditor-content[contenteditable="true"]',
    'div[contenteditable="true"][role="combobox"]',
    'div[contenteditable="true"]',
)


class TikTokOperatorError(ValueError):
    pass


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFC", s).replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").strip()


def _dir() -> Path:
    path = get_settings().resolved_data_dir / "tiktok_browser"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _db():
    conn = sqlite3.connect(_dir() / "jobs.sqlite3", timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("""CREATE TABLE IF NOT EXISTS publications (
        request_id TEXT PRIMARY KEY, render_id TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL,
        caption TEXT NOT NULL, state TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
        created REAL NOT NULL, updated REAL NOT NULL
    )""")
    return conn


def _public(row):
    return None if row is None else {
        "request_id": row["request_id"], "render_id": row["render_id"],
        "state": row["state"], "error": row["error"],
    }


def _render_path(render_id: str) -> Path:
    try:
        UUID(render_id)
    except ValueError as exc:
        raise TikTokOperatorError("ID de montaje no válido.") from exc
    with session_factory()() as session:
        render = session.get(ChapterRender, render_id)
        if not render or render.state != "completed" or not render.result_path:
            raise TikTokOperatorError("El montaje debe estar terminado en Fruticap.")
        relative_path = render.result_path
    base = get_settings().resolved_data_dir.resolve()
    path = (base / relative_path).resolve()
    if path == base or base not in path.parents or path.suffix.lower() != ".mp4" or not path.is_file():
        raise TikTokOperatorError("El MP4 del montaje no está disponible en el almacenamiento de Fruticap.")
    return path


class TikTokBrowser:
    """One browser/context, one thread, one account profile owned by Fruticap."""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fruti-tiktok")
        self.lock = threading.Lock()
        self.phase = "closed"
        self.detail = ""
        self.playwright = None
        self.context = None
        self.page = None
        # Never replay work that may already have pressed Publish before a crash.
        with _db() as db:
            db.execute(
                "UPDATE publications SET state='unknown', error='Se reinició el MCP durante la subida; verifica TikTok manualmente.', updated=? "
                "WHERE state IN ('queued','uploading','posting')", (time.time(),)
            )
            db.commit()

    def _set_phase(self, phase, detail=""):
        with self.lock:
            self.phase, self.detail = phase, detail

    def status(self):
        with self.lock:
            phase, detail = self.phase, self.detail
        with _db() as db:
            recent = db.execute("SELECT * FROM publications ORDER BY created DESC LIMIT 10").fetchall()
        return {
            "browser": phase, "detail": detail,
            "publications": [_public(x) for x in recent],
            "profile": "Perfil privado de Fruticap; no se exporta a Colab ni a Cline.",
        }

    def _ensure_browser(self):
        if self.context is not None:
            try:
                if self.context.pages:
                    return
            except Exception:
                pass
            self.context = None
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise TikTokOperatorError(
                "Falta Playwright en el entorno Python de Fruticap. Consulta docs/CLINE_TIKTOK_MCP.md."
            ) from exc
        if self.playwright is None:
            self.playwright = sync_playwright().start()
        self._set_phase("opening")
        profile = _dir() / "profile"
        # Never point Playwright to the personal Chrome profile or My Content's profile.
        try:
            self.context = self.playwright.chromium.launch_persistent_context(
                str(profile), channel="chrome", headless=False, accept_downloads=True,
                viewport={"width": 1280, "height": 900},
            )
        except Exception as exc:
            self._set_phase("error", "No se pudo abrir Chrome con el perfil aislado.")
            raise TikTokOperatorError(
                "No se pudo abrir Chrome. Instala Google Chrome o configura Playwright; comprueba que no haya otro navegador usando este perfil."
            ) from exc
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self._set_phase("open", "La autenticación debe completarla el usuario.")

    def open_login(self):
        self._ensure_browser()
        self.page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
        self._set_phase("login", "Inicia sesión manualmente en TikTok y completa cualquier verificación.")
        return {"browser": "open", "message": "Ventana de TikTok abierta. Completa el inicio de sesión manualmente."}

    def _unique(self, loc, label):
        count = loc.count()
        if count != 1:
            raise TikTokOperatorError(f"No hay un único control verificable para {label}; revisa TikTok.")
        return loc

    def _caption(self):
        for selector in CAPTION_SELECTORS:
            matches = self.page.locator(selector + ":visible")
            if matches.count() == 1:
                return matches
        raise TikTokOperatorError("No se encontró el editor único de la descripción.")

    def _check_login(self):
        if any(part in self.page.url.lower() for part in ("/login", "passport.tiktok")):
            raise TikTokOperatorError("La sesión caducó. Abre la ventana e inicia sesión manualmente.")

    def _success_messages(self):
        try:
            loc = self.page.get_by_text(SUCCESS)
            return {
                _normalize(loc.nth(i).inner_text(timeout=2000))
                for i in range(loc.count())
                if loc.nth(i).is_visible()
                and not loc.nth(i).evaluate(
                    "el => !!el.closest('[contenteditable], textarea, input, button, a')"
                )
            }
        except Exception:
            return set()

    def _mark(self, request_id, state, error=""):
        with _db() as db:
            db.execute(
                "UPDATE publications SET state=?,error=?,updated=? WHERE request_id=?",
                (state, error, time.time(), request_id),
            )
            db.commit()

    def _publish(self, request_id, render_id, caption):
        # Playwright calls are exclusively performed on this executor's thread.
        clicked = False
        try:
            self._ensure_browser()
            self._set_phase("publishing")
            file_path = _render_path(render_id)
            self._mark(request_id, "uploading")
            self.page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
            self._check_login()
            file_input = self._unique(self.page.locator('input[type="file"]'), "archivo de TikTok")
            file_input.set_input_files(str(file_path), timeout=60000)
            editor = self._caption()
            editor.fill(caption, timeout=30000)
            editor.press("Escape")
            deadline = time.monotonic() + 900
            post = None
            while time.monotonic() < deadline:
                self._check_login()
                post = self.page.get_by_role("button", name=POST_BUTTON)
                if post.count() == 1 and post.is_visible() and post.is_enabled():
                    break
                self.page.wait_for_timeout(1000)
            else:
                raise TikTokOperatorError("TikTok no habilitó Publicar; revisa el video y la cuenta.")
            if _normalize(editor.inner_text(timeout=5000)) != _normalize(caption):
                raise TikTokOperatorError("La descripción cambió. No se publicó.")
            post.click(trial=True, timeout=15000)
            previous = self._success_messages()
            # Journal first: do not repeat a click whose outcome is uncertain.
            self._mark(request_id, "posting")
            clicked = True
            post.click(timeout=15000, no_wait_after=True)
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                self._check_login()
                if self._success_messages() - previous:
                    self._mark(request_id, "published")
                    self._set_phase("open", "TikTok confirmó la publicación.")
                    return
                self.page.wait_for_timeout(1000)
            raise TikTokOperatorError("No llegó una confirmación inequívoca de TikTok.")
        except Exception as exc:
            # A click could have succeeded despite a timeout or lost response.
            self._mark(request_id, "unknown" if clicked else "failed",
                       str(exc)[:500] if not clicked else "Resultado incierto: revisa tu TikTok antes de otro intento.")
            self._set_phase("error", "Revisa la publicación y el estado del navegador.")

    def queue_render(self, request_id, render_id, caption, authorized):
        if not authorized:
            raise TikTokOperatorError("Publicar requiere authorized=True de forma explícita.")
        try:
            request_id, render_id = str(UUID(request_id)), str(UUID(render_id))
        except ValueError as exc:
            raise TikTokOperatorError("IDs UUID no válidos.") from exc
        if not caption or not caption.strip() or len(caption) > 2200:
            raise TikTokOperatorError("La descripción debe tener entre 1 y 2200 caracteres.")
        _render_path(render_id)  # Verify real completed video before opening the browser.
        fingerprint = hashlib.sha256(
            json.dumps([render_id, caption], ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        with _db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM publications WHERE request_id=? OR render_id=?",
                                  (request_id, render_id)).fetchone()
            if existing:
                if existing["request_id"] != request_id or existing["fingerprint"] != fingerprint:
                    raise TikTokOperatorError("Este montaje o ID ya pertenece a otra publicación.")
                return _public(existing)
            busy = db.execute(
                "SELECT 1 FROM publications WHERE state IN ('queued','uploading','posting','unknown')"
            ).fetchone()
            if busy:
                raise TikTokOperatorError("Hay una publicación activa o incierta; resuélvela antes de enviar otra.")
            db.execute(
                "INSERT INTO publications(request_id,render_id,fingerprint,caption,state,created,updated) "
                "VALUES(?,?,?,?,'queued',?,?)",
                (request_id, render_id, fingerprint, caption, time.time(), time.time()),
            )
            db.commit()
        self.executor.submit(self._publish, request_id, render_id, caption)
        return {"request_id": request_id, "render_id": render_id, "state": "queued"}

    def get_publication(self, request_id):
        try:
            request_id = str(UUID(request_id))
        except ValueError as exc:
            raise TikTokOperatorError("ID UUID no válido.") from exc
        with _db() as db:
            return _public(db.execute("SELECT * FROM publications WHERE request_id=?",
                                     (request_id,)).fetchone())


_operator = None
_guard = threading.Lock()


def operator():
    global _operator
    with _guard:
        if _operator is None:
            _operator = TikTokBrowser()
        return _operator
