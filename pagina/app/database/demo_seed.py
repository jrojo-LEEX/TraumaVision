"""
demo_seed.py — Carga los 10 usuarios de demostración.

La app es un prototipo de tesis, no un despliegue clínico: no hay alta de
usuarios, registro ni recuperación de contraseña. En su lugar se crean diez
cuentas fijas al iniciar, cada una con su propia contraseña y su propio
historial aislado del resto.

Las credenciales se muestran en la pantalla de login **sólo** cuando
DEMO_MODE=true. Poner DEMO_MODE=false en .env las oculta.

La cuenta con rol admin se CREA igual que las otras pero NO se publica en el
login (auditoría 2026-09-01, 03_base_datos H10): es la que puede exportar en
CSV los análisis y las opiniones de todo el sistema, y una contraseña de
administrador en la portada no se contiene con nada si la app llega a
servirse en una red. Su clave vive únicamente en `DEMO_USERS`, acá abajo.
"""

from sqlalchemy.orm import Session

from app.database import crud
from app.database.models import User

# Diez médicos ficticios. La contraseña sigue el patrón <usuario>.demo2026,
# distinta por cuenta para que el aislamiento entre historiales sea real.
DEMO_USERS: list[dict] = [
    {"email": "admin@traumavision.demo",    "name": "Dra. Administradora",       "password": "admin.demo2026",    "is_admin": True},
    {"email": "traumatologia@traumavision.demo", "name": "Dr. Traumatología",    "password": "traumato.demo2026", "is_admin": False},
    {"email": "guardia@traumavision.demo",  "name": "Dra. Guardia",              "password": "guardia.demo2026",  "is_admin": False},
    {"email": "pediatria@traumavision.demo","name": "Dr. Pediatría",             "password": "pediatria.demo2026","is_admin": False},
    {"email": "radiologia@traumavision.demo","name": "Dra. Radiología",          "password": "radiologia.demo2026","is_admin": False},
    {"email": "residente1@traumavision.demo","name": "Residente 1",              "password": "residente1.demo2026","is_admin": False},
    {"email": "residente2@traumavision.demo","name": "Residente 2",              "password": "residente2.demo2026","is_admin": False},
    {"email": "residente3@traumavision.demo","name": "Residente 3",              "password": "residente3.demo2026","is_admin": False},
    {"email": "docente@traumavision.demo",  "name": "Docente Evaluador",         "password": "docente.demo2026",  "is_admin": False},
    {"email": "tribunal@traumavision.demo", "name": "Tribunal",                  "password": "tribunal.demo2026", "is_admin": False},
]


def seed_demo_users(db: Session) -> list[User]:
    """Crea los usuarios que falten. Idempotente: no pisa los que ya existen."""
    creados = []
    for spec in DEMO_USERS:
        if crud.get_user_by_email(db, spec["email"]) is not None:
            continue
        creados.append(
            crud.create_user(
                db,
                email=spec["email"],
                name=spec["name"],
                password=spec["password"],
                is_admin=spec["is_admin"],
            )
        )
    return creados


def demo_credentials() -> list[dict]:
    """Credenciales para mostrar en la pantalla de login en modo demo.

    Sólo las cuentas SIN privilegio. La admin existe (la crea `seed_demo_users`)
    pero no se lista: quien tenga que entrar con ella conoce la clave por el
    código, no por la portada.
    """
    return [
        {"email": u["email"], "name": u["name"], "password": u["password"], "is_admin": u["is_admin"]}
        for u in DEMO_USERS
        if not u["is_admin"]
    ]
