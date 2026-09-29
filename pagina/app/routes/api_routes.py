"""
api_routes.py — API REST v1 para integración HIS/PACS.

Prefijo: /api/v1
Auth: header X-API-Key (se guarda sólo el SHA-256 en la tabla api_keys)

  POST /api/v1/analyze          analiza una imagen
  GET  /api/v1/analysis/{id}    resultado con bounding boxes
  POST /api/v1/feedback/{id}    feedback del radiólogo
  GET  /api/v1/models           modelos disponibles y sus métricas
  POST /api/v1/analyze/batch    (no implementado)
  POST /api/v1/keys             crea una API key — requiere X-Admin-Key

Cada API key pertenece a un usuario. Los análisis creados con ella quedan a
nombre de ese usuario y sólo esa key (u otra del mismo usuario) puede leerlos.
"""

import uuid
from io import BytesIO

import cv2
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import crud
from app.database.db import get_db
from app.database.models import ApiKey
from app.dependencies.api_key_auth import require_admin_key, require_api_key
from app.services.routing_service import calculate_urgency, route_image
from config.settings import (
    ABNORMAL_THRESHOLD,
    CONFIDENCE_THRESHOLD,
    DEFAULT_REGION,
    LEGAL_DISCLAIMER,
    MAX_UPLOAD_SIZE_MB,
    MODEL_METADATA,
    UPLOADS_DIR,
)

router = APIRouter(prefix="/api/v1", tags=["API REST v1"])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "application/dicom"}


# ─── POST /api/v1/analyze ────────────────────────────────────────────────────

@router.post("/analyze")
async def api_analyze(
    file: UploadFile = File(...),
    region: str = Form(DEFAULT_REGION),
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
):
    """Analiza una radiografía y devuelve el resultado en JSON."""
    filename_lower = (file.filename or "").lower()
    is_dicom = filename_lower.endswith(".dcm") or file.content_type == "application/dicom"

    if file.content_type not in _ALLOWED_TYPES and not is_dicom:
        raise HTTPException(
            status_code=400,
            detail="Tipo de archivo no permitido. Usar JPEG, PNG, BMP, TIFF o DICOM (.dcm).",
        )

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"La imagen excede el tamaño máximo de {MAX_UPLOAD_SIZE_MB} MB.",
        )
    if not contents:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")

    region_key, routing_method = route_image(region)

    try:
        if is_dicom:
            from src.preprocessing.transforms import load_dicom
            image = load_dicom(contents)
        else:
            image = Image.open(BytesIO(contents))
            image.load()
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="El archivo no es una imagen válida.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo procesar el archivo: {exc}")

    try:
        from src.detection.predict import FractureDetector
        detector = FractureDetector.get(region_key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Modelo no disponible: {exc}")

    analysis_uid = uuid.uuid4().hex[:12]
    original_filename = f"api{analysis_uid}_original.png"
    annotated_filename = f"api{analysis_uid}_annotated.png"

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(str(UPLOADS_DIR / original_filename))

    # La inferencia sale del bucle de eventos: ver el comentario en
    # analysis_routes.analyze_image.
    result = await run_in_threadpool(detector.predict, image)
    Image.fromarray(cv2.cvtColor(result.annotated_image, cv2.COLOR_BGR2RGB)).save(
        str(UPLOADS_DIR / annotated_filename)
    )

    report_text = detector.generate_report_text(result)
    urgency = calculate_urgency(result.max_detection_confidence)

    analysis = crud.create_analysis(
        db=db,
        user_id=api_key.owner_user_id,
        original_image_path=original_filename,
        annotated_image_path=annotated_filename,
        report_text=report_text,
        max_detection_confidence=result.max_detection_confidence,
        is_abnormal=result.is_abnormal,
        inference_time_ms=result.inference_time_ms,
        anatomical_region=region_key,
        model_version=result.model_version,
        routing_method=routing_method,
        urgency=urgency,
    )

    boxes_data = [
        {
            "x1": b.x1, "y1": b.y1, "x2": b.x2, "y2": b.y2,
            "confidence": round(b.confidence, 4),
            "above_abnormal_threshold": b.confidence >= ABNORMAL_THRESHOLD,
            "label": "fracture",
        }
        for b in result.boxes
    ]
    if boxes_data:
        crud.create_detection_boxes(db, analysis.id, boxes_data)

    return {
        "analysis_id": analysis.id,
        "region": region_key,
        "routing_method": routing_method,
        "is_abnormal": result.is_abnormal,
        "max_detection_confidence": round(result.max_detection_confidence, 4),
        "thresholds": {"draw": CONFIDENCE_THRESHOLD, "abnormal": ABNORMAL_THRESHOLD},
        "findings_above_threshold": len(result.significant_boxes),
        "low_confidence_findings": len(result.low_confidence_boxes),
        "urgency": urgency,
        "boxes": boxes_data,
        "inference_time_ms": round(result.inference_time_ms, 1),
        "model_version": result.model_version,
        "preprocessing": "clahe" if result.clahe_applied else "none",
        "disclaimer": LEGAL_DISCLAIMER,
    }


# ─── GET /api/v1/analysis/{id} ───────────────────────────────────────────────

@router.get("/analysis/{analysis_id}")
def api_get_analysis(
    analysis_id: int,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
):
    """Resultado completo de un análisis, si pertenece al dueño de la key."""
    analysis = crud.get_analysis_for_user(db, analysis_id, api_key.owner_user_id)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Análisis {analysis_id} no encontrado.")

    boxes = crud.get_boxes_by_analysis(db, analysis_id)

    return {
        "analysis_id": analysis.id,
        "region": analysis.anatomical_region,
        "routing_method": analysis.routing_method,
        "is_abnormal": analysis.is_abnormal,
        "max_detection_confidence": analysis.max_detection_confidence,
        "findings_above_threshold": analysis.findings_above_abnormal,
        "urgency": analysis.urgency,
        "boxes": [
            {
                "id": b.id,
                "x1": b.x1, "y1": b.y1, "x2": b.x2, "y2": b.y2,
                "confidence": b.confidence,
                "above_abnormal_threshold": b.confidence >= ABNORMAL_THRESHOLD,
                "label": b.label,
            }
            for b in boxes
        ],
        "report_text": analysis.report_text,
        "inference_time_ms": analysis.inference_time_ms,
        "model_version": analysis.model_version,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "disclaimer": LEGAL_DISCLAIMER,
    }


# ─── POST /api/v1/feedback/{id} ──────────────────────────────────────────────

@router.post("/feedback/{analysis_id}")
def api_submit_feedback(
    analysis_id: int,
    agreed: bool = Form(...),
    observations: str = Form(""),
    correct_diagnosis: str = Form(""),
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
):
    analysis = crud.get_analysis_for_user(db, analysis_id, api_key.owner_user_id)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Análisis {analysis_id} no encontrado.")

    if crud.get_feedback_by_analysis(db, analysis_id) is not None:
        raise HTTPException(status_code=409, detail="Ya se registró feedback para este análisis.")

    feedback = crud.create_feedback(
        db=db,
        analysis_id=analysis_id,
        agreed=agreed,
        observations=observations[:2000],
        correct_diagnosis=correct_diagnosis[:500],
    )
    return {
        "feedback_id": feedback.id,
        "analysis_id": analysis_id,
        "agreed": feedback.agreed,
        "message": "Feedback registrado correctamente.",
    }


# ─── GET /api/v1/models ──────────────────────────────────────────────────────

@router.get("/models")
def api_list_models(api_key: ApiKey = Depends(require_api_key)):
    """Modelos configurados, con las métricas medidas sobre su split de test."""
    return {
        "models": [
            {
                "region_key": region_key,
                "label": meta["label"],
                "description": meta["description"],
                "available": meta["available"],
                "metrics": {
                    "mAP50": meta.get("mAP50"),
                    "mAP50_95": meta.get("mAP50_95"),
                    "precision": meta.get("precision"),
                    "recall": meta.get("recall"),
                    "test_n": meta.get("test_n"),
                    "measured_on": meta.get("metrics_date"),
                },
            }
            for region_key, meta in MODEL_METADATA.items()
        ],
        "total": len(MODEL_METADATA),
    }


# ─── POST /api/v1/analyze/batch ──────────────────────────────────────────────

@router.post("/analyze/batch")
async def api_analyze_batch(
    file: UploadFile = File(...),
    region: str = Form(DEFAULT_REGION),
    api_key: ApiKey = Depends(require_api_key),
):
    """[No implementado] Analizar un ZIP con múltiples imágenes."""
    raise HTTPException(
        status_code=501,
        detail="Batch no implementado en esta versión. Usar POST /api/v1/analyze por imagen.",
    )


# ─── POST /api/v1/keys ───────────────────────────────────────────────────────

@router.post("/keys", status_code=201)
def api_create_key(
    label: str = Form(...),
    owner_user_id: int = Form(...),
    is_admin: bool = Form(False),
    db: Session = Depends(get_db),
    admin_key: ApiKey = Depends(require_admin_key),
):
    """Crea una API key nueva. Requiere una X-Admin-Key con privilegio admin.

    La key en texto plano se devuelve UNA sola vez; en la base queda su hash.
    """
    if crud.get_user_by_id(db, owner_user_id) is None:
        raise HTTPException(status_code=400, detail=f"El usuario {owner_user_id} no existe.")

    api_key_record, raw_key = crud.create_api_key(
        db, label=label, owner_user_id=owner_user_id, is_admin=is_admin
    )
    return {
        "id": api_key_record.id,
        "label": api_key_record.label,
        "owner_user_id": api_key_record.owner_user_id,
        "is_admin": api_key_record.is_admin,
        "key": raw_key,  # sólo en la creación
        "created_at": api_key_record.created_at.isoformat(),
        "warning": "Guardá esta key ahora. No se puede recuperar después.",
    }
