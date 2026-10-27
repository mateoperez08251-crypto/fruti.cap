"""Narrow, project-scoped Flow tools. No arbitrary selectors, file paths or shell."""
from typing import Literal
from uuid import UUID

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from frutinovelas.config import get_settings
from frutinovelas.services.flow_transport import local_secret


def flow_request(method, path, body=None):
    settings = get_settings()
    headers = {"X-Fruti-Flow-Key": local_secret("mcp")}
    if settings.api_token:
        headers["Authorization"] = "Bearer " + settings.api_token
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{settings.api_port}/api/v1/flow/",
                          headers=headers, timeout=30, trust_env=False, follow_redirects=False) as client:
            r = client.request(method, path, json=body) if body is not None else client.request(method, path)
        if not r.is_success:
            raise ToolError(str(r.json().get("detail", "Flow rechazó la solicitud.")))
        return r.json()
    except httpx.HTTPError as exc:
        raise ToolError("Studio no responde. Abre la API local; no se reenviará ninguna generación automáticamente.") from exc


def narrated_request(method, path, body=None):
    """Narrated-video endpoints share the Flow guard (MCP key, scope and read-only mode)."""
    settings = get_settings()
    headers = {"X-Fruti-Flow-Key": local_secret("mcp")}
    if settings.api_token:
        headers["Authorization"] = "Bearer " + settings.api_token
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{settings.api_port}/api/v1/narrated-videos/",
                          headers=headers, timeout=240, trust_env=False, follow_redirects=False) as client:
            r = client.request(method, path, json=body) if body is not None else client.request(method, path)
        if not r.is_success:
            raise ToolError(str(r.json().get("detail", "Studio rechazó la solicitud.")))
        return r.json()
    except httpx.HTTPError as exc:
        raise ToolError("Studio no responde. No se reenviará ninguna generación automáticamente.") from exc


def summarize(result):
    """Short answer for assistants: no prompts, base64, paths or provider URLs."""
    video = result.get("video", result)
    shots = [{"shot": i, "seconds": [s.get("start_seconds"), s.get("end_seconds")], "mode": s.get("media_mode"),
              "image": bool(s.get("image_asset_id")), "pinned": bool(s.get("selected_image_job_id")),
              "image_job": s.get("flow_image_job_id"), "clip_job": s.get("flow_video_job_id")}
             for i, s in enumerate(video.get("shots", []))]
    out = {"id": video.get("id"), "revision": video.get("revision"), "state": video.get("state"),
           "error": video.get("error") or None, "shots": shots}
    if "engine" in result:
        out["engine"] = result["engine"]
    if "jobs" in result:
        out["jobs"] = [{"id": j["id"], "shot": j.get("shot"), "kind": j["kind"], "state": j["state"],
                        "error": j.get("error") or None} for j in result["jobs"]]
    return out


def register_narrated_tools(server, read, write, request=narrated_request):
    @server.tool(annotations=write)
    def narrated_plan_shots(video_id: UUID, expected_revision: int, shot_count: int,
                            media_mode: Literal["static", "animated"] = "static", visual_style: str = "",
                            references: list[dict] | None = None,
                            flow_tool: Literal["standard", "storyboard_studio"] = "standard") -> dict:
        """Qwen reparte el guion guardado en tomas que cubren todo el audio. references: [{asset_id, role: identity|style, description}]. No genera imágenes."""
        return summarize(request("POST", f"{video_id}/plan", {
            "expected_revision": expected_revision, "shot_count": shot_count, "media_mode": media_mode,
            "visual_style": visual_style, "references": references or [], "flow_tool": flow_tool}))

    @server.tool(annotations=write)
    def narrated_send_to_flow(video_id: UUID, expected_revision: int, request_id: UUID,
                              clip_seconds: Literal[4, 6, 8, 10] = 6, automatic_approval: bool = False) -> dict:
        """Encola las tomas guardadas en Flow (consume créditos al ejecutarse). Misma historia = mismo proyecto Flow. Reutiliza request_id al reintentar la llamada."""
        return summarize(request("POST", f"{video_id}/flow", {
            "expected_revision": expected_revision, "request_id": str(request_id),
            "clip_seconds": clip_seconds, "automatic_approval": automatic_approval}))

    @server.tool(annotations=write)
    def narrated_animate_approved(video_id: UUID, expected_revision: int, request_id: UUID,
                                  clip_seconds: Literal[4, 6, 8, 10] = 6) -> dict:
        """Pide clips Flow para tomas animadas cuya imagen ya fue aprobada; no regenera la imagen."""
        return summarize(request("POST", f"{video_id}/animate", {
            "expected_revision": expected_revision, "request_id": str(request_id), "clip_seconds": clip_seconds}))

    @server.tool(annotations=write)
    def narrated_sync_results(video_id: UUID, expected_revision: int) -> dict:
        """Asigna a cada toma su resultado Flow verificado. Respeta versiones fijadas."""
        return summarize(request("POST", f"{video_id}/sync", {"expected_revision": expected_revision}))

    @server.tool(annotations=read)
    def narrated_shot_versions(video_id: UUID, shot_index: int) -> list[dict]:
        """Versiones de imagen de una toma (se conservan todas)."""
        return [{"id": j["id"], "state": j["state"], "has_result": bool(j.get("result_asset_id")),
                 "created_at": j.get("created_at")} for j in request("GET", f"{video_id}/shots/{shot_index}/versions")]

    @server.tool(annotations=write)
    def narrated_select_version(video_id: UUID, expected_revision: int, shot_index: int, job_id: UUID | None = None) -> dict:
        """Fija la versión elegida por el usuario para una toma; job_id nulo vuelve a la más reciente."""
        return summarize(request("POST", f"{video_id}/select-version", {
            "expected_revision": expected_revision, "shot_index": shot_index,
            "job_id": str(job_id) if job_id else None}))

    @server.tool(annotations=write)
    def narrated_render(video_id: UUID, expected_revision: int,
                        engine: Literal["auto", "local", "remote"] = "auto") -> dict:
        """Monta el video con la narración original como única pista: imágenes con movimiento FFmpeg y clips Flow verificados."""
        if get_settings().mcp_access_mode != "read_write":
            raise ToolError("MCP está en modo de solo lectura.")
        return summarize(request("POST", f"{video_id}/render", {"expected_revision": expected_revision, "engine": engine}))


def register_flow_tools(server, read, write, request=flow_request):
    def plan(project_id, chapter_id, scene_revisions, request_id, generation_mode, automatic_approval=False,
             prompts=None, video_prompts=None, duration_seconds=None):
        return request("POST", "generate", {
            "project_id": str(project_id), "chapter_id": str(chapter_id), "request_id": str(request_id),
            "scene_revisions": scene_revisions, "generation_mode": generation_mode,
            "automatic_approval": automatic_approval, "prompts": prompts or {},
            "video_prompts": video_prompts or {}, "duration_seconds": duration_seconds})

    @server.tool(annotations=read)
    def flow_detect_window() -> dict:
        """Detectar solo la ventana configurada de Userflex; la autenticación puede ser desconocida."""
        return request("GET", "detect")

    @server.tool(annotations=write)
    def flow_connect(mode: Literal["assisted", "uia", "browser"] = "assisted", authorized: bool = False) -> dict:
        """Conectar el controlador con autorización del usuario. UIA requiere perfil verificado localmente."""
        return request("POST", "connect", {"mode": mode, "authorized": authorized})

    @server.tool(annotations=write)
    def flow_disconnect() -> dict:
        """Pausar la cola local. No afirma que se haya detenido una generación remota."""
        return request("POST", "disconnect", {})

    @server.tool(annotations=read)
    def flow_get_status() -> dict:
        """Estado del agente y capacidades observadas. No devuelve credenciales ni rutas del escritorio."""
        return request("GET", "status")

    @server.tool(annotations=read)
    def flow_list_available_modes() -> dict:
        """Modos, formatos, referencias y duraciones del perfil local verificado; vacío si no se conocen."""
        return request("GET", "status").get("agent", {}).get("modes", {})

    @server.tool(annotations=write)
    def flow_focus_window() -> dict:
        """Enfocar la única ventana del ejecutable autorizado, bajo petición expresa."""
        return request("POST", "focus", {})

    @server.tool(annotations=write)
    def flow_generate_scene(project_id: UUID, chapter_id: UUID, scene_id: UUID, expected_revision: int,
                            request_id: UUID, generation_mode: Literal["image", "video", "image_video"] = "image",
                            prompt: str | None = None, video_prompt: str | None = None,
                            automatic_approval: bool = False, duration_seconds: float | None = None) -> list[dict]:
        """Encolar la revisión guardada. Puede usar cuota: requiere petición expresa. Imagen→video espera aprobación manual por defecto. No reenviar con otro ID ante timeout."""
        return plan(project_id, chapter_id, {str(scene_id): expected_revision}, request_id, generation_mode,
                    automatic_approval, {str(scene_id): prompt} if prompt is not None else {},
                    {str(scene_id): video_prompt} if video_prompt is not None else {}, duration_seconds)

    @server.tool(annotations=write)
    def flow_submit_image(project_id: UUID, chapter_id: UUID, scene_id: UUID, expected_revision: int,
                          request_id: UUID, prompt: str | None = None) -> list[dict]:
        """Encolar una imagen Flow con referencias de la revisión guardada, sin aprobarla ni animarla."""
        return plan(project_id, chapter_id, {str(scene_id): expected_revision}, request_id, "image",
                    prompts={str(scene_id): prompt} if prompt is not None else {})

    @server.tool(annotations=write)
    def flow_submit_video(project_id: UUID, chapter_id: UUID, scene_id: UUID, expected_revision: int,
                          request_id: UUID, prompt: str | None = None, duration_seconds: float | None = None) -> list[dict]:
        """Animar la imagen inicial elegida. Usa texto natural adaptado a Flow; no presupone sintaxis H3 ni cambia la narración."""
        return plan(project_id, chapter_id, {str(scene_id): expected_revision}, request_id, "video",
                    video_prompts={str(scene_id): prompt} if prompt is not None else {}, duration_seconds=duration_seconds)

    @server.tool(annotations=write)
    def flow_generate_chapter(project_id: UUID, chapter_id: UUID, scene_revisions: dict[str, int],
                              request_id: UUID, generation_mode: Literal["image", "video", "image_video"] = "image",
                              automatic_approval: bool = False, prompts: dict[str, str] | None = None,
                              video_prompts: dict[str, str] | None = None, duration_seconds: float | None = None) -> list[dict]:
        """Validar todas las escenas y encolar atómicamente en orden narrativo. Requiere IDs/revisiones reales. La aprobación automática solo bajo solicitud explícita."""
        return plan(project_id, chapter_id, scene_revisions, request_id, generation_mode,
                    automatic_approval, prompts, video_prompts, duration_seconds)

    @server.tool(annotations=read)
    def flow_get_job(job_id: UUID) -> dict:
        """Estado, referencias y prompts congelados del trabajo, sin controles arbitrarios de escritorio."""
        return request("GET", f"jobs/{job_id}")

    @server.tool(annotations=read)
    def flow_list_jobs(project_id: UUID, chapter_id: UUID | None = None) -> list[dict]:
        """Consultar trabajos de un proyecto; conserva aislamiento entre proyectos."""
        return request("GET", f"jobs?project_id={project_id}" + (f"&chapter_id={chapter_id}" if chapter_id else ""))

    @server.tool(annotations=write)
    def flow_cancel_job(job_id: UUID) -> dict:
        """Cancelar localmente; un envío incierto mantiene la reserva hasta confirmar su resultado/detención."""
        return request("POST", f"jobs/{job_id}/cancel", {})

    @server.tool(annotations=write)
    def flow_retry_job(job_id: UUID, request_id: UUID) -> dict:
        """Crear una nueva versión solo si el intento anterior terminó sin trabajo remoto activo."""
        return request("POST", f"jobs/{job_id}/retry", {"request_id": str(request_id)})

    @server.tool(annotations=write)
    def flow_import_result(job_id: UUID, asset_id: UUID) -> dict:
        """Asociar y validar una imagen ya importada en Studio. MP4 se descarga por el agente o se sube en la interfaz local; no admite rutas/URLs arbitrarias."""
        return request("POST", f"jobs/{job_id}/import-asset", {"asset_id": str(asset_id)})

    @server.tool(annotations=write)
    def flow_review_image(job_id: UUID, expected_revision: int, decision: Literal["approved", "rejected"]) -> dict:
        """Aprobar/rechazar SOLO conforme a la decisión del usuario. Aprobar puede desbloquear la animación solicitada anteriormente."""
        return request("POST", f"jobs/{job_id}/review", {"expected_revision": expected_revision, "decision": decision})


class BearerMiddleware:
    """ASGI authentication around the entire HTTP MCP app, including tool discovery."""
    def __init__(self, app, token):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            import secrets

            from starlette.responses import JSONResponse
            headers = dict(scope.get("headers", []))
            supplied = headers.get(b"authorization", b"").decode("latin1")
            if not secrets.compare_digest(supplied, "Bearer " + self.token):
                response = JSONResponse({"detail": "Se requiere token MCP."}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
