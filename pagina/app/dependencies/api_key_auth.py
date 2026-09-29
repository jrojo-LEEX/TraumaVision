"""
api_key_auth.py — Autenticación por API Key para la API REST.

Lee el header X-API-Key y verifica su SHA-256 contra la tabla `api_keys`.

`require_admin_key` exige además que la key esté marcada como administradora.
Antes ambas dependencias hacían exactamente lo mismo y sólo cambiaba el nombre
del header, así que cualquier key válida podía crear keys nuevas.
"""

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.database import crud
from app.database.db import get_db
from app.database.models import ApiKey

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def require_api_key(
    raw_key: str = Security(_api_key_header),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Exige un X-API-Key válido y activo."""
    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="Header X-API-Key requerido.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    api_key = crud.verify_api_key(db, raw_key)
    if api_key is None:
        raise HTTPException(
            status_code=401,
            detail="API Key inválida o inactiva.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key


def require_admin_key(
    raw_key: str = Security(_admin_key_header),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Exige un X-Admin-Key válido, activo Y con privilegio de administrador."""
    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="Header X-Admin-Key requerido para esta operación.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    api_key = crud.verify_api_key(db, raw_key)
    if api_key is None:
        raise HTTPException(
            status_code=401,
            detail="Admin Key inválida o inactiva.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not api_key.is_admin:
        # 403, no 401: la key es válida, lo que falta es el privilegio.
        raise HTTPException(
            status_code=403,
            detail="Esta API Key no tiene privilegios de administrador.",
        )

    return api_key
