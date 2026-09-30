"""
admin_routes.py — Panel de administración (sólo usuarios con is_admin).

Es la única pantalla que ve datos de todos los usuarios. Los totales cuentan
sólo el modelo vigente; los CSV exportan todo.
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
from src.analytics.stats import N_MINIMO, tasa

router = APIRouter(prefix="/admin")

templates = crear_templates()


def _suma_de_booleana(columna):
    """SUM() de una columna booleana como entero.

    Sin el cast, SQLAlchemy devuelve la suma como bool (79 -> True).
    """
    return func.sum(cast(func.coalesce(columna, 0), Integer))


def _resumen_por_usuario(db: Session) -> list[dict]:
    """Una fila por usuario activo: análisis, % anormales y % de acuerdo."""
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
        filas.append({
            "nombre": u.name,
            "email": u.email,
            "es_admin": u.is_admin,
            "analisis": n,
            "anormal": tasa(anormales or 0, n),
            "feedbacks": n_fb,
            "acuerdo": tasa(acuerdos or 0, n_fb),
            "ultima_actividad": ultima,
        })
    filas.sort(key=lambda f: f["analisis"], reverse=True)  # los más activos primero
    return filas


@router.get("/", response_class=HTMLResponse)
async def admin_panel(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
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
    # created_at se guarda en UTC sin zona: se compara contra UTC.
    hace_30_dias = ahora_utc_naive() - timedelta(days=30)
    recientes = analisis.filter(Analysis.created_at >= hace_30_dias).scalar() or 0

    return templates.TemplateResponse(
        request, "admin.html",
        {
            "app_name": APP_NAME,
            "disclaimer": LEGAL_DISCLAIMER,
            "current_user": admin,
            "csrf_token": get_csrf_token(request),
            "filas": _resumen_por_usuario(db),
            "global": {
                "analisis": total,
                "anormales": anormales,
                "recientes_30d": recientes,
                "feedbacks": n_fb,
                "acuerdos": acuerdos,
                "desacuerdos": n_fb - acuerdos,
                "anormal": tasa(anormales, total),
                "acuerdo": tasa(acuerdos, n_fb),
            },
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
    """Todos los análisis del sistema, con el email del usuario."""
    consulta = (
        db.query(Analysis, User.email)
        .options(selectinload(Analysis.detection_boxes))
        .join(User, Analysis.user_id == User.id)
        .order_by(Analysis.created_at.desc())
        .all()
    )
    filas = [[email] + filas_analisis([a])[0] for a, email in consulta]
    return respuesta_csv("traumavision_analisis_global",
                         ["usuario"] + ENCABEZADOS_ANALISIS, filas)


@router.get("/export/opiniones.csv")
async def export_opiniones_global(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> StreamingResponse:
    """Todas las opiniones del sistema, con el email del usuario."""
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
