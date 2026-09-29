"""
test_visor_js.py — El visor, ejercitado en un navegador de verdad.

`viewer.js` es lógica de estado: qué imagen está abierta, qué hallazgo está
fijado, qué dice cada botón sobre sí mismo. Eso no se puede probar leyendo el
archivo, y los dos bugs de esta ronda (ALTA-08 y ALTA-09) sólo aparecen
después de CAMBIAR de imagen — exactamente el camino que nadie prueba a mano.

La página que se carga es la REAL: se renderiza `study_results.html` por la
ruta de siempre y se le sirve el `viewer.js` del repo. No hay servidor: las
peticiones se interceptan y se responden desde disco, así que el test corre
igual que el resto de la suite.

Si Chromium no está disponible, los tests se saltan en vez de fallar.
"""

import io

import pytest

pytest.importorskip("playwright", reason="playwright no está instalado")


PAGINA = "http://visor.test/analysis/study/1"


def _png(valor: int = 60, ancho: int = 64, alto: int = 64) -> bytes:
    """Una PNG con dimensiones reales: el visor no arma los vectores hasta que
    `naturalWidth` es distinto de cero. Por defecto es chiquita; el test de
    geometría pide una del tamaño de una placa real, porque el bug de las
    cajas corridas sólo aparece cuando la imagen es MÁS ANCHA que el panel."""
    import numpy as np
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.full((alto, ancho, 3), valor, dtype=np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="session")
def navegador():
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            yield b
            b.close()
    except Exception as exc:  # pragma: no cover - depende del entorno
        pytest.skip(f"no hay Chromium utilizable: {exc}")


def _estudio_de_dos_imagenes(db_session, user_id, confianzas=(0.9, 0.8)):
    """Un estudio con dos imágenes, cada una con sus cajas.

    Las dos tienen hallazgos para que el panel de las dos traiga filas
    `[data-find]`: el bug del pin necesita volver a una imagen ya visitada.
    """
    from app.database import crud

    estudio = crud.create_study(
        db_session, user_id=user_id, original_filename="estudio.zip",
        total_images=len(confianzas), images_with_findings=len(confianzas),
        anatomical_region="muneca_pediatrica", model_version="yolov8m_v1",
    )
    for i, conf in enumerate(confianzas):
        a = crud.create_analysis(
            db_session, user_id=user_id, study_id=estudio.id,
            original_image_path=f"est{i}_original.png",
            annotated_image_path=f"est{i}_annotated.png",
            report_text=f"Imagen {i + 1}",
            max_detection_confidence=conf, is_abnormal=True,
            inference_time_ms=10.0, anatomical_region="muneca_pediatrica",
            model_version="yolov8m_v1", routing_method="manual", urgency="HIGH",
        )
        crud.create_detection_boxes(db_session, a.id, [
            {"x1": 5, "y1": 5, "x2": 25, "y2": 25, "confidence": conf},
            {"x1": 30, "y1": 30, "x2": 45, "y2": 45, "confidence": conf - 0.1},
        ])
    return estudio


def _abrir_visor(navegador, auth_client, db_session, users, imagen: bytes):
    """Abre el visor de un estudio de dos imágenes, con el JS y el CSS reales
    corriendo, y sirviendo `imagen` como cualquiera de las radiografías."""
    from pathlib import Path

    estudio = _estudio_de_dos_imagenes(db_session, users["principal"])
    html = auth_client.get(f"/analysis/study/{estudio.id}").text
    assert "data-filmstrip" in html, "La ruta no devolvió el visor"

    raiz = Path(__file__).resolve().parent.parent
    js = (raiz / "app/static/js/viewer.js").read_text(encoding="utf-8")
    css = (raiz / "app/static/css/style.css").read_text(encoding="utf-8")

    contexto = navegador.new_context(viewport={"width": 1400, "height": 900})
    page = contexto.new_page()

    def responder(route, request):
        url = request.url
        if "/analysis/imagen/" in url:
            route.fulfill(status=200, content_type="image/png", body=imagen)
        elif url.endswith(".js") or "/js/" in url:
            route.fulfill(status=200, content_type="application/javascript", body=js)
        elif url.endswith(".css") or "/css/" in url:
            route.fulfill(status=200, content_type="text/css", body=css)
        elif "/analysis/study/" in url:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        else:
            route.fulfill(status=204, body="")

    page.route("**/*", responder)
    page.goto(PAGINA, wait_until="load")
    # `armarVectores` corre en el load de la imagen: se espera a que el visor
    # declare que ya dibujó los vectores, no a un tiempo arbitrario.
    page.wait_for_function("window.__viewer && window.__viewer.vector === true")
    return page, contexto


@pytest.fixture
def visor(navegador, auth_client, db_session, users):
    """El visor con una placa chiquita: alcanza para probar el estado."""
    page, contexto = _abrir_visor(navegador, auth_client, db_session, users, _png())
    yield page
    contexto.close()


@pytest.fixture
def visor_placa_grande(navegador, auth_client, db_session, users):
    """El visor con una placa del tamaño de una radiografía real (1568×1732,
    las dimensiones del caso que destapó el bug), más ancha que el panel."""
    imagen = _png(ancho=1568, alto=1732)
    page, contexto = _abrir_visor(navegador, auth_client, db_session, users, imagen)
    yield page
    contexto.close()


class TestLasCajasCaenDondeElModeloLasPuso:
    """Auditoría 2026-09-01, hallazgo C1 — las cajas se dibujaban corridas.

    La cadena modelo → base → JSON → DOM estaba exacta al píxel; lo que
    fallaba era el CSS: la regla global `img, svg, canvas { max-width: 100% }`
    exceptuaba a la placa pero no a la capa SVG de las cajas. El SVG, con
    `width="1568"`, se achicaba al ancho del panel y `xMidYMid meet`
    comprimía y centraba su contenido. Con una placa de 64 px el bug no se
    ve (64 px caben en cualquier panel): por eso este test usa una grande.
    """

    GEOMETRIA = """
    () => {
      const img = document.querySelector('[data-stage-img]');
      const svg = document.querySelector('[data-boxlayer]');
      const rect = svg.querySelector('rect');
      const r = (e) => { const b = e.getBoundingClientRect();
                         return {x: b.left, y: b.top, w: b.width, h: b.height}; };
      return {img: r(img), svg: r(svg), caja: r(rect),
              natural: {w: img.naturalWidth, h: img.naturalHeight}};
    }
    """

    def test_la_capa_de_cajas_mide_exactamente_lo_que_mide_la_placa(self, visor_placa_grande):
        g = visor_placa_grande.evaluate(self.GEOMETRIA)
        assert g["natural"] == {"w": 1568, "h": 1732}, "La placa grande no se sirvió"
        for eje in ("x", "y", "w", "h"):
            assert abs(g["svg"][eje] - g["img"][eje]) < 1.0, (
                f"La capa SVG y la placa difieren en '{eje}': "
                f"svg={g['svg']} img={g['img']}. Si difieren, las cajas se dibujan "
                "en una geometría distinta de la de la imagen."
            )

    def test_la_primera_caja_cae_en_sus_coordenadas_de_pixel(self, visor_placa_grande):
        """La caja guardada es (5, 5)-(25, 25) en píxeles de la imagen. En
        pantalla tiene que empezar a 5·escala del borde de la placa y medir
        20·escala, con la MISMA escala que la placa."""
        g = visor_placa_grande.evaluate(self.GEOMETRIA)
        escala = g["img"]["w"] / g["natural"]["w"]
        esperado_x = g["img"]["x"] + 5 * escala
        esperado_y = g["img"]["y"] + 5 * escala
        esperado_lado = 20 * escala
        assert abs(g["caja"]["x"] - esperado_x) < 1.0, (g["caja"], esperado_x)
        assert abs(g["caja"]["y"] - esperado_y) < 1.0, (g["caja"], esperado_y)
        assert abs(g["caja"]["w"] - esperado_lado) < 1.0, (g["caja"], esperado_lado)
        assert abs(g["caja"]["h"] - esperado_lado) < 1.0, (g["caja"], esperado_lado)


def _cuadro(page, idx):
    return page.locator(f'.frame[data-idx="{idx}"]')


def _filas_del_panel_abierto(page):
    return page.locator("[data-panel-idx]:not([hidden]) [data-find]")


class TestPinAlCambiarDeImagen:
    """ALTA-08 — el pin se rompía en estudios multi-imagen.

    `cablearPanel()` corre en cada `armarVectores()`, o sea en cada cambio de
    imagen, y volvía a colgar listeners sobre las MISMAS filas. Al volver a
    una imagen ya visitada, cada fila tenía dos listeners de click: el primero
    fijaba el hallazgo y el segundo, viendo que `i === self.pinned`, lo
    soltaba. El pin quedaba muerto.
    """

    def test_fija_al_primer_intento_en_la_imagen_inicial(self, visor):
        """Control: sin cambiar de imagen el pin siempre anduvo."""
        fila = _filas_del_panel_abierto(visor).first
        fila.click()
        assert fila.get_attribute("aria-pressed") == "true"
        assert visor.evaluate("window.__viewer.pinned") == 0

    def test_sigue_fijando_despues_de_ir_y_volver(self, visor):
        _cuadro(visor, 2).click()
        visor.wait_for_function("window.__viewer.vector === true")
        _cuadro(visor, 1).click()
        visor.wait_for_function("window.__viewer.vector === true")

        fila = _filas_del_panel_abierto(visor).first
        fila.click()

        assert visor.evaluate("window.__viewer.pinned") == 0, (
            "El click se aplicó dos veces: hay listeners duplicados"
        )
        assert fila.get_attribute("aria-pressed") == "true"

    def test_un_segundo_click_sigue_soltando_el_pin(self, visor):
        """El arreglo no puede romper el toggle deliberado."""
        _cuadro(visor, 2).click()
        visor.wait_for_function("window.__viewer.vector === true")
        _cuadro(visor, 1).click()
        visor.wait_for_function("window.__viewer.vector === true")

        fila = _filas_del_panel_abierto(visor).first
        fila.click()
        fila.click()
        assert visor.evaluate("window.__viewer.pinned") == -1
        assert fila.get_attribute("aria-pressed") == "false"

    def test_no_se_acumulan_listeners_al_recorrer_el_estudio(self, visor):
        """Cinco vueltas por las dos imágenes y el pin sigue siendo uno."""
        for _ in range(5):
            for idx in (2, 1):
                _cuadro(visor, idx).click()
                visor.wait_for_function("window.__viewer.vector === true")

        fila = _filas_del_panel_abierto(visor).first
        fila.click()
        assert visor.evaluate("window.__viewer.pinned") == 0


class TestEstadoDeLosBotonesAlCambiarDeImagen:
    """ALTA-09 — `aria-pressed` desincronizado del estado real en `setSource`."""

    def test_el_hallazgo_fijado_deja_de_declararse_fijado(self, visor):
        """`setSource` pone `pinned = -1` pero dejaba la fila del panel que se
        abandona con `aria-pressed="true"`: el lector de pantalla anunciaba un
        hallazgo fijado que el visor ya no tenía."""
        _filas_del_panel_abierto(visor).first.click()
        assert visor.locator('[data-find][aria-pressed="true"]').count() == 1

        _cuadro(visor, 2).click()
        visor.wait_for_function("window.__viewer.vector === true")

        assert visor.evaluate("window.__viewer.pinned") == -1
        assert visor.locator('[data-find][aria-pressed="true"]').count() == 0, (
            "Quedó una fila declarándose fijada en un panel que ya no está abierto"
        )

    def test_al_volver_la_fila_no_arrastra_el_estado_viejo(self, visor):
        _filas_del_panel_abierto(visor).first.click()
        _cuadro(visor, 2).click()
        visor.wait_for_function("window.__viewer.vector === true")
        _cuadro(visor, 1).click()
        visor.wait_for_function("window.__viewer.vector === true")

        fila = _filas_del_panel_abierto(visor).first
        assert fila.get_attribute("aria-pressed") == "false"

    def test_el_boton_de_marcas_no_queda_diciendo_lo_contrario(self, visor):
        """`setSource` reponía `aria-pressed` pero no el `title`, así que el
        botón quedaba sin apretar y ofreciendo «Mostrar las marcas»."""
        boton = visor.locator('[data-act="original"]')
        boton.click()
        assert boton.get_attribute("aria-pressed") == "true"
        assert "Mostrar" in boton.get_attribute("title")

        _cuadro(visor, 2).click()
        visor.wait_for_function("window.__viewer.vector === true")

        assert boton.get_attribute("aria-pressed") == "false"
        assert "Ocultar" in boton.get_attribute("title"), (
            "El botón dice que va a mostrar las marcas y las marcas ya están puestas"
        )
