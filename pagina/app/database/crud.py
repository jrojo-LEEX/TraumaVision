"""
crud.py — Lecturas y escrituras en la base de datos.

Regla: toda función que devuelve datos de un paciente recibe el `user_id` del
que pide y filtra por él. Así un médico nunca ve estudios de otro.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database.models import Analysis, DetectionBox, Feedback, Study, User
from app.security import hash_password, verify_password
from config.settings import VERSIONES_VIGENTES


def condicion_vigente():
    """Filtro SQL: el análisis se hizo con el modelo vigente."""
    return Analysis.model_version.in_(sorted(VERSIONES_VIGENTES))


def _guardar(db: Session, objeto):
    db.add(objeto)
    db.commit()
    db.refresh(objeto)
    return objeto


# === USUARIOS ===

def create_user(db: Session, email: str, name: str, password: str, is_admin: bool = False) -> User:
    return _guardar(db, User(
        email=email.strip().lower(),
        name=name,
        password_hash=hash_password(password),
        is_admin=is_admin,
    ))


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.strip().lower()).first()


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """El usuario si email y contraseña son correctos; si no, None."""
    user = get_user_by_email(db, email)
    if user is None or not user.is_active:
        # Se calcula un hash igual, para que el tiempo de respuesta no revele si el email existe.
        verify_password(password, hash_password("dummy"))
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    return user


# === ANÁLISIS ===

def create_analysis(
    db: Session,
    user_id: int,
    original_image_path: str,
    annotated_image_path: str,
    report_text: str,
    max_detection_confidence: float,
    is_abnormal: bool,
    inference_time_ms: float,
    anatomical_region: Optional[str] = None,
    model_version: Optional[str] = None,
    routing_method: Optional[str] = None,
    urgency: Optional[str] = None,
    study_id: Optional[int] = None,
) -> Analysis:
    """Guarda un análisis, de imagen suelta o parte de un estudio."""
    return _guardar(db, Analysis(
        user_id=user_id,
        study_id=study_id,
        original_image_path=original_image_path,
        annotated_image_path=annotated_image_path,
        report_text=report_text,
        max_detection_confidence=max_detection_confidence,
        is_abnormal=is_abnormal,
        inference_time_ms=inference_time_ms,
        anatomical_region=anatomical_region,
        model_version=model_version,
        routing_method=routing_method,
        urgency=urgency,
    ))


def get_analysis_for_user(db: Session, analysis_id: int, user_id: int) -> Optional[Analysis]:
    """El análisis, sólo si es de ese usuario (si no, None)."""
    return (
        db.query(Analysis)
        .filter(Analysis.id == analysis_id, Analysis.user_id == user_id)
        .first()
    )


def count_analyses_by_user(db: Session, user_id: int) -> int:
    return db.query(func.count(Analysis.id)).filter(Analysis.user_id == user_id).scalar() or 0


def count_analyses_anteriores(db: Session, user_id: Optional[int] = None) -> int:
    """Análisis de modelos no vigentes. Sin `user_id`, los de todo el sistema."""
    # El IS NULL va aparte porque NOT IN nunca es verdadero para un NULL.
    consulta = db.query(func.count(Analysis.id)).filter(
        (Analysis.model_version.is_(None)) | ~condicion_vigente()
    )
    if user_id is not None:
        consulta = consulta.filter(Analysis.user_id == user_id)
    return consulta.scalar() or 0


def get_analyses_by_user(db: Session, user_id: int, limit: int = 50) -> list[Analysis]:
    """Los análisis del usuario, más nuevos primero, con cajas y opinión ya cargadas."""
    return (
        db.query(Analysis)
        .options(
            selectinload(Analysis.detection_boxes),
            selectinload(Analysis.feedback),
        )
        .filter(Analysis.user_id == user_id)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(limit)
        .all()
    )


def get_analyses_for_stats(db: Session, user_id: int, limit: int = 1000) -> list[Analysis]:
    """Los análisis del usuario hechos con el modelo vigente."""
    return (
        db.query(Analysis)
        .filter(Analysis.user_id == user_id, condicion_vigente())
        .order_by(Analysis.created_at.desc())
        .limit(limit)
        .all()
    )


# === CAJAS ===

def create_detection_boxes(db: Session, analysis_id: int, boxes: list[dict]) -> None:
    for b in boxes:
        db.add(DetectionBox(
            analysis_id=analysis_id,
            x1=int(b["x1"]),
            y1=int(b["y1"]),
            x2=int(b["x2"]),
            y2=int(b["y2"]),
            confidence=float(b["confidence"]),
        ))
    db.commit()


def get_boxes_by_analysis(db: Session, analysis_id: int) -> list[DetectionBox]:
    """Las cajas del análisis, de mayor a menor confianza."""
    return (
        db.query(DetectionBox)
        .filter(DetectionBox.analysis_id == analysis_id)
        .order_by(DetectionBox.confidence.desc())
        .all()
    )


# === OPINIONES ===

def create_feedback(
    db: Session,
    analysis_id: int,
    agreed: bool,
    observations: str = "",
    correct_diagnosis: str = "",
) -> Feedback:
    return _guardar(db, Feedback(
        analysis_id=analysis_id,
        agreed=agreed,
        observations=observations,
        correct_diagnosis=correct_diagnosis,
    ))


def get_feedback_by_analysis(db: Session, analysis_id: int) -> Optional[Feedback]:
    return db.query(Feedback).filter(Feedback.analysis_id == analysis_id).first()


# === ESTUDIOS ===

def create_study(
    db: Session,
    user_id: int,
    original_filename: str,
    total_images: int,
    images_with_findings: int,
    anatomical_region: Optional[str] = None,
    model_version: Optional[str] = None,
) -> Study:
    return _guardar(db, Study(
        user_id=user_id,
        original_filename=original_filename,
        total_images=total_images,
        images_with_findings=images_with_findings,
        anatomical_region=anatomical_region,
        model_version=model_version,
    ))


def get_study_for_user(db: Session, study_id: int, user_id: int) -> Optional[Study]:
    """El estudio, sólo si es de ese usuario (si no, None)."""
    return db.query(Study).filter(Study.id == study_id, Study.user_id == user_id).first()


def get_analyses_by_study(db: Session, study_id: int) -> list[Analysis]:
    """Las imágenes del estudio en orden, con sus cajas ya cargadas."""
    return (
        db.query(Analysis)
        .options(selectinload(Analysis.detection_boxes))
        .filter(Analysis.study_id == study_id)
        .order_by(Analysis.id.asc())
        .all()
    )
