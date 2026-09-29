"""
conftest.py — Fixtures compartidas.

Cada test corre contra una base SQLite **en memoria** (antes el comentario
decía "en memoria" pero se usaba un archivo `test.db` que quedaba en el repo).
Se usa StaticPool para que todas las sesiones compartan la misma conexión, que
es lo que hace falta para que una base en memoria sobreviva entre requests.
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import crud
from app.database.db import Base, get_db
from app.main import app
from app.services import rate_limit

TEST_USER = {
    "email": "test@traumavision.demo",
    "name": "Usuaria de Prueba",
    "password": "prueba.demo2026",
}
OTHER_USER = {
    "email": "otro@traumavision.demo",
    "name": "Otro Médico",
    "password": "otro.demo2026",
}


@pytest.fixture(scope="function")
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()


@pytest.fixture(scope="function")
def db_session(engine):
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(engine):
    """Cliente HTTP sin sesión iniciada."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    rate_limit.reset()

    # El cliente no sigue redirecciones por defecto: así los tests pueden
    # comprobar que una ruta protegida devuelve 303 hacia /login.
    with TestClient(app, follow_redirects=False) as c:
        yield c

    app.dependency_overrides.clear()
    rate_limit.reset()


@pytest.fixture(scope="function")
def users(engine):
    """Crea dos usuarios: el del test y otro, para probar el aislamiento."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        principal = crud.create_user(db, **TEST_USER)
        otro = crud.create_user(db, **OTHER_USER)
        db.refresh(principal)
        db.refresh(otro)
        return {"principal": principal.id, "otro": otro.id}
    finally:
        db.close()


_CSRF_RE = re.compile(r'name="csrf_token"\s+value="([^"]+)"')


def leer_csrf(client, ruta: str = "/analysis/upload") -> str:
    """Extrae el token CSRF de una página ya renderizada.

    Los formularios lo llevan como campo oculto. Los tests lo mandan por el
    header X-CSRF-Token, que la dependencia acepta igual que el campo.
    """
    r = client.get(ruta)
    m = _CSRF_RE.search(r.text)
    assert m, f"No se encontró el token CSRF en {ruta} (status {r.status_code})"
    return m.group(1)


@pytest.fixture(scope="function")
def auth_client(client, users):
    """Cliente con sesión iniciada como el usuario principal.

    Deja el token CSRF puesto como header por defecto, para que cada test no
    tenga que buscarlo. El test que verifica la protección lo saca a propósito.
    """
    r = client.post(
        "/login",
        data={"email": TEST_USER["email"], "password": TEST_USER["password"]},
    )
    assert r.status_code == 303, f"El login falló: {r.status_code}"
    client.headers["X-CSRF-Token"] = leer_csrf(client)
    return client


@pytest.fixture(scope="function")
def other_client(engine, users):
    """Segundo cliente, logueado como el otro usuario."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, follow_redirects=False) as c:
        r = c.post(
            "/login",
            data={"email": OTHER_USER["email"], "password": OTHER_USER["password"]},
        )
        assert r.status_code == 303
        c.headers["X-CSRF-Token"] = leer_csrf(c)
        yield c
