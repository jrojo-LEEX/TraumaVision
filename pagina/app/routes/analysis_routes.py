"""
analysis_routes.py — Rutas de análisis de radiografías.

  GET  /analysis/upload              formulario de carga
  POST /analysis/upload              analiza una imagen
  POST /analysis/upload-study        analiza un ZIP de DICOM
  GET  /analysis/history             historial del usuario
  GET  /analysis/{id}/results        resultado guardado
  GET  /analysis/{id}/pdf            informe en PDF
  POST /analysis/{id}/email          envía el informe por email
  GET  /analysis/study/{id}          resultado de un estudio
  GET  /analysis/imagen/{archivo}    sirve una imagen, previa verificación

Todas exigen sesión iniciada y sólo devuelven datos del usuario logueado.
"""

import json
import re
import uuid
from io import BytesIO
from pathlib import Path

import cv2
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.database import crud
from app.database.db import get_db
from app.database.models import User
from app.dependencies.auth import require_user
from app.dependencies.csrf import get_csrf_token, verify_csrf
from app.plantillas import crear_templates
from app.services.rate_limit import check_and_consume, segundos_hasta_liberar
from app.services.routing_service import (
    calculate_urgency,
    imagen_mas_urgente,
    route_image,
    urgency_detail,
)
from config.settings import (
    ABNORMAL_THRESHOLD,
    APP_NAME,
    CONFIDENCE_THRESHOLD,
    DEFAULT_REGION,
    EMAIL_RATE_LIMIT_PER_HOUR,
    MODELO_VIGENTE,
    LEGAL_DISCLAIMER,
    MAX_UPLOAD_SIZE_MB,
    MAX_ZIP_SIZE_MB,
    MODEL_METADATA,
    REGION_AVAILABLE,
    REGION_LABELS,
    SMTP_EMAIL,
    UPLOADS_DIR,
    es_modelo_vigente,
    texto_del_informe,
)

router = APIRouter()

templates = crear_templates()

# Tope de filas del historial. Antes eran 50, escritas a mano, y el chip
# "Todos" contaba esas 50 mientras el dashboard contaba 121 análisis: el
# número decía ser algo que no era.
#
# La tabla ya pagina de a 15 del lado del cliente, así que recortar la
# consulta no ahorraba nada de lo que se ve — sólo escondía registros
# clínicos. El tope queda como red de seguridad para una cuenta con años de
# uso; si alguna vez se alcanza, la pantalla lo dice con el total real en
# lugar de llamarlo "Todos".
HISTORIAL_MAX_FILAS = 500

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "application/dicom"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(png|jpg|jpeg)$")


def _base_context(request: Request, user: User) -> dict:
    """Contexto común de todas las plantillas."""
    return {
        "app_name": APP_NAME,
        "disclaimer": LEGAL_DISCLAIMER,
        "current_user": user,
        "model_metadata": MODEL_METADATA,
        "region_labels": REGION_LABELS,
        "region_available": REGION_AVAILABLE,
        "max_size_mb": MAX_UPLOAD_SIZE_MB,
        "max_zip_mb": MAX_ZIP_SIZE_MB,
        "abnormal_threshold": ABNORMAL_THRESHOLD,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        # Constantes de presentación. El bloque de alcance clínico cita el
        # recall y el dominio validado: son constantes de configuración, no
        # cálculos. Nada acá cambia una decisión, sólo la muestra.
        "model_sensitivity": MODEL_METADATA.get(DEFAULT_REGION, {}).get("recall", 0.0),
        "dominio_label": MODEL_METADATA.get(DEFAULT_REGION, {}).get(
            "label", DEFAULT_REGION
        ),
        # La fila entera de la región por defecto. El bloque de alcance del
        # visor citaba el ECE y el n de validación escritos a mano; con la
        # metadata a mano los deriva igual que el dashboard. Es `None` si la
        # región no está publicada, y entonces el bloque no cita métricas.
        "meta": MODEL_METADATA.get(DEFAULT_REGION),
        # El modelo vigente, para que el bloque de alcance de un análisis
        # hecho con otro modelo diga de quién son las métricas que cita.
        "modelo_vigente": MODELO_VIGENTE,
        "csrf_token": get_csrf_token(request),
    }


def _texto_del_informe(analysis) -> str:
    """El informe de texto que se puede mostrar (ver `texto_del_informe`)."""
    return texto_del_informe(analysis.model_version, analysis.report_text)


def _modelo_anterior(region, model_version) -> bool:
    """Análisis de la región validada hecho con un modelo que ya no está en uso.

    Distinto de «fuera del dominio» (región retirada o sin registrar), que ya
    tenía su aviso: éste es el caso de muñeca con v1, v2 o un registro viejo.
    Se muestra con cajas e imagen, pero sin prioridad de triage ni el corte de
    aviso del modelo vigente, que no son suyos.
    """
    return region == DEFAULT_REGION and not es_modelo_vigente(model_version)


def _boxes_json(boxes) -> str:
    """Las cajas YA PERSISTIDAS, serializadas para el cliente.

    No calcula nada ni vuelve a inferir: lee `detection_boxes` tal como la
    dejó el análisis y la pasa a la plantilla. Sirve para que el panel pueda
    encender sobre la placa el hallazgo que el médico señala, en vez de
    describir con palabras dónde está cada caja.

    Las coordenadas están en el espacio de píxeles de la imagen original, y
    la anotada tiene exactamente ese mismo tamaño, así que el cliente saca
    las dimensiones del propio `naturalWidth`/`naturalHeight` y no hace
    falta abrir el archivo en el servidor.

    Ordenadas por confianza descendente para que el índice coincida con el
    número de fila que muestra el panel.
    """
    ordenadas = sorted(boxes, key=lambda b: b.confidence, reverse=True)
    return json.dumps(
        [
            {
                "i": i,
                "x1": b.x1,
                "y1": b.y1,
                "x2": b.x2,
                "y2": b.y2,
                "c": round(b.confidence, 4),
            }
            for i, b in enumerate(ordenadas)
        ],
        separators=(",", ":"),
    )


def _upload_error(request: Request, user: User, mensaje: str, status_code: int = 200):
    return templates.TemplateResponse(
        request, "upload.html",
        {**_base_context(request, user), "error": mensaje},
        status_code=status_code,
    )


# ─── Formulario ──────────────────────────────────────────────────────────────

@router.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(request, "upload.html", _base_context(request, user))


# ─── Análisis de una imagen ──────────────────────────────────────────────────

async def _archivo_del_formulario(request: Request) -> tuple[StarletteUploadFile | None, str]:
    """Lee `file` y `region` del multipart, DESPUÉS de las dependencias.

    Los dos handlers de análisis declaraban `file: UploadFile = File(...)` en
    la firma. FastAPI parsea el cuerpo ANTES de resolver las dependencias
    cuando hay parámetros de cuerpo, así que un anónimo podía mandar 60 MB
    y el servidor se los tragaba enteros —a disco, por encima de 1 MB— para
    recién después contestarle 303 al login (auditoría 2026-09-01, 04_web
    H6). Sacando los parámetros de cuerpo de la firma, las dependencias se
    resuelven en orden de declaración: `require_user` corta sin haber leído
    un byte, y `verify_csrf` es el primero que toca el formulario.
    """
    form = await request.form()
    archivo = form.get("file")
    # El formulario crudo entrega el UploadFile de Starlette, del que el de
    # FastAPI es subclase: hay que comprobar contra el padre.
    if not isinstance(archivo, StarletteUploadFile):
        archivo = None
    region = form.get("region")
    region = region if isinstance(region, str) and region else DEFAULT_REGION
    return archivo, region


@router.post("/upload")
async def analyze_image(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
):
    """Analiza una radiografía y muestra el resultado."""
    file, region = await _archivo_del_formulario(request)
    if file is None:
        return _upload_error(request, user, "No se recibió ningún archivo. Elegí una radiografía para analizar.")

    filename_lower = (file.filename or "").lower()
    is_dicom = filename_lower.endswith(".dcm") or file.content_type == "application/dicom"

    if file.content_type not in _ALLOWED_IMAGE_TYPES and not is_dicom:
        return _upload_error(request, user, "Tipo de archivo no permitido. Use JPEG, PNG, BMP, TIFF o DICOM (.dcm).")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        return _upload_error(request, user, f"La imagen excede el tamaño máximo de {MAX_UPLOAD_SIZE_MB} MB.")
    if not contents:
        return _upload_error(request, user, "El archivo está vacío.")

    # Validar la región ANTES de tocar la imagen.
    try:
        region_key, routing_method = route_image(region)
    except HTTPException as exc:
        return _upload_error(request, user, exc.detail, status_code=exc.status_code)

    # Decodificar. Un error acá es del archivo, no del modelo: antes los dos
    # casos se reportaban como "el modelo no está disponible".
    try:
        if is_dicom:
            from src.preprocessing.transforms import load_dicom
            image = load_dicom(contents)
        else:
            image = Image.open(BytesIO(contents))
            image.load()
    except UnidentifiedImageError:
        return _upload_error(request, user, "No se pudo leer la imagen: el archivo no es una imagen válida o está dañado.")
    except Exception as exc:
        return _upload_error(request, user, f"No se pudo procesar el archivo: {exc}")

    # Cargar el modelo. Un error acá sí es del modelo.
    try:
        from src.detection.predict import FractureDetector
        detector = FractureDetector.get(region_key)
    except (FileNotFoundError, ValueError) as exc:
        return _upload_error(
            request, user,
            f"El modelo de IA no está disponible: {exc}",
            status_code=503,
        )

    analysis_uid = uuid.uuid4().hex[:12]
    original_filename = f"{analysis_uid}_original.png"
    annotated_filename = f"{analysis_uid}_annotated.png"

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(str(UPLOADS_DIR / original_filename))

    # La inferencia es sincrónica y tarda cerca de un segundo en CPU (cuatro
    # la primera vez). Dentro de un handler `async def` eso corría EN el
    # bucle de eventos y la aplicación entera se congelaba mientras el
    # modelo pensaba: ni el historial de otra pestaña, ni /health, ni el
    # propio overlay de progreso (auditoría 2026-09-01, 04_web H7).
    #
    # Se envuelve SÓLO la inferencia en `run_in_threadpool` en vez de volver
    # el handler `def`: lo segundo obligaba a cambiar `await file.read()` y
    # `await request.form()` por sus versiones sincrónicas en los tres
    # handlers, y a perder el orden de dependencias que arriba garantiza que
    # la sesión se compruebe antes de leer el cuerpo. Esto toca una línea por
    # inferencia y deja todo lo demás igual. `FractureDetector.predict` lleva
    # un candado, así que dos estudios simultáneos se infieren de a uno.
    result = await run_in_threadpool(detector.predict, image)

    annotated_pil = Image.fromarray(cv2.cvtColor(result.annotated_image, cv2.COLOR_BGR2RGB))
    annotated_pil.save(str(UPLOADS_DIR / annotated_filename))

    report_text = detector.generate_report_text(result)
    urgency = calculate_urgency(result.max_detection_confidence)

    analysis = crud.create_analysis(
        db=db,
        user_id=user.id,
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
        {"x1": b.x1, "y1": b.y1, "x2": b.x2, "y2": b.y2, "confidence": b.confidence}
        for b in result.boxes
    ]
    if boxes_data:
        crud.create_detection_boxes(db, analysis.id, boxes_data)

    return RedirectResponse(url=f"/analysis/{analysis.id}/results", status_code=303)


# ─── Resultado guardado ──────────────────────────────────────────────────────

@router.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Historial del usuario logueado, y sólo de él."""
    analyses = crud.get_analyses_by_user(db, user_id=user.id, limit=HISTORIAL_MAX_FILAS)
    return templates.TemplateResponse(
        request, "history.html",
        {
            **_base_context(request, user),
            "analyses": analyses,
            # El total REAL de la cuenta, para que la pantalla no llame
            # "Todos" a una ventana recortada. Ver HISTORIAL_MAX_FILAS.
            "total_registros": crud.count_analyses_by_user(db, user_id=user.id),
            # Para marcar en la tabla los registros de modelos retirados.
            "default_region": DEFAULT_REGION,
            # Para marcar «modelo anterior» y filtrar por el vigente.
            "vigentes": {a.id for a in analyses if es_modelo_vigente(a.model_version)},
        },
    )


@router.get("/imagen/{archivo}")
async def serve_image(
    archivo: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Sirve una imagen sólo si pertenece a un análisis del usuario.

    Antes `app/uploads` estaba montado como StaticFiles, así que las
    radiografías de todos los pacientes eran descargables por URL sin ninguna
    verificación.
    """
    if not _SAFE_FILENAME_RE.match(archivo):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")

    from app.database.models import Analysis

    pertenece = (
        db.query(Analysis)
        .filter(
            Analysis.user_id == user.id,
            (Analysis.original_image_path == archivo)
            | (Analysis.annotated_image_path == archivo),
        )
        .first()
    )
    if pertenece is None:
        raise HTTPException(status_code=404, detail="Imagen no encontrada.")

    ruta = (UPLOADS_DIR / archivo).resolve()
    if not str(ruta).startswith(str(UPLOADS_DIR.resolve())) or not ruta.exists():
        raise HTTPException(status_code=404, detail="Imagen no encontrada.")

    return FileResponse(
        str(ruta),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/{analysis_id}/results", response_class=HTMLResponse)
async def view_analysis(
    analysis_id: int,
    request: Request,
    email_sent: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    analysis = crud.get_analysis_for_user(db, analysis_id, user.id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")

    email_message = None
    if email_sent == "1":
        email_message = "Informe enviado correctamente."
    elif email_sent == "0":
        email_message = "No se pudo enviar el email. Revisá la configuración SMTP en .env."
    elif email_sent == "limit":
        espera = segundos_hasta_liberar(f"email:{user.id}")
        email_message = (
            f"Alcanzaste el límite de {EMAIL_RATE_LIMIT_PER_HOUR} envíos por hora. "
            f"Volvé a intentar en {espera // 60 + 1} minuto(s)."
        )

    boxes = crud.get_boxes_by_analysis(db, analysis.id)
    significativas = [b for b in boxes if b.confidence >= ABNORMAL_THRESHOLD]
    bajas = [b for b in boxes if b.confidence < ABNORMAL_THRESHOLD]

    return templates.TemplateResponse(
        request, "results.html",
        {
            **_base_context(request, user),
            "analysis": analysis,
            "analysis_id": analysis.id,
            "annotated_image": analysis.annotated_image_path,
            "original_image": analysis.original_image_path,
            "report_text": _texto_del_informe(analysis),
            "informe_oculto": not es_modelo_vigente(analysis.model_version),
            "is_abnormal": analysis.is_abnormal,
            "inference_time": f"{analysis.inference_time_ms or 0:.0f}",
            "boxes": boxes,
            "significant_boxes": significativas,
            "low_confidence_boxes": bajas,
            # Las mismas cajas, para el cliente. Ver _boxes_json.
            "boxes_json": _boxes_json(boxes),
            "urgency": urgency_detail(
                analysis.max_detection_confidence or 0.0,
                bool(analysis.is_abnormal),
            ),
            "anatomical_region": MODEL_METADATA.get(
                analysis.anatomical_region, {}
            ).get("label", analysis.anatomical_region or "—"),
            # Clave cruda de la región, además de la etiqueta legible: la
            # plantilla la necesita para marcar los registros que quedaron
            # fuera del dominio validado (modelos retirados o sin región).
            "region_key": analysis.anatomical_region,
            "default_region": DEFAULT_REGION,
            "model_version": analysis.model_version,
            # Muñeca, pero con un modelo que ya no está en uso (v1, v2, ...):
            # sin prioridad de triage ni corte de aviso, y las métricas del
            # alcance se atribuyen al modelo vigente, no a este resultado.
            "modelo_anterior": _modelo_anterior(analysis.anatomical_region, analysis.model_version),
            "feedback": crud.get_feedback_by_analysis(db, analysis.id),
            "email_message": email_message,
            "email_enabled": bool(SMTP_EMAIL),
        },
    )


# ─── PDF ─────────────────────────────────────────────────────────────────────

# Color de las cajas de un análisis que NO es del modelo vigente, en el PDF:
# el violeta 200 de KIBBO (--kb-violet-200, el --ov del quemado de la placa en
# style.css). La anotada guardada las pinta en rojo/ámbar según el corte de su
# época, y ese corte no es el del sistema de hoy.
_CAJA_NEUTRA = "#CFC4F1"


def _anotada_neutra(original: Image.Image, cajas) -> Image.Image:
    """La placa original con las cajas guardadas, todas en el color neutro."""
    from PIL import ImageDraw

    lienzo = original.convert("RGB")
    trazo = max(2, round(max(lienzo.size) / 500))
    dibujo = ImageDraw.Draw(lienzo)
    for b in cajas:
        dibujo.rectangle([b.x1, b.y1, b.x2, b.y2], outline=_CAJA_NEUTRA, width=trazo)
    return lienzo


def _cargar_imagenes(analysis) -> tuple[Image.Image, Image.Image]:
    original = Image.open(str(UPLOADS_DIR / analysis.original_image_path))
    if not es_modelo_vigente(analysis.model_version):
        # Las cajas se siguen mostrando, pero sin el color «sobre el corte».
        return original, _anotada_neutra(original, analysis.detection_boxes)
    anotada = Image.open(str(UPLOADS_DIR / analysis.annotated_image_path))
    return original, anotada


@router.get("/{analysis_id}/pdf")
async def download_pdf(
    analysis_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    analysis = crud.get_analysis_for_user(db, analysis_id, user.id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")

    from src.reports.generator import generate_pdf_report

    original, anotada = _cargar_imagenes(analysis)
    pdf_bytes = generate_pdf_report(
        original_image=original,
        annotated_image=anotada,
        report_text=_texto_del_informe(analysis),
        analysis_id=str(analysis.id),
        doctor_name=user.name,
        # La región del ANÁLISIS, no la del modelo vivo: un informe generado
        # con un modelo retirado no puede exhibir las métricas del actual.
        region=analysis.anatomical_region,
        created_at=analysis.created_at,
        # Y su modelo: uno de muñeca hecho con un modelo anterior lo declara.
        model_version=analysis.model_version,
    )

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=traumavision_informe_{analysis.id}.pdf"},
    )


@router.post("/{analysis_id}/email")
async def send_email_report(
    request: Request,
    analysis_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
):
    analysis = crud.get_analysis_for_user(db, analysis_id, user.id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")

    form_data = await request.form()
    to_email = (form_data.get("to_email") or "").strip()
    if not _EMAIL_RE.match(to_email):
        return RedirectResponse(url=f"/analysis/{analysis_id}/results?email_sent=0", status_code=303)

    # Tope por usuario: el endpoint saca imágenes de paciente del sistema.
    permitido, _ = check_and_consume(f"email:{user.id}", EMAIL_RATE_LIMIT_PER_HOUR)
    if not permitido:
        return RedirectResponse(url=f"/analysis/{analysis_id}/results?email_sent=limit", status_code=303)

    from app.services.email_service import send_report_email
    from src.reports.generator import generate_pdf_report

    original, anotada = _cargar_imagenes(analysis)
    pdf_bytes = generate_pdf_report(
        original_image=original,
        annotated_image=anotada,
        report_text=_texto_del_informe(analysis),
        analysis_id=str(analysis.id),
        doctor_name=user.name,
        # La región del ANÁLISIS, no la del modelo vivo: un informe generado
        # con un modelo retirado no puede exhibir las métricas del actual.
        region=analysis.anatomical_region,
        created_at=analysis.created_at,
        # Y su modelo: uno de muñeca hecho con un modelo anterior lo declara.
        model_version=analysis.model_version,
    )

    # SMTP es un socket bloqueante (con timeout, pero de 20 s): fuera del
    # bucle por el mismo motivo que la inferencia. `analysis_id` y `usuario`
    # van al registro de auditoría del servicio, no al correo.
    enviado = await run_in_threadpool(
        send_report_email,
        to_email=to_email,
        subject=f"[TraumaVision AI] Informe de análisis #{analysis.id}",
        body_text=(
            f"Adjunto el informe del análisis #{analysis.id} generado por TraumaVision AI.\n"
            f"Solicitado por: {user.name}\n\n"
            f"{_texto_del_informe(analysis)}\n\n"
            "AVISO: informe generado por un sistema de asistencia. Debe ser "
            "interpretado exclusivamente por un profesional médico matriculado."
        ),
        pdf_bytes=pdf_bytes,
        pdf_filename=f"traumavision_informe_{analysis.id}.pdf",
        analysis_id=analysis.id,
        usuario=user.email,
    )

    return RedirectResponse(
        url=f"/analysis/{analysis_id}/results?email_sent={'1' if enviado else '0'}",
        status_code=303,
    )


# ─── Estudios multi-imagen ───────────────────────────────────────────────────

@router.post("/upload-study")
async def analyze_study(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
):
    """Analiza un ZIP con varios DICOM y devuelve el resumen del estudio."""
    # Sesión antes que cuerpo: ver _archivo_del_formulario.
    file, region = await _archivo_del_formulario(request)
    if file is None:
        return _upload_error(request, user, "No se recibió ningún archivo. Subí un ZIP con los DICOM del estudio.")

    filename_lower = (file.filename or "").lower()
    is_zip = filename_lower.endswith(".zip") or file.content_type in (
        "application/zip", "application/x-zip-compressed",
    )
    if not is_zip:
        return _upload_error(request, user, "Para estudios multi-imagen, subí un archivo ZIP con los DICOM.")

    contents = await file.read()
    if len(contents) > MAX_ZIP_SIZE_MB * 1024 * 1024:
        return _upload_error(request, user, f"El archivo ZIP excede el límite de {MAX_ZIP_SIZE_MB} MB.")

    # La región también aplica al estudio. Antes se ignoraba y siempre se usaba
    # el modelo por defecto, sin importar lo que eligiera el médico.
    try:
        region_key, routing_method = route_image(region)
    except HTTPException as exc:
        return _upload_error(request, user, exc.detail, status_code=exc.status_code)

    try:
        from src.preprocessing.transforms import extract_dicoms_from_zip
        dicom_entries = extract_dicoms_from_zip(contents)
    except ValueError as exc:
        return _upload_error(request, user, str(exc))
    except Exception as exc:
        return _upload_error(request, user, f"No se pudo leer el ZIP: {exc}")

    try:
        from src.detection.predict import FractureDetector
        detector = FractureDetector.get(region_key)
    except (FileNotFoundError, ValueError) as exc:
        return _upload_error(request, user, f"El modelo de IA no está disponible: {exc}", status_code=503)

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    study_token = uuid.uuid4().hex[:8]

    study = crud.create_study(
        db=db,
        user_id=user.id,
        original_filename=file.filename or "estudio.zip",
        total_images=len(dicom_entries),
        images_with_findings=0,
        anatomical_region=region_key,
        model_version=detector.model_version,
    )

    con_hallazgos = 0

    for idx, entry in enumerate(dicom_entries):
        # Hasta MAX_ZIP_ENTRIES inferencias en un request: cada una fuera del
        # bucle, o la app quedaba muerta minutos enteros. Ver analyze_image.
        result = await run_in_threadpool(detector.predict, entry.image)

        token = f"{study_token}{idx:04d}"
        orig_name = f"{token}_original.png"
        annot_name = f"{token}_annotated.png"

        entry.image.convert("RGB").save(str(UPLOADS_DIR / orig_name))
        Image.fromarray(cv2.cvtColor(result.annotated_image, cv2.COLOR_BGR2RGB)).save(
            str(UPLOADS_DIR / annot_name)
        )

        urgency = calculate_urgency(result.max_detection_confidence)
        if result.is_abnormal:
            con_hallazgos += 1

        # Se guardan región, modelo, routing y urgencia también para el estudio:
        # antes esta rama perdía toda la trazabilidad del modelo usado.
        analysis = crud.create_analysis(
            db=db,
            user_id=user.id,
            study_id=study.id,
            original_image_path=orig_name,
            annotated_image_path=annot_name,
            report_text=(
                f"Imagen {idx + 1} — {entry.filename} — "
                f"{'Hallazgos detectados' if result.is_abnormal else 'Sin hallazgos sobre el umbral'}"
            ),
            max_detection_confidence=result.max_detection_confidence,
            is_abnormal=result.is_abnormal,
            inference_time_ms=result.inference_time_ms,
            anatomical_region=region_key,
            model_version=result.model_version,
            routing_method=routing_method,
            urgency=urgency,
        )
        if result.boxes:
            crud.create_detection_boxes(
                db, analysis.id,
                [{"x1": b.x1, "y1": b.y1, "x2": b.x2, "y2": b.y2, "confidence": b.confidence}
                 for b in result.boxes],
            )

        # Acá se armaba una segunda copia de cada fila para renderizarla en el
        # POST. Con el PRG la pantalla la arma `view_study` desde la base, así
        # que esa copia era trabajo por cada imagen del ZIP para tirarlo.

    study.images_with_findings = con_hallazgos
    db.commit()

    # POST-Redirect-GET. Antes esta rama renderizaba la plantilla sobre el
    # propio POST, así que la barra del navegador quedaba apuntando a
    # /analysis/upload-study con el cuerpo pegado: F5 o el botón atrás
    # reenviaban el formulario y el ZIP se procesaba de nuevo entero. El
    # médico terminaba con dos estudios idénticos y ninguna forma de saber
    # cuál era el bueno.
    #
    # `view_study` ya sabe rearmar exactamente esta pantalla desde la base
    # —es la que se usa al abrir un estudio desde el historial—, así que el
    # alta no necesita renderizar nada: sólo mandar ahí.
    return RedirectResponse(url=f"/analysis/study/{study.id}", status_code=303)


@router.get("/study/{study_id}", response_class=HTMLResponse)
async def view_study(
    study_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    study = crud.get_study_for_user(db, study_id, user.id)
    if not study:
        raise HTTPException(status_code=404, detail="Estudio no encontrado.")

    analyses = crud.get_analyses_by_study(db, study_id)

    def _fila(i, a):
        cajas = sorted(a.detection_boxes, key=lambda b: b.confidence, reverse=True)
        return {
            "index": i + 1,
            "analysis_id": a.id,
            "source_filename": a.original_image_path,
            "original_image": a.original_image_path,
            "annotated_image": a.annotated_image_path,
            "max_detection_confidence": a.max_detection_confidence or 0.0,
            "is_abnormal": a.is_abnormal,
            "significant_count": a.findings_above_abnormal,
            "low_confidence_count": len(a.detection_boxes) - a.findings_above_abnormal,
            "inference_time_ms": a.inference_time_ms or 0.0,
            "urgency": urgency_detail(a.max_detection_confidence or 0.0, bool(a.is_abnormal)),
            # Las cajas ya persistidas de cada imagen. Ver _boxes_json.
            "boxes": cajas,
            "boxes_json": _boxes_json(cajas),
        }

    resultados = [_fila(i, a) for i, a in enumerate(analyses)]

    # Fuera del dominio validado la plantilla neutraliza TODOS los veredictos
    # (la urgencia la calculó un modelo retirado y no ordena nada), así que no
    # hay ninguna imagen que priorizar: se abre en la primera.
    fuera_de_dominio = (
        study.anatomical_region != DEFAULT_REGION
        or _modelo_anterior(study.anatomical_region, study.model_version)
    )
    inicial = (
        resultados[0]["index"] if (fuera_de_dominio and resultados)
        else imagen_mas_urgente(resultados)
    )
    imagen_inicial = next((r for r in resultados if r["index"] == inicial), None)

    return templates.TemplateResponse(
        request, "study_results.html",
        {
            **_base_context(request, user),
            "study_id": study.id,
            # En qué imagen abre el visor y cuál es el veredicto del ESTUDIO
            # (el de su imagen más urgente). Los dos son decisiones clínicas:
            # se calculan en el servidor, no en la plantilla.
            "initial_index": inicial,
            "urgencia_estudio": imagen_inicial["urgency"] if imagen_inicial else None,
            "original_zip": study.original_filename,
            "total_images": study.total_images,
            "images_with_findings": study.images_with_findings,
            "anatomical_region": MODEL_METADATA.get(
                study.anatomical_region, {}
            ).get("label", study.anatomical_region or "—"),
            "region_key": study.anatomical_region,
            "default_region": DEFAULT_REGION,
            "model_version": study.model_version,
            "modelo_anterior": _modelo_anterior(study.anatomical_region, study.model_version),
            "results": resultados,
        },
    )

