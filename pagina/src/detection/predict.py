"""
predict.py — Inferencia con YOLOv8 para detección de fracturas.

Modelo en producción: YOLOv8m entrenado sobre GRAZPEDWRI-DX (muñeca pediátrica).
Las métricas medidas sobre el split de test (mAP50, mAP50-95, precisión,
recall, n y fecha de medición) viven en `config.settings.MODEL_METADATA`, que
es la única fuente que leen la pantalla y el PDF. No se copian acá: al
reentrenar, un número escrito en esta cabecera queda viejo sin que nadie lo note.

Preprocesamiento: se aplica el MISMO CLAHE que se aplicó al construir el
dataset de entrenamiento (ver config.settings.APPLY_CLAHE_AT_INFERENCE). Sin
eso, el modelo vería en producción una distribución distinta de la que aprendió.
"""

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from PIL import Image

from config.settings import (
    ABNORMAL_THRESHOLD,
    APPLY_CLAHE_AT_INFERENCE,
    CLAHE_CLIP_LIMIT,
    CLAHE_TILE_SIZE,
    CONFIDENCE_THRESHOLD,
    DEFAULT_REGION,
    MODEL_METADATA,
    YOLO_MODELS,
    YOLO_WEIGHTS_PATH,
)


@dataclass
class DetectionBox:
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float


@dataclass
class PredictionResult:
    """Resultado de una inferencia.

    `max_detection_confidence` es el máximo de las confianzas post-NMS de YOLO.
    NO es una probabilidad de fractura — es el score interno del
    detector. Se usa para decidir `is_abnormal` y el nivel de urgencia.
    """

    is_abnormal: bool
    max_detection_confidence: float
    boxes: List[DetectionBox]              # todas las cajas desde CONFIDENCE_THRESHOLD
    annotated_image: np.ndarray
    inference_time_ms: float
    image_size: tuple
    model_version: str = ""
    clahe_applied: bool = False

    @property
    def significant_boxes(self) -> List[DetectionBox]:
        """Cajas que superan el umbral de anormalidad."""
        return [b for b in self.boxes if b.confidence >= ABNORMAL_THRESHOLD]

    @property
    def low_confidence_boxes(self) -> List[DetectionBox]:
        """Cajas de referencia: se dibujan, pero no clasifican el estudio."""
        return [b for b in self.boxes if b.confidence < ABNORMAL_THRESHOLD]


def apply_clahe_rgb(pil_image: Image.Image) -> Image.Image:
    """Aplica CLAHE igual que el pipeline de entrenamiento.

    `build_grazpedwri_pipeline.py` convertía cada placa a escala de grises,
    le aplicaba CLAHE(clipLimit=2.0, tileGridSize=(8,8)) y la guardaba. YOLO
    después replica ese único canal a tres. Se reproduce esa cadena exacta.
    """
    gray = np.array(pil_image.convert("L"))
    clahe = cv2.createCLAHE(
        clipLimit=CLAHE_CLIP_LIMIT,
        tileGridSize=(CLAHE_TILE_SIZE, CLAHE_TILE_SIZE),
    )
    enhanced = clahe.apply(gray)
    return Image.fromarray(cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB))


class FractureDetector:
    """Detector con caché por región.

    `FractureDetector.get('muneca_pediatrica')` carga el modelo la primera vez
    y lo reutiliza en las siguientes.
    """

    _cache: dict = {}

    @classmethod
    def get(cls, region: Optional[str] = None) -> "FractureDetector":
        region = region or DEFAULT_REGION
        if region not in YOLO_MODELS:
            raise ValueError(
                f"Región '{region}' no configurada. "
                f"Disponibles: {', '.join(YOLO_MODELS)}"
            )
        if region not in cls._cache:
            cls._cache[region] = cls(weights_path=YOLO_MODELS[region], region=region)
        return cls._cache[region]

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()

    def __init__(self, weights_path: Optional[str] = None, region: Optional[str] = None):
        from ultralytics import YOLO

        path = Path(weights_path) if weights_path else Path(YOLO_WEIGHTS_PATH)
        if not path.exists():
            raise FileNotFoundError(
                f"Modelo no encontrado: {path}\n"
                "Verificá YOLO_MODEL_MUNECA en .env o que el checkpoint esté en disco."
            )

        self.model = YOLO(str(path))
        self.confidence_threshold = CONFIDENCE_THRESHOLD
        self.abnormal_threshold = ABNORMAL_THRESHOLD
        self.region = region or DEFAULT_REGION
        # Nombre de la corrida (modelo/<corrida>/weights/best.pt)
        self.model_version = path.parent.parent.name
        # Las rutas corren `predict` en el threadpool para no congelar el
        # bucle de eventos (auditoría 2026-09-01, 04_web H7). Eso significa
        # que dos estudios pueden llegar a la vez, y el predictor de
        # Ultralytics guarda estado entre llamadas: no está pensado para dos
        # hilos sobre el mismo objeto. El candado serializa las inferencias
        # —una a la vez, como antes— pero sin bloquear al resto de la app.
        self._candado = threading.Lock()
        print(
            f"[TraumaVision] Modelo cargado: {path.name} "
            f"({self.region} · {self.model_version} · "
            f"CLAHE={'sí' if APPLY_CLAHE_AT_INFERENCE else 'no'})"
        )

    def predict(self, image) -> PredictionResult:
        start = time.time()

        # Aceptar ruta, PIL Image o numpy array
        if isinstance(image, (str, Path)):
            pil_image = Image.open(str(image)).convert("RGB")
        elif isinstance(image, np.ndarray):
            pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        else:
            pil_image = image.convert("RGB")

        w, h = pil_image.size

        # La imagen que se muestra al médico es la ORIGINAL; el CLAHE se usa
        # sólo para alimentar al modelo. Mostrar la placa alterada sería
        # cambiarle la evidencia sobre la que decide.
        display_image = pil_image
        model_input = apply_clahe_rgb(pil_image) if APPLY_CLAHE_AT_INFERENCE else pil_image

        with self._candado:
            results = self.model.predict(
                source=model_input,
                conf=self.confidence_threshold,
                imgsz=640,
                verbose=False,
            )

        boxes: List[DetectionBox] = []
        max_conf = 0.0
        for box in results[0].boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf)
            boxes.append(DetectionBox(x1, y1, x2, y2, conf))
            max_conf = max(max_conf, conf)

        boxes.sort(key=lambda b: b.confidence, reverse=True)

        # El estudio se clasifica como anormal sólo si alguna detección supera
        # ABNORMAL_THRESHOLD. Las cajas entre CONFIDENCE_THRESHOLD y ese valor
        # se siguen dibujando como referencia, pero no lo vuelven anormal.
        is_abnormal = max_conf >= self.abnormal_threshold

        img_bgr = cv2.cvtColor(np.array(display_image), cv2.COLOR_RGB2BGR)
        annotated = self._draw_boxes(img_bgr, boxes)

        return PredictionResult(
            is_abnormal=is_abnormal,
            max_detection_confidence=max_conf,
            boxes=boxes,
            annotated_image=annotated,
            inference_time_ms=(time.time() - start) * 1000,
            image_size=(w, h),
            model_version=self.model_version,
            clahe_applied=APPLY_CLAHE_AT_INFERENCE,
        )

    def _draw_boxes(self, img: np.ndarray, boxes: List[DetectionBox]) -> np.ndarray:
        """Dibuja las cajas distinguiendo hallazgo de referencia.

        Rojo sólido = supera el umbral de anormalidad.
        Ámbar punteado = hallazgo de baja confianza, sólo para correlacionar.
        """
        out = img.copy()
        for b in boxes:
            significativa = b.confidence >= self.abnormal_threshold
            color = (0, 0, 220) if significativa else (0, 170, 240)  # BGR
            grosor = 2 if significativa else 1

            if significativa:
                cv2.rectangle(out, (b.x1, b.y1), (b.x2, b.y2), color, grosor)
            else:
                self._dashed_rectangle(out, (b.x1, b.y1), (b.x2, b.y2), color, grosor)

            etiqueta = (
                f"Hallazgo {b.confidence:.0%}"
                if significativa
                else f"Baja conf. {b.confidence:.0%}"
            )
            (tw, th), _ = cv2.getTextSize(etiqueta, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            y_texto = max(b.y1, th + 6)
            cv2.rectangle(out, (b.x1, y_texto - th - 6), (b.x1 + tw + 6, y_texto), color, -1)
            cv2.putText(
                out, etiqueta, (b.x1 + 3, y_texto - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
            )
        return out

    @staticmethod
    def _dashed_rectangle(img, pt1, pt2, color, grosor, dash=8):
        """Rectángulo punteado, para que un hallazgo dudoso no se vea igual
        que uno confirmado."""
        x1, y1 = pt1
        x2, y2 = pt2
        for x in range(x1, x2, dash * 2):
            cv2.line(img, (x, y1), (min(x + dash, x2), y1), color, grosor)
            cv2.line(img, (x, y2), (min(x + dash, x2), y2), color, grosor)
        for y in range(y1, y2, dash * 2):
            cv2.line(img, (x1, y), (x1, min(y + dash, y2)), color, grosor)
            cv2.line(img, (x2, y), (x2, min(y + dash, y2)), color, grosor)

    @staticmethod
    def _ubicacion_en_imagen(b: DetectionBox, ancho: int, alto: int) -> str:
        """Describe DÓNDE está la caja, en coordenadas de la imagen.

        Deliberadamente NO usa términos anatómicos (radio, cúbito, proximal,
        distal): el modelo detecta una sola clase y no conoce la orientación
        de la placa ni la lateralidad. Nombrar un hueso desde la posición del
        recuadro sería precisión inventada — el tipo de afirmación que un
        radiólogo desarma en una pregunta. La localización anatómica y la
        tipificación (AO) son el trabajo futuro documentado del sistema.
        """
        cx = (b.x1 + b.x2) / 2 / max(ancho, 1)
        cy = (b.y1 + b.y2) / 2 / max(alto, 1)
        franja_v = "superior" if cy < 1 / 3 else ("central" if cy < 2 / 3 else "inferior")
        franja_h = "izquierdo" if cx < 1 / 3 else ("central" if cx < 2 / 3 else "derecho")
        if franja_v == "central" and franja_h == "central":
            return "sector central de la imagen"
        return f"sector {franja_v} {franja_h} de la imagen"

    @staticmethod
    def _tamano_relativo(b: DetectionBox, ancho: int, alto: int) -> str:
        area = ((b.x2 - b.x1) * (b.y2 - b.y1)) / max(ancho * alto, 1)
        if area < 0.01:
            return "focal"
        if area < 0.05:
            return "de pequeño tamaño"
        return "extenso"

    def generate_report_text(self, result: PredictionResult) -> str:
        """Informe estructurado al estilo de un informe radiológico.

        Secciones TÉCNICA / HALLAZGOS / IMPRESIÓN / LIMITACIONES, con la
        regla de oro de no afirmar nada que el sistema no sepa: localización
        en coordenadas de imagen (no anatómicas), el score del detector
        nombrado como tal, y negativos que no descartan patología.
        """
        ancho, alto = result.image_size
        significativas = result.significant_boxes
        bajas = result.low_confidence_boxes

        lineas = [
            "INFORME DE ANÁLISIS AUTOMATIZADO — TraumaVision AI",
            # ASCII puro: este texto se guarda en la base y termina impreso en
            # el PDF, que se arma con Helvetica y no tiene los caracteres de
            # dibujo de caja — salían como una fila de cuadrados negros. La
            # consola de Windows (cp1252) tampoco los sabe escribir.
            "=" * 49,
            "",
            "TÉCNICA",
            f"Radiografía analizada con detector de fracturas YOLOv8m "
            f"({result.model_version}), preprocesamiento "
            f"{'CLAHE' if result.clahe_applied else 'sin realce'}, "
            f"en {result.inference_time_ms:.0f} ms.",
            f"Umbral de señalización: {self.confidence_threshold:.0%} · "
            f"umbral de anormalidad: {self.abnormal_threshold:.0%}.",
            "",
            "HALLAZGOS",
        ]

        if not result.boxes:
            lineas.append(
                "No se identifican imágenes compatibles con trazo de fractura "
                "por encima del umbral de señalización."
            )
        else:
            for i, b in enumerate(significativas, 1):
                lineas.append(
                    f"{i}. Imagen compatible con trazo de fractura, "
                    f"{self._tamano_relativo(b, ancho, alto)}, en el "
                    f"{self._ubicacion_en_imagen(b, ancho, alto)} "
                    f"(confianza del detector: {b.confidence:.0%})."
                )
            if bajas:
                lineas.append("")
                lineas.append(
                    f"Se señalan además {len(bajas)} región(es) de baja confianza "
                    "(línea punteada), como referencia para correlación clínica; "
                    "no constituyen hallazgo positivo:"
                )
                for b in bajas:
                    lineas.append(
                        f"   • {self._ubicacion_en_imagen(b, ancho, alto)} "
                        f"({b.confidence:.0%})"
                    )

        lineas += ["", "IMPRESIÓN"]
        if result.is_abnormal:
            lineas.append(
                f"Estudio CON HALLAZGOS: {len(significativas)} imagen(es) "
                "compatible(s) con fractura que superan el umbral de anormalidad."
            )
        else:
            lineas.append(
                "Estudio SIN HALLAZGOS por encima del umbral de anormalidad."
            )
        lineas.append(
            "Nota: la confianza informada es el score interno del detector, "
            "no una probabilidad de fractura."
        )

        # La sensibilidad a nivel de estudio estaba escrita a mano en este
        # informe, que es el que va al PDF. Era el único número clínico que
        # quedaba suelto: al reentrenar, el PDF seguía afirmando el viejo.
        # Ahora sale de la metadata de LA REGIÓN CON LA QUE SE CORRIÓ esta
        # inferencia, no de la del modelo vivo: si la región no publica sus
        # métricas, el
        # informe no cita ninguna en vez de prestarse la del vecino (misma
        # regla que `domain_disclaimer`).
        meta = MODEL_METADATA.get(self.region) or {}
        sensibilidad = meta.get("sensibilidad")
        if sensibilidad is None:
            medida = "."
        else:
            medida = (
                " (sensibilidad medida: "
                + ("%.1f" % (sensibilidad * 100)).replace(".", ",")
                + " % a nivel de estudio)."
            )

        lineas += [
            "",
            "LIMITACIONES",
            "El sistema detecta y localiza imágenes compatibles con fractura en "
            "muñeca pediátrica; no tipifica el trazo ni identifica el hueso "
            f"comprometido. Un resultado sin hallazgos no descarta patología{medida}",
            "",
            "AVISO LEGAL: informe generado por un sistema de soporte a la "
            "decisión clínica. Debe ser interpretado, validado y firmado por "
            "un médico matriculado.",
        ]
        return chr(10).join(lineas)
