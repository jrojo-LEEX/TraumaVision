"""
demo_seed.py — Los 10 usuarios de demostración.

Se crean al arrancar en modo demo. El login muestra sus credenciales, salvo
la de la cuenta admin, que no se publica.
"""

from sqlalchemy.orm import Session

from app.database import crud
from app.database.models import User

DEMO_USERS: list[dict] = [
    {"email": "admin@traumavision.demo",         "name": "Dra. Administradora", "password": "admin.demo2026",      "is_admin": True},
    {"email": "traumatologia@traumavision.demo", "name": "Dr. Traumatología",   "password": "traumato.demo2026",   "is_admin": False},
    {"email": "guardia@traumavision.demo",       "name": "Dra. Guardia",        "password": "guardia.demo2026",    "is_admin": False},
    {"email": "pediatria@traumavision.demo",     "name": "Dr. Pediatría",       "password": "pediatria.demo2026",  "is_admin": False},
    {"email": "radiologia@traumavision.demo",    "name": "Dra. Radiología",     "password": "radiologia.demo2026", "is_admin": False},
    {"email": "residente1@traumavision.demo",    "name": "Residente 1",         "password": "residente1.demo2026", "is_admin": False},
    {"email": "residente2@traumavision.demo",    "name": "Residente 2",         "password": "residente2.demo2026", "is_admin": False},
    {"email": "residente3@traumavision.demo",    "name": "Residente 3",         "password": "residente3.demo2026", "is_admin": False},
    {"email": "docente@traumavision.demo",       "name": "Docente Evaluador",   "password": "docente.demo2026",    "is_admin": False},
    {"email": "tribunal@traumavision.demo",      "name": "Tribunal",            "password": "tribunal.demo2026",   "is_admin": False},
]


def seed_demo_users(db: Session) -> list[User]:
    """Crea los usuarios que falten y devuelve los creados."""
    return [
        crud.create_user(db, **u)
        for u in DEMO_USERS
        if crud.get_user_by_email(db, u["email"]) is None
    ]


def demo_credentials() -> list[dict]:
    """Las cuentas sin privilegio de admin, para listarlas en el login."""
    return [dict(u) for u in DEMO_USERS if not u["is_admin"]]
