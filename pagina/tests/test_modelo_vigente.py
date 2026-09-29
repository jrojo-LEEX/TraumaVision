"""
test_modelo_vigente.py — La página cuenta sólo el modelo vigente.

La base guarda análisis de muchos modelos (v1, v2, modelos retirados de otras
regiones, registros sin modelo). Nada se borra ni se modifica: el historial
los sigue listando, marcados como «modelo anterior». Pero Métricas, el panel
admin y /dashboard/api/stats cuentan SÓLO los del modelo vigente, y la
pantalla de resultados de un análisis de muñeca hecho con un modelo anterior
no le presta la prioridad de triage ni el corte de aviso del vigente.
"""

import re

from tests.test_api import TestAdminYExportacion, crear_analisis
from tests.test_correcciones import _guardar_imagenes_de, texto_del_pdf

V2 = "yolov8m_v2_radiologico"


def _sin_etiquetas(html: str) -> str:
    return re.sub(r"<[^>]+>|&nbsp;|\s", "", html)


# ─── (d) Qué cuenta como vigente ────────────────────────────────────────────

class TestQueEsVigente:

    def test_v1r_y_yolov8m_v1r_son_el_modelo_vigente(self):
        from config.settings import es_modelo_vigente

        assert es_modelo_vigente("v1r")
        assert es_modelo_vigente("yolov8m_v1r")

    def test_los_demas_no(self):
        from config.settings import es_modelo_vigente

        for viejo in (V2, "yolov8m_v1", "muneca_pediatrica", "general_adulto",
                      "extremidad_inferior", "mano_adulto", None, ""):
            assert not es_modelo_vigente(viejo), viejo

    def test_el_nombre_sale_de_la_ruta_de_los_pesos(self):
        """Una sola fuente de verdad: la misma regla con la que
        FractureDetector guarda `model_version` en cada análisis."""
        from pathlib import Path

        from config.settings import MODELO_VIGENTE, VERSIONES_VIGENTES, YOLO_WEIGHTS_PATH

        assert MODELO_VIGENTE == Path(YOLO_WEIGHTS_PATH).parent.parent.name
        assert MODELO_VIGENTE in VERSIONES_VIGENTES

    def test_los_dos_nombres_cuentan_en_metricas(self, auth_client, db_session, users):
        from app.database import crud

        for nombre in ("v1r", "yolov8m_v1r"):
            a = crear_analisis(db_session, users["principal"], model_version=nombre)
            crud.create_feedback(db_session, a.id, agreed=True)

        datos = auth_client.get("/dashboard/api/stats").json()
        assert datos["total_analyses"] == 2
        assert datos["agreement_details"]["total"] == 2


# ─── (a) Métricas y admin no cuentan los modelos anteriores ─────────────────

class TestMetricasSoloVigente:

    def _un_vigente_y_un_v2(self, db_session, user_id):
        from app.database import crud

        vig = crear_analisis(db_session, user_id, model_version="v1r")
        crud.create_feedback(db_session, vig.id, agreed=True)
        viejo = crear_analisis(db_session, user_id, model_version=V2)
        crud.create_feedback(db_session, viejo.id, agreed=False,
                             correct_diagnosis="DIAGNOSTICO_DEL_V2")
        return vig, viejo

    def test_la_opinion_sobre_v2_no_entra_en_el_acuerdo(
        self, auth_client, db_session, users
    ):
        self._un_vigente_y_un_v2(db_session, users["principal"])

        datos = auth_client.get("/dashboard/api/stats").json()
        assert datos["total_analyses"] == 1
        assert datos["agreement_details"] == {
            "total": 1, "agreed": 1, "disagreed": 0, "rate": 1.0,
        }

        html = auth_client.get("/dashboard/").text
        # Cobertura: revisaste 1 de 1 (el de v2 no está ni en el denominador).
        assert "revisaste1de1" in _sin_etiquetas(html)
        # Su desacuerdo tampoco aparece entre los casos corregidos.
        assert "DIAGNOSTICO_DEL_V2" not in html

    def test_metricas_dice_cuantos_anteriores_quedaron_afuera(
        self, auth_client, db_session, users
    ):
        self._un_vigente_y_un_v2(db_session, users["principal"])
        crear_analisis(db_session, users["principal"], model_version="yolov8m_v1")

        html = auth_client.get("/dashboard/").text
        assert "Se cuentan solo los análisis hechos con el modelo vigente" in html
        assert "Tus2análisisanterioressiguen" in _sin_etiquetas(html)
        # El bloque de versiones ya no existe.
        assert "Modelo con el que corrieron" not in html
        assert "más de un modelo" not in html

    def test_sin_anteriores_no_hay_linea(self, auth_client, db_session, users):
        crear_analisis(db_session, users["principal"], model_version="v1r")
        html = auth_client.get("/dashboard/").text
        assert "Se cuentan solo los análisis" not in html

    def test_el_admin_tampoco_los_cuenta(self, engine, users, client, db_session):
        from app.routes.admin_routes import _resumen_por_usuario

        self._un_vigente_y_un_v2(db_session, users["principal"])

        filas = {f["email"]: f for f in _resumen_por_usuario(db_session)}
        fila = filas["test@traumavision.demo"]
        assert fila["analisis"] == 1
        assert fila["feedbacks"] == 1
        assert fila["acuerdo"]["parte"] == 1

        c = TestAdminYExportacion()._login_admin(engine, users)
        html = c.get("/admin/").text
        bloque = re.search(r"Sistema completo.*?Actividad por usuario", html, re.S).group(0)
        plano = _sin_etiquetas(bloque)
        # 1 análisis, 1 opinión de acuerdo (1/1) y 0 desacuerdos.
        assert "1Análisistotales" in plano
        assert "1/1" in plano
        assert "0Desacuerdos" in plano
        assert "1análisisdemodelosanterioresnosecuenta" in plano

    def test_el_csv_del_admin_sigue_completo(self, engine, users, client, db_session):
        self._un_vigente_y_un_v2(db_session, users["principal"])
        c = TestAdminYExportacion()._login_admin(engine, users)
        csv = c.get("/admin/export/analisis.csv").text
        assert V2 in csv and "v1r" in csv


# ─── (b) El historial los lista, marcados ───────────────────────────────────

class TestHistorial:

    def test_lista_el_de_v2_con_la_etiqueta_modelo_anterior(
        self, auth_client, db_session, users
    ):
        crear_analisis(db_session, users["principal"], model_version="v1r")
        viejo = crear_analisis(db_session, users["principal"], model_version=V2)

        html = auth_client.get("/analysis/history").text
        assert f"/analysis/{viejo.id}/results" in html
        assert html.count(">modelo anterior<") == 1
        assert f'title="Modelo: {V2}"' in html

    def test_filtro_modelo_vigente(self, auth_client, db_session, users):
        crear_analisis(db_session, users["principal"], model_version="v1r")
        crear_analisis(db_session, users["principal"], model_version=V2)

        html = auth_client.get("/analysis/history").text
        assert 'data-f="vig"' in html
        assert "Modelovigente1" in _sin_etiquetas(html)
        assert html.count('data-vig="true"') == 1
        assert html.count('data-vig="false"') == 1

    def test_la_seguridad_va_en_escala_0_1(self, auth_client, db_session, users):
        crear_analisis(db_session, users["principal"], max_detection_confidence=0.694)
        html = auth_client.get("/analysis/history").text
        assert "0,694" in html
        assert "69,4" not in html


# ─── (c) Resultados de un análisis de muñeca con un modelo anterior ─────────

class TestResultadoDeModeloAnterior:

    def test_muestra_el_aviso_y_no_la_prioridad(self, auth_client, db_session, users):
        a = crear_analisis(db_session, users["principal"], model_version=V2,
                           max_detection_confidence=0.95, urgency="HIGH")
        html = auth_client.get(f"/analysis/{a.id}/results").text

        assert "Análisis hecho con un modelo anterior" in html
        assert V2 in html
        assert "No se informa prioridad clínica" in html
        assert "Prioritario" not in html
        assert 'class="verdict-word">Sin prioridad' in html
        # El alcance queda, pero atribuido al modelo vigente.
        assert "no del que" in html and "produjo este resultado" in html

    def test_sin_la_marca_del_corte(self, auth_client, db_session, users):
        from app.database import crud

        a = crear_analisis(db_session, users["principal"], model_version=V2)
        crud.create_detection_boxes(db_session, a.id, [
            {"x1": 1, "y1": 1, "x2": 9, "y2": 9, "confidence": 0.95},
        ])
        html = auth_client.get(f"/analysis/{a.id}/results").text
        assert "find-cut" not in html
        assert "sobre el corte de aviso" not in html

    def test_el_vigente_conserva_la_prioridad(self, auth_client, db_session, users):
        from app.database import crud

        a = crear_analisis(db_session, users["principal"], model_version="v1r",
                           max_detection_confidence=0.95, urgency="HIGH")
        crud.create_detection_boxes(db_session, a.id, [
            {"x1": 1, "y1": 1, "x2": 9, "y2": 9, "confidence": 0.95},
        ])
        html = auth_client.get(f"/analysis/{a.id}/results").text
        assert "modelo anterior" not in html
        assert 'class="verdict-word">Prioritario' in html
        assert "find-cut" in html

    def test_muneca_sin_modelo_registrado_tambien_es_anterior(
        self, auth_client, db_session, users
    ):
        a = crear_analisis(db_session, users["principal"], model_version=None)
        html = auth_client.get(f"/analysis/{a.id}/results").text
        assert "Análisis hecho con un modelo anterior" in html
        assert "Prioritario" not in html

    def test_el_pdf_lo_declara(self, auth_client, db_session, users):
        a = crear_analisis(db_session, users["principal"], model_version=V2)
        _guardar_imagenes_de(a)
        texto = texto_del_pdf(auth_client.get(f"/analysis/{a.id}/pdf").content).lower()
        assert "modelo anterior" in texto
        assert "no se informa prioridad" in texto
        assert "modelo vigente" in texto

    def test_el_pdf_del_vigente_no_cambia(self, auth_client, db_session, users):
        a = crear_analisis(db_session, users["principal"], model_version="v1r")
        _guardar_imagenes_de(a)
        texto = texto_del_pdf(auth_client.get(f"/analysis/{a.id}/pdf").content).lower()
        assert "modelo anterior" not in texto
        assert "validado" in texto

    def test_el_estudio_de_un_modelo_anterior_tambien(
        self, auth_client, db_session, users
    ):
        from app.database import crud

        e = crud.create_study(
            db_session, user_id=users["principal"], original_filename="e.zip",
            total_images=1, images_with_findings=1,
            anatomical_region="muneca_pediatrica", model_version="yolov8m_v1",
        )
        crear_analisis(db_session, users["principal"], study_id=e.id,
                       model_version="yolov8m_v1", urgency="HIGH")
        html = auth_client.get(f"/analysis/study/{e.id}").text
        assert "Análisis hecho con un modelo anterior" in html
        assert "Prioritario" not in html


# ─── La validación externa se declara sólo en Métricas ──────────────────────

class TestValidacionEnMetricas:

    def test_metricas_declara_el_test_externo(self, auth_client):
        html = auth_client.get("/dashboard/").text
        assert "externa retrospectiva" in html
        assert "Interna, separada por paciente" not in html

    def test_resultados_conserva_su_texto(self, auth_client, db_session, users):
        a = crear_analisis(db_session, users["principal"])
        html = auth_client.get(f"/analysis/{a.id}/results").text
        assert "Interna, separada por paciente" in html
        assert "externa retrospectiva" not in html


# ─── El informe de texto guardado por un modelo anterior no se muestra ──────

INFORME_V2 = (
    "Probabilidad estimada de fractura en el estudio: más de 95 % "
    "(score calibrado por Platt scaling sobre validación). "
    "Otra versión: 60 % (score calibrado por regresión isotónica)."
)
PROHIBIDAS = ("Platt", "isotónica", "Probabilidad estimada")


class TestInformeDeModeloAnterior:

    def test_ni_la_pagina_ni_el_pdf_muestran_el_informe_viejo(
        self, auth_client, db_session, users
    ):
        a = crear_analisis(db_session, users["principal"], model_version=V2,
                           report_text=INFORME_V2)
        _guardar_imagenes_de(a)

        html = auth_client.get(f"/analysis/{a.id}/results").text
        pdf = texto_del_pdf(auth_client.get(f"/analysis/{a.id}/pdf").content)
        for palabra in PROHIBIDAS:
            assert palabra not in html, palabra
            assert palabra.lower() not in pdf.lower(), palabra
        assert "lo generó un modelo anterior y no se muestra" in html
        assert "no se muestra" in pdf

    def test_el_correo_tampoco(self, auth_client, db_session, users, monkeypatch):
        import app.services.email_service as es

        a = crear_analisis(db_session, users["principal"], model_version=V2,
                           report_text=INFORME_V2)
        _guardar_imagenes_de(a)
        recibido = {}
        monkeypatch.setattr(es, "send_report_email", lambda **kw: recibido.update(kw) or True)
        auth_client.post(f"/analysis/{a.id}/email", data={"to_email": "dra@hospital.test"})
        assert "Platt" not in recibido["body_text"]
        assert "no se muestra" in recibido["body_text"]

    def test_el_vigente_si_muestra_su_informe(self, auth_client, db_session, users):
        a = crear_analisis(db_session, users["principal"], model_version="v1r",
                           report_text="INFORME_VIGENTE")
        html = auth_client.get(f"/analysis/{a.id}/results").text
        assert "INFORME_VIGENTE" in html

    def test_el_csv_conserva_el_informe_original(self, auth_client, db_session, users):
        a = crear_analisis(db_session, users["principal"], model_version=V2,
                           report_text=INFORME_V2)
        from app.database.models import Analysis

        assert db_session.get(Analysis, a.id).report_text == INFORME_V2
        csv = auth_client.get("/dashboard/export/analisis.csv").text
        assert V2 in csv
        assert "Platt scaling" in csv and "informe_texto" in csv
