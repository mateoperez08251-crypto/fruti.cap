"""Aplicación de migraciones Alembic sin archivo alembic.ini.

Las migraciones viven en ``migrations/`` en el repositorio y se empaquetan como
``frutinovelas/_migrations`` en la rueda (ver pyproject.toml).
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from frutinovelas.config import get_settings


def migrations_dir() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here / "_migrations", here.parents[1] / "migrations"):
        if (candidate / "env.py").is_file():
            return candidate
    raise FileNotFoundError("No se encontró la carpeta de migraciones de FRUTINOVELAS Studio.")


def alembic_config(db_url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir()))
    cfg.set_main_option("sqlalchemy.url", db_url or f"sqlite:///{get_settings().db_path}")
    return cfg


def upgrade_to_head(db_url: str | None = None) -> None:
    command.upgrade(alembic_config(db_url), "head")
