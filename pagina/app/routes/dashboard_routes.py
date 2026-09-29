"""
dashboard_routes.py — Estadísticas de uso y exportación de datos.

Las métricas son SIEMPRE del usuario logueado: cada médico ve su práctica.
La vista global vive en /admin (app/routes/admin_routes.py).

Exportación CSV: pensada para abrir directo en Excel en configuración
regional española/argentina — separador ';' y BOM UTF-8 (sin el BOM, Excel
interpreta los acentos como mojibake; con coma, mete todo en una columna).
"""

import csv
import io
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database import crud
from app.database.db import get_db
from app.database.models import Analysis, DetectionBox, Feedback, User
from app.dependencies.auth import require_user
from app.dependencies.csrf import get_csrf_token
from app.plantillas import crear_templates
from config.settings import (
    ABNORMAL_THRESHOLD,
    APP_NAME,
    CONFIDENCE_THRESHOLD,
    LEGAL_DISCLAIMER,
    MODEL_METADATA,
)
from config.tiempo import ahora_local, fmt_local
from src.analytics.stats import (
    analyses_per_day,
    calculate_agreement_rate,
    concordancia,
    confidence_distribution,
    dashboard_summary,
    desempeno_sistema,
    practica,
    urgency_distribution,
)

router = APIRouter()

templates = crear_templates()


def _registros(db: Session, user: User) -> list[dict]:
    """UNA fila por análisis, con la opinión del médico pegada al lado.

    Las métricas de concordancia se abren por propiedades del ANÁLISIS —qué
    dijo el sistema, con cuánta seguridad, en qué nivel de triage— así que la
    opinión tiene que viajar junto al análisis que la motivó. Con dos listas
    sueltas (análisis por un lado, opiniones por el otro) esa pregunta no se
    puede contestar: no hay por dónde unirlas.

    `agreed` es None cuando todavía no se opinó, y eso NO es lo mismo que un
    desacuerdo. La cobertura de revisión se calcula justamente contando esos
    None, así que el campo no se rellena con un valor por defecto.

    El conteo de zonas sale de una sola consulta agrupada y no de N consultas
    dentro del bucle.
    """
    analyses = crud.get_analyses_for_stats(db, user_id=user.id)
    ids = [a.id for a in analyses]

    opiniones: dict[int, bool] = {}
    zonas: dict[int, int] = {}
    if ids:
        opiniones = {
            f.analysis_id: f.agreed
            for f in db.query(Feedback).filter(Feedback.analysis_id.in_(ids)).all()
        }
        zonas = {
            fila[0]: fila[1]
            for fila in db.query(DetectionBox.analysis_id, func.count(DetectionBox.id))
            .filter(DetectionBox.analysis_id.in_(ids))
            .group_by(DetectionBox.analysis_id)
            .all()
        }

    return [
        {
            "id": a.id,
            "timestamp": a.created_at,
            "max_detection_confidence": a.max_detection_confidence or 0.0,
            "is_abnormal": a.is_abnormal,
            "urgency": a.urgency,
            "inference_time_ms": a.inference_time_ms,
            "model_version": a.model_version,
            "n_zonas": zonas.get(a.id, 0),
            "agreed": opiniones.get(a.id),
        }
        for a in analyses
    ]


def _datos_usuario(db: Session, user: User) -> tuple[list[dict], list[dict]]:
    """Forma vieja —dos listas sueltas— que siguen consumiendo el resumen del
    dashboard y el endpoint JSON. Se arma a partir de `_registros` para que no
    existan dos caminos que puedan contar cosas distintas."""
    registros = _registros(db, user)
    feedbacks_data = [
        {"agreed": r["agreed"], "timestamp": r["timestamp"]}
        for r in registros if r["agreed"] is not None
    ]
    return registros, feedbacks_data


def _desacuerdos(db: Session, user_id: int, limite: int = 15) -> list[dict]:
    """Los casos donde el médico corrigió al sistema: el material más valioso
    del dashboard, porque son los candidatos a reanotación y reentrenamiento."""
    filas = (
        db.query(Feedback, Analysis)
        .join(Analysis, Feedback.analysis_id == Analysis.id)
        .filter(Analysis.user_id == user_id, Feedback.agreed.is_(False))
        .order_by(Feedback.created_at.desc())
        .limit(limite)
        .all()
    )
    return [
        {
            "analysis_id": a.id,
            "fecha": f.created_at,
            "sistema_dijo": "Con hallazgo" if a.is_abnormal else "Sin hallazgos",
            "es_anormal": bool(a.is_abnormal),
            "diagnostico": f.correct_diagnosis or "—",
            "observaciones": f.observations or "",
        }
        for f, a in filas
    ]


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    analyses_data, feedbacks_data = _datos_usuario(db, user)
    per_day = analyses_per_day(analyses_data)
    urgencias = urgency_distribution(analyses_data)
    confianzas = confidence_distribution(analyses_data)

    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            "app_name": APP_NAME,
            "disclaimer": LEGAL_DISCLAIMER,
            "current_user": user,
            "csrf_token": get_csrf_token(request),
            "summary": dashboard_summary(analyses_data, feedbacks_data),
            # Listas de Python, no cadenas ya serializadas: la plantilla
            # las inyecta con el filtro tojson, que escapa para contexto de
            # script. Antes se serializaban acá y se marcaban como seguras en
            # la plantilla, lo que desactiva todo el escapado dentro del
            # bloque de script.
            "per_day_labels": per_day["labels"],
            "per_day_values": per_day["values"],
            "urgency_labels": urgencias["labels"],
            "urgency_values": urgencias["values"],
            "conf_labels": confianzas["labels"],
            "conf_values": confianzas["values"],
            "agreement": calculate_agreement_rate(feedbacks_data),
            # Las tres lecturas nuevas de la pantalla. Los umbrales que
            # parten las franjas de seguridad salen de settings, no de acá:
            # son los mismos con los que el visor decide qué dibuja y qué
            # clasifica como anormal.
            "concordancia": concordancia(
                analyses_data, CONFIDENCE_THRESHOLD, ABNORMAL_THRESHOLD),
            "sistema": desempeno_sistema(analyses_data),
            "practica": practica(analyses_data),
            "umbral_dibujo": CONFIDENCE_THRESHOLD,
            "corte_aviso": ABNORMAL_THRESHOLD,
            "desacuerdos": _desacuerdos(db, user.id),
            "model_metadata": MODEL_METADATA,
        },
    )


@router.get("/api/stats")
async def get_stats(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    analyses_data, feedbacks_data = _datos_usuario(db, user)
    return JSONResponse(content=dashboard_summary(analyses_data, feedbacks_data))


# ─── Exportación CSV ─────────────────────────────────────────────────────────

# Los cuatro caracteres con los que Excel, LibreOffice y Google Sheets abren
# una FÓRMULA, más el tabulador y el retorno de carro, que también arrancan
# expresión en algunos parsers.
_INICIOS_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r")

# Un número, en cualquiera de las dos notaciones decimales. El sistema exporta
# es-AR (coma), pero se acepta el punto para no depender de eso.
_RE_NUMERO = re.compile(r"^[+-]?(\d+([.,]\d+)?|[.,]\d+)$")


def _sanear_celda_csv(valor):
    """Neutraliza la inyección de fórmulas sin romper los números.

    Un médico escribe la observación de un desacuerdo; otro abre la planilla
    exportada y Excel le EJECUTA lo que el primero escribió. Prefijar con
    comilla simple obliga a la planilla a tratar la celda como texto; la
    comilla no se ve en la celda.

    El detalle que importa: `-12,5` empieza con `-` y **es un número**, no una
    fórmula. Prefijarlo lo convertiría en texto y la planilla dejaría de poder
    sumar la columna, que es para lo que se exporta. Por eso `+` y `-` sólo se
    neutralizan cuando lo que sigue NO es un número (`-1+1` sí, `-12,5` no).

    Los `int` y `float` se devuelven tal cual: no hay forma de que un número
    de Python sea una fórmula.
    """
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, (int, float)):
        return valor

    texto = str(valor)
    if not texto or texto[0] not in _INICIOS_DE_FORMULA:
        return texto
    if texto[0] in ("+", "-") and _RE_NUMERO.match(texto):
        return texto
    return "'" + texto


def respuesta_csv(nombre_base: str, encabezados: list[str], filas) -> StreamingResponse:
    """Arma la descarga CSV para Excel es-AR: BOM UTF-8 y separador ';'.

    Es el único embudo de las cuatro exportaciones del sistema (las dos del
    usuario y las dos globales del panel admin), así que el saneado va acá:
    ninguna puede olvidárselo.
    """
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\n")
    escritor.writerow([_sanear_celda_csv(e) for e in encabezados])
    escritor.writerows([_sanear_celda_csv(c) for c in fila] for fila in filas)

    contenido = "﻿" + buffer.getvalue()   # BOM: Excel detecta UTF-8
    fecha = ahora_local().strftime("%Y%m%d")
    return StreamingResponse(
        iter([contenido.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre_base}_{fecha}.csv"'},
    )


def filas_analisis(analyses: list[Analysis]) -> list[list]:
    return [
        [
            a.id,
            # La columna guarda UTC. Se exporta en la zona de presentación:
            # una planilla que dice otro día que la pantalla no sirve de nada.
            fmt_local(a.created_at, "%Y-%m-%d %H:%M"),
            a.anatomical_region or "",
            "anormal" if a.is_abnormal else "sin hallazgos",
            a.urgency or "",
            f"{(a.max_detection_confidence or 0):.4f}".replace(".", ","),
            a.findings_above_abnormal,
            len(a.detection_boxes),
            a.model_version or "",
            f"{(a.inference_time_ms or 0):.0f}",
        ]
        for a in analyses
    ]


ENCABEZADOS_ANALISIS = [
    "id", "fecha", "region", "clasificacion", "urgencia",
    "confianza_maxima", "hallazgos_sobre_umbral", "regiones_marcadas",
    "modelo", "inferencia_ms",
]


def filas_opiniones(pares: list[tuple[Feedback, Analysis]]) -> list[list]:
    return [
        [
            f.analysis_id,
            fmt_local(f.created_at, "%Y-%m-%d %H:%M"),
            "anormal" if a.is_abnormal else "sin hallazgos",
            "de acuerdo" if f.agreed else "en desacuerdo",
            f.correct_diagnosis or "",
            (f.observations or "").replace("\n", " "),
        ]
        for f, a in pares
    ]


ENCABEZADOS_OPINIONES = [
    "analisis_id", "fecha_opinion", "sistema_dijo", "opinion",
    "diagnostico_correcto", "observaciones",
]


@router.get("/export/analisis.csv")
async def export_analisis(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Todos los análisis del usuario logueado, para planilla o análisis externo."""
    # `filas_analisis` lee `findings_above_abnormal` y `len(detection_boxes)`
    # de cada análisis: sin cargar las cajas por adelantado es una consulta
    # por fila exportada.
    analyses = (
        db.query(Analysis)
        .options(selectinload(Analysis.detection_boxes))
        .filter(Analysis.user_id == user.id)
        .order_by(Analysis.created_at.desc())
        .all()
    )
    return respuesta_csv("traumavision_analisis", ENCABEZADOS_ANALISIS, filas_analisis(analyses))


@router.get("/export/opiniones.csv")
async def export_opiniones(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Las opiniones del usuario. Los desacuerdos son los candidatos a
    reanotación para un futuro reentrenamiento."""
    pares = (
        db.query(Feedback, Analysis)
        .join(Analysis, Feedback.analysis_id == Analysis.id)
        .filter(Analysis.user_id == user.id)
        .order_by(Feedback.created_at.desc())
        .all()
    )
    return respuesta_csv("traumavision_opiniones", ENCABEZADOS_OPINIONES, filas_opiniones(pares))
