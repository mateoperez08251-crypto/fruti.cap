"""Migraciones Alembic, copia SQLite previa y comprobación antes de arrancar la cola."""

from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from frutinovelas.config import get_settings

log = logging.getLogger(__name__)


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


def backup_pending_sqlite(cfg: Config) -> Path | None:
    """Back up a real existing SQLite database using its backup API, including WAL pages."""
    url = make_url(cfg.get_main_option("sqlalchemy.url"))
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    path = Path(url.database).resolve()
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=15)) as source:
        has_version = source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        current = (
            {row[0] for row in source.execute("SELECT version_num FROM alembic_version")}
            if has_version
            else set()
        )
        if current == set(ScriptDirectory.from_config(cfg).get_heads()):
            return None
        folder = path.parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = folder / f"{path.stem}-antes-migracion-{stamp}-{uuid4().hex[:8]}.sqlite3"
        deadline = time.monotonic() + 60

        def progress(_status, _remaining, _total):
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "La copia de seguridad excedió el tiempo límite. Cierra las otras copias de Studio y reintenta."
                )

        try:
            with closing(sqlite3.connect(backup)) as destination:
                source.backup(destination, pages=256, progress=progress, sleep=0.05)
        except Exception:
            backup.unlink(missing_ok=True)
            raise
    log.info("Copia de seguridad previa a la migración: %s", backup)
    return backup


def validate_schema(db_url: str) -> None:
    """Fail startup once, before workers, if migration history disagrees with real columns."""
    from frutinovelas.models import Base

    engine = create_engine(db_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            missing = []
            for table in Base.metadata.sorted_tables:
                if table.name not in tables:
                    missing.append(table.name)
                    continue
                actual = {column["name"] for column in inspector.get_columns(table.name)}
                missing.extend(
                    f"{table.name}.{column.name}" for column in table.columns if column.name not in actual
                )
            if missing:
                raise RuntimeError(
                    "La base de datos está incompleta; faltan: "
                    + ", ".join(missing)
                    + ". No se inició la cola. Conserva la base y sus copias de seguridad; actualiza Studio antes de reintentar."
                )
    finally:
        engine.dispose()


def upgrade_to_head(db_url: str | None = None) -> None:
    cfg = alembic_config(db_url)
    backup_pending_sqlite(cfg)
    command.upgrade(cfg, "head")
    validate_schema(cfg.get_main_option("sqlalchemy.url"))
