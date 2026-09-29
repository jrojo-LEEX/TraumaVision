"""
auth_routes.py — Inicio y cierre de sesión.

  GET  /login    formulario
  POST /login    valida credenciales y abre la sesión
  POST /logout   cierra la sesión

En modo demo (DEMO_MODE=true) la pantalla de login lista las cuentas de
demostración SIN privilegio con su contraseña, para que el tribunal pueda
entrar sin credenciales previas. La cuenta admin se crea pero no se publica
(ver demo_seed.py). Con DEMO_MODE=false la lista no se muestra.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import crud
from app.database.db import get_db
from app.database.demo_seed import demo_credentials
from app.dependencies.auth import get_current_user, login_user, logout_user
from app.dependencies.csrf import get_csrf_token, verify_csrf
from app.plantillas import crear_templates
from app.services.rate_limit import check_and_consume
from config.settings import APP_NAME, DEMO_MODE, LEGAL_DISCLAIMER

router = APIRouter()

templates = crear_templates()

# Intentos de login por IP y por hora, para que no se pueda probar contraseñas
# a fuerza bruta contra las diez cuentas conocidas.
_MAX_INTENTOS_POR_HORA = 40


def _login_context(request: Request, **extra) -> dict:
    return {
        "app_name": APP_NAME,
        "disclaimer": LEGAL_DISCLAIMER,
        "demo_mode": DEMO_MODE,
        "demo_users": demo_credentials() if DEMO_MODE else [],
        "csrf_token": get_csrf_token(request),
        **extra,
    }


def _destino_seguro(next_url: str | None) -> str:
    """Evita el open redirect: sólo se aceptan rutas internas."""
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        return "/analysis/upload"
    return next_url


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next: str | None = None,
    db: Session = Depends(get_db),
):
    if get_current_user(request, db) is not None:
        return RedirectResponse(url=_destino_seguro(next), status_code=303)
    return templates.TemplateResponse(
        request, "login.html", _login_context(request, next=next or "")
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "desconocida"
    permitido, _ = check_and_consume(f"login:{ip}", _MAX_INTENTOS_POR_HORA)
    if not permitido:
        return templates.TemplateResponse(
            request, "login.html",
            _login_context(
                request,
                next=next,
                error="Demasiados intentos fallidos. Esperá unos minutos.",
            ),
            status_code=429,
        )

    user = crud.authenticate_user(db, email, password)
    if user is None:
        # Mismo mensaje para email inexistente y contraseña incorrecta: no hay
        # que revelar cuáles de las cuentas existen.
        return templates.TemplateResponse(
            request, "login.html",
            _login_context(request, next=next, error="Email o contraseña incorrectos.", email=email),
            status_code=401,
        )

    login_user(request, user)
    return RedirectResponse(url=_destino_seguro(next), status_code=303)


@router.post("/logout")
async def logout(request: Request, _: None = Depends(verify_csrf)):
    logout_user(request)
    return RedirectResponse(url="/login", status_code=303)
