"""
auth.py — Autenticación por sesión para la interfaz web.

El usuario se guarda en la cookie de sesión firmada (SessionMiddleware) como
`user_id`. Estas dependencias lo resuelven contra la base en cada request.

Uso:
    @router.get("/algo")
    async def algo(user: User = Depends(require_user)):
        ...
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import crud
from app.database.db import get_db
from app.database.models import User

SESSION_USER_KEY = "user_id"


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Devuelve el usuario logueado, o None. No bloquea el request."""
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    user = crud.get_user_by_id(db, int(user_id))
    if user is None:
        # La sesión apunta a un usuario borrado o desactivado: se limpia.
        request.session.clear()
        return None
    return user


def require_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Exige sesión activa. Si no hay, redirige al login.

    Se responde 303 con Location en vez de 401 para que el navegador vaya
    directo al formulario, conservando en `next` la página pedida.
    """
    user = get_current_user(request, db)
    if user is None:
        destino = request.url.path
        if request.url.query:
            destino = f"{destino}?{request.url.query}"
        raise HTTPException(
            status_code=303,
            detail="Se requiere iniciar sesión.",
            headers={"Location": f"/login?next={destino}"},
        )
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    """Exige que el usuario logueado sea administrador."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Se requieren permisos de administrador.")
    return user


def login_user(request: Request, user: User) -> None:
    """Registra al usuario en la sesión y rota el token CSRF."""
    from app.dependencies.csrf import rotate_csrf_token

    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    # Token nuevo tras autenticarse: evita la fijación de sesión.
    rotate_csrf_token(request)


def logout_user(request: Request) -> None:
    request.session.clear()
