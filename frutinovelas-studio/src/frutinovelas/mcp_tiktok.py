"""Cline-local TikTok tools: a new Fruticap-owned browser, not a My Content dependency.

Registered ONLY on stdio, never public/tunnelled HTTP MCP.
"""
from __future__ import annotations

from uuid import UUID

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from frutinovelas.tiktok_browser import TikTokOperatorError, operator


def register_tiktok_tools(server):
    read = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    act = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
    )

    def safe(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except TikTokOperatorError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(annotations=read)
    def tiktok_browser_status() -> dict:
        """Obtener estado y últimos trabajos; no abre ventanas ni muestra cookies."""
        return safe(operator().status)

    @server.tool(annotations=act)
    def tiktok_open_manual_login() -> dict:
        """Abrir Chrome exclusivo de Fruticap para que el usuario inicie sesión manualmente."""
        return safe(operator().open_login)

    @server.tool(annotations=read)
    def tiktok_get_publication(request_id: UUID) -> dict:
        """Consultar un trabajo de publicación por su UUID; no reenviar."""
        result = safe(operator().get_publication, str(request_id))
        if result is None:
            raise ToolError("Publicación no encontrada.")
        return result

    @server.tool(annotations=act)
    def tiktok_publish_chapter(
        request_id: UUID, render_id: UUID, caption: str, authorized: bool = False
    ) -> dict:
        """Publicar un MP4 de capítulo FINALIZADO solo con autorización expresa.

        No acepta archivos arbitrarios: render_id debe existir en Fruticap.
        Si una publicación queda incierta, NUNCA repetir automáticamente.
        La cuenta y su segundo factor se gestionan manualmente en Chrome.
        """
        return safe(operator().queue_render, str(request_id), str(render_id), caption, authorized)

    @server.tool(annotations=act)
    def tiktok_confirm_not_published(request_id: UUID, confirmed_not_published: bool = False) -> dict:
        """Liberar una subida incierta SOLO después de comprobar manualmente TikTok."""
        return safe(operator().reconcile, str(request_id), confirmed_not_published)
