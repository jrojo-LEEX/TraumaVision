"""
main.py — Punto de entrada de TraumaVision AI.

Configura la aplicación FastAPI: middlewares, sesión, plantillas, archivos
estáticos, base de datos y rutas.

Para arrancar:
    python -m app.main
o bien:
    uvicorn app.main:app --reload --port 8000
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
from app.plantillas import crear_templates
from config.settings import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_VERSION,
    CORS_ORIGINS,
    DEFAULT_REGION,
    DEMO_MODE,
    LEGAL_DISCLAIMER,
    SECRET_KEY,
    SESSION_COOKIE_NAME,
    SESSION_HTTPS_ONLY,
    SESSION_MAX_AGE_SECONDS,
)


def precalentar_modelo() -> bool:
    """Una inferencia de descarte para que el primer paciente no la pague.

    Medido (auditoría 2026-09-01, 05_integracion H5): la PRIMERA llamada a
    `predict()` de la vida del proceso tarda ~3,4 veces más que las
    siguientes, porque además de la inferencia paga la construcción diferida
    del predictor de Ultralytics. Cargar los pesos no alcanza: hay que
    inferir una vez. Se hace acá, al arrancar, sobre una imagen sintética
    chica; nada de lo que produce se guarda.

    Devuelve False, sin levantar, si el modelo no está: la app tiene que
    arrancar igual y avisar en pantalla al primer análisis, como ya hace.
    """
    from PIL import Image

    try:
        from src.detection.predict import FractureDetector

        detector = FractureDetector.get(DEFAULT_REGION)
        # 64 px de gris plano: lo más barato que atraviesa CLAHE y el modelo
        # sin dejar de ser una imagen.
        detector.predict(Image.new("RGB", (64, 64), color=128))
    except Exception as exc:  # noqa: BLE001 — cualquier fallo acá es sólo un aviso
        print(f"[TraumaVision] Sin warm-up del modelo: {type(exc).__name__}: {exc}")
        return False
    print("[TraumaVision] Modelo precalentado: la primera inferencia ya se pagó.")
    return True


# El warm-up corre UNA vez por proceso, no una vez por arranque de la app:
# los tests levantan la aplicación decenas de veces con TestClient y cada
# una dispararía el lifespan.
_modelo_precalentado = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepara la base al arrancar y precalienta el modelo."""
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

# --- Sesión firmada (cookie) ---
# https_only se controla con SESSION_HTTPS_ONLY en .env. Queda en False porque
# la demo corre sobre http://localhost; en cualquier despliegue con TLS hay que
# ponerlo en true, si no la cookie de sesión viaja en claro.
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie=SESSION_COOKIE_NAME,
    max_age=SESSION_MAX_AGE_SECONDS,
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
)

# --- CORS ---
# Lista explícita de orígenes. Con allow_credentials=True el comodín "*" es
# inválido por spec y el navegador rechaza la respuesta.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# --- Archivos estáticos (CSS, JS) ---
# Sólo assets públicos. Las radiografías NO se sirven desde acá: van por
# /analysis/imagen/{archivo}, que verifica que el estudio sea del usuario.
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

(Path(__file__).parent / "templates").mkdir(exist_ok=True)
templates = crear_templates()

(Path(__file__).parent / "uploads").mkdir(exist_ok=True)


# --- Cabeceras de seguridad ---
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


# --- Redirección al login ---
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

# Texto propio cuando el detalle es el genérico en inglés de Starlette: la
# interfaz está en español y "Not Found" suelto no le dice nada a nadie.
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

_DETALLES_GENERICOS_EN = {
    "Not Found", "Method Not Allowed", "Internal Server Error",
    "Forbidden", "Unauthorized", "Bad Request",
}


def _quiere_html(request: Request) -> bool:
    """Si el que pide es un navegador, y no un cliente de la API."""
    if request.url.path.startswith("/api/"):
        return False
    return "text/html" in request.headers.get("accept", "")


# Se registra sobre la clase de Starlette, no sobre la de FastAPI: una URL que
# no matchea ninguna ruta la levanta Starlette, y como la de FastAPI es una
# subclase, registrar la padre cubre los dos casos. Con la subclase sola, los
# 404 de ruta inexistente se escapaban y salían como JSON crudo.
@app.exception_handler(StarletteHTTPException)
async def redirect_o_error(request: Request, exc: HTTPException):
    """`require_user` levanta 303 con Location para mandar al formulario.

    Starlette no convierte sola una HTTPException en redirección, así que se
    traduce acá.

    Para el resto de los errores, a un navegador se le devuelve una página
    con la identidad del sistema y una salida. Antes cualquier URL mal
    tipeada devolvía `{"detail":"Not Found"}` en crudo, sin estilo ni
    navegación: en una demostración eso rompe la ilusión entera.
    La API sigue recibiendo JSON.
    """
    if exc.status_code == 303 and "location" in {k.lower() for k in (exc.headers or {})}:
        destino = next(v for k, v in exc.headers.items() if k.lower() == "location")
        return RedirectResponse(url=destino, status_code=303)

    if _quiere_html(request):
        from app.dependencies.csrf import get_csrf_token

        db = SessionLocal()
        try:
            user = get_current_user(request, db)
        except Exception:
            user = None
        finally:
            db.close()

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
                "detalle": (
                    exc.detail
                    if isinstance(exc.detail, str)
                    and exc.detail not in _DETALLES_GENERICOS_EN
                    else _DETALLES_ERROR.get(
                        exc.status_code, "No pudimos completar la operación."
                    )
                ),
            },
            status_code=exc.status_code,
        )

    return await http_exception_handler(request, exc)


# === RUTAS PRINCIPALES ===

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Entrada: al análisis si hay sesión, si no al login."""
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    finally:
        db.close()
    destino = "/analysis/upload" if user else "/login"
    return RedirectResponse(url=destino, status_code=303)


@app.get("/health")
async def health_check():
    """Estado del servicio."""
    from config.settings import YOLO_MODELS

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
    from app.dependencies.csrf import get_csrf_token

    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    finally:
        db.close()
    from config.settings import DEFAULT_REGION, MODEL_METADATA

    return templates.TemplateResponse(
        request, "legal.html",
        {
            "app_name": APP_NAME,
            "disclaimer": LEGAL_DISCLAIMER,
            "current_user": user,
            "csrf_token": get_csrf_token(request),
            # La página de alcance citaba el recall y el ECE en prosa, con los
            # números escritos a mano. Es la página que define qué promete el
            # sistema: si el modelo se reentrena y ella se queda quieta, el
            # alcance publicado pasa a ser falso. `None` si la región no está
            # publicada — y entonces la página no cita ninguna métrica.
            "meta": MODEL_METADATA.get(DEFAULT_REGION),
        },
    )


# --- Routers ---
from app.routes import (  # noqa: E402
    admin_routes,
    analysis_routes,
    api_routes,
    auth_routes,
    dashboard_routes,
    feedback_routes,
)

app.include_router(auth_routes.router, tags=["Sesión"])
app.include_router(analysis_routes.router, prefix="/analysis", tags=["Análisis"])
app.include_router(feedback_routes.router, prefix="/feedback", tags=["Feedback"])
app.include_router(dashboard_routes.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(admin_routes.router, tags=["Administración"])
app.include_router(api_routes.router)  # prefijo /api/v1 definido en el router


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
