"""
db.py — Conexión a la base de datos (SQLite con SQLAlchemy).
"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config.settings import DATABASE_URL

_es_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _es_sqlite else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


@event.listens_for(Engine, "connect")
def _activar_claves_foraneas(dbapi_connection, connection_record):
    """SQLite ignora las claves foráneas si no se le pide lo contrario."""
    if not _es_sqlite:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def get_db():
    """Una sesión de base por request (dependencia de FastAPI)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    """Crea las tablas de models.py que todavía no existan."""
    import app.database.models  # noqa: F401 — registra las tablas en Base.metadata

    Base.metadata.create_all(bind=engine)
