"""
main.py — Punto de entrada de TraumaVision AI.

Arma la aplicación FastAPI: sesión, CORS, archivos estáticos, errores y rutas.
Se arranca con `python -m app.main`.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.database.db import SessionLocal, create_tables
from app.database.demo_seed import seed_demo_users
from app.dependencies.auth import get_current_user
from app.dependencies.csrf import get_csrf_token
from app.plantillas import crear_templates
from config.settings import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_VERSION,
    CORS_ORIGINS,
    DEFAULT_REGION,
    DEMO_MODE,
    LEGAL_DISCLAIMER,
    MODEL_METADATA,
    SECRET_KEY,
    SESSION_COOKIE_NAME,
    SESSION_HTTPS_ONLY,
    SESSION_MAX_AGE_SECONDS,
    YOLO_MODELS,
)

CARPETA_APP = Path(__file__).parent


def precalentar_modelo() -> None:
    """Hace una inferencia de descarte: la primera siempre es mucho más lenta."""
    from PIL import Image

    try:
        from src.detection.predict import FractureDetector

        detector = FractureDetector.get(DEFAULT_REGION)
        detector.predict(Image.new("RGB", (64, 64), color=128))
    except Exception as exc:  # noqa: BLE001 — sin modelo la app arranca igual
        print(f"[TraumaVision] Sin warm-up del modelo: {type(exc).__name__}: {exc}")
        return
    print("[TraumaVision] Modelo precalentado: la primera inferencia ya se pagó.")


# Una sola vez por proceso: los tests levantan la app muchas veces.
_modelo_precalentado = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Al arrancar: crea las tablas, los usuarios demo y precalienta el modelo."""
    global _modelo_precalentado

    create_tables()
    if DEMO_MODE:
        db = SessionLocal()
        try:
            creados = seed_demo_users(db)
            if creados:
                print(f"[TraumaVision] {len(creados)} usuarios de demostración creados.")
        finally:
            db.close()
    if not _modelo_precalentado:
        _modelo_precalentado = True
        precalentar_modelo()
    yield


app = FastAPI(
    title=APP_NAME,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    lifespan=lifespan,
)

# Sesión en una cookie firmada. Con TLS hay que poner SESSION_HTTPS_ONLY=true.
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie=SESSION_COOKIE_NAME,
    max_age=SESSION_MAX_AGE_SECONDS,
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Sólo CSS y JS. Las radiografías van por /analysis/imagen/, que verifica al dueño.
(CARPETA_APP / "static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(CARPETA_APP / "static")), name="static")

(CARPETA_APP / "templates").mkdir(exist_ok=True)
templates = crear_templates()

(CARPETA_APP / "uploads").mkdir(exist_ok=True)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    # Las imágenes de pacientes no deben quedar en caches intermedios.
    if request.url.path.startswith("/analysis/imagen/"):
        response.headers["Cache-Control"] = "private, no-store"
    return response


# --- Páginas de error ---

_TITULOS_ERROR = {
    400: "Pedido inválido",
    401: "Sesión no iniciada",
    403: "Sin permiso para ver esto",
    404: "No encontramos esa página",
    413: "El archivo es demasiado grande",
    429: "Demasiados intentos",
    500: "Error interno del sistema",
    503: "El servicio no está disponible",
}

_DETALLES_ERROR = {
    400: "El pedido no se pudo interpretar. Revisá el enlace e intentá de nuevo.",
    401: "Iniciá sesión para continuar.",
    403: "Esta cuenta no tiene acceso a ese recurso.",
    404: "La dirección no existe o el estudio ya no está disponible.",
    413: "El archivo supera el tamaño permitido.",
    429: "Esperá unos minutos antes de volver a intentar.",
    500: "Ocurrió un error inesperado. Si se repite, revisá la consola del servidor.",
    503: "El modelo o el servicio no están disponibles en este momento.",
}

# Mensajes en inglés de Starlette que se reemplazan por el texto en español.
_DETALLES_GENERICOS_EN = {
    "Not Found", "Method Not Allowed", "Internal Server Error",
    "Forbidden", "Unauthorized", "Bad Request",
}


def _usuario_de_la_sesion(request: Request):
    """El usuario logueado o None, con una sesión de base propia."""
    db = SessionLocal()
    try:
        return get_current_user(request, db)
    finally:
        db.close()


def _detalle_del_error(exc: HTTPException) -> str:
    if isinstance(exc.detail, str) and exc.detail not in _DETALLES_GENERICOS_EN:
        return exc.detail
    return _DETALLES_ERROR.get(exc.status_code, "No pudimos completar la operación.")


# Se registra sobre la clase de Starlette para atrapar también los 404 de rutas inexistentes.
@app.exception_handler(StarletteHTTPException)
async def redirect_o_error(request: Request, exc: HTTPException):
    """Convierte el 303 de `require_user` en redirección; a un navegador le muestra una página de error."""
    cabeceras = {k.lower(): v for k, v in (exc.headers or {}).items()}
    if exc.status_code == 303 and "location" in cabeceras:
        return RedirectResponse(url=cabeceras["location"], status_code=303)

    if "text/html" not in request.headers.get("accept", ""):
        return await http_exception_handler(request, exc)

    try:
        user = _usuario_de_la_sesion(request)
    except Exception:
        user = None

    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "app_name": APP_NAME,
            "disclaimer": LEGAL_DISCLAIMER,
            "current_user": user,
            "csrf_token": get_csrf_token(request),
            "status_code": exc.status_code,
            "titulo": _TITULOS_ERROR.get(exc.status_code, "Algo salió mal"),
            "detalle": _detalle_del_error(exc),
        },
        status_code=exc.status_code,
    )


# --- Rutas sueltas ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Al análisis si hay sesión; si no, al login."""
    destino = "/analysis/upload" if _usuario_de_la_sesion(request) else "/login"
    return RedirectResponse(url=destino, status_code=303)


@app.get("/health")
async def health_check():
    modelos = {k: Path(v).exists() for k, v in YOLO_MODELS.items()}
    return {
        "status": "ok" if all(modelos.values()) else "degraded",
        "app": APP_NAME,
        "version": APP_VERSION,
        "demo_mode": DEMO_MODE,
        "models_available": modelos,
    }


@app.get("/aviso-legal", response_class=HTMLResponse)
async def aviso_legal(request: Request):
    return templates.TemplateResponse(
        request, "legal.html",
        {
            "app_name": APP_NAME,
            "disclaimer": LEGAL_DISCLAIMER,
            "current_user": _usuario_de_la_sesion(request),
            "csrf_token": get_csrf_token(request),
            "meta": MODEL_METADATA.get(DEFAULT_REGION),
        },
    )


# --- Routers ---
from app.routes import (  # noqa: E402
    admin_routes,
    analysis_routes,
    auth_routes,
    dashboard_routes,
    feedback_routes,
)

app.include_router(auth_routes.router, tags=["Sesión"])
app.include_router(analysis_routes.router, prefix="/analysis", tags=["Análisis"])
app.include_router(feedback_routes.router, prefix="/feedback", tags=["Feedback"])
app.include_router(dashboard_routes.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(admin_routes.router, tags=["Administración"])


if __name__ == "__main__":
    import uvicorn

    print(f"\n{'=' * 60}")
    print(f"  {APP_NAME} v{APP_VERSION}")
    print(f"  {APP_DESCRIPTION}")
    print(f"{'=' * 60}")
    print("\n  Navegador:      http://localhost:8000")
    print("  Documentación:  http://localhost:8000/docs")
    if DEMO_MODE:
        print("  Modo demo activo — las credenciales se listan en la pantalla de login.\n")

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
