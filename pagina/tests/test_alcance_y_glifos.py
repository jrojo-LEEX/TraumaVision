"""
test_alcance_y_glifos.py — Ronda 2026-08-25 (segunda tanda).

Dos reglas, las dos sobre lo que el sistema AFIRMA:

  1. Ningún número clínico puede estar escrito a mano. La página de alcance
     legal decía «0,866» y «13 de cada 100» en prosa, y el informe del
     detector decía «94,9 %». Con el reentrenamiento esos tres pasan a ser
     mentira publicada. Todos salen de MODEL_METADATA.

  2. Ningún glifo puede llegar al PDF si la fuente base del PDF no lo tiene.
     Helvetica —la fuente que usa reportlab sin registrar ninguna TTF— sólo
     dibuja WinAnsiEncoding. Los caracteres de dibujo de caja («─», «═»)
     salían como cuadrados negros, y una fila de 41 de ellos además rompía
     el maquetado: reportlab no puede cortar esa «palabra» y desparramaba el
     informe en dos páginas de basura.

La segunda tiene una vuelta que la primera no: 407 de los 600 análisis de la
base ya tienen el «─» GUARDADO en `report_text`. Arreglar sólo el código
fuente deja rotos todos los informes viejos. Por eso el saneado vive en el
generador del PDF, que es el único lugar por donde pasan los dos.
"""

import re
import unicodedata

import pytest

from tests.test_correcciones import imagen_pil, pdf_de_prueba, texto_del_pdf


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _macros():
    from app.plantillas import crear_templates

    return crear_templates().env.get_template("_macros.html").module


def _fuente(nombre: str) -> str:
    """El texto de una plantilla, SIN los comentarios de Jinja.

    Un `{# ... #}` no se renderiza: puede citar el número viejo sin mentirle
    a nadie. Lo que se busca es prosa que SÍ llegue a la pantalla.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    ruta = raiz / "app" / "templates" / nombre
    texto = ruta.read_text(encoding="utf-8")
    return re.sub(r"\{#.*?#\}", " ", texto, flags=re.S)


def _detector_stub(region="muneca_pediatrica"):
    """Un `FractureDetector` sin modelo cargado.

    `generate_report_text` no usa los pesos: sólo los umbrales y la región.
    Instanciar de verdad cargaría 52 MB de checkpoint en cada test.
    """
    from config.settings import ABNORMAL_THRESHOLD, CONFIDENCE_THRESHOLD
    from src.detection.predict import FractureDetector

    d = object.__new__(FractureDetector)
    d.confidence_threshold = CONFIDENCE_THRESHOLD
    d.abnormal_threshold = ABNORMAL_THRESHOLD
    d.region = region
    d.model_version = "yolov8m_v1"
    return d


def _resultado(conf=0.80):
    import numpy as np

    from src.detection.predict import DetectionBox, PredictionResult

    return PredictionResult(
        is_abnormal=True,
        max_detection_confidence=conf,
        boxes=[DetectionBox(10, 10, 40, 40, conf)],
        annotated_image=np.zeros((100, 100, 3), dtype=np.uint8),
        inference_time_ms=123.0,
        image_size=(100, 100),
        model_version="yolov8m_v1",
        clahe_applied=True,
    )


def _no_winansi(texto: str) -> set:
    """Caracteres que Helvetica no puede dibujar."""
    fuera = set()
    for ch in texto:
        try:
            ch.encode("cp1252")
        except UnicodeEncodeError:
            fuera.add(ch)
    return fuera


# ─────────────────────────────────────────────────────────────────────────────
# La página de alcance legal citaba métricas escritas a mano
# ─────────────────────────────────────────────────────────────────────────────

class TestNumerosDeLaPaginaDeAlcance:
    """`/aviso-legal` es la página que define qué promete el sistema.

    Tenía «0,866», «13 de cada 100», «0,017» y «0,190» escritos en la prosa.
    El resto de la app deriva esos cuatro de MODEL_METADATA; esta página se
    había quedado congelada. Al reentrenar, la página de alcance sería el
    único lugar del sistema que sigue afirmando el recall viejo.
    """

    def test_el_recall_sale_de_la_metadata(self, client, monkeypatch):
        from config.settings import DEFAULT_REGION, MODEL_METADATA

        monkeypatch.setitem(MODEL_METADATA[DEFAULT_REGION], "recall", 0.70)
        html = client.get("/aviso-legal").text
        assert "0,700" in html
        assert "30 de cada 100" in html
        assert "0,866" not in html
        assert "13 de cada 100" not in html

    def test_con_los_valores_reales_dice_lo_mismo_de_siempre(self, client):
        """El arreglo no cambia lo que se lee hoy: lo ata a su fuente."""
        from config.settings import DEFAULT_REGION, MODEL_METADATA

        meta = MODEL_METADATA[DEFAULT_REGION]
        html = client.get("/aviso-legal").text
        assert ("%.3f" % meta["recall"]).replace(".", ",") in html
        assert f"{round((1 - meta['recall']) * 100)} de cada 100" in html

    def test_la_pagina_no_deja_ningun_decimal_escrito_a_mano(self):
        """Guarda de regresión sobre la fuente, no sobre el render.

        Cualquier `0,xxx` o `N de cada 100` que aparezca literal en el HTML
        —fuera de los comentarios— es un número que el reentrenamiento va a
        dejar mintiendo.
        """
        texto = _fuente("legal.html")
        assert not re.findall(r"\b\d,\d{2,}\b", texto), "decimal literal en legal.html"
        assert not re.findall(r"\b\d+\s+de\s+cada\s+100\b", texto), (
            "tasa literal en legal.html"
        )

    def test_sin_metadata_la_pagina_no_inventa_ninguna_metrica(
        self, client, monkeypatch
    ):
        """Modelo retirado: se pierde el número, no se presta el del vecino.

        Es la misma regla que ya aplica `domain_disclaimer(None)` para el PDF
        (commit a619297). Una página que cita el recall del modelo vivo para
        un modelo que ya no está afirma algo que nadie midió.
        """
        from config.settings import DEFAULT_REGION, MODEL_METADATA

        monkeypatch.delitem(MODEL_METADATA, DEFAULT_REGION)
        r = client.get("/aviso-legal")
        assert r.status_code == 200
        assert "de cada 100" not in r.text
        assert "0,866" not in r.text
        assert "ECE" not in r.text


class TestNumerosDelBloqueDeAlcanceDelVisor:
    """El mismo bug, en el plegable que ve el médico sobre cada estudio.

    `alcance_clinico` ya derivaba el recall (commit a63d626) pero seguía con
    el ECE y el n de validación escritos. Es la pantalla que el tribunal mira
    al lado de la placa.
    """

    def test_los_macros_no_dejan_decimales_escritos_a_mano(self):
        texto = _fuente("_macros.html")
        assert "0,190" not in texto
        assert "0,017" not in texto
        assert "3119" not in texto


class TestSensibilidadDelInformeDelDetector:
    """El informe que va al PDF cerraba con «sensibilidad medida: 94,9 %».

    Escrito a mano dentro de `generate_report_text`. El PDF es el artefacto
    que sale del sistema: es exactamente donde un número viejo hace daño.
    """

    def test_la_sensibilidad_sale_de_la_metadata(self, monkeypatch):
        from config.settings import MODEL_METADATA

        monkeypatch.setitem(MODEL_METADATA["muneca_pediatrica"], "sensibilidad", 0.800)
        texto = _detector_stub().generate_report_text(_resultado())
        assert "80,0 %" in texto
        assert "94,9" not in texto

    def test_con_el_valor_real_dice_lo_de_siempre(self):
        from config.settings import MODEL_METADATA

        sens = MODEL_METADATA["muneca_pediatrica"]["sensibilidad"]
        texto = _detector_stub().generate_report_text(_resultado())
        assert ("%.1f" % (sens * 100)).replace(".", ",") in texto

    def test_fuera_del_dominio_no_cita_ninguna_sensibilidad(self):
        """Región sin metadata: el informe no se presta la del modelo vivo."""
        texto = _detector_stub(region="tobillo_inventado").generate_report_text(
            _resultado()
        )
        assert "sensibilidad medida" not in texto
        assert "94,9" not in texto
        assert "no descarta patología" in texto

    def test_el_codigo_no_lleva_el_numero_escrito(self):
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent
        fuente = (raiz / "src/detection/predict.py").read_text(encoding="utf-8")
        assert "94,9" not in fuente


# ─────────────────────────────────────────────────────────────────────────────
# M1 — Los cuadrados negros del PDF
# ─────────────────────────────────────────────────────────────────────────────

SEPARADOR_VIEJO = "─" * 41          # el que quedó guardado en 407 filas
BOX_DRAWING = re.compile("[\u2500-\u257F]")


class TestSaneadoDeGlifos:
    """`glifos_seguros` es el embudo: nada llega al PDF sin pasar por él."""

    def test_reemplaza_el_dibujo_de_caja_por_ascii(self):
        from src.reports.generator import glifos_seguros

        assert glifos_seguros("─" * 5) == "-" * 5
        assert glifos_seguros("═" * 5) == "=" * 5
        assert glifos_seguros("a│b║c") == "a|b|c"

    def test_reemplaza_flechas_y_marcas(self):
        from src.reports.generator import glifos_seguros

        assert glifos_seguros("(1,2)→(3,4)") == "(1,2)->(3,4)"
        assert "✓" not in glifos_seguros("✓ ok")
        assert "⚠" not in glifos_seguros("⚠ ojo")

    def test_no_toca_nada_que_helvetica_sepa_dibujar(self):
        """El castellano entero está en WinAnsi. No se folda ni un acento."""
        from src.reports.generator import glifos_seguros

        intacto = "Muñeca — Pediátrica (0–17 años) · 94,9 % ¿qué? ¡ojo! • ítem"
        assert glifos_seguros(intacto) == intacto

    def test_lo_que_sale_siempre_es_dibujable(self):
        from src.reports.generator import glifos_seguros

        raro = "─═║→✓✗⚠█⭐\U0001f9b4"
        assert _no_winansi(glifos_seguros(raro)) == set()


class TestElPDFNoTieneCuadradosNegros:
    """Verificación de punta a punta sobre el PDF real."""

    def test_el_separador_del_pie_es_ascii(self):
        """La regla sobre el pie del informe, dicha en positivo.

        Buscar la ausencia de «─» no alcanza: reportlab dibuja el cuadrado
        negro pero el extractor devuelve otra cosa, así que el texto extraído
        parece limpio. Lo que prueba el arreglo es que la línea ASCII ESTÉ.
        """
        texto = texto_del_pdf(pdf_de_prueba())
        assert "-" * 80 in texto.replace(" ", "")
        assert not BOX_DRAWING.search(texto)
        assert _no_winansi(texto) == set()

    def test_un_informe_viejo_guardado_sale_limpio(self):
        """Las 407 filas que ya tienen «─» guardado en `report_text`.

        Arreglar sólo el código fuente no las alcanza: el texto viene de la
        base. El saneado tiene que estar en el generador.
        """
        viejo = (
            "REPORTE — TraumaVision AI\n"
            f"{SEPARADOR_VIEJO}\n"
            "Evaluación: 2 HALLAZGO(S) DETECTADO(S).\n"
            "  • Región 1: confianza 78.7% — "
            "coordenadas (72,346)→(122,391)\n"
        )
        texto = texto_del_pdf(pdf_de_prueba(report_text=viejo))
        assert not BOX_DRAWING.search(texto)
        assert _no_winansi(texto) == set()
        assert "-" * 41 in texto.replace(" ", "")

    def test_el_separador_viejo_no_desparrama_el_informe(self):
        """41 cuadrados negros seguidos rompían el maquetado.

        Reportlab no puede cortar una «palabra» de 41 glifos anchos: el
        informe se iba a tres páginas repitiendo basura. Con ASCII entra en
        las mismas páginas que un informe sin separador.
        """
        import fitz

        def paginas(texto):
            doc = fitz.open(stream=pdf_de_prueba(report_text=texto), filetype="pdf")
            try:
                return doc.page_count
            finally:
                doc.close()

        assert paginas(f"Linea 1\n{SEPARADOR_VIEJO}\nLinea 2") == paginas(
            "Linea 1\nLinea 2"
        )

    def test_el_informe_del_detector_entra_al_pdf_sin_tofu(self):
        texto_informe = _detector_stub().generate_report_text(_resultado())
        assert not BOX_DRAWING.search(texto_informe), (
            "el informe todavía se escribe con dibujo de caja"
        )
        texto = texto_del_pdf(pdf_de_prueba(report_text=texto_informe))
        assert _no_winansi(texto) == set()

    def test_la_salvedad_de_dominio_es_dibujable(self):
        """El texto derivado de MODEL_METADATA también va al PDF."""
        from config.settings import LEGAL_DISCLAIMER, domain_disclaimer

        assert _no_winansi(domain_disclaimer()) == set()
        assert _no_winansi(domain_disclaimer(None)) == set()
        assert _no_winansi(LEGAL_DISCLAIMER) == set()


class TestFuentesSinDibujoDeCaja:
    """Guarda de regresión: el dibujo de caja no vuelve por la puerta de atrás."""

    @pytest.mark.parametrize(
        "ruta", ["src/reports/generator.py", "src/detection/predict.py"]
    )
    def test_no_hay_dibujo_de_caja_en_literales(self, ruta):
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent
        for n, linea in enumerate(
            (raiz / ruta).read_text(encoding="utf-8").splitlines(), 1
        ):
            pelado = linea.strip()
            if pelado.startswith("#"):
                continue
            m = BOX_DRAWING.search(linea)
            assert not m, (
                f"{ruta}:{n} usa "
                f"U+{ord(m.group()):04X} "
                f"{unicodedata.name(m.group(), '?')}"
            )
