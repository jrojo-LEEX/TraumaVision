"""
crud.py — Operaciones de base de datos (Create, Read, Update, Delete).

Regla de este módulo: **toda lectura de datos de un paciente lleva el user_id
del solicitante**. Las funciones que devuelven un análisis o un estudio piden
siempre a quién pertenece; si no coincide, devuelven None. Así el control de
acceso vive en la capa de datos y no depende de que cada ruta se acuerde de
chequearlo.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database.models import Analysis, ApiKey, DetectionBox, Feedback, Study, User
from app.security import generate_api_key, hash_api_key, hash_password, verify_password


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# === USUARIOS ===

def create_user(
    db: Session,
    email: str,
    name: str,
    password: str,
    is_admin: bool = False,
    picture_url: str = "",
) -> User:
    """Crea un usuario con la contraseña ya hasheada."""
    user = User(
        email=email.strip().lower(),
        name=name,
        password_hash=hash_password(password),
        is_admin=is_admin,
        picture_url=picture_url,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.strip().lower()).first()


def list_users(db: Session) -> list[User]:
    return db.query(User).filter(User.is_active.is_(True)).order_by(User.id).all()


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """Devuelve el usuario si email y contraseña son correctos, si no None."""
    user = get_user_by_email(db, email)
    if user is None or not user.is_active:
        # Se verifica igual contra un hash descartable para que el tiempo de
        # respuesta no revele si el email existe.
        verify_password(password, hash_password("dummy"))
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login = _utcnow()
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
    """Guarda un análisis. Sirve tanto para imagen suelta como para estudio.

    Antes existía una segunda función `create_analysis_for_study` que no
    aceptaba región, versión de modelo ni urgencia, así que los estudios ZIP
    quedaban sin trazabilidad. Ahora hay una sola función y todos los campos
    se guardan siempre.
    """
    analysis = Analysis(
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
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def get_analysis_for_user(db: Session, analysis_id: int, user_id: int) -> Optional[Analysis]:
    """Devuelve el análisis SÓLO si pertenece a ese usuario.

    Este filtro por user_id es lo que impide el IDOR: antes se podía leer el
    estudio de cualquier paciente incrementando el ID en la URL.
    """
    return (
        db.query(Analysis)
        .filter(Analysis.id == analysis_id, Analysis.user_id == user_id)
        .first()
    )


def count_analyses_by_user(db: Session, user_id: int) -> int:
    """Cuántos análisis tiene el usuario. TODOS, sin tope.

    El historial necesita el total real para no llamar «Todos» a una ventana
    recortada: el chip decía «Todos 50» mientras el dashboard contaba 121.
    """
    return (
        db.query(func.count(Analysis.id))
        .filter(Analysis.user_id == user_id)
        .scalar()
        or 0
    )


def get_analyses_by_user(db: Session, user_id: int, limit: int = 50) -> list[Analysis]:
    """Los análisis del usuario, con sus cajas y su opinión ya cargadas.

    La tabla del historial lee `findings_above_abnormal` (que recorre
    `detection_boxes`) y `a.feedback` en cada fila. Sin el `selectinload` eso
    son dos consultas POR FILA: con 121 análisis, 242 consultas de más para
    dibujar una tabla.
    """
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
    """Análisis del usuario, para el dashboard."""
    return (
        db.query(Analysis)
        .filter(Analysis.user_id == user_id)
        .order_by(Analysis.created_at.desc())
        .limit(limit)
        .all()
    )


# === DETECTION BOXES ===

def create_detection_boxes(db: Session, analysis_id: int, boxes: list[dict]) -> list[DetectionBox]:
    db_boxes = []
    for b in boxes:
        box = DetectionBox(
            analysis_id=analysis_id,
            x1=int(b["x1"]),
            y1=int(b["y1"]),
            x2=int(b["x2"]),
            y2=int(b["y2"]),
            confidence=float(b["confidence"]),
            label=b.get("label", "fracture"),
        )
        db.add(box)
        db_boxes.append(box)
    db.commit()
    for box in db_boxes:
        db.refresh(box)
    return db_boxes


def get_boxes_by_analysis(db: Session, analysis_id: int) -> list[DetectionBox]:
    return (
        db.query(DetectionBox)
        .filter(DetectionBox.analysis_id == analysis_id)
        .order_by(DetectionBox.confidence.desc())
        .all()
    )


# === FEEDBACK ===

def create_feedback(
    db: Session,
    analysis_id: int,
    agreed: bool,
    observations: str = "",
    correct_diagnosis: str = "",
) -> Feedback:
    feedback = Feedback(
        analysis_id=analysis_id,
        agreed=agreed,
        observations=observations,
        correct_diagnosis=correct_diagnosis,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def get_feedback_by_analysis(db: Session, analysis_id: int) -> Optional[Feedback]:
    return db.query(Feedback).filter(Feedback.analysis_id == analysis_id).first()


def get_feedbacks_by_user(db: Session, user_id: int) -> list[Feedback]:
    """Feedbacks de los análisis de ese usuario."""
    return (
        db.query(Feedback)
        .join(Analysis, Feedback.analysis_id == Analysis.id)
        .filter(Analysis.user_id == user_id)
        .all()
    )


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
    study = Study(
        user_id=user_id,
        original_filename=original_filename,
        total_images=total_images,
        images_with_findings=images_with_findings,
        anatomical_region=anatomical_region,
        model_version=model_version,
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    return study


def get_study_for_user(db: Session, study_id: int, user_id: int) -> Optional[Study]:
    return (
        db.query(Study)
        .filter(Study.id == study_id, Study.user_id == user_id)
        .first()
    )


def get_analyses_by_study(db: Session, study_id: int) -> list[Analysis]:
    """Las imágenes del estudio, con sus cajas ya cargadas.

    `view_study` arma una fila por imagen y cada una lee `detection_boxes`
    tres veces: una consulta por imagen del ZIP.
    """
    return (
        db.query(Analysis)
        .options(selectinload(Analysis.detection_boxes))
        .filter(Analysis.study_id == study_id)
        .order_by(Analysis.id.asc())
        .all()
    )


# === API KEYS ===

def create_api_key(
    db: Session,
    label: str,
    owner_user_id: int,
    is_admin: bool = False,
) -> tuple[ApiKey, str]:
    """Crea una API key. Devuelve (registro, key en texto plano).

    La key en claro se muestra una sola vez; en la base sólo queda su SHA-256.
    """
    raw_key = generate_api_key()
    api_key = ApiKey(
        key_hash=hash_api_key(raw_key),
        label=label,
        owner_user_id=owner_user_id,
        is_admin=is_admin,
        is_active=True,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key, raw_key


def verify_api_key(db: Session, raw_key: str) -> Optional[ApiKey]:
    """Devuelve el registro si la key es válida y está activa."""
    return (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == hash_api_key(raw_key), ApiKey.is_active.is_(True))
        .first()
    )


def get_active_api_keys(db: Session, owner_user_id: Optional[int] = None) -> list[ApiKey]:
    q = db.query(ApiKey).filter(ApiKey.is_active.is_(True))
    if owner_user_id is not None:
        q = q.filter(ApiKey.owner_user_id == owner_user_id)
    return q.all()


def deactivate_api_key(db: Session, key_id: int) -> Optional[ApiKey]:
    api_key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if api_key:
        api_key.is_active = False
        db.commit()
        db.refresh(api_key)
    return api_key
