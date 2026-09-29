"""
transforms.py — Preprocesamiento de imágenes radiográficas.

Contiene la conversión de DICOM a imagen lista para el modelo y la extracción
de estudios comprimidos.

El CLAHE que usa la inferencia vive en `src/detection/predict.py`
(`apply_clahe_rgb`), junto al detector, para que no pueda quedar desincronizado
del preprocesamiento con el que se entrenó.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
import pydicom
from PIL import Image
try:  # pydicom >= 3
    from pydicom.pixels import apply_modality_lut, apply_voi_lut
except ImportError:  # pydicom 2.x
    from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut

from config.settings import (
    MAX_ZIP_ENTRIES,
    MAX_ZIP_UNCOMPRESSED_MB,
)

# ──────────────────────────────────────────────────────────────────────────────
# Utilidades genéricas
# ──────────────────────────────────────────────────────────────────────────────


def resize_image(image: np.ndarray, size: int = 640) -> np.ndarray:
    """Redimensiona manteniendo la proporción y rellena hasta un cuadrado."""
    h, w = image.shape[:2]
    scale = size / max(h, w)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    y_off = (size - new_h) // 2
    x_off = (size - new_w) // 2
    canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
    return canvas


def apply_clahe(image: np.ndarray, clip_limit: float = 2.0, tile_size: int = 8) -> np.ndarray:
    """CLAHE sobre un array de OpenCV. Se conserva para los scripts de dataset.

    La inferencia usa `src.detection.predict.apply_clahe_rgb`, que trabaja
    sobre PIL y replica exactamente la cadena del pipeline de entrenamiento.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_size, tile_size))
    enhanced = clahe.apply(gray)
    if image.ndim == 3:
        enhanced = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
    return enhanced


def pil_to_cv2(pil_image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2BGR)


def cv2_to_pil(cv2_image: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB))


def sanitize_filename(nombre: str) -> str:
    """Deja sólo el nombre base, sin ruta y sin datos identificatorios obvios.

    Los archivos dentro de un estudio DICOM real suelen traer el ID de paciente
    o de estudio en el nombre. Ese nombre se llegaba a guardar en el reporte y
    a mostrar en pantalla, lo que anulaba la desidentificación que sí hace
    `load_dicom` al descartar los metadatos.
    """
    base = nombre.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"\.(dcm|dicom)$", "", base, flags=re.IGNORECASE)
    # Cualquier secuencia de 4 o más dígitos se enmascara: fechas de nacimiento,
    # números de documento, IDs de historia clínica.
    base = re.sub(r"\d{4,}", "…", base)
    base = re.sub(r"[^\w\s.\-…]", "", base, flags=re.UNICODE).strip()
    return base[:60] or "imagen"


# ──────────────────────────────────────────────────────────────────────────────
# DICOM
# ──────────────────────────────────────────────────────────────────────────────


def load_dicom(dicom_bytes: bytes) -> Image.Image:
    """Convierte un DICOM en una imagen PIL de 8 bits lista para el modelo.

    Aplica la cadena de transformación que define el estándar, en orden:

      1. **Modality LUT** (RescaleSlope / RescaleIntercept): lleva los valores
         crudos del detector a la escala física del equipo.
      2. **VOI LUT** (WindowCenter / WindowWidth): aplica la ventana de
         visualización que el equipo grabó en el estudio. Es lo que hace el
         visor del radiólogo; sin esto, un DICOM de 12–16 bits normalizado por
         mínimo y máximo puede quedar con un contraste muy distinto del que
         tuvo la imagen con la que se entrenó.
      3. **MONOCHROME1**: en esa interpretación fotométrica el blanco es el
         valor MÍNIMO, o sea la imagen viene invertida respecto de MONOCHROME2.
         Sin invertirla, el modelo recibe un negativo de la radiografía.

    Si el estudio no trae ventana, cae a un estirado por mínimo y máximo, que
    es el comportamiento anterior.

    Los metadatos del paciente no se leen ni se almacenan.
    """
    ds = pydicom.dcmread(io.BytesIO(dicom_bytes))
    arr = ds.pixel_array

    # 1. Modality LUT
    try:
        arr = apply_modality_lut(arr, ds)
    except Exception:
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
        arr = arr.astype(np.float32) * slope + intercept

    # 2. VOI LUT / ventana
    tiene_ventana = hasattr(ds, "WindowCenter") or hasattr(ds, "VOILUTSequence")
    if tiene_ventana:
        try:
            arr = apply_voi_lut(arr, ds)
        except Exception:
            pass  # se resuelve con el estirado de abajo

    arr = np.asarray(arr, dtype=np.float32)

    # Un estudio multiframe llega como (n, alto, ancho): se toma el primer corte.
    if arr.ndim == 3 and arr.shape[0] > 1 and arr.shape[-1] not in (1, 3):
        arr = arr[0]

    # 3. Normalizar a 0–255
    lo, hi = float(np.nanmin(arr)), float(np.nanmax(arr))
    arr = (arr - lo) / (hi - lo) * 255.0 if hi > lo else np.zeros_like(arr)

    # 4. MONOCHROME1 viene invertida
    if str(getattr(ds, "PhotometricInterpretation", "")).strip().upper() == "MONOCHROME1":
        arr = 255.0 - arr

    arr = arr.astype(np.uint8)

    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
    elif arr.ndim == 3 and arr.shape[2] == 1:
        arr = cv2.cvtColor(arr[:, :, 0], cv2.COLOR_GRAY2RGB)

    return Image.fromarray(arr)


@dataclass
class DicomEntry:
    """Un DICOM extraído de un ZIP."""

    filename: str                          # nombre ya sanitizado, sin ruta ni IDs
    image: Image.Image
    instance_number: Optional[int] = None


def extract_dicoms_from_zip(zip_bytes: bytes) -> list[DicomEntry]:
    """Extrae y convierte los DICOM de un ZIP, en memoria.

    Protecciones contra ZIP malicioso:
      - tope de entradas (MAX_ZIP_ENTRIES)
      - tope del total descomprimido (MAX_ZIP_UNCOMPRESSED_MB), calculado desde
        la cabecera ANTES de descomprimir nada
      - se ignora cualquier entrada con ruta absoluta o con '..' (zip slip)

    Devuelve la lista ordenada por InstanceNumber si está disponible, o por
    nombre. Levanta ValueError si no hay ningún DICOM válido.
    """
    entries: list[DicomEntry] = []
    errores: list[str] = []
    tope_bytes = MAX_ZIP_UNCOMPRESSED_MB * 1024 * 1024

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        infos = [
            i for i in zf.infolist()
            if not i.is_dir()
            and not i.filename.startswith("__MACOSX")
            and not i.filename.rsplit("/", 1)[-1].startswith(".")
            and not i.filename.startswith(("/", "\\"))
            and ".." not in i.filename.replace("\\", "/").split("/")
        ]

        if len(infos) > MAX_ZIP_ENTRIES:
            raise ValueError(
                f"El ZIP contiene {len(infos)} archivos y el máximo admitido es "
                f"{MAX_ZIP_ENTRIES}."
            )

        total_declarado = sum(i.file_size for i in infos)
        if total_declarado > tope_bytes:
            raise ValueError(
                f"El contenido descomprimido ({total_declarado / 1024 / 1024:.0f} MB) "
                f"supera el máximo de {MAX_ZIP_UNCOMPRESSED_MB} MB."
            )

        leidos = 0
        for info in infos:
            nombre = info.filename
            ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre.rsplit("/", 1)[-1] else ""
            # Muchos DICOM clínicos no tienen extensión.
            if ext not in ("dcm", "dicom", ""):
                continue

            datos = zf.read(nombre)
            leidos += len(datos)
            if leidos > tope_bytes:
                raise ValueError(
                    f"El ZIP excede el máximo descomprimido de {MAX_ZIP_UNCOMPRESSED_MB} MB."
                )

            try:
                instance_number = None
                cabecera = pydicom.dcmread(io.BytesIO(datos), stop_before_pixels=True)
                if hasattr(cabecera, "InstanceNumber"):
                    try:
                        instance_number = int(cabecera.InstanceNumber)
                    except (ValueError, TypeError):
                        pass

                entries.append(
                    DicomEntry(
                        filename=sanitize_filename(nombre),
                        image=load_dicom(datos),
                        instance_number=instance_number,
                    )
                )
            except Exception as exc:
                errores.append(f"{sanitize_filename(nombre)}: {exc}")
                continue

    if not entries:
        detalle = "; ".join(errores[:5]) if errores else "El ZIP no contiene archivos DICOM válidos."
        raise ValueError(f"No se encontraron imágenes DICOM en el archivo: {detalle}")

    entries.sort(key=lambda e: (e.instance_number is None, e.instance_number or 0, e.filename))
    return entries
