"""
test_despliegue_y_concurrencia.py — Auditoría del 2026-09-01, arreglos aprobados.

Cubre los hallazgos de `docs/auditoria/2026-09-01/`:

  04_web H4  · `.env.example` apuntaba al checkpoint retirado (v1).
  04_web H3  · SMTP sin verificar el certificado y sin rastro del envío.
  04_web H5  · el panel admin publicaba porcentajes fuera de `_tasa` / `N_MINIMO`.
  04_web H6  · el cuerpo del upload se leía ANTES de comprobar la sesión.
  03_bd  H10 · `DEMO_MODE` publicaba la contraseña de la cuenta admin.
  04_web H7  · la inferencia corría en el bucle de eventos y congelaba la app.
  05_int H5  · sin warm-up, la primera inferencia del proceso pagaba 3,4x.
  04_web H13 · faltaba el enlace «Saltar al contenido» (WCAG 2.4.1).
  04_web H17 · `urgency_detail` podía imprimir «100 %» sin el techo de presentación.

Ningún número clínico está escrito a mano: los umbrales salen de `config` y
de `stats.N_MINIMO`, y el checkpoint esperado se lee del default de settings.
"""

import asyncio
import io
import logging
import re
import ssl
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tests.conftest import TEST_USER

RAIZ = Path(__file__).resolve().parent.parent


def _png(ancho: int = 64, alto: int = 64, valor: int = 0) -> bytes:
    img = Image.fromarray(np.full((alto, ancho, 3), valor, dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fuente_plantilla(nombre: str) -> str:
    """El texto de una plantilla sin los comentarios de Jinja: lo que se
    busca es lo que llega a la pantalla, no lo que se explica al lado."""
    texto = (RAIZ / "app" / "templates" / nombre).read_text(encoding="utf-8")
    return re.sub(r"\{#.*?#\}", " ", texto, flags=re.S)


# ─────────────────────────────────────────────────────────────────────────────
# H4 — .env.example
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvExample:

    def _valores(self):
        texto = (RAIZ / ".env.example").read_text(encoding="utf-8")
        return dict(re.findall(r"^([A-Z_]+)=(.*)$", texto, re.M)), texto

    def test_apunta_al_checkpoint_de_produccion(self):
        """El checkpoint de producción es el DEFAULT de settings. El ejemplo
        que el README manda copiar no puede apuntar a otro."""
        fuente = (RAIZ / "config" / "settings.py").read_text(encoding="utf-8")
        m = re.search(r'"YOLO_MODEL_MUNECA",\s*str\(BASE_DIR\.parent / "([^"]+)"\)', fuente)
        assert m, "no se encontró el default de YOLO_MODEL_MUNECA en settings.py"
        valores, _ = self._valores()
        assert valores["YOLO_MODEL_MUNECA"].strip() == "../" + m.group(1)

    def test_describe_el_modo_demo_sin_mentir(self):
        _, texto = self._valores()
        # La contraseña de las cuentas demo es real: el texto viejo decía lo
        # contrario.
        assert "sin contraseña real" not in texto
        bloque = texto[texto.index("# --- Modo demo"):texto.index("DEMO_MODE=")]
        assert "admin" in bloque.lower()
        assert "no se publica" in bloque.lower()


# ─────────────────────────────────────────────────────────────────────────────
# H3 — SMTP verificado y con registro
# ─────────────────────────────────────────────────────────────────────────────

class _SMTPFalso:
    """Registra cómo lo llamaron; no abre ningún socket."""

    instancias: list = []
    falla: Exception | None = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.contexto = "sin-starttls"
        self.enviado = None
        _SMTPFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.contexto = context

    def login(self, usuario, clave):
        if _SMTPFalso.falla is not None:
            raise _SMTPFalso.falla

    def send_message(self, msg):
        self.enviado = msg


@pytest.fixture
def smtp_falso(monkeypatch):
    import app.services.email_service as es

    _SMTPFalso.instancias = []
    _SMTPFalso.falla = None
    monkeypatch.setattr(es.smtplib, "SMTP", _SMTPFalso)
    monkeypatch.setattr(es, "SMTP_EMAIL", "bot@traumavision.test")
    monkeypatch.setattr(es, "SMTP_PASSWORD", "clave-que-no-debe-salir")
    return _SMTPFalso


class TestEnvioDeEmail:

    def _enviar(self, **extra):
        from app.services.email_service import send_report_email

        return send_report_email(
            to_email="dra@hospital.test",
            subject="Informe",
            body_text="cuerpo",
            pdf_bytes=b"%PDF-1.4",
            analysis_id=42,
            usuario=TEST_USER["email"],
            **extra,
        )

    def test_starttls_verifica_certificado_y_hostname(self, smtp_falso):
        assert self._enviar() is True
        s = smtp_falso.instancias[0]
        assert isinstance(s.contexto, ssl.SSLContext)
        assert s.contexto.check_hostname is True
        assert s.contexto.verify_mode == ssl.CERT_REQUIRED
        # Un servidor que no contesta no puede colgar el proceso.
        assert s.timeout is not None and s.timeout > 0

    def test_el_envio_exitoso_queda_registrado(self, smtp_falso, caplog):
        with caplog.at_level(logging.INFO, logger="traumavision.email"):
            self._enviar()
        registro = " ".join(r.getMessage() for r in caplog.records)
        assert "42" in registro
        assert "dra@hospital.test" in registro
        assert TEST_USER["email"] in registro
        assert "enviado" in registro.lower()
        assert "clave-que-no-debe-salir" not in caplog.text

    def test_el_fallo_queda_registrado_sin_la_clave(self, smtp_falso, caplog):
        import smtplib

        smtp_falso.falla = smtplib.SMTPAuthenticationError(535, b"credenciales malas")
        with caplog.at_level(logging.INFO, logger="traumavision.email"):
            assert self._enviar() is False
        registro = " ".join(r.getMessage() for r in caplog.records)
        assert "42" in registro
        assert "dra@hospital.test" in registro
        assert "fall" in registro.lower()  # falló / fallido
        assert "clave-que-no-debe-salir" not in caplog.text

    def test_la_ruta_pasa_analisis_y_usuario_al_servicio(
        self, auth_client, db_session, users, monkeypatch
    ):
        from app.database import crud
        from config.settings import UPLOADS_DIR
        import app.services.email_service as es

        a = crud.create_analysis(
            db_session, user_id=users["principal"],
            original_image_path="mail_o.png", annotated_image_path="mail_a.png",
            report_text="Informe", max_detection_confidence=0.5, is_abnormal=True,
            inference_time_ms=1.0, anatomical_region="muneca_pediatrica",
            model_version="v", routing_method="manual", urgency="MEDIUM",
        )
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        (UPLOADS_DIR / "mail_o.png").write_bytes(_png())
        (UPLOADS_DIR / "mail_a.png").write_bytes(_png())

        recibido = {}

        def falso_envio(**kw):
            recibido.update(kw)
            return True

        monkeypatch.setattr(es, "send_report_email", falso_envio)
        r = auth_client.post(f"/analysis/{a.id}/email", data={"to_email": "dra@hospital.test"})
        assert r.status_code == 303
        assert recibido["analysis_id"] == a.id
        assert recibido["usuario"] == TEST_USER["email"]
        assert recibido["to_email"] == "dra@hospital.test"


# ─────────────────────────────────────────────────────────────────────────────
# H5 — El panel admin pasa por _tasa / N_MINIMO
# ─────────────────────────────────────────────────────────────────────────────

def _analisis_en_serie(db_session, user_id: int, n: int, anormales: int):
    from tests.test_api import crear_analisis

    for i in range(n):
        crear_analisis(db_session, user_id, is_abnormal=i < anormales,
                       urgency="HIGH" if i < anormales else "LOW")


class TestPanelAdminConMuestraMinima:

    def test_stats_expone_tasa_publica(self):
        from src.analytics import stats

        t = stats.tasa(3, 4)
        assert set(t) == {"parte", "total", "tasa", "suficiente"}
        assert t["suficiente"] is (4 >= stats.N_MINIMO)

    def test_las_filas_llevan_el_dict_de_tasa(self, db_session, users):
        from app.routes.admin_routes import _resumen_por_usuario
        from src.analytics.stats import N_MINIMO

        _analisis_en_serie(db_session, users["principal"], n=N_MINIMO, anormales=N_MINIMO)
        filas = {f["email"]: f for f in _resumen_por_usuario(db_session)}
        fila = filas[TEST_USER["email"]]
        assert fila["anormal"] == {"parte": N_MINIMO, "total": N_MINIMO,
                                   "tasa": 1.0, "suficiente": True}
        assert fila["acuerdo"]["total"] == 0 and fila["acuerdo"]["suficiente"] is False

    def test_bajo_la_muestra_minima_publica_el_recuento_y_no_la_tasa(
        self, engine, users, client, db_session
    ):
        from src.analytics.stats import N_MINIMO
        from tests.test_api import TestAdminYExportacion

        n = N_MINIMO - 1
        _analisis_en_serie(db_session, users["principal"], n=n, anormales=n)
        c = TestAdminYExportacion()._login_admin(engine, users)
        html = c.get("/admin/").text
        fila = re.search(r"test@traumavision\.demo.*?</tr>", html, re.S).group(0)
        assert "100" not in fila, "publica «100 %» con n < N_MINIMO"
        assert f"{n}/{n}" in re.sub(r"<[^>]+>|&nbsp;|\s", "", fila)

    def test_con_la_muestra_minima_si_publica_la_tasa(
        self, engine, users, client, db_session
    ):
        from src.analytics.stats import N_MINIMO
        from tests.test_api import TestAdminYExportacion

        _analisis_en_serie(db_session, users["principal"], n=N_MINIMO, anormales=N_MINIMO)
        c = TestAdminYExportacion()._login_admin(engine, users)
        html = c.get("/admin/").text
        fila = re.search(r"test@traumavision\.demo.*?</tr>", html, re.S).group(0)
        assert "100" in fila

    def test_el_acuerdo_global_sobre_una_opinion_no_dice_cien(
        self, engine, users, client, db_session
    ):
        from app.database import crud
        from tests.test_api import TestAdminYExportacion, crear_analisis

        a = crear_analisis(db_session, users["principal"])
        crud.create_feedback(db_session, a.id, agreed=True)
        c = TestAdminYExportacion()._login_admin(engine, users)
        html = c.get("/admin/").text
        bloque = re.search(r"Sistema completo.*?Actividad por usuario", html, re.S).group(0)
        assert "100" not in bloque
        assert "1/1" in re.sub(r"<[^>]+>|&nbsp;|\s", "", bloque)

    def test_el_umbral_del_pie_no_esta_escrito_a_mano(self, engine, users, client):
        from src.analytics.stats import N_MINIMO
        from tests.test_api import TestAdminYExportacion

        c = TestAdminYExportacion()._login_admin(engine, users)
        html = c.get("/admin/").text
        assert "Menos de 5 opiniones" not in html
        assert f"Menos de {N_MINIMO}" in html

    def test_la_plantilla_no_calcula_porcentajes_por_su_cuenta(self):
        fuente = _fuente_plantilla("admin.html")
        assert "* 100" not in fuente
        assert '"%.0f"|format' not in fuente
        assert "pct_" not in fuente


# ─────────────────────────────────────────────────────────────────────────────
# H6 — La sesión se comprueba ANTES de leer el cuerpo
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def espia_de_formulario(monkeypatch):
    """Anota cada vez que alguien parsea el cuerpo de un request."""
    from starlette.requests import Request

    lecturas = []
    original = Request.form

    def espia(self, *args, **kwargs):
        lecturas.append(self.url.path)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Request, "form", espia)
    return lecturas


class TestSesionAntesDelCuerpo:

    @pytest.mark.parametrize("ruta", ["/analysis/upload", "/analysis/upload-study"])
    def test_sin_sesion_no_se_lee_el_cuerpo(self, client, espia_de_formulario, ruta):
        r = client.post(ruta, files={"file": ("rx.png", _png(), "image/png")})
        assert r.status_code == 303
        assert "/login" in r.headers["location"]
        assert espia_de_formulario == [], "el cuerpo se parseó antes de rechazar la sesión"

    def test_con_sesion_el_cuerpo_si_se_lee(self, auth_client, espia_de_formulario):
        r = auth_client.post(
            "/analysis/upload",
            files={"file": ("nota.txt", b"hola", "text/plain")},
        )
        assert r.status_code == 200
        assert "no permitido" in r.text.lower()
        assert "/analysis/upload" in espia_de_formulario

    def test_sin_archivo_en_el_formulario_no_explota(self, auth_client):
        r = auth_client.post("/analysis/upload", data={"region": "muneca_pediatrica"})
        assert r.status_code == 200
        assert "archivo" in r.text.lower()


# ─────────────────────────────────────────────────────────────────────────────
# H10 (base de datos) — La admin no se publica en el login
# ─────────────────────────────────────────────────────────────────────────────

class TestModoDemoSinLaAdmin:

    def _admins(self):
        from app.database.demo_seed import DEMO_USERS

        admins = [u for u in DEMO_USERS if u["is_admin"]]
        assert admins, "el seed tiene que seguir creando una cuenta admin"
        return admins

    def test_las_credenciales_publicadas_no_incluyen_a_la_admin(self):
        from app.database.demo_seed import demo_credentials

        publicadas = demo_credentials()
        assert publicadas, "el modo demo sigue listando cuentas"
        assert all(not u["is_admin"] for u in publicadas)
        emails = {u["email"] for u in publicadas}
        for a in self._admins():
            assert a["email"] not in emails

    def test_el_seed_sigue_creando_a_la_admin(self, db_session):
        from app.database import crud
        from app.database.demo_seed import seed_demo_users

        seed_demo_users(db_session)
        for a in self._admins():
            u = crud.get_user_by_email(db_session, a["email"])
            assert u is not None and u.is_admin

    def test_el_login_en_modo_demo_no_publica_la_admin(self, client, monkeypatch):
        import app.routes.auth_routes as ar

        monkeypatch.setattr(ar, "DEMO_MODE", True)
        html = client.get("/login").text
        assert "Cuentas de demostración" in html
        for a in self._admins():
            assert a["password"] not in html
            assert a["email"] not in html


# ─────────────────────────────────────────────────────────────────────────────
# H7 — La inferencia sale del bucle de eventos
# ─────────────────────────────────────────────────────────────────────────────

class _DetectorEspia:
    """Un detector sin pesos que anota DESDE DÓNDE lo llamaron.

    `asyncio.get_running_loop()` sólo funciona en el hilo del bucle. Si
    `predict` corre en el threadpool, levanta RuntimeError: eso es lo que se
    quiere ver.
    """

    model_version = "espia"

    def __init__(self):
        self.en_el_bucle: list[bool] = []
        self.imagenes: list = []

    def predict(self, image):
        from src.detection.predict import PredictionResult

        try:
            asyncio.get_running_loop()
            self.en_el_bucle.append(True)
        except RuntimeError:
            self.en_el_bucle.append(False)
        self.imagenes.append(image)
        img = image.convert("RGB")
        return PredictionResult(
            is_abnormal=False,
            max_detection_confidence=0.0,
            boxes=[],
            annotated_image=np.zeros((img.height, img.width, 3), dtype=np.uint8),
            inference_time_ms=1.0,
            image_size=img.size,
            model_version=self.model_version,
        )

    def generate_report_text(self, result):
        return "informe del espía"


@pytest.fixture
def detector_espia(monkeypatch):
    from src.detection.predict import FractureDetector

    espia = _DetectorEspia()
    monkeypatch.setattr(FractureDetector, "get", classmethod(lambda cls, region=None: espia))
    return espia


class TestInferenciaFueraDelBucle:

    def test_upload_infiere_en_el_threadpool(self, auth_client, detector_espia):
        r = auth_client.post(
            "/analysis/upload",
            files={"file": ("rx.png", _png(), "image/png")},
        )
        assert r.status_code == 303, r.text[:300]
        assert detector_espia.en_el_bucle == [False]

    def test_el_estudio_infiere_en_el_threadpool(self, auth_client, detector_espia):
        from tests.test_api import make_zip_with_dicoms

        r = auth_client.post(
            "/analysis/upload-study",
            files={"file": ("estudio.zip", make_zip_with_dicoms(2), "application/zip")},
        )
        assert r.status_code == 303, r.text[:300]
        assert detector_espia.en_el_bucle == [False, False]

    def test_la_api_infiere_en_el_threadpool(self, client, db_session, users, detector_espia):
        from app.database import crud

        _, raw = crud.create_api_key(db_session, "k", owner_user_id=users["principal"])
        r = client.post(
            "/api/v1/analyze",
            files={"file": ("rx.png", _png(), "image/png")},
            headers={"X-API-Key": raw},
        )
        assert r.status_code == 200, r.text[:300]
        assert detector_espia.en_el_bucle == [False]


# ─────────────────────────────────────────────────────────────────────────────
# H5 (integración) — Warm-up al arrancar
# ─────────────────────────────────────────────────────────────────────────────

class TestWarmUp:

    def test_precalienta_con_una_imagen_sintetica(self, detector_espia):
        from app.main import precalentar_modelo

        assert precalentar_modelo() is True
        assert len(detector_espia.imagenes) == 1
        assert isinstance(detector_espia.imagenes[0], Image.Image)

    def test_sin_modelo_no_rompe_el_arranque(self, monkeypatch):
        from src.detection.predict import FractureDetector
        from app.main import precalentar_modelo

        def sin_pesos(cls, region=None):
            raise FileNotFoundError("no hay checkpoint")

        monkeypatch.setattr(FractureDetector, "get", classmethod(sin_pesos))
        assert precalentar_modelo() is False

    def test_el_arranque_lo_llama_una_sola_vez_por_proceso(self, engine, monkeypatch):
        from fastapi.testclient import TestClient

        import app.main as main

        llamadas = []
        monkeypatch.setattr(main, "precalentar_modelo", lambda: llamadas.append(1) or True)
        monkeypatch.setattr(main, "_modelo_precalentado", False)
        with TestClient(main.app):
            pass
        with TestClient(main.app):
            pass
        assert len(llamadas) == 1


# ─────────────────────────────────────────────────────────────────────────────
# H13 — Enlace de salto (WCAG 2.4.1)
# ─────────────────────────────────────────────────────────────────────────────

class TestEnlaceDeSalto:

    def test_es_lo_primero_del_body_y_apunta_al_main(self):
        fuente = _fuente_plantilla("base.html")
        cuerpo = fuente[fuente.index("<body"):]
        primer_tag = re.search(r"<body[^>]*>(?:\s|\{%[^%]*%\})*<(a)\b[^>]*>", cuerpo)
        assert primer_tag, "el enlace de salto tiene que ser el primer hijo de <body>"
        assert 'class="skip-link"' in primer_tag.group(0)
        assert 'href="#contenido"' in primer_tag.group(0)
        assert re.search(r'<main[^>]*\bid="contenido"', fuente)

    def test_se_renderiza_antes_de_la_barra(self, client):
        html = client.get("/login").text
        assert "Saltar al contenido" in html
        assert html.index('class="skip-link"') < html.index("<nav")

    def test_el_css_lo_esconde_hasta_el_foco_de_teclado(self):
        css = (RAIZ / "app" / "static" / "css" / "style.css").read_text(encoding="utf-8")
        reposo = re.search(r"\.skip-link\s*\{([^}]*)\}", css)
        foco = re.search(r"\.skip-link:focus-visible\s*\{([^}]*)\}", css)
        assert reposo and foco
        assert "position:" in reposo.group(1)
        # Fuera de pantalla en reposo, en su lugar con foco.
        assert "translateY" in reposo.group(1) or "top:" in reposo.group(1)
        assert "--kb-violet" in reposo.group(1) + foco.group(1)


# ─────────────────────────────────────────────────────────────────────────────
# urgency_detail no presenta el score como probabilidad
# ─────────────────────────────────────────────────────────────────────────────

class TestDetalleDeUrgencia:

    @pytest.mark.parametrize("conf,anormal", [(0.99, True), (0.5, True), (0.2, False), (0.0, False)])
    def test_no_habla_de_probabilidad(self, conf, anormal):
        from app.services.routing_service import urgency_detail

        detalle = urgency_detail(conf, anormal)
        assert "probabilidad" not in detalle["detalle"].lower()
        assert "probabilidad" not in detalle



def test_los_tests_no_escriben_en_los_uploads_reales():
    from config.settings import BASE_DIR, UPLOADS_DIR

    assert UPLOADS_DIR.resolve() != (BASE_DIR / "app" / "uploads").resolve()
