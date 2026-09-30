"""
routing_service.py — Elección del modelo y nivel de urgencia.

Valida la región que eligió el médico y traduce el score del detector a un
nivel de triage. Los cortes son operativos: el score NO es una probabilidad.
"""

from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from config.settings import (
    ABNORMAL_THRESHOLD,
    CONFIDENCE_THRESHOLD,
    DEFAULT_REGION,
    REGION_AVAILABLE,
    URGENCY_HIGH_THRESHOLD,
    URGENCY_MED_THRESHOLD,
    YOLO_MODELS,
)


def route_image(manual_region: str | None) -> tuple[str, str]:
    """Devuelve (region, 'manual'). 400 si la región no existe, 503 si su modelo no está."""
    region = (manual_region or DEFAULT_REGION).strip()

    if region not in YOLO_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Región '{region}' no reconocida. Opciones válidas: {', '.join(YOLO_MODELS)}",
        )

    if not REGION_AVAILABLE.get(region, False):
        disponibles = ", ".join(r for r, ok in REGION_AVAILABLE.items() if ok) or "ninguna"
        raise HTTPException(
            status_code=503,
            detail=f"El modelo para '{region}' no está disponible. Regiones activas: {disponibles}",
        )

    pesos = Path(YOLO_MODELS[region])
    if not pesos.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                f"Falta el archivo de pesos de '{region}': {pesos.name}. "
                "Verificá que el checkpoint esté en disco y que la ruta de .env sea correcta."
            ),
        )

    return region, "manual"


def calculate_urgency(max_detection_confidence: float) -> str:
    """'HIGH', 'MEDIUM' o 'LOW' según el score máximo del detector."""
    if max_detection_confidence >= URGENCY_HIGH_THRESHOLD:
        return "HIGH"
    if max_detection_confidence >= URGENCY_MED_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def urgency_detail(max_detection_confidence: float, is_abnormal: bool) -> dict:
    """Texto e ícono del nivel de urgencia. Separa el caso límite del negativo limpio."""
    conf = max_detection_confidence
    nivel = calculate_urgency(conf)

    if nivel == "HIGH":
        return {
            "nivel": "HIGH",
            "titulo": "PRIORITARIO — Revisión radiológica inmediata",
            "icono": "🔴",
            "clase": "urgency-high",
            "detalle": "Hallazgo de alta confianza del detector.",
        }

    if nivel == "MEDIUM":
        return {
            "nivel": "MEDIUM",
            "titulo": "REVISAR — Confirmar con lectura médica",
            "icono": "🟡",
            "clase": "urgency-medium",
            "detalle": f"Hallazgo por encima del umbral de anormalidad ({ABNORMAL_THRESHOLD:.0%}).",
        }

    # Bajo el umbral, pero con una caja dibujada: caso límite.
    if not is_abnormal and conf >= CONFIDENCE_THRESHOLD:
        return {
            "nivel": "LOW_BORDERLINE",
            "titulo": "LÍMITE — Sin hallazgo confirmado, con región señalada",
            "icono": "🟠",
            "clase": "urgency-borderline",
            "detalle": (
                f"La confianza máxima ({conf:.0%}) quedó por debajo "
                f"del umbral de anormalidad ({ABNORMAL_THRESHOLD:.0%}) pero no es "
                "despreciable. Correlacionar con la clínica."
            ),
        }

    if conf > 0:
        detalle = f"Confianza máxima {conf:.0%}, por debajo del umbral. No descarta patología."
    else:
        detalle = "El detector no marcó ninguna región. No descarta patología."
    return {
        "nivel": "LOW",
        "titulo": "SIN HALLAZGOS — Considerar contexto clínico",
        "icono": "🟢",
        "clase": "urgency-low",
        "detalle": detalle,
    }


# Orden de gravedad de los niveles de `urgency_detail`. Uno desconocido cuenta como el más bajo.
_GRAVEDAD = {"HIGH": 3, "MEDIUM": 2, "LOW_BORDERLINE": 1, "LOW": 0}


def imagen_mas_urgente(resultados: list[dict]) -> Optional[int]:
    """El `index` de la imagen más urgente de un estudio (en la que abre el visor).

    Desempata por score más alto y después por índice más bajo, para que
    el mismo estudio abra siempre en la misma imagen.
    """
    if not resultados:
        return None

    def clave(r: dict) -> tuple:
        nivel = (r.get("urgency") or {}).get("nivel") or "LOW"
        return (
            _GRAVEDAD.get(nivel, 0),
            r.get("max_detection_confidence") or 0.0,
            -(r.get("index") or 0),
        )

    return max(resultados, key=clave)["index"]
