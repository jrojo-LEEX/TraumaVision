"""
Configuración centralizada del proyecto TraumaVision AI.

Lee las variables del archivo .env y las expone al resto del proyecto, para no
escribir claves ni rutas absolutas dentro del código.
"""

import os
import secrets
import warnings
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Rutas del proyecto ---
BASE_DIR = Path(__file__).resolve().parent.parent  # Carpeta raíz del proyecto
UPLOADS_DIR = BASE_DIR / "app" / "uploads"

# --- Constantes de la aplicación ---
APP_NAME = "TraumaVision AI"
APP_VERSION = "1.0.0"
APP_DESCRIPTION = "Sistema de Soporte a la Decisión Clínica para Detección de Fracturas"
MAX_UPLOAD_SIZE_MB = 20      # Tamaño máximo de imagen suelta
MAX_ZIP_SIZE_MB = 200        # Tamaño máximo del ZIP de un estudio
MAX_ZIP_UNCOMPRESSED_MB = 600  # Tope del contenido descomprimido (anti zip-bomb)
MAX_ZIP_ENTRIES = 400        # Tope de archivos dentro del ZIP

# Modo demo: la app es un prototipo de tesis, no un despliegue clínico.
# Default en "false" a propósito: un despliegue que omita esta variable, o
# copie .env.example sin editar, no debe arrancar exponiendo credenciales de
# demo conocidas (incluida una cuenta admin) en la pantalla de login. El modo
# demo se pide explícitamente, no se hereda por omisión.
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes")

# --- Seguridad ---
_DEFAULT_SECRET = "dev-key-cambiar-en-produccion"
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY == _DEFAULT_SECRET:
    # Sin SECRET_KEY el cookie de sesión sería falsificable. En vez de arrancar
    # con una clave conocida, se genera una efímera y se avisa: las sesiones
    # existentes se invalidan en cada reinicio, que es el comportamiento seguro.
    SECRET_KEY = secrets.token_hex(32)
    warnings.warn(
        "SECRET_KEY no definida en .env — se generó una clave efímera. "
        "Las sesiones se invalidan al reiniciar. Definí SECRET_KEY en .env "
        "con: python -c \"import secrets; print(secrets.token_hex(32))\"",
        RuntimeWarning,
        stacklevel=2,
    )

SESSION_COOKIE_NAME = "traumavision_session"
SESSION_MAX_AGE_SECONDS = int(os.getenv("SESSION_MAX_AGE_SECONDS", str(8 * 3600)))
# Marca la cookie de sesión como Secure. False para la demo sobre localhost;
# obligatorio en true en cualquier despliegue con TLS.
SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "false").lower() in ("1", "true", "yes")

# Orígenes permitidos para CORS. Nunca "*": con allow_credentials=True el
# comodín es inválido por spec y el navegador rechaza la respuesta.
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if o.strip()
]

# --- Base de datos ---
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'traumavision.db'}")

# --- Email ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
# Envíos de informe por hora y por usuario. El endpoint manda imágenes de
# pacientes: sin tope sirve como canal de exfiltración y como relay de spam.
EMAIL_RATE_LIMIT_PER_HOUR = int(os.getenv("EMAIL_RATE_LIMIT_PER_HOUR", "10"))

# ── Preprocesamiento ──────────────────────────────────────────────────────────
# El dataset de entrenamiento se generó aplicando CLAHE a cada imagen
# (datos/grazpedwri/armar_dataset.py, clipLimit=2.0, tileGridSize=8x8).
# La inferencia aplica exactamente el mismo filtro para que el modelo vea en
# producción la misma distribución que vio al entrenar.
# Se aplica en entrenamiento e inferencia por consistencia.
APPLY_CLAHE_AT_INFERENCE = os.getenv("APPLY_CLAHE_AT_INFERENCE", "true").lower() in ("1", "true", "yes")
CLAHE_CLIP_LIMIT = float(os.getenv("CLAHE_CLIP_LIMIT", "2.0"))
CLAHE_TILE_SIZE = int(os.getenv("CLAHE_TILE_SIZE", "8"))

# ── Umbrales de detección ─────────────────────────────────────────────────────
# Dos umbrales distintos, con propósitos distintos:
#
#   CONFIDENCE_THRESHOLD (0.15) — a partir de acá se DIBUJA la caja. Es un
#   umbral de VISUALIZACIÓN, más bajo que el de anormalidad: sirve para
#   mostrarle al médico hallazgos dudosos como referencia, sin que por eso
#   el estudio se clasifique como anormal.
#
#   ABNORMAL_THRESHOLD (0.22) — a partir de acá el estudio se CLASIFICA como
#   anormal. Separar ambos evita reportar como patológico todo lo que se dibuja.
#
#   El valor 0.22 se eligió el 2026-09-28 sobre VALIDACIÓN (n=3.119) con el
#   modelo v1r: es el umbral más alto que alcanza sensibilidad por imagen
#   >= 96 % (especificidad 90,6 % en validación). Se fijó ANTES de medir el
#   test. El 0.25 anterior se había elegido mirando el test con v1.
#
#   Es bajo y no 0.50 porque el sistema es de SCREENING: perder una
#   fractura (FN) tiene peor consecuencia clínica que una alarma falsa (FP),
#   que el médico descarta al leer la placa. Cuántas fracturas recupera bajar
#   el umbral, y a cambio de cuántos FP, se lee en modelo/resultados/.
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.15"))
ABNORMAL_THRESHOLD = float(os.getenv("ABNORMAL_THRESHOLD", "0.22"))

# ── Urgencia clínica ──────────────────────────────────────────────────────────
# Los dos cortes son sobre el score post-NMS de YOLO, que NO es una
# probabilidad de fractura: son umbrales operativos para ordenar la revisión,
# no una estimación de riesgo.
URGENCY_HIGH_THRESHOLD = float(os.getenv("URGENCY_HIGH_THRESHOLD", "0.85"))
# Atado a ABNORMAL_THRESHOLD a propósito: son la misma frontera clínica
# ("¿este estudio es anormal?"). Tenerlas como dos constantes independientes
# fue lo que permitió que divergieran (0.50 en el código contra 0.25 en el
# informe de nivel imagen) sin que nadie lo notara.
URGENCY_MED_THRESHOLD = float(os.getenv("URGENCY_MED_THRESHOLD", str(ABNORMAL_THRESHOLD)))

# ── Modelos disponibles ───────────────────────────────────────────────────────
# Un único modelo en producción: muñeca pediátrica sobre GRAZPEDWRI-DX.
#
# Los modelos 'general_adulto' (yolov8m_general_v3) y 'extremidad_inferior'
# (yolov8m_extremidad_v1) se retiraron el 2026-08-24:
#   - extremidad_inferior: su dataset se construyó aumentando x4 ANTES de hacer
#     el split, así que copias de la misma placa quedaron en train y en test.
#     Sus métricas publicadas (mAP 0.961 / recall 0.927) no son válidas.
#   - general_adulto: los pools de datos que lo entrenaron (general_pool_v3)
#     fueron borrados, así que no es reproducible ni re-validable.
YOLO_MODELS = {
    # yolov8m_v1r: v1 reentrenado el 2026-09-28 (modelo/entrenar.py). El
    # checkpoint de v1 sigue en modelo/archivados/v1/.
    "muneca_pediatrica": os.getenv(
        "YOLO_MODEL_MUNECA",
        str(BASE_DIR.parent / "modelo/v1r/weights/best.pt"),
    ),
}

# Ruta por defecto cuando no se especifica región.
DEFAULT_REGION = "muneca_pediatrica"
YOLO_WEIGHTS_PATH = YOLO_MODELS[DEFAULT_REGION]

# Metadata para la UI de selección.
#
# CADA NÚMERO DE ACÁ TIENE UN ARTEFACTO, y tests/test_metadata_vs_artefactos.py
# comprueba que coincidan. Si se re-mide, se cambian los dos o el test avisa.
#
#   Todos salen de modelo/resultados/metricas.json, que escribe
#   modelo/test_interno.py: caja con model.val sobre el split test (imgsz 640,
#   workers=0) y nivel imagen a τ = ABNORMAL_THRESHOLD (sens, espec, VPP con
#   IC de Wilson, AUC-ROC, AP, TP/FN/FP/TN).
#
# El test tiene 3.038 imágenes de 914 pacientes. Entre el 2026-05-20 y el
# 2026-09-01 faltaron 340 en disco; toda métrica de esas fechas es sobre
# n=2.698 y no se compara con éstas sin decirlo.
#
# workers=0 no es decorativo: con el default (workers=8) la validación en
# Windows lanza multiprocessing por spawn y el proceso se re-importa a sí
# mismo hasta colgarse.
MODEL_METADATA: dict = {
    "muneca_pediatrica": {
        "label": "Muñeca — Pediátrica (0–17 años)",
        "description": "GRAZPEDWRI-DX · 20.327 imágenes · YOLOv8m · 60 épocas",
        "icon": "🦴",
        "available": True,
        # ── caja · modelo/resultados/metricas.json ───────────────────────
        "mAP50": 0.9436,
        "mAP50_95": 0.5528,
        "precision": 0.92,
        "recall": 0.8875,
        "test_n": 3038,
        "test_n_pacientes": 914,
        "test_n_instancias": 2722,
        "metrics_date": "2026-09-29",
        # ── nivel imagen · modelo/resultados/metricas.json ───────────────
        # En el punto de operación real del sistema (τ = ABNORMAL_THRESHOLD).
        # Son las clínicamente interpretables: dicen si el sistema acierta al
        # decir "este estudio tiene fractura". Intervalos de Wilson al 95 %.
        "sensibilidad": 0.9674,
        "sensibilidad_ic95": (0.9588, 0.9743),
        "especificidad": 0.9308,
        "especificidad_ic95": (0.9135, 0.9449),
        "vpp": 0.9655,
        "vpp_ic95": (0.9567, 0.9726),
        # AUC-ROC y AP no dependen del umbral: contestan «¿qué tan bien
        # separa?» sin la discusión de dónde se puso el corte.
        "auc_roc": 0.9868,
        "ap": 0.9932,
        "test_TP": 1960,
        "test_FN": 66,
        "test_FP": 70,
        "test_TN": 942,
        "test_n_positivos": 2026,
        "test_n_negativos": 1012,
        # ── test externo PediURF · modelo/resultados/metricas_externo.json ─
        # Radiografías de antebrazo pediátrico recortadas a la muñeca. Por
        # CASO (positivo si alguna de sus vistas marca fractura) y por imagen.
        "test_externo": {
            "pesos": "modelo/v1r/weights/best.pt",
            "fecha": "2026-09-29",
            "umbral": 0.22,
            "n_casos": 1000,
            "n_imagenes": 1790,
            "por_caso": {
                "TP": 493,
                "FN": 7,
                "FP": 84,
                "TN": 416,
                "sensibilidad": 0.986,
                "sensibilidad_ic95": (0.9714, 0.9932),
                "especificidad": 0.832,
                "especificidad_ic95": (0.7967, 0.8622),
            },
            "por_imagen": {
                "TP": 968,
                "FN": 26,
                "FP": 93,
                "TN": 703,
                "sensibilidad": 0.9738,
                "sensibilidad_ic95": (0.9619, 0.9821),
                "especificidad": 0.8832,
                "especificidad_ic95": (0.859, 0.9037),
            },
        },
        "supported_regions": ["Muñeca pediátrica"],
        "low_recall_regions": [],
    },
}

REGION_LABELS = {k: f"{v['icon']} {v['label']}" for k, v in MODEL_METADATA.items()}
REGION_AVAILABLE = {k: v["available"] for k, v in MODEL_METADATA.items()}


# --- Disclaimer legal (se muestra en toda la app) ---
LEGAL_DISCLAIMER = (
    "AVISO LEGAL: Este sistema constituye un Sistema de Soporte a la Decisión Clínica (SSDC). "
    "NO reemplaza el juicio clínico del profesional médico. Los resultados generados son "
    "sugerencias computacionales que deben ser interpretadas, validadas y aprobadas por un "
    "médico matriculado. Este software no realiza diagnósticos médicos."
)


# --- Salvedad de dominio y desempeño -----------------------------------------
# LEGAL_DISCLAIMER dice qué ES el sistema. No dice NADA sobre en qué población
# fue validado ni cuánto se le escapa, y esas dos cosas son las que deciden si
# un informe se puede leer o no.
#
# La pantalla ya las decía (macro `alcance_clinico` en _macros.html). El PDF
# no las mencionaba ni una vez, y el PDF es el artefacto que sale del sistema:
# el que llega al tribunal y el que puede llegar al paciente. Un informe que
# afirma menos salvedades que la pantalla de la que salió es una mentira por
# omisión.
#
# El texto se DERIVA de MODEL_METADATA. No se escribe a mano en ningún lado:
# si mañana cambia el recall medido, el informe cambia solo. Ésa es la única forma de que la web y
# el PDF no puedan divergir.

# Centinela para distinguir dos cosas que NO son lo mismo:
#   domain_disclaimer()      -> informe genérico, habla del modelo en producción
#   domain_disclaimer(None)  -> este registro no guardó con qué se procesó
# Con `region=None` como default las dos colapsaban en la primera, y los 390
# análisis de la base sin región registrada recibían las métricas del modelo
# vivo — que no son las suyas.
REGION_NO_INDICADA = object()


def domain_disclaimer(region=REGION_NO_INDICADA) -> str:
    """Alcance y limitaciones del modelo que produjo un resultado.

    `region` es la clave de la región con la que se corrió la inferencia.
    Si no está en MODEL_METADATA —modelo retirado— o si es None —el registro
    no guardó su procedencia— el texto lo dice y NO cita ninguna métrica: las
    del modelo vivo no son las suyas, y prestárselas sería inventar un número.

    Es la misma regla que aplica la pantalla:
    `out_of_domain = region_key != default_region`, y None nunca es igual.
    """
    clave = DEFAULT_REGION if region is REGION_NO_INDICADA else region
    meta = MODEL_METADATA.get(clave) if clave else None

    if not meta:
        return (
            "ALCANCE Y LIMITACIONES: este resultado quedó FUERA DEL DOMINIO VALIDADO. "
            "Se generó con un modelo retirado del sistema o sin región registrada, "
            "cuyas métricas no son reproducibles. El resultado no debe usarse para ordenar la revisión ni para ninguna "
            "conducta clínica."
        )

    recall = meta["recall"]
    faltan = round((1 - recall) * 100)
    coma = lambda x: ("%.3f" % x).replace(".", ",")  # noqa: E731

    return (
        "ALCANCE Y LIMITACIONES: el modelo está validado ÚNICAMENTE sobre "
        f"{meta['label']}, entrenado y evaluado sobre {meta['description']}. "
        "Fuera de ese dominio este informe no tiene validez. "
        f"Recall de detección {coma(recall)}, medido el {meta['metrics_date']} sobre "
        f"un conjunto de test de {meta['test_n']} imágenes separado por paciente: "
        f"alrededor de {faltan} de cada 100 fracturas anotadas no se detectan, de modo "
        "que UN INFORME SIN HALLAZGOS NO DESCARTA FRACTURA. "
        "La confianza que muestra el sistema es el score del detector y no debe "
        "leerse como probabilidad de fractura. "
        "Validación interna, separada por paciente: sin estudio prospectivo ni "
        "multicéntrico."
    )
