"""
test_metadata_vs_artefactos.py — Cada número de MODEL_METADATA tiene un artefacto.

Los números del modelo que muestra la página no se escriben a mano: salen de
modelo/resultados/metricas.json, que escribe modelo/test_interno.py. Si se
re-mide, se cambian los dos o este test avisa.
"""

import json
from pathlib import Path

import pytest

from config.settings import ABNORMAL_THRESHOLD, DEFAULT_REGION, MODEL_METADATA, YOLO_WEIGHTS_PATH

METRICAS = Path(__file__).resolve().parents[2] / "modelo" / "resultados" / "metricas.json"
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
