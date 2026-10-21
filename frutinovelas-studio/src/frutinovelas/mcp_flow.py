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
    def flow_connect(mode: Literal["assisted", "uia"] = "assisted", authorized: bool = False) -> dict:
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
