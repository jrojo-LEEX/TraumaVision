"""
admin_routes.py — Panel de administración.

Vista GLOBAL del sistema, reservada al perfil administrador (User.is_admin):
actividad por usuario, acuerdo médico-IA por perfil, totales, y exportación
CSV de todo el sistema. Es la única pantalla que cruza datos de más de un
usuario — el resto de la app aísla cada cuenta a su propia práctica.

Los totales, el acuerdo y la actividad por usuario cuentan SÓLO análisis del
modelo vigente (y sus opiniones); la pantalla dice cuántos anteriores quedaron
afuera. Las exportaciones CSV siguen completas: son datos crudos y traen la
columna del modelo.

El flag is_admin existía en el modelo desde la migración 002 pero ninguna
pantalla lo usaba: este panel le da el propósito.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session, selectinload

from app.database import crud
from app.database.crud import condicion_vigente
from app.database.db import get_db
from app.database.models import Analysis, Feedback, User
from app.dependencies.auth import require_admin
from app.dependencies.csrf import get_csrf_token
from app.plantillas import crear_templates
from app.routes.dashboard_routes import (
    ENCABEZADOS_ANALISIS,
    ENCABEZADOS_OPINIONES,
    filas_analisis,
    filas_opiniones,
    respuesta_csv,
)
from config.settings import APP_NAME, LEGAL_DISCLAIMER, MODEL_METADATA, MODELO_VIGENTE
from config.tiempo import ahora_utc_naive
# Las proporciones del panel pasan por el MISMO embudo que las de Métricas:
# denominador siempre a la vista y, por debajo de N_MINIMO, recuento crudo en
# vez de porcentaje. Este panel las calculaba a mano y publicaba «100 %» de
# acuerdo sobre una única opinión (auditoría 2026-09-01, 04_web H5).
from src.analytics.stats import N_MINIMO, tasa

router = APIRouter(prefix="/admin")

templates = crear_templates()


def _suma_de_booleana(columna):
    """SUM() sobre una columna Boolean, devuelta como entero.

    `func.sum(func.coalesce(Analysis.is_abnormal, 0))` parece correcto y no lo
    es: la expresión hereda el tipo Boolean de la columna, así que SQLAlchemy
    le aplica el procesador de resultado de Boolean a la SUMA y 79 vuelve como
    `True`. Después `True / 121 * 100` se muestra como 1 %.

    El `cast(..., Integer)` le dice al ORM qué tipo tiene el agregado. Sin él
    el panel informaba 1 % donde el valor real era 65 %, para todos los
    usuarios y en las dos columnas de porcentaje.
    """
    return func.sum(cast(func.coalesce(columna, 0), Integer))


def _hace_treinta_dias():
    """El borde de la ventana de 30 días, comparable con `Analysis.created_at`.

    La columna guarda UTC como naive. `datetime.now()` devuelve hora LOCAL
    naive, así que la comparación corría la ventana tantas horas como tenga el
    offset de la máquina: en Argentina, tres.
    """
    return ahora_utc_naive() - timedelta(days=30)


def _resumen_por_usuario(db: Session) -> list[dict]:
    """Una fila por usuario: actividad, mezcla y acuerdo. Todo en dos consultas
    agregadas — nada de traer 572 filas para contarlas en Python."""
    actividad = {
        uid: (total, anormales, ultima)
        for uid, total, anormales, ultima in db.query(
            Analysis.user_id,
            func.count(Analysis.id),
            _suma_de_booleana(Analysis.is_abnormal),
            func.max(Analysis.created_at),
        ).filter(condicion_vigente()).group_by(Analysis.user_id)
    }
    opiniones = {
        uid: (total, acuerdos)
        for uid, total, acuerdos in db.query(
            Analysis.user_id,
            func.count(Feedback.id),
            _suma_de_booleana(Feedback.agreed),
        )
        .join(Analysis, Feedback.analysis_id == Analysis.id)
        .filter(condicion_vigente())
        .group_by(Analysis.user_id)
    }

    filas = []
    for u in db.query(User).filter(User.is_active.is_(True)).order_by(User.id):
        n, anormales, ultima = actividad.get(u.id, (0, 0, None))
        n_fb, acuerdos = opiniones.get(u.id, (0, 0))
        anormal = tasa(anormales or 0, n)
        acuerdo = tasa(acuerdos or 0, n_fb)
        filas.append({
            "nombre": u.name,
            "email": u.email,
            "es_admin": u.is_admin,
            "analisis": n,
            "anormal": anormal,
            "feedbacks": n_fb,
            "acuerdo": acuerdo,
            # Los dos porcentajes en crudo se conservan sólo para el código que
            # los lee como número (tests de la agregación). La plantilla NO los
            # usa: publica `anormal` / `acuerdo` a través de las macros, que
            # son las que saben callarse cuando la muestra no alcanza.
            "pct_anormal": anormal["tasa"] * 100 if n else None,
            "pct_acuerdo": acuerdo["tasa"] * 100 if n_fb else None,
            "ultima_actividad": ultima,
        })
    # Los más activos primero: es la lectura natural del panel.
    filas.sort(key=lambda f: f["analisis"], reverse=True)
    return filas


@router.get("/", response_class=HTMLResponse)
async def admin_panel(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    filas = _resumen_por_usuario(db)

    # Sólo el modelo vigente. Las opiniones se cuentan por el análisis que
    # opinan: una opinión sobre un análisis de v2 no es acuerdo con v1r.
    analisis = db.query(func.count(Analysis.id)).filter(condicion_vigente())
    opiniones = (
        db.query(func.count(Feedback.id))
        .join(Analysis, Feedback.analysis_id == Analysis.id)
        .filter(condicion_vigente())
    )
    total = analisis.scalar() or 0
    anormales = analisis.filter(Analysis.is_abnormal.is_(True)).scalar() or 0
    n_fb = opiniones.scalar() or 0
    acuerdos = opiniones.filter(Feedback.agreed.is_(True)).scalar() or 0
    hace_30 = _hace_treinta_dias()
    recientes = analisis.filter(Analysis.created_at >= hace_30).scalar() or 0
    desacuerdos = n_fb - acuerdos

    return templates.TemplateResponse(
        request, "admin.html",
        {
            "app_name": APP_NAME,
            "disclaimer": LEGAL_DISCLAIMER,
            "current_user": admin,
            "csrf_token": get_csrf_token(request),
            "filas": filas,
            "global": {
                "analisis": total,
                "anormales": anormales,
                "recientes_30d": recientes,
                "feedbacks": n_fb,
                "acuerdos": acuerdos,
                "desacuerdos": desacuerdos,
                "anormal": tasa(anormales, total),
                "acuerdo": tasa(acuerdos, n_fb),
            },
            # El pie de la tabla cita el umbral de muestra mínima: sale de
            # stats.py, no se escribe en la plantilla.
            "n_minimo": N_MINIMO,
            "model_metadata": MODEL_METADATA,
            "modelo_vigente": MODELO_VIGENTE,
            "n_anteriores": crud.count_analyses_anteriores(db),
        },
    )


@router.get("/export/analisis.csv")
async def export_analisis_global(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> StreamingResponse:
    """Todos los análisis del sistema, con la columna de usuario agregada.

    Completo a propósito, también los de modelos anteriores: es el dato crudo
    y trae la columna `modelo`."""
    filas = []
    # Igual que el export propio: `filas_analisis` recorre las cajas de cada
    # análisis. Acá pesa el doble, porque son los 600 del sistema entero.
    consulta = (
        db.query(Analysis, User.email)
        .options(selectinload(Analysis.detection_boxes))
        .join(User, Analysis.user_id == User.id)
        .order_by(Analysis.created_at.desc())
        .all()
    )
    for a, email in consulta:
        filas.append([email] + filas_analisis([a])[0])
    return respuesta_csv("traumavision_analisis_global",
                         ["usuario"] + ENCABEZADOS_ANALISIS, filas)


@router.get("/export/opiniones.csv")
async def export_opiniones_global(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> StreamingResponse:
    """Todas las opiniones del sistema. Los desacuerdos alimentan un futuro
    reentrenamiento."""
    consulta = (
        db.query(Feedback, Analysis, User.email)
        .join(Analysis, Feedback.analysis_id == Analysis.id)
        .join(User, Analysis.user_id == User.id)
        .order_by(Feedback.created_at.desc())
        .all()
    )
    filas = [[email] + filas_opiniones([(f, a)])[0] for f, a, email in consulta]
    return respuesta_csv("traumavision_opiniones_global",
                         ["usuario"] + ENCABEZADOS_OPINIONES, filas)
