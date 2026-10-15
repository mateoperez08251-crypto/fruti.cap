"""Conexión a SQLite mediante SQLAlchemy 2.x.

Política de conexiones:
- Un motor por ruta de base de datos (caché por proceso).
- Cada conexión activa claves foráneas, WAL, ``busy_timeout`` y ``synchronous=NORMAL``.
- Sesiones cortas: una por petición HTTP; nunca se mantiene una transacción abierta
  durante una inferencia o una descarga.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from frutinovelas.config import get_settings

BUSY_TIMEOUT_MS = 15_000


def _configure_sqlite(dbapi_connection, _record) -> None:  # pragma: no cover - trivial
    cur = dbapi_connection.cursor()
    try:
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cur.execute("PRAGMA synchronous=NORMAL")
    finally:
        cur.close()


@lru_cache(maxsize=4)
def _engine_for(db_path: str) -> Engine:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": BUSY_TIMEOUT_MS / 1000, "check_same_thread": False},
        future=True,
    )
    event.listen(engine, "connect", _configure_sqlite)
    return engine


def get_engine() -> Engine:
    return _engine_for(str(get_settings().db_path))


@lru_cache(maxsize=4)
def _sessionmaker_for(db_path: str) -> sessionmaker[Session]:
    return sessionmaker(bind=_engine_for(db_path), expire_on_commit=False, future=True)


def session_factory() -> sessionmaker[Session]:
    return _sessionmaker_for(str(get_settings().db_path))


def get_session() -> Iterator[Session]:
    """Dependencia FastAPI: una sesión por petición."""
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_engine_cache() -> None:
    """Usado por las pruebas al cambiar de directorio de datos."""
    for fn in (_engine_for, _sessionmaker_for):
        fn.cache_clear()
