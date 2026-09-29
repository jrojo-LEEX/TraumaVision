"""
test_metadata_vs_artefactos.py — Cada número de MODEL_METADATA tiene un artefacto.

Los números del modelo que muestra la página no se escriben a mano: salen de
modelo/resultados/metricas.json, que escribe modelo/test_interno.py. Si se
re-mide, se cambian los dos o este test avisa. Lo mismo vale para el test
externo (META["test_externo"]) y modelo/resultados/metricas_externo.json,
que escribe modelo/test_externo.py.
"""

import json
from pathlib import Path

import pytest

from config.settings import ABNORMAL_THRESHOLD, DEFAULT_REGION, MODEL_METADATA, YOLO_WEIGHTS_PATH

METRICAS = Path(__file__).resolve().parents[2] / "modelo" / "resultados" / "metricas.json"
EXTERNO = Path(__file__).resolve().parents[2] / "modelo" / "resultados" / "metricas_externo.json"
META = MODEL_METADATA[DEFAULT_REGION]
TOL = 5e-4


@pytest.fixture(scope="module")
def m():
    assert METRICAS.exists(), "Falta modelo/resultados/metricas.json: la metadata no tiene respaldo"
    return json.loads(METRICAS.read_text(encoding="utf-8"))


def test_caja(m):
    for clave in ("mAP50", "mAP50_95", "precision", "recall"):
        assert META[clave] == pytest.approx(m[clave], abs=TOL), clave
    assert META["test_n"] == m["n_imagenes"]
    assert META["test_n_instancias"] == m["n_instancias"]


def test_nivel_imagen(m):
    for clave in ("sensibilidad", "especificidad", "vpp", "auc_roc", "ap"):
        assert META[clave] == pytest.approx(m[clave], abs=TOL), clave
    for clave in ("sensibilidad_ic95", "especificidad_ic95", "vpp_ic95"):
        assert tuple(META[clave]) == pytest.approx(tuple(m[clave]), abs=TOL), clave


def test_matriz_de_confusion(m):
    assert (META["test_TP"], META["test_FN"], META["test_FP"], META["test_TN"]) == (m["TP"], m["FN"], m["FP"], m["TN"])
    assert META["test_n_positivos"] == m["n_positivos"]
    assert META["test_n_negativos"] == m["n_negativos"]


def test_umbral_pesos_y_fecha(m):
    assert m["umbral"] == pytest.approx(ABNORMAL_THRESHOLD)
    assert Path(m["pesos"]).parts[-3:] == Path(YOLO_WEIGHTS_PATH).parts[-3:]
    assert m["fecha"] == META["metrics_date"]


@pytest.fixture(scope="module")
def ext():
    assert EXTERNO.exists(), "Falta modelo/resultados/metricas_externo.json: la metadata externa no tiene respaldo"
    return json.loads(EXTERNO.read_text(encoding="utf-8"))


def test_externo_encabezado(ext):
    e = META["test_externo"]
    assert e["n_casos"] == ext["n_casos"]
    assert e["n_imagenes"] == ext["n_imagenes"]
    assert e["fecha"] == ext["fecha"]
    assert e["umbral"] == pytest.approx(ext["umbral"])
    assert ext["umbral"] == pytest.approx(ABNORMAL_THRESHOLD)
    assert Path(ext["pesos"]).parts[-3:] == Path(YOLO_WEIGHTS_PATH).parts[-3:]


@pytest.mark.parametrize("nivel", ["por_caso", "por_imagen"])
def test_externo_por_nivel(ext, nivel):
    e, a = META["test_externo"][nivel], ext[nivel]
    assert (e["TP"], e["FN"], e["FP"], e["TN"]) == (a["TP"], a["FN"], a["FP"], a["TN"])
    for clave in ("sensibilidad", "especificidad"):
        assert e[clave] == pytest.approx(a[clave], abs=TOL), clave
        assert tuple(e[clave + "_ic95"]) == pytest.approx(tuple(a[clave + "_ic95"]), abs=TOL), clave
