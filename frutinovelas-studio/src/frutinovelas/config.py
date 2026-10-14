"""Configuración de FRUTINOVELAS Studio.

Las variables se leen del entorno (prefijo ``FRUTINOVELAS_`` o nombres explícitos)
y opcionalmente de un archivo ``.env``. El directorio de datos es persistente y vive
fuera del código fuente; nunca depende del directorio de trabajo del proceso.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_dir
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "FRUTINOVELAS Studio"
APP_SLUG = "frutinovelas-studio"


def _default_data_dir() -> Path:
    return Path(user_data_dir(APP_SLUG, appauthor=False, roaming=False))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_dir: Path | None = Field(default=None, validation_alias="FRUTINOVELAS_DATA_DIR")

    api_host: str = Field(default="127.0.0.1", validation_alias="FRUTINOVELAS_API_HOST")
    api_port: int = Field(default=8765, validation_alias="FRUTINOVELAS_API_PORT")
    api_url: str = Field(default="http://127.0.0.1:8765", validation_alias="FRUTINOVELAS_API_URL")
    # Token opcional. Si se define, todas las rutas de modificación lo exigen
    # (cabecera Authorization: Bearer ...). Obligatorio cuando se expone en red.
    api_token: str | None = Field(default=None, validation_alias="FRUTINOVELAS_API_TOKEN")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"],
        validation_alias="FRUTINOVELAS_CORS_ORIGINS",
    )

    mcp_host: str = Field(default="127.0.0.1", validation_alias="FRUTINOVELAS_MCP_HOST")
    mcp_port: int = Field(default=8766, validation_alias="FRUTINOVELAS_MCP_PORT")
    # Token que deben presentar los clientes remotos del endpoint Streamable HTTP.
    mcp_token: str | None = Field(default=None, validation_alias="FRUTINOVELAS_MCP_TOKEN")
    # Token con el que el adaptador MCP se identifica ante el backend. El backend
    # reconoce así al actor MCP y le aplica su política (modo y proyecto) por sí mismo.
    mcp_backend_token: str | None = Field(default=None, validation_alias="FRUTINOVELAS_MCP_BACKEND_TOKEN")
    # Restringe todas las lecturas, imágenes y escrituras MCP a un proyecto.
    mcp_project_id: str | None = Field(default=None, validation_alias="FRUTINOVELAS_MCP_PROJECT_ID")
    # read_only | read_write
    mcp_access_mode: str = Field(default="read_write", validation_alias="FRUTINOVELAS_MCP_ACCESS_MODE")
    mcp_preview_max_edge: int = Field(default=1280, validation_alias="FRUTINOVELAS_MCP_PREVIEW_MAX_EDGE")
    mcp_max_page_size: int = Field(default=100, validation_alias="FRUTINOVELAS_MCP_MAX_PAGE_SIZE")
    mcp_max_frames: int = Field(default=5, validation_alias="FRUTINOVELAS_MCP_MAX_FRAMES")
    mcp_script_section_chars: int = Field(default=12000, validation_alias="FRUTINOVELAS_MCP_SCRIPT_SECTION_CHARS")
    mcp_backend_timeout: float = Field(default=30.0, validation_alias="FRUTINOVELAS_MCP_BACKEND_TIMEOUT")

    comfyui_base_url: str = Field(
        default="http://127.0.0.1:8188",
        validation_alias=AliasChoices("COMFYUI_BASE_URL", "FRUTINOVELAS_COMFYUI_BASE_URL"),
    )
    ffmpeg_path: str = Field(default="ffmpeg", validation_alias=AliasChoices("FFMPEG_PATH", "FRUTINOVELAS_FFMPEG_PATH"))
    ffprobe_path: str = Field(
        default="ffprobe", validation_alias=AliasChoices("FFPROBE_PATH", "FRUTINOVELAS_FFPROBE_PATH")
    )

    max_upload_mb: int = Field(default=40, validation_alias="FRUTINOVELAS_MAX_UPLOAD_MB")
    max_image_side: int = Field(default=8192, validation_alias="FRUTINOVELAS_MAX_IMAGE_SIDE")
    max_zip_mb: int = Field(default=2048, validation_alias="FRUTINOVELAS_MAX_ZIP_MB")
    max_zip_entries: int = Field(default=5000, validation_alias="FRUTINOVELAS_MAX_ZIP_ENTRIES")

    worker_poll_seconds: float = Field(default=1.5, validation_alias="FRUTINOVELAS_WORKER_POLL_SECONDS")
    worker_lease_seconds: float = Field(default=30.0, validation_alias="FRUTINOVELAS_WORKER_LEASE_SECONDS")
    # Ejecutar el coordinador dentro del proceso de la API (cómodo en local).
    embedded_worker: bool = Field(default=True, validation_alias="FRUTINOVELAS_EMBEDDED_WORKER")

    comfy_connect_timeout: float = Field(default=10.0, validation_alias="FRUTINOVELAS_COMFY_CONNECT_TIMEOUT")
    comfy_request_timeout: float = Field(default=60.0, validation_alias="FRUTINOVELAS_COMFY_REQUEST_TIMEOUT")
    comfy_execution_timeout: float = Field(
        default=3 * 3600.0, validation_alias="FRUTINOVELAS_COMFY_EXECUTION_TIMEOUT"
    )

    @property
    def resolved_data_dir(self) -> Path:
        base = self.data_dir if self.data_dir else _default_data_dir()
        return Path(base).expanduser().resolve()

    @property
    def db_path(self) -> Path:
        return self.resolved_data_dir / "frutinovelas.sqlite3"

    @property
    def assets_dir(self) -> Path:
        return self.resolved_data_dir / "assets"

    @property
    def versions_dir(self) -> Path:
        return self.resolved_data_dir / "versions"

    @property
    def exports_dir(self) -> Path:
        return self.resolved_data_dir / "exports"

    @property
    def tmp_dir(self) -> Path:
        return self.resolved_data_dir / "tmp"

    @property
    def cache_dir(self) -> Path:
        return self.resolved_data_dir / "cache"

    @property
    def logs_dir(self) -> Path:
        return self.resolved_data_dir / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.resolved_data_dir / "backups"

    def ensure_dirs(self) -> None:
        for d in (
            self.resolved_data_dir,
            self.assets_dir,
            self.versions_dir,
            self.exports_dir,
            self.tmp_dir,
            self.cache_dir,
            self.logs_dir,
            self.backups_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


def reset_settings_cache() -> None:
    """Usado por las pruebas para recargar configuración tras cambiar el entorno."""
    get_settings.cache_clear()
