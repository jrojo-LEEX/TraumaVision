"""
db.py — Configuración de la base de datos.

SQLite mediante SQLAlchemy. Un archivo único, sin servidor que instalar.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config.settings import DATABASE_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """Activa las claves foráneas en SQLite.

    SQLite las ignora por defecto. Sin este PRAGMA se podían insertar análisis
    con user_id apuntando a un usuario inexistente — que es exactamente lo que
    había pasado: 558 análisis con user_id=1 y la tabla users vacía.
    """
    if not _is_sqlite:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def get_db():
    """Sesión de base de datos por request (dependency de FastAPI)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    """Crea todas las tablas definidas en models.py si no existen."""
    from app.database.models import ALL_MODELS  # noqa: F401  (registra el metadata)

    assert ALL_MODELS  # las 6 tablas quedan registradas al importar
    Base.metadata.create_all(bind=engine)
