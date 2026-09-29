"""
feedback_routes.py — Opinión del médico sobre un análisis.

El feedback mide la tasa de acuerdo médico-IA (métrica de la tesis) y es la
base para un futuro reentrenamiento.

Sólo se acepta feedback sobre análisis del propio usuario.
"""

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import crud
from app.database.db import get_db
from app.database.models import User
from app.dependencies.auth import require_user
from app.dependencies.csrf import verify_csrf

router = APIRouter()


@router.post("/submit")
async def submit_feedback(
    analysis_id: int = Form(...),
    agreed: bool = Form(...),
    observations: str = Form(""),
    correct_diagnosis: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
):
    """Registra el feedback y vuelve a la pantalla del análisis."""
    # El filtro por usuario impide dejar feedback sobre estudios ajenos.
    analysis = crud.get_analysis_for_user(db, analysis_id, user.id)
    if not analysis:
        return RedirectResponse(url="/analysis/history?error=notfound", status_code=303)

    if crud.get_feedback_by_analysis(db, analysis_id) is not None:
        return RedirectResponse(
            url=f"/analysis/{analysis_id}/results?feedback=duplicado", status_code=303
        )

    crud.create_feedback(
        db=db,
        analysis_id=analysis_id,
        agreed=agreed,
        observations=observations.strip()[:2000],
        correct_diagnosis=correct_diagnosis.strip()[:500],
    )

    return RedirectResponse(
        url=f"/analysis/{analysis_id}/results?feedback=ok", status_code=303
    )
