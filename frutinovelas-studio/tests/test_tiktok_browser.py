"""Regresiones sin red para el nuevo bot propio de Fruticap.

No usan navegador ni publican en TikTok. La compatibilidad real se verifica aparte.
"""
from __future__ import annotations

from uuid import uuid4
import pytest

from frutinovelas import tiktok_browser as tk


@pytest.fixture
def browser(data_dir, monkeypatch):
    # All database files and the persistent Chromium profile live in temporary storage.
    b = tk.TikTokBrowser()
    monkeypatch.setattr(b.executor, "submit", lambda *args: None)
    yield b
    b.executor.shutdown(wait=False)


def test_rejects_missing_authorization_and_non_uuid(browser, monkeypatch):
    monkeypatch.setattr(tk, "_render_path", lambda _: data_dir / "sample.mp4")
    with pytest.raises(tk.TikTokOperatorError, match="authorized=True"):
        browser.queue_render(str(uuid4()), str(uuid4()), "Un capítulo", False)
    with pytest.raises(tk.TikTokOperatorError, match="UUID"):
        browser.queue_render("invalid", str(uuid4()), "Un capítulo", True)
    assert browser.status()["publications"] == []


def test_one_render_one_request_prevents_duplicates(browser, monkeypatch, data_dir):
    monkeypatch.setattr(tk, "_render_path", lambda _: data_dir / "sample.mp4")
    rid, video_id = str(uuid4()), str(uuid4())
    first = browser.queue_render(rid, video_id, "Escena 1 🎬", True)
    assert first["state"] == "queued"
    assert browser.queue_render(rid, video_id, "Escena 1 🎬", True)["request_id"] == rid
    with pytest.raises(tk.TikTokOperatorError, match="otro contenido|otra publicación"):
        browser.queue_render(str(uuid4()), video_id, "Escena 1 🎬", True)
    with pytest.raises(tk.TikTokOperatorError, match="otro contenido|otra publicación"):
        browser.queue_render(rid, video_id, "Otro texto", True)
    with pytest.raises(tk.TikTokOperatorError, match="activa o incierta"):
        browser.queue_render(str(uuid4()), str(uuid4()), "Otro video", True)


def test_unknown_needs_human_reconciliation(browser, monkeypatch, data_dir):
    monkeypatch.setattr(tk, "_render_path", lambda _: data_dir / "sample.mp4")
    rid, video_id = str(uuid4()), str(uuid4())
    browser.queue_render(rid, video_id, "Texto exacto", True)
    browser._mark(rid, "unknown", "Resultado incierto")
    with pytest.raises(tk.TikTokOperatorError, match="NO se publicó"):
        browser.reconcile(rid, False)
    assert browser.get_publication(rid)["state"] == "unknown"
    result = browser.reconcile(rid, True)
    assert result["state"] == "not_published"
    assert browser.get_publication(rid)["state"] == "not_published"


def test_restart_preserves_unknown_and_never_replays(browser, monkeypatch, data_dir):
    monkeypatch.setattr(tk, "_render_path", lambda _: data_dir / "sample.mp4")
    rid, video_id = str(uuid4()), str(uuid4())
    browser.queue_render(rid, video_id, "Texto", True)
    fresh = tk.TikTokBrowser()
    try:
        assert fresh.get_publication(rid)["state"] == "unknown"
    finally:
        fresh.executor.shutdown(wait=False)


def test_text_comparison_preserves_accents_newlines_and_emojis():
    assert tk._normalize("  ¡Hola! 👋\r\n#Darío\xa0 ") == "¡Hola! 👋\n#Darío"
    assert tk._normalize("#Darío\nHola") != tk._normalize("#Dario Hola")


def test_render_is_validated_inside_studio(data_dir):
    with pytest.raises(tk.TikTokOperatorError, match="ID"):
        tk._render_path("not-a-uuid")


def test_login_calls_browser_on_single_playwright_thread(data_dir, monkeypatch):
    b = tk.TikTokBrowser()
    try:
        monkeypatch.setattr(b, "_open_login", lambda: {"browser": "open"})
        assert b.open_login() == {"browser": "open"}
    finally:
        b.executor.shutdown(wait=True)
