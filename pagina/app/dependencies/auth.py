"""
auth.py — Sesión del usuario en la interfaz web.

La cookie de sesión guarda `user_id`; estas dependencias lo buscan en la base
en cada request.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import crud
from app.database.db import get_db
from app.database.models import User
from app.dependencies.csrf import rotate_csrf_token

SESSION_USER_KEY = "user_id"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """El usuario logueado, o None si no hay sesión."""
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    user = crud.get_user_by_id(db, int(user_id))
    if user is None:
        # La sesión apunta a un usuario borrado o desactivado.
        request.session.clear()
    return user


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Exige sesión. Si no hay, redirige (303) al login recordando la página pedida en `next`."""
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
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Se requieren permisos de administrador.")
    return user


def login_user(request: Request, user: User) -> None:
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    # Token CSRF nuevo al autenticarse: evita la fijación de sesión.
    rotate_csrf_token(request)


def logout_user(request: Request) -> None:
    request.session.clear()
