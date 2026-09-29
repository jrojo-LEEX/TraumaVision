"""
test_correcciones.py — Ronda de corrección de bugs 2026-08-25.

Cada bloque de esta suite nació como un test ROJO que reproducía un bug
concreto. El orden es el de gravedad con que se atacaron:

  A1         el informe PDF no llevaba la salvedad de dominio
  BLOCKER-4  los porcentajes por usuario del panel admin
  ALTA-10    timestamps UTC mostrados como si fueran hora local
  ALTA-06    inyección de fórmulas en las descargas CSV
  A2         upload-study sin POST-Redirect-GET
  BLOCKER-2  el estudio multi-imagen abría siempre en la imagen 1
  MEDIA-05   recorte del intervalo de confianza en el eje truncado
  M2         el historial decía "Todos 50" con 121 análisis guardados
  N+1        consultas por fila en exportaciones e historial
  "13"       la tasa de fallo del visor estaba escrita a mano

La regla que las ordena a todas: **ningún número que se muestre puede estar
escrito a mano**. Todos salen de config/settings.py o de la base.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import TEST_USER


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def texto_del_pdf(pdf_bytes: bytes) -> str:
    """Texto plano de un PDF, con los saltos de línea del maquetado aplanados.

    reportlab justifica los párrafos y parte las líneas donde le conviene, así
    que sin aplanar los espacios ninguna frase se puede buscar entera.
    """
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        crudo = "\n".join(pagina.get_text() for pagina in doc)
    finally:
        doc.close()
    return " ".join(crudo.split())


def imagen_pil(valor: int = 40):
    import numpy as np
    from PIL import Image

    return Image.fromarray(np.full((48, 48, 3), valor, dtype=np.uint8))


def pdf_de_prueba(**kwargs) -> bytes:
    from src.reports.generator import generate_pdf_report

    datos = dict(
        original_image=imagen_pil(20),
        annotated_image=imagen_pil(90),
        report_text="Se observa una región señalada por el sistema.",
        doctor_name="Dra. Prueba",
        analysis_id="7",
    )
    datos.update(kwargs)
    return generate_pdf_report(**datos)


# ─────────────────────────────────────────────────────────────────────────────
# A1 — El PDF tiene que decir lo mismo que la pantalla
# ─────────────────────────────────────────────────────────────────────────────

class TestSalvedadDeDominioEnElPDF:
    """El PDF es el artefacto que llega al tribunal y al paciente.

    La web declaraba el dominio validado y la ausencia de calibración; el PDF
    no las mencionaba ni una vez. Un informe que sale del sistema sin decir
    sobre qué población fue validado el modelo es el peor error posible en una
    tesis sobre honestidad de métricas.
    """

    def test_el_pdf_nombra_el_dominio_validado(self):
        from config.settings import DEFAULT_REGION, MODEL_METADATA

        etiqueta = MODEL_METADATA[DEFAULT_REGION]["label"]
        texto = texto_del_pdf(pdf_de_prueba())
        assert etiqueta in texto, "El PDF no dice sobre qué región está validado el modelo"

    def test_el_pdf_cita_el_recall_medido_y_su_complemento(self):
        """El número sale de settings, no de los dedos de nadie."""
        from config.settings import DEFAULT_REGION, MODEL_METADATA

        recall = MODEL_METADATA[DEFAULT_REGION]["recall"]
        recall_es = ("%.3f" % recall).replace(".", ",")
        faltan = round((1 - recall) * 100)

        texto = texto_del_pdf(pdf_de_prueba())
        assert recall_es in texto, f"El PDF no cita el recall medido ({recall_es})"
        assert f"{faltan} de cada 100" in texto

    def test_el_pdf_dice_que_sin_hallazgos_no_descarta_fractura(self):
        texto = texto_del_pdf(pdf_de_prueba()).upper()
        assert "NO DESCARTA FRACTURA" in texto

    def test_el_pdf_dice_que_la_confianza_no_es_una_probabilidad(self):
        """El score del detector no es una probabilidad de fractura, y el
        informe que sale del sistema lo tiene que decir."""
        texto = texto_del_pdf(pdf_de_prueba()).lower()
        assert "no debe leerse como probabilidad de fractura" in texto
        assert "calibra" not in texto

    def test_el_pdf_declara_que_la_validacion_no_es_prospectiva(self):
        texto = texto_del_pdf(pdf_de_prueba()).lower()
        assert "sin estudio prospectivo" in texto

    def test_el_texto_sigue_a_la_fuente_y_no_al_reves(self, monkeypatch):
        """Si cambia el recall en settings, cambia el informe. Sin tocar el PDF.

        Éste es el test que importa: prueba que el número NO está escrito en
        `generator.py`. Con el valor hardcodeado, el PDF seguiría diciendo 13.
        """
        from config import settings

        falso = dict(settings.MODEL_METADATA[settings.DEFAULT_REGION])
        falso["recall"] = 0.5000
        monkeypatch.setitem(settings.MODEL_METADATA, settings.DEFAULT_REGION, falso)

        texto = texto_del_pdf(pdf_de_prueba())
        assert "0,500" in texto
        assert "50 de cada 100" in texto

    def test_fuera_del_dominio_el_pdf_lo_dice_en_vez_de_inventar_metricas(self):
        """Un análisis de un modelo retirado no puede exhibir el recall del
        modelo vivo: sus métricas no son las suyas."""
        texto = texto_del_pdf(pdf_de_prueba(region="extremidad_inferior")).lower()
        assert "fuera del dominio validado" in texto
        assert "0,866" not in texto

    def test_un_analisis_sin_region_registrada_tambien_esta_fuera_del_dominio(self):
        """`region=None` no significa «usá el modelo por defecto».

        Significa que el registro no guardó con qué se procesó — 390 de los 600
        análisis de la base están así. La pantalla ya los marca fuera del
        dominio (`out_of_domain = region_key != default_region`, y None nunca
        es igual). El PDF les estaba imprimiendo las métricas del modelo vivo,
        que no son las suyas: la misma divergencia web/PDF que abrió A1.
        """
        texto = texto_del_pdf(pdf_de_prueba(region=None)).lower()
        assert "fuera del dominio validado" in texto
        assert "0,866" not in texto

    def test_sin_pasar_region_el_texto_es_el_del_modelo_en_produccion(self):
        """Omitir el argumento sí es «el modelo por defecto»: es el informe
        genérico, no un registro sin procedencia."""
        from config.settings import DEFAULT_REGION, MODEL_METADATA

        texto = texto_del_pdf(pdf_de_prueba())
        assert MODEL_METADATA[DEFAULT_REGION]["label"] in texto

    def test_la_ruta_manda_el_none_del_registro_sin_region(
        self, auth_client, db_session, users
    ):
        from tests.test_api import crear_analisis

        a = crear_analisis(
            db_session, users["principal"],
            anatomical_region=None, model_version=None,
        )
        _guardar_imagenes_de(a)
        texto = texto_del_pdf(auth_client.get(f"/analysis/{a.id}/pdf").content).lower()
        assert "fuera del dominio validado" in texto

    def test_la_ruta_del_pdf_pasa_la_region_del_analisis(self, auth_client, db_session, users):
        """No alcanza con que el generador sepa: la ruta tiene que decírselo."""
        from tests.test_api import crear_analisis

        a = crear_analisis(
            db_session, users["principal"],
            anatomical_region="extremidad_inferior",
            model_version="yolov8m_extremidad_v1",
        )
        _guardar_imagenes_de(a)
        r = auth_client.get(f"/analysis/{a.id}/pdf")
        assert r.status_code == 200
        texto = texto_del_pdf(r.content).lower()
        assert "fuera del dominio validado" in texto


def _guardar_imagenes_de(analysis) -> None:
    """Escribe en disco las dos PNG que el generador de PDF va a abrir."""
    from config.settings import UPLOADS_DIR

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    imagen_pil(20).save(str(UPLOADS_DIR / analysis.original_image_path))
    imagen_pil(90).save(str(UPLOADS_DIR / analysis.annotated_image_path))


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER-4 — Los porcentajes por usuario del panel admin
# ─────────────────────────────────────────────────────────────────────────────

class TestAgregacionDelPanelAdmin:
    """`func.sum(func.coalesce(Analysis.is_abnormal, 0))` colapsaba a 1.

    La columna está declarada `Boolean`, así que SQLAlchemy le aplicaba el
    procesador de resultado del tipo Boolean a la SUMA: 79 volvía como True,
    y `True / 121 * 100` se muestra como 1 %. El panel mostraba 1 % donde el
    valor real era 65 %.

    Es un bug de agregación, no de lógica clínica: la suma tiene que salir
    como entero (`cast(..., Integer)`).
    """

    def _cuatro_analisis(self, db_session, user_id, anormales):
        from tests.test_api import crear_analisis

        creados = []
        for i in range(4):
            creados.append(
                crear_analisis(db_session, user_id, is_abnormal=(i < anormales))
            )
        return creados

    def test_porcentaje_de_anormales_es_la_proporcion_real(self, db_session, users):
        from app.routes.admin_routes import _resumen_por_usuario

        self._cuatro_analisis(db_session, users["principal"], anormales=3)

        fila = next(
            f for f in _resumen_por_usuario(db_session)
            if f["email"] == TEST_USER["email"]
        )
        assert fila["analisis"] == 4
        assert fila["pct_anormal"] == pytest.approx(75.0), (
            "La suma de is_abnormal se está colapsando a un booleano"
        )

    def test_porcentaje_de_acuerdo_es_la_proporcion_real(self, db_session, users):
        from app.database import crud
        from app.routes.admin_routes import _resumen_por_usuario

        analisis = self._cuatro_analisis(db_session, users["principal"], anormales=4)
        for i, a in enumerate(analisis):
            crud.create_feedback(db_session, a.id, agreed=(i < 3))

        fila = next(
            f for f in _resumen_por_usuario(db_session)
            if f["email"] == TEST_USER["email"]
        )
        assert fila["feedbacks"] == 4
        assert fila["pct_acuerdo"] == pytest.approx(75.0), (
            "La suma de agreed se está colapsando a un booleano"
        )

    def test_cero_anormales_no_es_lo_mismo_que_uno(self, db_session, users):
        """El síntoma al revés: con la suma colapsada, 0 anormales daba 0 % y
        1 anormal daba 1 % — indistinguibles de 4 anormales."""
        from app.routes.admin_routes import _resumen_por_usuario

        self._cuatro_analisis(db_session, users["principal"], anormales=0)
        self._cuatro_analisis(db_session, users["otro"], anormales=4)

        filas = {f["email"]: f for f in _resumen_por_usuario(db_session)}
        assert filas[TEST_USER["email"]]["pct_anormal"] == pytest.approx(0.0)
        from tests.conftest import OTHER_USER
        assert filas[OTHER_USER["email"]]["pct_anormal"] == pytest.approx(100.0)

    def test_el_panel_renderiza_el_porcentaje_real(self, engine, users, client, db_session):
        """De punta a punta: el HTML del panel tiene que mostrar 75 %, no 1 %.

        Con cuatro análisis el panel ya NO publica porcentaje: desde la
        auditoría 2026-09-01 (A13) toda proporción del admin pasa por `_tasa`
        y con n < N_MINIMO se muestra el recuento crudo. Por eso se crean tres
        tandas (12 análisis, 9 anormales): sigue siendo 75 % y ahora sí se
        renderiza como tal.
        """
        from tests.test_api import TestAdminYExportacion

        for _ in range(3):
            self._cuatro_analisis(db_session, users["principal"], anormales=3)
        c = TestAdminYExportacion()._login_admin(engine, users)
        html = c.get("/admin/").text
        fila = re.search(
            r"test@traumavision\.demo.*?</tr>", html, re.S,
        )
        assert fila, "No se encontró la fila del usuario en el panel"
        assert "75" in fila.group(0)


# ─────────────────────────────────────────────────────────────────────────────
# ALTA-10 — Timestamps UTC mostrados como si fueran hora local
# ─────────────────────────────────────────────────────────────────────────────

def _utc_desde_local(dia_offset: int = 0, hora: int = 23, minuto: int = 30):
    """Un instante expresado en hora LOCAL, devuelto como el naive-UTC que la
    base guardaría para él.

    Con la zona de presentación en UTC-3, las 23:30 locales de ayer son las
    02:30 UTC de hoy: distinto DÍA. Es el caso que rompe un registro clínico.
    """
    from datetime import time as _time

    from config.tiempo import ahora_local, zona

    dia = ahora_local().date() + timedelta(days=dia_offset)
    local = datetime.combine(dia, _time(hora, minuto), tzinfo=zona())
    return local.astimezone(timezone.utc).replace(tzinfo=None), local


class TestZonaDePresentacion:
    """La base guarda UTC (`models._utcnow`) y SQLite lo devuelve *naive*.

    Formatear ese naive con strftime lo muestra como si fuera hora local y
    corre el registro clínico tres horas. Entre las 21:00 y las 24:00 eso
    cambia el DÍA del estudio. El mismo desfase hacía que los análisis de la
    noche se cayeran del gráfico de 30 días.
    """

    def test_un_naive_se_interpreta_como_utc(self):
        from config.tiempo import a_local, zona

        crudo = datetime(2026, 8, 25, 2, 30)          # naive, pero es UTC
        local = a_local(crudo)
        esperado = datetime(2026, 8, 25, 2, 30, tzinfo=timezone.utc).astimezone(zona())
        assert local == esperado
        assert local.tzinfo is not None

    def test_un_aware_se_convierte_sin_romperse(self):
        from config.tiempo import a_local, zona

        crudo = datetime(2026, 8, 25, 2, 30, tzinfo=timezone.utc)
        assert a_local(crudo) == crudo.astimezone(zona())

    def test_la_zona_por_defecto_es_argentina(self):
        """La app se defiende en Córdoba. Si alguien cambia el default, que se
        entere por este test y no por un informe con el día corrido."""
        from config.tiempo import ZONA_PRESENTACION, a_local

        assert ZONA_PRESENTACION == "America/Argentina/Buenos_Aires"
        # Argentina no tiene horario de verano desde 2009: siempre UTC-3.
        assert a_local(datetime(2026, 8, 25, 2, 30)).utcoffset() == timedelta(hours=-3)

    def test_none_sigue_siendo_none(self):
        from config.tiempo import a_local, fmt_local

        assert a_local(None) is None
        assert fmt_local(None, "%d/%m/%Y") == ""


class TestGraficoDeTreintaDias:

    def test_no_pierde_los_analisis_de_la_noche(self):
        """22:00 locales de hoy son mañana en UTC: el análisis se caía del
        gráfico porque su bucket no existía entre las etiquetas."""
        from config.tiempo import ahora_local
        from src.analytics.stats import analyses_per_day

        utc, local = _utc_desde_local(dia_offset=0, hora=22, minuto=0)
        datos = analyses_per_day([{"timestamp": utc}])

        assert sum(datos["values"]) == 1, "El análisis desapareció del gráfico"
        assert datos["labels"][-1] == ahora_local().strftime("%Y-%m-%d")
        assert datos["values"][-1] == 1
        assert datos["labels"][-1] == local.strftime("%Y-%m-%d")

    def test_agrupa_por_el_dia_local_y_no_por_el_dia_utc(self):
        """23:30 de ayer local = 02:30 de hoy UTC. Va en el bucket de AYER."""
        from src.analytics.stats import analyses_per_day

        utc, local = _utc_desde_local(dia_offset=-1, hora=23, minuto=30)
        datos = analyses_per_day([{"timestamp": utc}])
        i = datos["labels"].index(local.strftime("%Y-%m-%d"))

        assert datos["values"][i] == 1
        assert utc.strftime("%Y-%m-%d") != local.strftime("%Y-%m-%d"), (
            "El escenario no separa el día UTC del local: no prueba nada"
        )

    def test_la_ventana_tiene_exactamente_los_dias_pedidos(self):
        from src.analytics.stats import analyses_per_day

        datos = analyses_per_day([], days=30)
        assert len(datos["labels"]) == 30
        assert len(datos["values"]) == 30
        assert sorted(datos["labels"]) == datos["labels"]

    def test_lo_de_afuera_de_la_ventana_no_entra(self):
        from src.analytics.stats import analyses_per_day

        viejo, _ = _utc_desde_local(dia_offset=-45, hora=12)
        assert sum(analyses_per_day([{"timestamp": viejo}])["values"]) == 0


class TestFechasEnPantallaYEnElInforme:
    """De punta a punta: visor, historial, panel admin, PDF y CSV."""

    def _analisis_de_anoche(self, db_session, user_id):
        from tests.test_api import crear_analisis

        utc, local = _utc_desde_local(dia_offset=-1, hora=23, minuto=30)
        a = crear_analisis(db_session, user_id)
        a.created_at = utc
        db_session.commit()
        db_session.refresh(a)
        assert utc.strftime("%d/%m/%Y") != local.strftime("%d/%m/%Y")
        return a, utc, local

    def test_el_visor_muestra_la_fecha_local(self, auth_client, db_session, users):
        a, utc, local = self._analisis_de_anoche(db_session, users["principal"])
        html = auth_client.get(f"/analysis/{a.id}/results").text
        assert local.strftime("%d/%m/%Y %H:%M") in html
        assert utc.strftime("%d/%m/%Y %H:%M") not in html

    def test_el_historial_muestra_la_fecha_local(self, auth_client, db_session, users):
        a, utc, local = self._analisis_de_anoche(db_session, users["principal"])
        html = auth_client.get("/analysis/history").text
        assert local.strftime("%d/%m/%Y") in html
        assert local.strftime("%H:%M") in html
        assert utc.strftime("%d/%m/%Y") not in html

    def test_el_panel_admin_muestra_la_ultima_actividad_local(
        self, engine, users, client, db_session
    ):
        from tests.test_api import TestAdminYExportacion

        a, utc, local = self._analisis_de_anoche(db_session, users["principal"])
        c = TestAdminYExportacion()._login_admin(engine, users)
        html = c.get("/admin/").text
        fila = re.search(r"test@traumavision\.demo.*?</tr>", html, re.S).group(0)
        assert local.strftime("%d/%m/%Y") in fila

    def test_el_pdf_fecha_el_analisis_y_no_la_impresion(
        self, auth_client, db_session, users
    ):
        """El campo dice Fecha del análisis y llevaba la hora de impresión: un
        informe reimpreso una semana después se fechaba solo."""
        a, utc, local = self._analisis_de_anoche(db_session, users["principal"])
        _guardar_imagenes_de(a)
        texto = texto_del_pdf(auth_client.get(f"/analysis/{a.id}/pdf").content)
        assert local.strftime("%d/%m/%Y %H:%M") in texto
        assert utc.strftime("%d/%m/%Y %H:%M") not in texto

    def test_el_csv_exporta_la_fecha_local(self, auth_client, db_session, users):
        a, utc, local = self._analisis_de_anoche(db_session, users["principal"])
        csv = auth_client.get("/dashboard/export/analisis.csv").text
        assert local.strftime("%Y-%m-%d %H:%M") in csv
        assert utc.strftime("%Y-%m-%d %H:%M") not in csv

    def test_el_csv_de_opiniones_exporta_la_fecha_local(
        self, auth_client, db_session, users
    ):
        from app.database import crud

        a, utc, local = self._analisis_de_anoche(db_session, users["principal"])
        f = crud.create_feedback(db_session, a.id, agreed=True)
        f.created_at = utc
        db_session.commit()
        csv = auth_client.get("/dashboard/export/opiniones.csv").text
        assert local.strftime("%Y-%m-%d %H:%M") in csv

    def test_el_conteo_de_30_dias_del_admin_compara_contra_utc(
        self, db_session, users
    ):
        """`datetime.now()` es hora local: comparado contra una columna en UTC
        la ventana queda corrida tres horas."""
        from sqlalchemy import func

        from app.database.models import Analysis
        from app.routes.admin_routes import _hace_treinta_dias
        from tests.test_api import crear_analisis

        a = crear_analisis(db_session, users["principal"])
        # Justo dentro del borde: 29 días y 23 horas antes de AHORA en UTC.
        a.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=29, hours=23
        )
        db_session.commit()

        hace_30 = _hace_treinta_dias()
        n = (
            db_session.query(func.count(Analysis.id))
            .filter(Analysis.created_at >= hace_30)
            .scalar()
        )
        assert n == 1
        assert hace_30.tzinfo is None


# ─────────────────────────────────────────────────────────────────────────────
# ALTA-06 — Inyección de fórmulas en las descargas CSV
# ─────────────────────────────────────────────────────────────────────────────

class TestSaneadoDeCeldasCSV:
    """Excel evalúa toda celda que empieza con = + - @ al abrir el archivo.

    Un médico escribe la observación; otro abre la planilla y le corre una
    fórmula. El saneado tiene que neutralizar eso SIN romper los números: un
    negativo empieza con `-` y sigue siendo un número, no una fórmula. Ése es
    el caso que separa un saneado correcto de uno que rompe la exportación.
    """

    @pytest.mark.parametrize("peligroso", [
        "=1+1",
        "=HYPERLINK(\"http://malo\",\"click\")",
        "@SUM(A1:A9)",
        "+1+1",
        "-1+1",
        "=cmd|' /C calc'!A1",
        "\tformula",
        "\r=1+1",
    ])
    def test_neutraliza_lo_que_excel_evaluaria(self, peligroso):
        from app.routes.dashboard_routes import _sanear_celda_csv

        salida = _sanear_celda_csv(peligroso)
        assert salida.startswith("'"), f"{peligroso!r} sale sin neutralizar"
        assert salida[1:] == peligroso, "El saneado no puede perder el contenido"

    @pytest.mark.parametrize("numero", [
        "-12,5",     # negativo con coma decimal: es el formato es-AR del sistema
        "-12.5",
        "-7",
        "+3",
        "-0,0001",
        "0,9000",
        "12",
    ])
    def test_no_toca_los_numeros_legitimos(self, numero):
        """Los negativos son NÚMEROS. Prefijarlos con comilla los convierte en
        texto y la planilla deja de poder sumarlos."""
        from app.routes.dashboard_routes import _sanear_celda_csv

        assert _sanear_celda_csv(numero) == numero

    def test_no_toca_el_texto_comun(self):
        from app.routes.dashboard_routes import _sanear_celda_csv

        for texto in ["fractura de radio distal", "", "sin hallazgos", "—"]:
            assert _sanear_celda_csv(texto) == texto

    def test_los_enteros_y_flotantes_pasan_como_numeros(self):
        from app.routes.dashboard_routes import _sanear_celda_csv

        assert _sanear_celda_csv(12) == 12
        assert _sanear_celda_csv(-3.5) == -3.5
        assert _sanear_celda_csv(None) == ""


class TestExportacionesSaneadas:
    """Los cuatro endpoints que usan `respuesta_csv`."""

    FORMULA = '=HYPERLINK("http://malo","abrime")'

    def _analisis_con_region_hostil(self, db_session, user_id):
        from tests.test_api import crear_analisis

        a = crear_analisis(db_session, user_id)
        # `anatomical_region` es una columna de texto libre: sirve para probar
        # que las filas de análisis también pasan por el saneado.
        a.anatomical_region = self.FORMULA
        db_session.commit()
        return a

    def _opinion_hostil(self, db_session, user_id):
        from app.database import crud
        from tests.test_api import crear_analisis

        a = crear_analisis(db_session, user_id)
        crud.create_feedback(
            db_session, a.id, agreed=False,
            observations=self.FORMULA,
            correct_diagnosis="@SUM(A1:A9)",
        )
        return a

    def _celdas(self, respuesta) -> list[str]:
        """Todas las celdas de la descarga, parseadas como las lee Excel.

        Comparar contra el texto crudo no sirve: el escritor CSV encomilla las
        celdas que llevan `"` o `;` y duplica las comillas internas. Lo que
        importa es el valor de la CELDA, que es lo que la planilla evalúa.
        """
        import csv as _csv

        texto = respuesta.text.lstrip("﻿")
        return [c for fila in _csv.reader(texto.splitlines(), delimiter=";") for c in fila]

    def test_export_propio_de_analisis(self, auth_client, db_session, users):
        self._analisis_con_region_hostil(db_session, users["principal"])
        celdas = self._celdas(auth_client.get("/dashboard/export/analisis.csv"))
        assert f"'{self.FORMULA}" in celdas
        assert self.FORMULA not in celdas

    def test_export_propio_de_opiniones(self, auth_client, db_session, users):
        self._opinion_hostil(db_session, users["principal"])
        celdas = self._celdas(auth_client.get("/dashboard/export/opiniones.csv"))
        assert f"'{self.FORMULA}" in celdas
        assert "'@SUM(A1:A9)" in celdas
        assert self.FORMULA not in celdas
        assert "@SUM(A1:A9)" not in celdas

    def test_export_global_de_analisis(self, engine, users, client, db_session):
        from tests.test_api import TestAdminYExportacion

        self._analisis_con_region_hostil(db_session, users["principal"])
        c = TestAdminYExportacion()._login_admin(engine, users)
        celdas = self._celdas(c.get("/admin/export/analisis.csv"))
        assert f"'{self.FORMULA}" in celdas
        assert self.FORMULA not in celdas

    def test_export_global_de_opiniones(self, engine, users, client, db_session):
        from tests.test_api import TestAdminYExportacion

        self._opinion_hostil(db_session, users["principal"])
        c = TestAdminYExportacion()._login_admin(engine, users)
        celdas = self._celdas(c.get("/admin/export/opiniones.csv"))
        assert f"'{self.FORMULA}" in celdas
        assert "'@SUM(A1:A9)" in celdas

    def test_el_saneado_no_arruina_la_columna_de_score(
        self, auth_client, db_session, users
    ):
        """La exportación sigue sirviendo: el score se exporta como número."""
        from tests.test_api import crear_analisis

        crear_analisis(db_session, users["principal"], max_detection_confidence=0.9)
        celdas = self._celdas(auth_client.get("/dashboard/export/analisis.csv"))
        assert "0,9000" in celdas
        assert "'0,9000" not in celdas


# ─────────────────────────────────────────────────────────────────────────────
# A2 — upload-study sin POST-Redirect-GET
# ─────────────────────────────────────────────────────────────────────────────

class TestPostRedirectGetDelEstudio:
    """`analyze_study` renderizaba la plantilla directo sobre el POST.

    Con eso, la barra del navegador queda apuntando a `/analysis/upload-study`
    con un cuerpo POST pegado: F5 —o el botón atrás— reenvía el formulario y
    el ZIP se vuelve a procesar entero. El médico termina con dos estudios
    idénticos y no hay forma de saber cuál es el bueno.

    El alta de una imagen suelta ya redirigía. Ésta era la única rama del
    sistema que creaba registros sobre un POST renderizado.

    Estos tests corren el modelo de verdad: la ruta que se prueba es la del
    alta, y mockear el detector sería probar otra cosa.
    """

    def _subir_estudio(self, auth_client, n=1):
        from tests.test_api import make_zip_with_dicoms

        return auth_client.post(
            "/analysis/upload-study",
            files={"file": ("estudio.zip", make_zip_with_dicoms(n), "application/zip")},
        )

    def test_el_alta_redirige_en_vez_de_renderizar(self, auth_client):
        r = self._subir_estudio(auth_client)
        assert r.status_code == 303, (
            f"El POST devolvió {r.status_code}: sigue renderizando sobre el POST"
        )
        assert re.fullmatch(r"/analysis/study/\d+", r.headers["location"])

    def test_el_redirect_lleva_al_estudio_recien_creado(self, auth_client, db_session, users):
        from app.database.models import Study

        r = self._subir_estudio(auth_client)
        estudio = db_session.query(Study).filter(Study.user_id == users["principal"]).one()
        assert r.headers["location"] == f"/analysis/study/{estudio.id}"

        pagina = auth_client.get(r.headers["location"])
        assert pagina.status_code == 200
        assert f"Estudio <span class=\"page-id\">#{estudio.id}</span>" in pagina.text

    def test_refrescar_no_duplica_el_estudio(self, auth_client, db_session, users):
        """F5 sobre el resultado es un GET: no puede crear nada."""
        from app.database.models import Analysis, Study

        destino = self._subir_estudio(auth_client).headers["location"]
        for _ in range(3):
            assert auth_client.get(destino).status_code == 200

        assert db_session.query(Study).filter(Study.user_id == users["principal"]).count() == 1
        assert db_session.query(Analysis).filter(
            Analysis.user_id == users["principal"]
        ).count() == 1

    def test_un_zip_invalido_sigue_mostrando_el_error_en_la_misma_pagina(self, auth_client):
        """El PRG es para el ALTA. Un error de validación no creó nada, así que
        se sigue contestando con la página del formulario."""
        r = auth_client.post(
            "/analysis/upload-study",
            files={"file": ("radiografia.png", b"no soy un zip", "image/png")},
        )
        assert r.status_code == 200
        assert "subí un archivo ZIP" in r.text


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER-2 — El estudio multi-imagen abría siempre en la imagen 1
# ─────────────────────────────────────────────────────────────────────────────

def _res(index, nivel, conf=0.5):
    """Una fila de `results` con lo único que mira la escalera de urgencia."""
    return {"index": index, "urgency": {"nivel": nivel}, "max_detection_confidence": conf}


class TestImagenMasUrgente:
    """Cuál de las imágenes de un estudio tiene que abrir el visor.

    El estudio #1 de la base tiene la fractura en la imagen 3. Al abrirlo, el
    panel gritaba SIN HALLAZGOS en 48 px —el veredicto de la imagen 1— y el
    recuento real del estudio vivía en texto chico. La primera lectura del
    médico era la equivocada.
    """

    def test_abre_en_la_imagen_de_mayor_urgencia(self):
        from app.services.routing_service import imagen_mas_urgente

        assert imagen_mas_urgente([
            _res(1, "LOW"), _res(2, "LOW"), _res(3, "HIGH"),
        ]) == 3

    def test_respeta_toda_la_escalera(self):
        from app.services.routing_service import imagen_mas_urgente

        assert imagen_mas_urgente([_res(1, "LOW"), _res(2, "LOW_BORDERLINE")]) == 2
        assert imagen_mas_urgente([_res(1, "LOW_BORDERLINE"), _res(2, "MEDIUM")]) == 2
        assert imagen_mas_urgente([_res(1, "MEDIUM"), _res(2, "HIGH")]) == 2

    def test_no_depende_del_orden_de_la_lista(self):
        from app.services.routing_service import imagen_mas_urgente

        filas = [_res(1, "LOW"), _res(2, "MEDIUM"), _res(3, "HIGH"), _res(4, "LOW")]
        for corte in range(len(filas)):
            rotadas = filas[corte:] + filas[:corte]
            assert imagen_mas_urgente(rotadas) == 3

    def test_a_igual_urgencia_gana_el_score_mas_alto(self):
        from app.services.routing_service import imagen_mas_urgente

        assert imagen_mas_urgente([
            _res(1, "HIGH", 0.91), _res(2, "HIGH", 0.97), _res(3, "HIGH", 0.93),
        ]) == 2

    def test_el_desempate_final_es_estable_y_determinista(self):
        """Empate total: siempre la primera imagen, y siempre la misma.

        Sin desempate explícito, dos aperturas del mismo estudio podían abrir
        en imágenes distintas. Un visor clínico no puede hacer eso."""
        from app.services.routing_service import imagen_mas_urgente

        filas = [_res(3, "HIGH", 0.9), _res(1, "HIGH", 0.9), _res(2, "HIGH", 0.9)]
        assert imagen_mas_urgente(filas) == 1
        assert len({imagen_mas_urgente(filas) for _ in range(20)}) == 1

    def test_un_estudio_sin_imagenes_no_abre_nada(self):
        from app.services.routing_service import imagen_mas_urgente

        assert imagen_mas_urgente([]) is None

    def test_un_nivel_desconocido_no_gana_por_accidente(self):
        """Si mañana aparece un nivel nuevo sin ubicar en la escalera, tiene
        que caer al piso, no colarse arriba de un HIGH."""
        from app.services.routing_service import imagen_mas_urgente

        assert imagen_mas_urgente([_res(1, "HIGH"), _res(2, "NIVEL_NUEVO")]) == 1


def _panel_abierto(html):
    """El `data-panel-idx` del único panel sin `hidden`."""
    abiertos = [
        int(m.group(1))
        for m in re.finditer(r'data-panel-idx="(\d+)"(\s*)(hidden)?>', html)
        if not m.group(3)
    ]
    assert len(abiertos) == 1, f"Paneles abiertos: {abiertos}"
    return abiertos[0]


def _cuadro_marcado(html):
    """El `data-idx` de la miniatura con `aria-current="true"`."""
    marcados = re.findall(r'aria-current="true"[\s\S]{0,200}?data-idx="(\d+)"', html)
    assert len(marcados) == 1, f"Miniaturas marcadas: {marcados}"
    return int(marcados[0])


class TestAperturaDelEstudioEnPantalla:

    def _estudio(self, db_session, user_id, confianzas):
        """Un estudio real: la urgencia la calcula el sistema desde el score."""
        from app.database import crud
        from app.services.routing_service import calculate_urgency

        estudio = crud.create_study(
            db_session, user_id=user_id, original_filename="serie.zip",
            total_images=len(confianzas),
            images_with_findings=sum(1 for c in confianzas if c >= 0.25),
            anatomical_region="muneca_pediatrica", model_version="v1r",
        )
        for i, conf in enumerate(confianzas):
            a = crud.create_analysis(
                db_session, user_id=user_id, study_id=estudio.id,
                original_image_path=f"s{i}_original.png",
                annotated_image_path=f"s{i}_annotated.png",
                report_text=f"Imagen {i + 1}",
                max_detection_confidence=conf, is_abnormal=conf >= 0.25,
                inference_time_ms=10.0, anatomical_region="muneca_pediatrica",
                model_version="v1r", routing_method="manual",
                urgency=calculate_urgency(conf),
            )
            if conf > 0:
                crud.create_detection_boxes(db_session, a.id, [
                    {"x1": 1, "y1": 1, "x2": 9, "y2": 9, "confidence": conf},
                ])
        return estudio

    def test_abre_en_la_imagen_con_la_fractura_y_no_en_la_primera(
        self, auth_client, db_session, users
    ):
        """El caso del estudio #1: la fractura está en la tercera imagen."""
        e = self._estudio(db_session, users["principal"], [0.0, 0.02, 0.97])
        html = auth_client.get(f"/analysis/study/{e.id}").text

        assert _panel_abierto(html) == 3
        assert _cuadro_marcado(html) == 3

    def test_la_franja_de_veredicto_visible_es_la_de_esa_imagen(
        self, auth_client, db_session, users
    ):
        e = self._estudio(db_session, users["principal"], [0.0, 0.02, 0.97])
        html = auth_client.get(f"/analysis/study/{e.id}").text

        visibles = [
            int(m.group(1))
            for m in re.finditer(r'data-strip-idx="(\d+)"(\s*)(hidden)?>', html)
            if not m.group(3)
        ]
        assert visibles == [3]

    def test_la_placa_y_las_cajas_son_las_de_esa_imagen(
        self, auth_client, db_session, users
    ):
        """Si el visor abre en la 3 pero carga la placa de la 1, es peor que
        antes: el veredicto diría una cosa y la imagen mostraría otra."""
        e = self._estudio(db_session, users["principal"], [0.0, 0.02, 0.97])
        html = auth_client.get(f"/analysis/study/{e.id}").text

        assert 'src="/analysis/imagen/s2_annotated.png"' in html
        assert 'data-stage-base aria-hidden="true" alt=""\n           src="/analysis/imagen/s2_original.png"' in html \
            or 'src="/analysis/imagen/s2_original.png"' in html
        # El host de hallazgos publica las cajas de la imagen abierta.
        host = re.search(r'data-find-host[\s\S]*?data-boxes="([^"]*)"', html).group(1)
        assert "0.97" in host.replace("&#34;", '"')

    def test_sin_hallazgos_en_ninguna_abre_en_la_primera(
        self, auth_client, db_session, users
    ):
        e = self._estudio(db_session, users["principal"], [0.0, 0.0, 0.0])
        html = auth_client.get(f"/analysis/study/{e.id}").text
        assert _panel_abierto(html) == 1
        assert _cuadro_marcado(html) == 1

    def test_fuera_del_dominio_abre_en_la_primera(
        self, auth_client, db_session, users
    ):
        """Con un modelo retirado la plantilla neutraliza todos los veredictos:
        no hay urgencia que ordenar, así que se abre en la primera."""
        from app.database.models import Analysis, Study

        e = self._estudio(db_session, users["principal"], [0.0, 0.02, 0.97])
        db_session.query(Study).filter(Study.id == e.id).update(
            {"anatomical_region": "extremidad_inferior"}
        )
        db_session.query(Analysis).filter(Analysis.study_id == e.id).update(
            {"anatomical_region": "extremidad_inferior"}
        )
        db_session.commit()

        html = auth_client.get(f"/analysis/study/{e.id}").text
        assert _panel_abierto(html) == 1
        assert _cuadro_marcado(html) == 1

    def test_cada_panel_dice_de_qué_imagen_habla(
        self, auth_client, db_session, users
    ):
        """El veredicto del panel es de UNA imagen. Sin decirlo, se lee como
        el del estudio entero."""
        e = self._estudio(db_session, users["principal"], [0.0, 0.02, 0.97])
        html = auth_client.get(f"/analysis/study/{e.id}").text
        for i in (1, 2, 3):
            assert f"Imagen {i} de 3" in html

    def test_la_cabecera_lleva_el_veredicto_del_estudio(
        self, auth_client, db_session, users
    ):
        """El veredicto del ESTUDIO es el de su imagen más urgente, y va en la
        barra del estudio: es lo que decide el triage."""
        e = self._estudio(db_session, users["principal"], [0.0, 0.02, 0.97])
        html = auth_client.get(f"/analysis/study/{e.id}").text
        barra = re.search(r'<div class="study-bar">[\s\S]*?</div>\s*</div>', html).group(0)
        assert "Prioritario" in barra

    def test_el_veredicto_del_estudio_sigue_a_la_peor_imagen(
        self, auth_client, db_session, users
    ):
        e = self._estudio(db_session, users["principal"], [0.0, 0.30, 0.0])
        html = auth_client.get(f"/analysis/study/{e.id}").text
        barra = re.search(r'<div class="study-bar">[\s\S]*?</div>\s*</div>', html).group(0)
        assert "Revisar" in barra
        assert _panel_abierto(html) == 2


# ─────────────────────────────────────────────
# Helpers de macros
# ─────────────────────────────────────────────

def _macros():
    """Los macros de `_macros.html`, invocables desde Python."""
    from app.plantillas import crear_templates

    return crear_templates().env.get_template("_macros.html").module


def _var(html: str, nombre: str) -> float:
    """El valor de una custom property CSS del marcado, como número."""
    m = re.search(rf"--{nombre}:\s*([\d.]+)%", html)
    assert m, f"No se encontró --{nombre} en:\n{html}"
    return float(m.group(1))


# ─────────────────────────────────────────────────────────────────────────────
# MEDIA-05 — El recorte del IC en el eje truncado
# ─────────────────────────────────────────────────────────────────────────────

class TestRecorteDelIntervaloDeConfianza:
    """`metric_row` dibuja sobre un eje truncado a [piso, 1].

    Un valor por debajo del piso queda FUERA DE ESCALA POR LA IZQUIERDA. El
    punto (`pos`) y el extremo inferior del intervalo (`lo`) se recortaban
    bien, a 0. El extremo superior (`hi`) se recortaba a **100**, o sea al
    borde OPUESTO: con un intervalo entero por debajo del piso, el segmento se
    dibujaba cruzando el eje completo mientras el punto quedaba clavado en el
    cero. El gráfico afirmaba que el límite superior llegaba al 100 %.

    La condición es `ic[1] > piso`: pregunta si el extremo superior está por
    encima del PISO, no si se pasa del techo. Cuando es falsa, el valor cayó
    por la izquierda igual que los otros dos, y el recorte correcto es 0.
    """

    def test_un_intervalo_normal_se_ubica_donde_corresponde(self):
        """Control: con la escala 0,80–1,00 y el IC de sensibilidad medido."""
        html = _macros().metric_row("Sensibilidad", 0.949, (0.937, 0.958), piso=0.80)
        assert _var(html, "lo") == pytest.approx(68.50, abs=0.01)
        assert _var(html, "hi") == pytest.approx(79.00, abs=0.01)
        assert _var(html, "pos") == pytest.approx(74.50, abs=0.01)

    def test_un_intervalo_entero_bajo_el_piso_se_recorta_a_la_izquierda(self):
        """El caso que delata el signo invertido."""
        html = _macros().metric_row("Métrica", 0.50, (0.40, 0.60), piso=0.80)
        assert _var(html, "pos") == 0.0
        assert _var(html, "lo") == 0.0
        assert _var(html, "hi") == 0.0, (
            "El extremo superior se está recortando al borde derecho: el "
            "gráfico dibuja un intervalo que cruza todo el eje"
        )

    def test_un_intervalo_a_caballo_del_piso_arranca_en_el_borde(self):
        html = _macros().metric_row("Métrica", 0.85, (0.75, 0.90), piso=0.80)
        assert _var(html, "lo") == 0.0
        assert _var(html, "hi") == pytest.approx(50.00, abs=0.01)

    @pytest.mark.parametrize("v,ic,piso", [
        (0.949, (0.937, 0.958), 0.80),
        (0.50, (0.40, 0.60), 0.80),
        (0.85, (0.75, 0.90), 0.80),
        (0.90, (0.80, 1.00), 0.80),
        (0.99, (0.98, 1.00), 0.96),
    ])
    def test_el_segmento_nunca_sale_al_reves(self, v, ic, piso):
        """Invariante: el extremo superior nunca queda a la izquierda del
        inferior, y ninguno se sale del eje."""
        html = _macros().metric_row("Métrica", v, ic, piso=piso)
        lo, hi = _var(html, "lo"), _var(html, "hi")
        assert 0.0 <= lo <= hi <= 100.0


# ─────────────────────────────────────────────────────────────────────────────
# El "13" escrito a mano
# ─────────────────────────────────────────────────────────────────────────────

class TestTasaDeFalloDerivada:
    """El visor decía «alrededor de 13 de cada 100» con el número escrito.

    Al lado, en el mismo bloque, mostraba el recall calculado. Si mañana
    cambia el recall, el visor sigue diciendo 13 y el dashboard —que sí lo
    calcula— dice otra cosa. Dos pantallas del mismo sistema afirmando cosas
    distintas sobre lo que se le escapa al modelo.
    """

    def test_el_visor_deriva_la_tasa_del_recall_que_recibe(self):
        html = _macros().alcance_clinico(0.70, "Muñeca")
        assert "30 de cada 100" in html
        assert "13 de cada 100" not in html

    def test_con_el_recall_real_da_el_mismo_numero_de_siempre(self):
        """El arreglo no cambia lo que se ve hoy: lo ata a su fuente.

        El «13» esperado también se deriva: con v1 (recall 0,8662) daba 13 y
        con v2 (0,8634) da 14. Escrito a mano, este test volvía a ser el
        rincón que afirma la métrica vieja — que es exactamente el bug que
        la macro arregló.
        """
        from config.settings import DEFAULT_REGION, MODEL_METADATA

        recall = MODEL_METADATA[DEFAULT_REGION]["recall"]
        esperado = round((1 - recall) * 100)
        html = _macros().alcance_clinico(recall, "Muñeca")
        assert f"{esperado} de cada 100" in html
        assert ("%.3f" % recall).replace(".", ",") in html

    def test_el_visor_y_el_dashboard_no_pueden_discrepar(self):
        """La misma pregunta contestada por los dos bloques de alcance."""
        from config.settings import DEFAULT_REGION, MODEL_METADATA

        meta = MODEL_METADATA[DEFAULT_REGION]
        visor = _macros().alcance_clinico(meta["recall"], meta["label"])
        panel = _macros().alcance_metricas(meta, meta["label"])
        esperado = f"{round((1 - meta['recall']) * 100)} de cada 100"
        assert esperado in visor
        assert esperado in panel

    def test_la_grilla_del_dashboard_cuenta_lo_mismo(self):
        """`waffle_misses` marca una casilla por fractura no detectada."""
        from config.settings import DEFAULT_REGION, MODEL_METADATA

        recall = MODEL_METADATA[DEFAULT_REGION]["recall"]
        html = _macros().waffle_misses(recall)
        assert html.count("wcell is-miss") == round((1 - recall) * 100)


# ─────────────────────────────────────────────────────────────────────────────
# M2 — El historial decía "Todos 50" con 121 análisis guardados
# ─────────────────────────────────────────────────────────────────────────────

class TestHistorialCompleto:
    """El chip decía «Todos 50» mientras el dashboard contaba 121.

    El chip no contaba los análisis del usuario: contaba las FILAS que la
    consulta había traído, con un tope de 50 escrito a mano. Y los otros dos
    chips —«Con hallazgos» y «Sin hallazgos»— se calculaban sobre esas mismas
    50 filas, así que también mentían.

    Se elige mostrar el historial completo en vez de maquillar el chip: la
    tabla ya pagina de a 15 del lado del cliente, así que no hay nada que
    recortar. Queda un tope alto como red de seguridad y, si alguna vez se
    alcanza, la pantalla lo DICE con el total real en vez de llamarlo «Todos».
    """

    def _n_analisis(self, db_session, user_id, n):
        from tests.test_api import crear_analisis

        for i in range(n):
            crear_analisis(db_session, user_id, is_abnormal=(i % 2 == 0))

    def _filas(self, html):
        return len(re.findall(r'<tr data-abn="', html))

    def test_el_chip_cuenta_todos_los_analisis_del_usuario(
        self, auth_client, db_session, users
    ):
        self._n_analisis(db_session, users["principal"], 60)
        html = auth_client.get("/analysis/history").text

        assert 'data-f="all" aria-pressed="true">Todos <span class="count">60</span>' in html
        assert self._filas(html) == 60

    def test_los_chips_de_clasificacion_cuentan_sobre_el_total(
        self, auth_client, db_session, users
    ):
        self._n_analisis(db_session, users["principal"], 60)
        html = auth_client.get("/analysis/history").text
        assert '>Con hallazgos <span class="count">30</span>' in html
        assert '>Sin hallazgos <span class="count">30</span>' in html

    def test_no_promete_completitud_cuando_hay_recorte(
        self, auth_client, db_session, users, monkeypatch
    ):
        """Si se alcanza el tope, el chip deja de decir «Todos» y la pantalla
        informa el total real. Nunca un número que no es el que dice ser."""
        from app.routes import analysis_routes

        monkeypatch.setattr(analysis_routes, "HISTORIAL_MAX_FILAS", 3)
        self._n_analisis(db_session, users["principal"], 5)
        html = auth_client.get("/analysis/history").text

        assert self._filas(html) == 3
        assert 'data-f="all" aria-pressed="true">Todos' not in html
        assert "3" in html and "5" in html
        assert "más recientes" in html
        assert "de 5" in html

    def test_sin_recorte_no_aparece_el_aviso(self, auth_client, db_session, users):
        self._n_analisis(db_session, users["principal"], 4)
        html = auth_client.get("/analysis/history").text
        assert "más recientes" not in html

    def test_el_historial_sigue_sin_mezclar_usuarios(
        self, auth_client, db_session, users
    ):
        """Levantar el tope no puede aflojar el aislamiento por usuario."""
        self._n_analisis(db_session, users["principal"], 4)
        self._n_analisis(db_session, users["otro"], 7)
        html = auth_client.get("/analysis/history").text
        assert self._filas(html) == 4
        assert 'data-f="all" aria-pressed="true">Todos <span class="count">4</span>' in html


# ─────────────────────────────────────────────────────────────────────────────
# N+1 — Una consulta por fila
# ─────────────────────────────────────────────────────────────────────────────

class ContadorDeConsultas:
    """Cuenta los SELECT que ejecuta un engine mientras dura el bloque."""

    def __init__(self, engine):
        self.engine = engine
        self.sentencias = []

    def __enter__(self):
        from sqlalchemy import event

        def antes(conn, cursor, sentencia, *resto):
            if sentencia.lstrip().upper().startswith("SELECT"):
                self.sentencias.append(sentencia)

        self._antes = antes
        event.listen(self.engine, "before_cursor_execute", antes)
        return self

    def __exit__(self, *exc):
        from sqlalchemy import event

        event.remove(self.engine, "before_cursor_execute", self._antes)
        return False

    def __len__(self):
        return len(self.sentencias)


class TestSinConsultasPorFila:
    """El costo de estas pantallas crecía con la cantidad de registros.

    `findings_above_abnormal` y `len(a.detection_boxes)` disparan la carga
    perezosa de las cajas: una consulta por análisis. Con 121 análisis, el
    historial hacía 121 consultas de más — y el export global del admin, una
    por cada uno de los 600 del sistema.

    El test no fija un número de consultas: comprueba que el número NO CRECE
    con la cantidad de filas, que es la definición del problema.
    """

    def _con_cajas(self, db_session, user_id, n):
        from app.database import crud
        from tests.test_api import crear_analisis

        for i in range(n):
            a = crear_analisis(db_session, user_id)
            crud.create_detection_boxes(db_session, a.id, [
                {"x1": 1, "y1": 1, "x2": 9, "y2": 9, "confidence": 0.9},
                {"x1": 2, "y1": 2, "x2": 8, "y2": 8, "confidence": 0.1},
            ])

    def _consultas(self, engine, client, ruta, db_session, users, n):
        self._con_cajas(db_session, users["principal"], n)
        with ContadorDeConsultas(engine) as contador:
            assert client.get(ruta).status_code == 200
        return len(contador)

    @pytest.mark.parametrize("ruta", [
        "/analysis/history",
        "/dashboard/export/analisis.csv",
    ])
    def test_el_costo_no_crece_con_la_cantidad_de_analisis(
        self, engine, auth_client, db_session, users, ruta
    ):
        pocas = self._consultas(engine, auth_client, ruta, db_session, users, 3)
        muchas = self._consultas(engine, auth_client, ruta, db_session, users, 12)
        assert muchas == pocas, (
            f"{ruta}: {pocas} consultas con 3 análisis y {muchas} con 15. "
            "El costo crece por fila."
        )

    def test_el_estudio_no_consulta_una_vez_por_imagen(
        self, engine, auth_client, db_session, users
    ):
        from app.database import crud

        def estudio_de(n):
            e = crud.create_study(
                db_session, user_id=users["principal"], original_filename="s.zip",
                total_images=n, images_with_findings=n,
                anatomical_region="muneca_pediatrica", model_version="v1r",
            )
            for i in range(n):
                a = crud.create_analysis(
                    db_session, user_id=users["principal"], study_id=e.id,
                    original_image_path=f"x{i}_original.png",
                    annotated_image_path=f"x{i}_annotated.png",
                    report_text="", max_detection_confidence=0.9, is_abnormal=True,
                    inference_time_ms=1.0, anatomical_region="muneca_pediatrica",
                    model_version="v1r", routing_method="manual", urgency="HIGH",
                )
                crud.create_detection_boxes(db_session, a.id, [
                    {"x1": 1, "y1": 1, "x2": 9, "y2": 9, "confidence": 0.9},
                ])
            return e

        chico, grande = estudio_de(2), estudio_de(9)
        with ContadorDeConsultas(engine) as c1:
            auth_client.get(f"/analysis/study/{chico.id}")
        with ContadorDeConsultas(engine) as c2:
            auth_client.get(f"/analysis/study/{grande.id}")
        assert len(c2) == len(c1)

    def test_el_export_global_del_admin_tampoco(
        self, engine, users, client, db_session
    ):
        from tests.test_api import TestAdminYExportacion

        c = TestAdminYExportacion()._login_admin(engine, users)
        self._con_cajas(db_session, users["principal"], 3)
        with ContadorDeConsultas(engine) as c1:
            assert c.get("/admin/export/analisis.csv").status_code == 200
        self._con_cajas(db_session, users["otro"], 12)
        with ContadorDeConsultas(engine) as c2:
            assert c.get("/admin/export/analisis.csv").status_code == 200
        assert len(c2) == len(c1)


# ─────────────────────────────────────────────────────────────────────────────
# Datos inyectados en <script>
# ─────────────────────────────────────────────────────────────────────────────

class TestDatosHaciaJavaScript:
    """`{{ x|safe }}` sobre `json.dumps` dentro de un `<script>`.

    Hoy no es explotable: las etiquetas de los tres gráficos son fechas,
    rótulos fijos y bordes de histograma — ninguna llega desde el usuario. Es
    una corrección de construcción, no un agujero abierto: `|safe` desactiva
    todo escapado, así que el día que una etiqueta traiga texto de la base, el
    cierre de etiqueta se lo lleva puesto.

    `|tojson` de Jinja escapa `<`, `>`, `&` y la comilla simple para contexto
    de script, que es exactamente lo que hace falta acá.
    """

    def test_una_etiqueta_hostil_no_puede_cerrar_el_script(
        self, auth_client, db_session, users, monkeypatch
    ):
        from app.routes import dashboard_routes
        from tests.test_api import crear_analisis

        crear_analisis(db_session, users["principal"])
        monkeypatch.setattr(
            dashboard_routes, "analyses_per_day",
            lambda *a, **k: {"labels": ["</script><script>alert(1)</script>"], "values": [1]},
        )
        html = auth_client.get("/dashboard/").text
        assert "</script><script>alert(1)" not in html
        assert "alert(1)" in html          # el dato llega, escapado
        assert "\\u003c" in html or "\\u003C" in html

    def test_los_graficos_siguen_recibiendo_json_valido(
        self, auth_client, db_session, users
    ):
        import json as _json

        from tests.test_api import crear_analisis

        crear_analisis(db_session, users["principal"])
        html = auth_client.get("/dashboard/").text
        m = re.search(r"var etiquetas = (\[.*?\]);", html)
        assert m, "El gráfico de 30 días no recibió sus etiquetas"
        assert len(_json.loads(m.group(1))) == 30
