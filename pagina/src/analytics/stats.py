"""
stats.py — Funciones de análisis de datos para el dashboard.

¿Qué hace este archivo?
Calcula estadísticas y genera datos para los gráficos del dashboard:
- Diagnósticos realizados por fecha
- Distribución por tipo de hallazgo
- Tasa de acuerdo médico-IA
- Confianza promedio del modelo
- Métricas de rendimiento del sistema

Es como el departamento de estadística del hospital que analiza
los datos de todos los estudios realizados.
"""

from datetime import timedelta
from typing import Optional
from collections import Counter

from config.tiempo import a_local, ahora_local


def calculate_agreement_rate(feedbacks: list[dict]) -> dict:
    """
    Calcula la tasa de acuerdo entre el médico y la IA.

    Parámetros:
    -----------
    feedbacks : list[dict]
        Lista de feedbacks con formato:
        [{"agreed": True/False, "timestamp": datetime, ...}, ...]

    Retorna:
    --------
    dict con estadísticas de acuerdo.
    """
    if not feedbacks:
        return {"total": 0, "agreed": 0, "disagreed": 0, "rate": 0.0}

    agreed = sum(1 for f in feedbacks if f.get("agreed"))
    total = len(feedbacks)

    return {
        "total": total,
        "agreed": agreed,
        "disagreed": total - agreed,
        "rate": agreed / total if total > 0 else 0.0,
    }


def analyses_per_day(analyses: list[dict], days: int = 30) -> dict:
    """
    Cuenta la cantidad de análisis realizados por día en los últimos N días.
    Devuelve datos listos para un gráfico de barras/líneas.

    Los `timestamp` vienen de la base en UTC (naive). El gráfico es una lectura
    del calendario del médico, así que se agrupa por el día en la ZONA DE
    PRESENTACIÓN, no por el día UTC.

    Antes se hacían las dos cosas mezcladas: las etiquetas salían de
    `datetime.now()` (hora local) y los buckets de `timestamp.strftime()` (UTC).
    Un estudio de las 22:00 locales cae en el día siguiente en UTC, y ese
    bucket no existía entre las etiquetas: el análisis DESAPARECÍA del gráfico.
    """
    hoy = ahora_local().date()
    inicio = hoy - timedelta(days=days - 1)

    por_dia = Counter()
    for a in analyses:
        local = a_local(a.get("timestamp"))
        if local is None:
            continue
        dia = local.date()
        if inicio <= dia <= hoy:
            por_dia[dia] += 1

    # Todas las fechas de la ventana, incluso las que no tienen análisis.
    dias = [inicio + timedelta(days=i) for i in range(days)]
    return {
        "labels": [d.strftime("%Y-%m-%d") for d in dias],
        "values": [por_dia.get(d, 0) for d in dias],
    }


def confidence_distribution(analyses: list[dict], bins: int = 10) -> dict:
    """
    Distribución de las confidences máximas de detección.
    Útil para entender en qué rango opera el modelo.
    """
    confidences = [a.get("max_detection_confidence", 0) for a in analyses]

    if not confidences:
        return {"labels": [], "values": []}

    import numpy as np
    counts, bin_edges = np.histogram(confidences, bins=bins, range=(0, 1))
    # Escala 0–1, como la muestra el resto de la app: con «%» el score se
    # lee como riesgo, y no es una probabilidad de fractura.
    coma = lambda x: f"{x:.1f}".replace(".", ",")  # noqa: E731
    labels = [f"{coma(bin_edges[i])}–{coma(bin_edges[i+1])}" for i in range(len(counts))]

    return {"labels": labels, "values": counts.tolist()}


def dashboard_summary(analyses: list[dict], feedbacks: list[dict]) -> dict:
    """
    Genera un resumen completo para el dashboard.
    """
    total_analyses = len(analyses)
    total_detections = sum(1 for a in analyses if a.get("is_abnormal", False))
    agreement = calculate_agreement_rate(feedbacks)

    avg_confidence = 0.0
    if total_analyses > 0:
        avg_confidence = sum(a.get("max_detection_confidence", 0) for a in analyses) / total_analyses

    return {
        "total_analyses": total_analyses,
        "total_detections": total_detections,
        "avg_confidence": round(avg_confidence, 3),
        "agreement_rate": round(agreement["rate"], 3),
        "agreement_details": agreement,
    }


def urgency_distribution(analyses: list[dict]) -> dict:
    """Cuenta los análisis por nivel de urgencia, en orden clínico fijo.

    El orden HIGH → MEDIUM → LOW se mantiene aunque falte alguno, para que
    el gráfico no cambie de forma entre usuarios.
    """
    orden = ["HIGH", "MEDIUM", "LOW"]
    etiquetas = {"HIGH": "Prioritario", "MEDIUM": "Revisar", "LOW": "Sin hallazgos"}
    conteo = Counter(a.get("urgency") or "LOW" for a in analyses)
    return {
        "labels": [etiquetas[u] for u in orden],
        "values": [conteo.get(u, 0) for u in orden],
    }

# ═════════════════════════════════════════════════════════════════════════
# MÉTRICAS DE PRÁCTICA — reescritas el 31/08/2026
# -------------------------------------------------------------------------
# Lo que había acá era una tasa de acuerdo suelta y un promedio de confianza.
# Ninguna de las dos le contesta a un médico la pregunta que un médico hace,
# que no es «¿cuánto coincidimos?» sino «¿DÓNDE no coincidimos, y cuál de
# esos desacuerdos me puede costar caro?».
#
# TRES REGLAS QUE VALEN PARA TODO ESTE BLOQUE:
#
# 1. NINGUNA TASA SIN SU DENOMINADOR. Todas las funciones devuelven `n` al
#    lado de la proporción, siempre. Un «100 %» sobre una opinión cargada no
#    es un resultado, es un accidente de muestreo, y ya pasó en esta pantalla.
#
# 2. POR DEBAJO DE `N_MINIMO` NO SE PUBLICA PORCENTAJE. Se devuelve
#    `suficiente: False` y la interfaz muestra el recuento crudo. El umbral
#    es arbitrario y por eso está acá, con nombre, y no repartido en la
#    plantilla.
#
# 3. ESTO NO MIDE AL MODELO. Mide el ACUERDO entre el sistema y quien lo usa.
#    El médico no es patrón de oro y su opinión no está verificada contra
#    nada: un desacuerdo es un desacuerdo, no un error probado. Sensibilidad
#    y especificidad reales viven en MODEL_METADATA, medidas contra el test
#    anotado, y son otra cosa. Ninguna función de acá las recalcula ni las
#    aproxima.
# ═════════════════════════════════════════════════════════════════════════

N_MINIMO = 10


def _tasa(parte: int, total: int) -> dict:
    """Una proporción que se declara insuficiente en vez de mentir."""
    return {
        "parte": parte,
        "total": total,
        "tasa": (parte / total) if total else 0.0,
        "suficiente": total >= N_MINIMO,
    }


# El mismo embudo, con nombre público, para quien publique una proporción
# FUERA de este módulo. El panel de administración calculaba las suyas a mano
# (`acuerdos / n * 100`) y así publicaba «100 %» sobre una sola opinión, que
# es exactamente el accidente que las tres reglas de arriba existen para
# impedir (auditoría 2026-09-01, 04_web H5). Cualquier porcentaje de la app
# tiene que salir de acá, y las macros de _macros.html sólo comen este dict.
tasa = _tasa


# Franjas de seguridad del detector. Los cortes NO son redondos por gusto:
# el de abajo es el umbral de dibujo y el del medio el corte de aviso, así
# que cada franja significa algo que ya existe en el resto del sistema.
#   · por debajo del umbral de dibujo: el sistema no marcó nada
#   · entre dibujo y aviso: marcó, pero no clasificó el estudio como anormal
#   · del aviso para arriba, partido en dos: donde el sistema se juega
def franjas_de_seguridad(umbral_dibujo: float, corte_aviso: float) -> list[dict]:
    medio = corte_aviso + (1.0 - corte_aviso) / 2
    return [
        {"clave": "sin_marca", "desde": 0.0, "hasta": umbral_dibujo,
         "etiqueta": "Sin marca"},
        {"clave": "bajo_aviso", "desde": umbral_dibujo, "hasta": corte_aviso,
         "etiqueta": "Marcó, bajo el corte"},
        {"clave": "sobre_aviso", "desde": corte_aviso, "hasta": medio,
         "etiqueta": "Sobre el corte"},
        {"clave": "alta", "desde": medio, "hasta": 1.01,
         "etiqueta": "Seguridad alta"},
    ]


def concordancia(registros: list[dict], umbral_dibujo: float, corte_aviso: float) -> dict:
    """El acuerdo entre el sistema y el médico, abierto por donde importa.

    `registros` es una fila por análisis con: `is_abnormal`, `urgency`,
    `max_detection_confidence` y `agreed` (True / False / None si todavía no
    se opinó).

    EL CUADRANTE es el corazón de esta pantalla, y se lee como lo lee un
    médico frente a la placa:

                      coincidís        discrepás
      marcó algo      confirmado       marcó de más
      no marcó nada   confirmado       NO MARCÓ LO QUE HABÍA   <-- el caro

    La celda de abajo a la derecha es la única de las cuatro que describe un
    posible falso negativo, que es el modo de falla que el sistema no puede
    permitirse: el recall medido (MODEL_METADATA['recall']) deja fracturas
    anotadas sin detectar y un informe sin hallazgos nunca descarta fractura.
    Por eso se cuenta aparte y se nombra entera.
    """
    revisados = [r for r in registros if r.get("agreed") is not None]
    total = len(registros)
    n = len(revisados)

    acuerdo = sum(1 for r in revisados if r["agreed"])

    marco_ok = sum(1 for r in revisados if r.get("is_abnormal") and r["agreed"])
    marco_no = sum(1 for r in revisados if r.get("is_abnormal") and not r["agreed"])
    limpio_ok = sum(1 for r in revisados if not r.get("is_abnormal") and r["agreed"])
    limpio_no = sum(1 for r in revisados if not r.get("is_abnormal") and not r["agreed"])

    etiquetas = {
        "HIGH": "Prioritario",
        "MEDIUM": "Revisar",
        "LOW_BORDERLINE": "Límite",
        "LOW": "Sin hallazgos",
    }
    por_triage = []
    for clave in ("HIGH", "MEDIUM", "LOW_BORDERLINE", "LOW"):
        grupo = [r for r in revisados if (r.get("urgency") or "LOW") == clave]
        if not grupo:
            continue
        por_triage.append({
            "clave": clave,
            "etiqueta": etiquetas[clave],
            **_tasa(sum(1 for r in grupo if r["agreed"]), len(grupo)),
        })

    por_franja = []
    for f in franjas_de_seguridad(umbral_dibujo, corte_aviso):
        grupo = [r for r in revisados
                 if f["desde"] <= (r.get("max_detection_confidence") or 0.0) < f["hasta"]]
        if not grupo:
            continue
        por_franja.append({
            "clave": f["clave"],
            "etiqueta": f["etiqueta"],
            "desde": f["desde"],
            "hasta": min(f["hasta"], 1.0),
            **_tasa(sum(1 for r in grupo if r["agreed"]), len(grupo)),
        })

    return {
        "n": n,
        "total": total,
        # Sin cobertura, la tasa de acuerdo no significa nada: es el acuerdo
        # sobre los casos que alguien se tomó el trabajo de revisar, y ésos
        # no son una muestra al azar de la práctica.
        "cobertura": _tasa(n, total),
        "general": _tasa(acuerdo, n),
        "cuadrante": {
            "marco_ok": marco_ok,
            "marco_no": marco_no,
            "limpio_ok": limpio_ok,
            "limpio_no": limpio_no,
        },
        "cuando_marco": _tasa(marco_ok, marco_ok + marco_no),
        "cuando_no_marco": _tasa(limpio_ok, limpio_ok + limpio_no),
        "por_triage": por_triage,
        "por_franja": por_franja,
    }


def _percentil(valores: list[float], p: float) -> Optional[float]:
    """Percentil por interpolación lineal, sin traerse numpy para tres datos."""
    if not valores:
        return None
    orden = sorted(valores)
    if len(orden) == 1:
        return orden[0]
    pos = (len(orden) - 1) * p
    bajo = int(pos)
    alto = min(bajo + 1, len(orden) - 1)
    return orden[bajo] + (orden[alto] - orden[bajo]) * (pos - bajo)


def desempeno_sistema(registros: list[dict]) -> dict:
    """Cuánto tarda el sistema.

    Los registros ya vienen filtrados al modelo vigente, así que no hay
    versiones que listar: acá había un recuento por modelo que mezclaba los
    viejos con el actual.

    La MEDIANA y no el promedio: un solo estudio lento —la primera inferencia
    después de arrancar carga los pesos y puede tardar diez veces más— corre
    el promedio y deja de describir la experiencia real. El p95 va al lado
    porque es el que contesta «¿cuánto es lo peor que me va a pasar?».
    """
    tiempos = [r["inference_time_ms"] for r in registros
               if r.get("inference_time_ms")]

    return {
        "n": len(tiempos),
        "mediana_ms": _percentil(tiempos, 0.50),
        "p95_ms": _percentil(tiempos, 0.95),
        "max_ms": max(tiempos) if tiempos else None,
    }


def practica(registros: list[dict], dias: int = 30) -> dict:
    """El uso propio: cuántos, desde cuándo, y qué le encontró.

    `por_dia_activo` divide por DÍAS CON ACTIVIDAD y no por días corridos.
    Dividir por los corridos convierte una semana intensa hace dos meses en
    «0,3 análisis por día», que no describe ninguna jornada real.
    """
    total = len(registros)
    fechas = [a_local(r.get("timestamp")) for r in registros]
    fechas = [f.date() for f in fechas if f is not None]

    hoy = ahora_local().date()
    desde = hoy - timedelta(days=dias - 1)
    en_ventana = sum(1 for f in fechas if desde <= f <= hoy)

    dias_activos = len(set(fechas))
    marcados = sum(1 for r in registros if r.get("is_abnormal"))
    zonas = [r.get("n_zonas") or 0 for r in registros]

    return {
        "total": total,
        "ventana_dias": dias,
        "en_ventana": en_ventana,
        "primero": min(fechas) if fechas else None,
        "ultimo": max(fechas) if fechas else None,
        "dias_activos": dias_activos,
        "por_dia_activo": (total / dias_activos) if dias_activos else 0.0,
        "marcados": _tasa(marcados, total),
        "zonas_total": sum(zonas),
        "zonas_por_estudio": (sum(zonas) / total) if total else 0.0,
        "zonas_max": max(zonas) if zonas else 0,
    }
