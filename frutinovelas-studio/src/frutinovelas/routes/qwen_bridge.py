"""Loopback OpenAI bridge: upstream non-streaming, local SSE compatibility."""
from __future__ import annotations

import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from frutinovelas.flow_vision import VisionClient, load_connection
from frutinovelas.routes.flow import guard
from frutinovelas.services.flow_transport import FlowError

router = APIRouter(prefix="/qwen/v1", tags=["Qwen local"], dependencies=[Depends(guard)])


def authorized(request):
    try:
        connection = load_connection()
    except FlowError as exc:
        raise HTTPException(503, str(exc)) from exc
    supplied = ("Bearer " + request.headers["x-qwen-key"] if request.headers.get("x-qwen-key") else
                request.headers.get("authorization", ""))
    if not secrets.compare_digest(supplied, "Bearer " + connection.api_key):
        raise HTTPException(401, "Se requiere la clave Qwen configurada.")
    return connection


def sse_frames(result, include_usage=False):
    """Serialize only the actual provider response; never execute returned tools."""
    common = {"id": result["id"], "object": "chat.completion.chunk",
              "created": result.get("created", int(time.time())), "model": result["model"]}
    def frame(choices, **extra):
        return "data: " + json.dumps({**common, "choices": choices, **extra}, ensure_ascii=False) + "\n\n"
    for choice in result["choices"]:
        message = dict(choice["message"])
        # Streaming tool calls require an index; preserve IDs, names and arguments.
        if message.get("tool_calls"):
            message["tool_calls"] = [{**tool, "index": index} for index, tool in enumerate(message["tool_calls"])]
        index = choice.get("index", 0)
        yield frame([{"index": index, "delta": message, "finish_reason": None}])
        yield frame([{"index": index, "delta": {}, "finish_reason": choice.get("finish_reason")}])
    if include_usage and result.get("usage"):
        yield frame([], usage=result["usage"])
    yield "data: [DONE]\n\n"


@router.get("/models")
def models(request: Request):
    connection = authorized(request)
    return {"object": "list", "data": [{"id": connection.model, "object": "model", "owned_by": "configured-qwen"}]}


@router.post("/chat/completions")
async def complete(request: Request):
    connection = authorized(request)
    raw = await request.body()
    if len(raw) > 16 * 1024**2:
        raise HTTPException(413, "La consulta supera 16 MiB.")
    try:
        body = json.loads(raw)
        if not isinstance(body, dict) or not isinstance(body.get("messages"), list) or not body["messages"]:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Se requiere una consulta OpenAI con messages.") from exc
    if body.get("model") != connection.model:
        raise HTTPException(422, "Selecciona el ID exacto de modelo publicado en /models.")
    stream = body.get("stream", False)
    if not isinstance(stream, bool):
        raise HTTPException(422, "stream debe ser booleano.")
    options = body.pop("stream_options", None)
    include_usage = isinstance(options, dict) and options.get("include_usage") is True
    body["stream"] = False
    def query():
        client = VisionClient(connection.base_url, connection.api_key, timeout_seconds=180)
        try:
            result = client._request("POST", "chat/completions", body)
            if (not isinstance(result, dict) or not isinstance(result.get("choices"), list)
                    or not result["choices"] or not result.get("id") or not result.get("model")
                    or any(not isinstance(choice, dict) or not isinstance(choice.get("message"), dict)
                           for choice in result["choices"])):
                raise FlowError("Qwen devolvió una respuesta de chat incompleta.")
            return result
        finally:
            client.close()
    try:
        result = await run_in_threadpool(query)
    except FlowError as exc:
        raise HTTPException(502, str(exc)) from exc
    if not stream:
        return JSONResponse(result)
    return StreamingResponse(sse_frames(result, include_usage), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
