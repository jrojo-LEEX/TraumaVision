"""
csrf.py — Protección contra Cross-Site Request Forgery.

Cada sesión tiene un token aleatorio que va oculto en los formularios (o en
el header X-CSRF-Token) y se verifica en cada POST. Otra página no puede
leerlo, así que no puede falsificar un envío en nombre del médico.
"""

import secrets

from fastapi import HTTPException, Request

SESSION_CSRF_KEY = "csrf_token"


def get_csrf_token(request: Request) -> str:
    """El token de la sesión; lo crea la primera vez."""
    if not request.session.get(SESSION_CSRF_KEY):
        rotate_csrf_token(request)
    return request.session[SESSION_CSRF_KEY]


def rotate_csrf_token(request: Request) -> None:
    request.session[SESSION_CSRF_KEY] = secrets.token_urlsafe(32)


async def verify_csrf(request: Request) -> None:
    """Dependencia de los POST: 403 si falta el token o no coincide con el de la sesión."""
    esperado = request.session.get(SESSION_CSRF_KEY)

    enviado = request.headers.get("X-CSRF-Token")
    if not enviado:
        try:
            enviado = (await request.form()).get("csrf_token")
        except Exception:
            enviado = None

    if not esperado or not enviado or not secrets.compare_digest(str(esperado), str(enviado)):
        raise HTTPException(
            status_code=403,
            detail="Token de seguridad inválido o vencido. Recargá la página e intentá de nuevo.",
        )
