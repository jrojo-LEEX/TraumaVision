"""
test_pagina.py — Lo esencial de la página, en un solo archivo.

1-2. Los números del modelo que muestra la página salen de los JSON que
     escriben modelo/test_interno.py y modelo/test_externo.py.
3-4. Login y rutas protegidas.
5-7. Subir una radiografía, aislamiento entre médicos y PDF.
8-9. Métricas: sin margen de error y sólo con el modelo vigente.
10.  Los tests no escriben en app/uploads real.
"""

import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tests.conftest import TEST_USER

RESULTADOS = Path(__file__).resolve().parents[2] / "modelo" / "resultados"
TOL = 5e-4
V2 = "yolov8m_v2_radiologico"


# ─── Ayudas ──────────────────────────────────────────────────────────────────

def png_bytes(lado: int = 128, valor: int = 0) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.full((lado, lado, 3), valor, dtype=np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


def crear_analisis(db_session, user_id: int, **kwargs):
    from app.database import crud

    datos = dict(
        user_id=user_id,
        original_image_path="a_original.png",
        annotated_image_path="a_annotated.png",
        report_text="Informe de prueba",
        max_detection_confidence=0.9,
        is_abnormal=True,
        inference_time_ms=12.0,
        anatomical_region="muneca_pediatrica",
        model_version="v1r",
        routing_method="manual",
        urgency="HIGH",
    )
    datos.update(kwargs)
    return crud.create_analysis(db_session, **datos)


def guardar_imagenes_de(analysis) -> None:
    """Escribe en disco las dos PNG que el generador de PDF va a abrir."""
    from config.settings import UPLOADS_DIR

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 48), 20).save(str(UPLOADS_DIR / analysis.original_image_path))
    Image.new("RGB", (48, 48), 90).save(str(UPLOADS_DIR / analysis.annotated_image_path))


# ─── 1-2. Números de la página == artefactos del modelo ─────────────────────

def test_metadata_igual_a_metricas_del_test_interno():
    from config.settings import ABNORMAL_THRESHOLD, DEFAULT_REGION, MODEL_METADATA, YOLO_WEIGHTS_PATH

    meta = MODEL_METADATA[DEFAULT_REGION]
    archivo = RESULTADOS / "metricas.json"
    assert archivo.exists(), "Falta modelo/resultados/metricas.json: la metadata no tiene respaldo"
    m = json.loads(archivo.read_text(encoding="utf-8"))

    # Caja
    for clave in ("mAP50", "mAP50_95", "precision", "recall"):
        assert meta[clave] == pytest.approx(m[clave], abs=TOL), clave
    assert meta["test_n"] == m["n_imagenes"]
    assert meta["test_n_instancias"] == m["n_instancias"]
    # Nivel imagen
    for clave in ("sensibilidad", "especificidad", "vpp", "auc_roc", "ap"):
        assert meta[clave] == pytest.approx(m[clave], abs=TOL), clave
    for clave in ("sensibilidad_ic95", "especificidad_ic95", "vpp_ic95"):
        assert tuple(meta[clave]) == pytest.approx(tuple(m[clave]), abs=TOL), clave
    # Matriz de confusión
    assert (meta["test_TP"], meta["test_FN"], meta["test_FP"], meta["test_TN"]) == (
        m["TP"], m["FN"], m["FP"], m["TN"])
    assert meta["test_n_positivos"] == m["n_positivos"]
    assert meta["test_n_negativos"] == m["n_negativos"]
    # Umbral, pesos y fecha
    assert m["umbral"] == pytest.approx(ABNORMAL_THRESHOLD)
    assert Path(m["pesos"]).parts[-3:] == Path(YOLO_WEIGHTS_PATH).parts[-3:]
    assert m["fecha"] == meta["metrics_date"]


def test_metadata_igual_a_metricas_del_test_externo():
    from config.settings import ABNORMAL_THRESHOLD, DEFAULT_REGION, MODEL_METADATA, YOLO_WEIGHTS_PATH

    e = MODEL_METADATA[DEFAULT_REGION]["test_externo"]
    archivo = RESULTADOS / "metricas_externo.json"
    assert archivo.exists(), "Falta modelo/resultados/metricas_externo.json: la metadata externa no tiene respaldo"
    ext = json.loads(archivo.read_text(encoding="utf-8"))

    assert e["n_casos"] == ext["n_casos"]
    assert e["n_imagenes"] == ext["n_imagenes"]
    assert e["fecha"] == ext["fecha"]
    assert e["umbral"] == pytest.approx(ext["umbral"])
    assert ext["umbral"] == pytest.approx(ABNORMAL_THRESHOLD)
    assert Path(ext["pesos"]).parts[-3:] == Path(YOLO_WEIGHTS_PATH).parts[-3:]
    for nivel in ("por_caso", "por_imagen"):
        a, b = e[nivel], ext[nivel]
        assert (a["TP"], a["FN"], a["FP"], a["TN"]) == (b["TP"], b["FN"], b["FP"], b["TN"]), nivel
        for clave in ("sensibilidad", "especificidad"):
            assert a[clave] == pytest.approx(b[clave], abs=TOL), (nivel, clave)
            assert tuple(a[clave + "_ic95"]) == pytest.approx(tuple(b[clave + "_ic95"]), abs=TOL), (nivel, clave)


# ─── 3-4. Sesión ─────────────────────────────────────────────────────────────

def test_login_correcto_e_incorrecto(client, users):
    r = client.post("/login", data={"email": TEST_USER["email"], "password": "mala"})
    assert r.status_code == 401
    assert "incorrectos" in r.text.lower()

    r = client.post("/login", data={"email": TEST_USER["email"], "password": TEST_USER["password"]})
    assert r.status_code == 303
    assert r.headers["location"] == "/analysis/upload"


def test_sin_sesion_las_pantallas_redirigen_al_login(client):
    for ruta in ("/", "/analysis/upload", "/analysis/history", "/dashboard/", "/dashboard/api/stats"):
        r = client.get(ruta)
        assert r.status_code == 303, ruta
        assert r.headers["location"].startswith("/login"), ruta


# ─── 5-7. Análisis ───────────────────────────────────────────────────────────

def test_subir_una_radiografia_crea_un_analisis(auth_client, db_session, users):
    from app.database import crud

    r = auth_client.post(
        "/analysis/upload",
        files={"file": ("rx.png", png_bytes(128), "image/png")},
    )
    assert r.status_code == 303, r.text[:400]
    assert "/results" in r.headers["location"]

    analisis = crud.get_analyses_by_user(db_session, users["principal"])
    assert len(analisis) == 1
    assert analisis[0].model_version
    assert analisis[0].anatomical_region == "muneca_pediatrica"
    assert auth_client.get(r.headers["location"]).status_code == 200


def test_un_medico_no_ve_el_analisis_la_imagen_ni_el_pdf_de_otro(auth_client, db_session, users):
    ajeno = crear_analisis(db_session, users["otro"], annotated_image_path="secreto_annotated.png")
    guardar_imagenes_de(ajeno)

    assert auth_client.get(f"/analysis/{ajeno.id}/results").status_code == 404
    assert auth_client.get("/analysis/imagen/secreto_annotated.png").status_code == 404
    assert auth_client.get(f"/analysis/{ajeno.id}/pdf").status_code == 404


def test_el_pdf_de_un_analisis_propio_se_genera(auth_client, db_session, users):
    a = crear_analisis(db_session, users["principal"])
    guardar_imagenes_de(a)

    r = auth_client.get(f"/analysis/{a.id}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


# ─── 8-9. Métricas ───────────────────────────────────────────────────────────

def test_metricas_responde_y_no_muestra_el_margen_de_error(auth_client):
    r = auth_client.get("/dashboard/")
    assert r.status_code == 200
    html = r.text
    assert "IC 95" not in html and "IC&nbsp;95" not in html
    assert "intervalo de confianza" not in html


def test_un_analisis_de_un_modelo_anterior_no_cuenta_ni_muestra_su_informe(
    auth_client, db_session, users
):
    from app.database import crud

    vigente = crear_analisis(db_session, users["principal"], model_version="v1r")
    crud.create_feedback(db_session, vigente.id, agreed=True)
    viejo = crear_analisis(
        db_session, users["principal"], model_version=V2,
        report_text="Probabilidad estimada de fractura: 95 % (score calibrado por Platt scaling).",
    )
    crud.create_feedback(db_session, viejo.id, agreed=False)

    datos = auth_client.get("/dashboard/api/stats").json()
    assert datos["total_analyses"] == 1
    assert datos["agreement_details"]["total"] == 1

    html = auth_client.get(f"/analysis/{viejo.id}/results").text
    assert "Platt" not in html and "Probabilidad estimada" not in html
    assert "lo generó un modelo anterior y no se muestra" in html


# ─── 10. Carpeta de uploads ──────────────────────────────────────────────────

def test_los_tests_no_escriben_en_los_uploads_reales():
    from config.settings import BASE_DIR, UPLOADS_DIR

    assert UPLOADS_DIR.resolve() != (BASE_DIR / "app" / "uploads").resolve()


# ─── 11-13. Enviar el informe por mail ──────────────────────────────────────

class ServidorDeMentira:
    """Reemplaza al servidor de correo: guarda lo que recibe en vez de mandarlo."""

    enviados = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, context=None):
        pass

    def login(self, usuario, clave):
        pass

    def send_message(self, mensaje):
        ServidorDeMentira.enviados.append(mensaje)


@pytest.fixture
def mail_configurado(monkeypatch):
    import app.routes.analysis_routes as rutas
    import app.services.email_service as servicio
    from app.services import rate_limit

    monkeypatch.setattr(rutas, "EMAIL_HABILITADO", True)
    monkeypatch.setattr(servicio, "SMTP_EMAIL", "traumavision@ejemplo.com")
    monkeypatch.setattr(servicio, "SMTP_PASSWORD", "clave-de-prueba")
    monkeypatch.setattr(servicio.smtplib, "SMTP", ServidorDeMentira)
    ServidorDeMentira.enviados = []
    rate_limit.reset()
    return ServidorDeMentira.enviados


def test_enviar_por_mail_manda_el_pdf_adjunto(auth_client, db_session, users, mail_configurado):
    a = crear_analisis(db_session, users["principal"])
    guardar_imagenes_de(a)

    r = auth_client.post(f"/analysis/{a.id}/email", data={"destino": "colega@hospital.com"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("?mail=enviado")
    assert len(mail_configurado) == 1
    mensaje = mail_configurado[0]
    assert mensaje["To"] == "colega@hospital.com"
    adjunto = next(mensaje.iter_attachments())
    assert adjunto.get_content_type() == "application/pdf"
    assert adjunto.get_content().startswith(b"%PDF")
    assert "Informe enviado por mail" in auth_client.get(r.headers["location"]).text


def test_no_se_puede_mandar_por_mail_el_analisis_de_otro_ni_a_un_mail_invalido(
    auth_client, db_session, users, mail_configurado
):
    ajeno = crear_analisis(db_session, users["otro"])
    assert auth_client.post(f"/analysis/{ajeno.id}/email", data={"destino": "a@b.com"}).status_code == 404

    propio = crear_analisis(db_session, users["principal"])
    r = auth_client.post(f"/analysis/{propio.id}/email", data={"destino": "no-es-un-mail"}, follow_redirects=False)
    assert r.headers["location"].endswith("?mail=invalido")
    assert mail_configurado == []


def test_sin_smtp_configurado_el_boton_aparece_desactivado(auth_client, db_session, users, monkeypatch):
    import app.routes.analysis_routes as rutas

    monkeypatch.setattr(rutas, "EMAIL_HABILITADO", False)
    a = crear_analisis(db_session, users["principal"])
    html = auth_client.get(f"/analysis/{a.id}/results").text
    assert "Enviar por mail" in html and "disabled" in html
    assert 'id="mail-dialogo"' not in html
