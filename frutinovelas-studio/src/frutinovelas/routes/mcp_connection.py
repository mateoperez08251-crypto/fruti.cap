"""Asistente de conexión MCP para el Studio local. No administra cuentas ni secretos."""

from fastapi import APIRouter, HTTPException, Response

from frutinovelas.services.mcp_connection import (
    McpConnectionInfo,
    McpConnectionStatus,
    connection_info,
    connection_status,
)

router = APIRouter(prefix="/mcp", tags=["conexión MCP"])


@router.get("/connection", response_model=McpConnectionInfo)
def get_mcp_connection(response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return connection_info()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/status", response_model=McpConnectionStatus)
async def get_mcp_status(response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await connection_status()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
