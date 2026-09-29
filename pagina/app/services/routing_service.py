"""
routing_service.py — Selección del modelo y urgencia clínica.

La región la elige el médico en el formulario; no hay clasificador automático.
Este módulo valida que la región exista, que su modelo esté marcado como
disponible y que el checkpoint esté en disco, y traduce el resultado de la
inferencia a un nivel de urgencia interpretable.
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
    """Valida la región y devuelve (region_key, 'manual').

    Raises:
        HTTPException 400: la región no existe en la configuración.
        HTTPException 503: el modelo no está disponible o falta su checkpoint.
    """
    region = (manual_region or DEFAULT_REGION).strip()

    if region not in YOLO_MODELS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Región '{region}' no reconocida. "
                f"Opciones válidas: {', '.join(YOLO_MODELS)}"
            ),
        )

    if not REGION_AVAILABLE.get(region, False):
        disponibles = ", ".join(r for r, ok in REGION_AVAILABLE.items() if ok) or "ninguna"
        raise HTTPException(
            status_code=503,
            detail=(
                f"El modelo para '{region}' no está disponible. "
                f"Regiones activas: {disponibles}"
            ),
        )

    weights_path = Path(YOLO_MODELS[region])
    if not weights_path.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                f"Falta el archivo de pesos de '{region}': {weights_path.name}. "
                "Verificá que el checkpoint esté en disco y que la ruta de .env sea correcta."
            ),
        )

    return region, "manual"


def calculate_urgency(max_detection_confidence: float) -> str:
    """Nivel de urgencia: 'HIGH', 'MEDIUM' o 'LOW'.

    Los dos cortes son sobre el score crudo del detector y son OPERATIVOS: el
    score post-NMS no es una probabilidad de fractura, así que un estudio
    marcado como prioritario no tiene "90 % de probabilidad" de nada. Sólo
    dice que el detector lo ubicó por encima de URGENCY_HIGH_THRESHOLD.
    """
    if max_detection_confidence >= URGENCY_HIGH_THRESHOLD:
        return "HIGH"
    if max_detection_confidence >= URGENCY_MED_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def urgency_detail(max_detection_confidence: float, is_abnormal: bool) -> dict:
    """Descripción para la UI, distinguiendo el negativo limpio del casi-positivo.

    Antes, un estudio con confianza 0,00 y otro con 0,24 mostraban exactamente
    el mismo badge verde. El segundo es un caso límite y el médico debería
    poder distinguirlo de un negativo sin ningún hallazgo.
    """
    nivel = calculate_urgency(max_detection_confidence)

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
            "detalle": (
                f"Hallazgo por encima del umbral de anormalidad "
                f"({ABNORMAL_THRESHOLD:.0%})."
            ),
        }

    # LOW: se separa el negativo sin hallazgos del caso límite.
    if not is_abnormal and max_detection_confidence >= CONFIDENCE_THRESHOLD:
        return {
            "nivel": "LOW_BORDERLINE",
            "titulo": "LÍMITE — Sin hallazgo confirmado, con región señalada",
            "icono": "🟠",
            "clase": "urgency-borderline",
            "detalle": (
                f"La confianza máxima ({max_detection_confidence:.0%}) quedó por debajo "
                f"del umbral de anormalidad ({ABNORMAL_THRESHOLD:.0%}) pero no es "
                "despreciable. Correlacionar con la clínica."
            ),
        }

    if max_detection_confidence > 0:
        return {
            "nivel": "LOW",
            "titulo": "SIN HALLAZGOS — Considerar contexto clínico",
            "icono": "🟢",
            "clase": "urgency-low",
            "detalle": (
                f"Confianza máxima {max_detection_confidence:.0%}, por debajo del "
                "umbral. No descarta patología."
            ),
        }

    return {
        "nivel": "LOW",
        "titulo": "SIN HALLAZGOS — Considerar contexto clínico",
        "icono": "🟢",
        "clase": "urgency-low",
        "detalle": "El detector no marcó ninguna región. No descarta patología.",
    }


# Los cuatro niveles que devuelve `urgency_detail`, ordenados por gravedad.
# Un nivel que no esté acá cae al piso: si mañana aparece uno nuevo sin
# ubicar, tiene que quedar abajo de un HIGH, no colarse arriba por accidente.
_ESCALERA_DE_URGENCIA = {"HIGH": 3, "MEDIUM": 2, "LOW_BORDERLINE": 1, "LOW": 0}


def imagen_mas_urgente(resultados: list[dict]) -> Optional[int]:
    """El `index` de la imagen en la que el visor tiene que abrir un estudio.

    El visor abría siempre en la primera imagen del ZIP. En el estudio #1 la
    fractura está en la TERCERA: al abrirlo, el panel anunciaba en 48 px el
    veredicto de la primera —SIN HALLAZGOS— y el recuento real del estudio
    quedaba en texto chico. La primera lectura del médico era la equivocada, y
    la primera lectura es la que ordena el triage.

    El orden es el de la escalera clínica que ya calcula `urgency_detail`.
    Los dos desempates son explícitos y en ese orden:

      1. a igual nivel, el score crudo más alto;
      2. a igual score, el índice más bajo.

    El segundo no es cosmética: sin él, dos aperturas del mismo estudio
    podrían abrir en imágenes distintas según cómo quedara ordenada la lista.
    Un visor clínico tiene que abrir siempre en el mismo lugar.
    """
    if not resultados:
        return None

    def clave(r: dict) -> tuple:
        nivel = (r.get("urgency") or {}).get("nivel") or "LOW"
        return (
            _ESCALERA_DE_URGENCIA.get(nivel, 0),
            r.get("max_detection_confidence") or 0.0,
            -(r.get("index") or 0),
        )

    return max(resultados, key=clave)["index"]
