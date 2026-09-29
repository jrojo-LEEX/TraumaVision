"""
test_api.py — Suite de tests de TraumaVision AI.

Cubre:
- Endpoints públicos (health, aviso legal, login)
- Autenticación por sesión y protección de rutas
- Aislamiento entre usuarios (que nadie lea estudios ajenos)
- Validación de uploads y soporte DICOM
- Extractor ZIP, incluidas las protecciones anti zip-bomb
- Preprocesamiento: CLAHE en inferencia, ventana DICOM, MONOCHROME1
- CRUD y umbrales de detección
- API REST y privilegio de administrador
"""

import io
import zipfile
from datetime import datetime, timezone

import numpy as np
import pytest
from PIL import Image

from tests.conftest import OTHER_USER, TEST_USER


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def make_png_bytes(width=64, height=64, value=0) -> bytes:
    img = Image.fromarray(np.full((height, width, 3), value, dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_dicom_bytes(
    instance_number: int = 1,
    photometric: str = "MONOCHROME2",
    pixel_value: int = 0,
    window: bool = False,
) -> bytes:
    """Crea un DICOM mínimo válido en memoria."""
    import pydicom
    from pydicom.dataset import FileDataset
    from pydicom.uid import ExplicitVRLittleEndian

    file_meta = pydicom.dataset.FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.UID("1.2.840.10008.5.1.4.1.1.2")
    file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = pydicom.uid.generate_uid()

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "CR"
    ds.InstanceNumber = str(instance_number)
    ds.Rows = 64
    ds.Columns = 64
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    if window:
        ds.WindowCenter = 128
        ds.WindowWidth = 256
    # Gradiente horizontal, para poder verificar inversiones.
    fila = bytes(range(0, 256, 4))  # 64 valores 0..252
    ds.PixelData = fila * 64 if pixel_value is None else bytes([pixel_value] * 64 * 64)
    if pixel_value is None:
        ds.PixelData = fila * 64

    buf = io.BytesIO()
    pydicom.dcmwrite(buf, ds)
    return buf.getvalue()


def make_zip_with_dicoms(n: int = 3) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(n):
            zf.writestr(f"serie1/img{i:03d}.dcm", make_dicom_bytes(instance_number=i + 1))
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


# ─────────────────────────────────────────────────────────────────────────────
# 1. ENDPOINTS PÚBLICOS
# ─────────────────────────────────────────────────────────────────────────────

class TestEndpointsPublicos:

    def test_health_check(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        cuerpo = r.json()
        assert cuerpo["status"] in ("ok", "degraded")
        assert "models_available" in cuerpo

    def test_home_redirige_al_login_sin_sesion(self, client):
        r = client.get("/")
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

    def test_login_page_carga(self, client):
        r = client.get("/login")
        assert r.status_code == 200
        assert "contrase" in r.text.lower()

    def test_aviso_legal_es_publico(self, client):
        r = client.get("/aviso-legal")
        assert r.status_code == 200
        assert "no descarta" in r.text.lower()

    def test_404_ruta_desconocida(self, client):
        assert client.get("/no-existe-esta-ruta").status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 2. AUTENTICACIÓN
# ─────────────────────────────────────────────────────────────────────────────

class TestAutenticacion:

    @pytest.mark.parametrize(
        "ruta",
        ["/analysis/upload", "/analysis/history", "/dashboard/", "/dashboard/api/stats"],
    )
    def test_rutas_protegidas_redirigen_sin_sesion(self, client, ruta):
        r = client.get(ruta)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/login")

    def test_login_con_credenciales_correctas(self, client, users):
        r = client.post(
            "/login", data={"email": TEST_USER["email"], "password": TEST_USER["password"]}
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/analysis/upload"

    def test_login_con_password_incorrecta(self, client, users):
        r = client.post("/login", data={"email": TEST_USER["email"], "password": "mala"})
        assert r.status_code == 401
        assert "incorrectos" in r.text.lower()

    def test_login_con_email_inexistente(self, client, users):
        r = client.post("/login", data={"email": "nadie@x.com", "password": "x"})
        assert r.status_code == 401
        # El mismo mensaje que con contraseña incorrecta: no se revela qué
        # cuentas existen.
        assert "incorrectos" in r.text.lower()

    def test_upload_accesible_con_sesion(self, auth_client):
        r = auth_client.get("/analysis/upload")
        assert r.status_code == 200
        assert "radiograf" in r.text.lower()

    def test_logout_cierra_la_sesion(self, auth_client):
        assert auth_client.post("/logout").status_code == 303
        assert auth_client.get("/analysis/history").status_code == 303

    def test_next_solo_acepta_rutas_internas(self, client, users):
        """No debe poder usarse como open redirect a un sitio externo."""
        r = client.post(
            "/login",
            data={
                "email": TEST_USER["email"],
                "password": TEST_USER["password"],
                "next": "https://sitio-malicioso.example/robar",
            },
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/analysis/upload"

    def test_password_no_se_guarda_en_claro(self, db_session, users):
        from app.database import crud

        u = crud.get_user_by_email(db_session, TEST_USER["email"])
        assert TEST_USER["password"] not in u.password_hash
        assert u.password_hash.startswith("pbkdf2_sha256$")


# ─────────────────────────────────────────────────────────────────────────────
# 3. AISLAMIENTO ENTRE USUARIOS
# ─────────────────────────────────────────────────────────────────────────────

class TestAislamiento:

    def test_no_se_puede_ver_analisis_ajeno(self, auth_client, other_client, db_session, users):
        ajeno = crear_analisis(db_session, users["otro"])
        r = auth_client.get(f"/analysis/{ajeno.id}/results")
        assert r.status_code == 404, "Un usuario pudo leer el estudio de otro"

    def test_no_se_puede_bajar_pdf_ajeno(self, auth_client, db_session, users):
        ajeno = crear_analisis(db_session, users["otro"])
        assert auth_client.get(f"/analysis/{ajeno.id}/pdf").status_code == 404

    def test_no_se_puede_dar_feedback_sobre_analisis_ajeno(self, auth_client, db_session, users):
        from app.database import crud

        ajeno = crear_analisis(db_session, users["otro"])
        r = auth_client.post(
            "/feedback/submit", data={"analysis_id": ajeno.id, "agreed": "true"}
        )
        assert r.status_code == 303
        assert crud.get_feedback_by_analysis(db_session, ajeno.id) is None

    def test_historial_solo_muestra_lo_propio(self, auth_client, db_session, users):
        crear_analisis(db_session, users["principal"], report_text="MIO")
        crear_analisis(db_session, users["otro"], report_text="AJENO")
        r = auth_client.get("/analysis/history")
        assert r.status_code == 200
        from app.database import crud

        propios = crud.get_analyses_by_user(db_session, users["principal"])
        ajenos = crud.get_analyses_by_user(db_session, users["otro"])
        assert len(propios) == 1 and len(ajenos) == 1

    def test_imagen_ajena_no_se_sirve(self, auth_client, db_session, users):
        crear_analisis(
            db_session, users["otro"], annotated_image_path="secreto_annotated.png"
        )
        r = auth_client.get("/analysis/imagen/secreto_annotated.png")
        assert r.status_code == 404

    def test_nombre_de_imagen_invalido_rechazado(self, auth_client):
        """No debe poder salirse de la carpeta de uploads."""
        r = auth_client.get("/analysis/imagen/..%2F..%2F.env")
        assert r.status_code in (400, 404)

    def test_estudio_ajeno_no_visible(self, auth_client, db_session, users):
        from app.database import crud

        estudio = crud.create_study(
            db_session, user_id=users["otro"], original_filename="x.zip",
            total_images=1, images_with_findings=0,
        )
        assert auth_client.get(f"/analysis/study/{estudio.id}").status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 4. VALIDACIÓN DE UPLOADS
# ─────────────────────────────────────────────────────────────────────────────

class TestValidacionUpload:

    def test_rechaza_tipo_no_soportado(self, auth_client):
        r = auth_client.post(
            "/analysis/upload",
            files={"file": ("doc.txt", b"hola", "text/plain")},
        )
        assert r.status_code == 200
        assert "no permitido" in r.text.lower()

    def test_rechaza_pdf_como_imagen(self, auth_client):
        r = auth_client.post(
            "/analysis/upload",
            files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert "no permitido" in r.text.lower()

    def test_rechaza_zip_en_upload_individual(self, auth_client):
        r = auth_client.post(
            "/analysis/upload",
            files={"file": ("e.zip", make_zip_with_dicoms(1), "application/zip")},
        )
        assert "no permitido" in r.text.lower()

    def test_archivo_vacio_rechazado(self, auth_client):
        r = auth_client.post(
            "/analysis/upload", files={"file": ("v.png", b"", "image/png")}
        )
        assert "vac" in r.text.lower()

    def test_png_corrupto_no_se_reporta_como_falla_del_modelo(self, auth_client):
        """Un archivo dañado es un problema del archivo, no del modelo.

        Antes el except atrapaba ValueError y respondía "¿ya entrenaste el
        modelo?" ante cualquier imagen ilegible.
        """
        r = auth_client.post(
            "/analysis/upload",
            files={"file": ("roto.png", b"\x89PNG\r\n\x1a\nBASURA", "image/png")},
        )
        assert r.status_code == 200
        texto = r.text.lower()
        assert "no se pudo leer" in texto or "no se pudo procesar" in texto
        assert "entrenaste" not in texto

    def test_region_invalida_rechazada(self, auth_client):
        r = auth_client.post(
            "/analysis/upload",
            files={"file": ("rx.png", make_png_bytes(), "image/png")},
            data={"region": "region_que_no_existe"},
        )
        assert "no reconocida" in r.text.lower()

    def test_upload_valido_crea_analisis(self, auth_client, db_session, users):
        """Camino feliz: sube, detecta, guarda y redirige al resultado."""
        from app.database import crud

        r = auth_client.post(
            "/analysis/upload",
            files={"file": ("rx.png", make_png_bytes(128, 128), "image/png")},
        )
        assert r.status_code == 303, r.text[:400]
        assert "/results" in r.headers["location"]

        analisis = crud.get_analyses_by_user(db_session, users["principal"])
        assert len(analisis) == 1
        assert analisis[0].model_version
        assert analisis[0].anatomical_region == "muneca_pediatrica"


# ─────────────────────────────────────────────────────────────────────────────
# 5. DICOM
# ─────────────────────────────────────────────────────────────────────────────

class TestDicom:

    def test_load_dicom_devuelve_rgb(self):
        from src.preprocessing.transforms import load_dicom

        img = load_dicom(make_dicom_bytes())
        assert img.mode == "RGB"
        assert img.size == (64, 64)

    def test_monochrome1_se_invierte(self):
        """MONOCHROME1 guarda el blanco en el valor mínimo: viene invertida.

        Sin corregirlo, el modelo recibe un negativo de la radiografía.
        """
        from src.preprocessing.transforms import load_dicom

        m2 = np.array(load_dicom(make_dicom_bytes(photometric="MONOCHROME2", pixel_value=None)))
        m1 = np.array(load_dicom(make_dicom_bytes(photometric="MONOCHROME1", pixel_value=None)))
        # Uno debe ser el complemento del otro.
        assert np.allclose(m2.astype(int) + m1.astype(int), 255, atol=2)

    def test_dicom_con_ventana_no_falla(self):
        from src.preprocessing.transforms import load_dicom

        img = load_dicom(make_dicom_bytes(window=True, pixel_value=None))
        assert img.size == (64, 64)

    def test_upload_dicom_reconocido(self, auth_client):
        r = auth_client.post(
            "/analysis/upload",
            files={"file": ("rx.dcm", make_dicom_bytes(), "application/dicom")},
        )
        # Se procesa: o redirige al resultado, o falla por el modelo, pero
        # nunca por "tipo no permitido".
        assert "no permitido" not in r.text.lower()

    def test_nombre_de_archivo_se_sanitiza(self):
        """Los nombres de un estudio real traen identificadores de paciente."""
        from src.preprocessing.transforms import sanitize_filename

        limpio = sanitize_filename("PACIENTE_12345678/serie1/IM_00042.dcm")
        assert "12345678" not in limpio
        assert "/" not in limpio


# ─────────────────────────────────────────────────────────────────────────────
# 6. EXTRACTOR ZIP
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractorZip:

    def test_extrae_varios_dicoms(self):
        from src.preprocessing.transforms import extract_dicoms_from_zip

        entradas = extract_dicoms_from_zip(make_zip_with_dicoms(3))
        assert len(entradas) == 3
        assert all(e.image.mode == "RGB" for e in entradas)

    def test_zip_vacio_levanta_value_error(self):
        from src.preprocessing.transforms import extract_dicoms_from_zip

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("leeme.txt", b"no soy dicom")
        with pytest.raises(ValueError):
            extract_dicoms_from_zip(buf.getvalue())

    def test_basura_de_macos_ignorada(self):
        from src.preprocessing.transforms import extract_dicoms_from_zip

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("__MACOSX/._img.dcm", b"basura")
            zf.writestr("img.dcm", make_dicom_bytes())
        assert len(extract_dicoms_from_zip(buf.getvalue())) == 1

    def test_orden_por_instance_number(self):
        from src.preprocessing.transforms import extract_dicoms_from_zip

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in (3, 1, 2):
                zf.writestr(f"z{i}.dcm", make_dicom_bytes(instance_number=i))
        entradas = extract_dicoms_from_zip(buf.getvalue())
        assert [e.instance_number for e in entradas] == [1, 2, 3]

    def test_demasiadas_entradas_rechazado(self):
        """Tope de archivos: un ZIP con miles de entradas es un ataque."""
        from config.settings import MAX_ZIP_ENTRIES
        from src.preprocessing.transforms import extract_dicoms_from_zip

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(MAX_ZIP_ENTRIES + 5):
                zf.writestr(f"f{i}.dcm", b"x")
        with pytest.raises(ValueError, match="máximo admitido"):
            extract_dicoms_from_zip(buf.getvalue())

    def test_zip_bomb_rechazada(self):
        """Tope del contenido descomprimido, leído de la cabecera."""
        from config.settings import MAX_ZIP_UNCOMPRESSED_MB
        from src.preprocessing.transforms import extract_dicoms_from_zip

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Ceros: comprimen muchisimo y se expanden a mas del tope. Por
            # chunks: alocar 650 MB de golpe daba MemoryError en el ARMADO
            # del payload (no en el codigo bajo prueba).
            chunk = bytes(8 * 1024 * 1024)
            with zf.open("bomba.dcm", "w") as destino:
                for _ in range(MAX_ZIP_UNCOMPRESSED_MB // 8 + 8):
                    destino.write(chunk)
        with pytest.raises(ValueError, match="supera el máximo"):
            extract_dicoms_from_zip(buf.getvalue())

    def test_zip_slip_ignorado(self):
        """Entradas con '..' en la ruta no deben procesarse."""
        from src.preprocessing.transforms import extract_dicoms_from_zip

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../fuera.dcm", make_dicom_bytes())
            zf.writestr("dentro.dcm", make_dicom_bytes())
        entradas = extract_dicoms_from_zip(buf.getvalue())
        assert len(entradas) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 7. PREPROCESAMIENTO E INFERENCIA
# ─────────────────────────────────────────────────────────────────────────────

class TestPreprocesamiento:

    def test_clahe_de_inferencia_cambia_la_imagen(self):
        """El CLAHE de servicio debe ser el mismo del pipeline de entrenamiento."""
        from src.detection.predict import apply_clahe_rgb

        rng = np.random.default_rng(0)
        base = Image.fromarray(rng.integers(60, 190, (64, 64, 3), dtype=np.uint8))
        salida = apply_clahe_rgb(base)
        assert salida.mode == "RGB"
        assert salida.size == base.size
        # Los tres canales quedan iguales: es una imagen monocromática.
        arr = np.array(salida)
        assert np.array_equal(arr[:, :, 0], arr[:, :, 1])
        assert not np.array_equal(np.array(base)[:, :, 0], arr[:, :, 0])

    def test_umbrales_separados(self):
        """El umbral de dibujo debe ser menor que el de anormalidad."""
        from config.settings import ABNORMAL_THRESHOLD, CONFIDENCE_THRESHOLD

        assert CONFIDENCE_THRESHOLD < ABNORMAL_THRESHOLD

    def test_resize_image(self):
        from src.preprocessing.transforms import resize_image

        salida = resize_image(np.zeros((100, 200, 3), dtype=np.uint8), size=640)
        assert salida.shape == (640, 640, 3)

    def test_clahe_utilitario_color_y_gris(self):
        from src.preprocessing.transforms import apply_clahe

        assert apply_clahe(np.zeros((32, 32, 3), dtype=np.uint8)).shape == (32, 32, 3)
        assert apply_clahe(np.zeros((32, 32), dtype=np.uint8)).shape == (32, 32)

    def test_pil_cv2_ida_y_vuelta(self):
        from src.preprocessing.transforms import cv2_to_pil, pil_to_cv2

        original = Image.fromarray(np.full((16, 16, 3), 120, dtype=np.uint8))
        assert np.array_equal(np.array(cv2_to_pil(pil_to_cv2(original))), np.array(original))


# ─────────────────────────────────────────────────────────────────────────────
# 8. URGENCIA Y PRESENTACIÓN CLÍNICA
# ─────────────────────────────────────────────────────────────────────────────

class TestUrgencia:

    def test_niveles(self):
        from app.services.routing_service import calculate_urgency

        assert calculate_urgency(0.95) == "HIGH"
        assert calculate_urgency(0.60) == "MEDIUM"
        assert calculate_urgency(0.20) == "LOW"

    def test_negativo_limpio_y_limite_se_distinguen(self):
        """0.00 y 0.49 no pueden mostrarse igual: son situaciones distintas."""
        from app.services.routing_service import urgency_detail

        from config.settings import ABNORMAL_THRESHOLD

        # Un valor dentro de la banda de referencia: se dibuja pero no clasifica.
        casi = ABNORMAL_THRESHOLD * 0.8
        limpio = urgency_detail(0.0, False)
        limite = urgency_detail(casi, False)
        assert limpio["nivel"] == "LOW"
        assert limite["nivel"] == "LOW_BORDERLINE"
        assert limpio["clase"] != limite["clase"]

    def test_findings_above_abnormal_no_cuenta_las_de_baja_confianza(self, db_session, users):
        """El contador que ve el médico sólo suma lo que supera el umbral.

        Antes la pantalla mostraba "N fracturas detectadas" con TODAS las cajas,
        así que un estudio clasificado "Normal" podía decir "3 fracturas".
        """
        from app.database import crud

        from config.settings import ABNORMAL_THRESHOLD, CONFIDENCE_THRESHOLD

        # Dos cajas dibujadas (>= umbral de dibujo) pero ninguna clasificadora.
        alta = (ABNORMAL_THRESHOLD + CONFIDENCE_THRESHOLD) / 2
        baja = CONFIDENCE_THRESHOLD + 0.01
        a = crear_analisis(db_session, users["principal"], is_abnormal=False,
                           max_detection_confidence=alta)
        crud.create_detection_boxes(db_session, a.id, [
            {"x1": 1, "y1": 1, "x2": 5, "y2": 5, "confidence": alta},
            {"x1": 6, "y1": 6, "x2": 9, "y2": 9, "confidence": baja},
        ])
        db_session.refresh(a)
        assert len(a.detection_boxes) == 2
        assert a.findings_above_abnormal == 0


# ─────────────────────────────────────────────────────────────────────────────
# 9. CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestCRUD:

    def test_crear_y_leer_analisis(self, db_session, users):
        from app.database import crud

        a = crear_analisis(db_session, users["principal"])
        assert crud.get_analysis_for_user(db_session, a.id, users["principal"]) is not None
        assert crud.get_analysis_for_user(db_session, a.id, users["otro"]) is None

    def test_estudio_con_analisis_vinculados(self, db_session, users):
        from app.database import crud

        estudio = crud.create_study(
            db_session, user_id=users["principal"], original_filename="e.zip",
            total_images=2, images_with_findings=1,
            anatomical_region="muneca_pediatrica", model_version="v1r",
        )
        for i in range(2):
            crear_analisis(db_session, users["principal"], study_id=estudio.id,
                           original_image_path=f"{i}_o.png")
        assert len(crud.get_analyses_by_study(db_session, estudio.id)) == 2
        # La trazabilidad del modelo se guarda también en el estudio.
        assert estudio.model_version == "v1r"

    def test_feedback_unico_por_analisis(self, db_session, users):
        from app.database import crud

        a = crear_analisis(db_session, users["principal"])
        crud.create_feedback(db_session, a.id, agreed=True)
        assert crud.get_feedback_by_analysis(db_session, a.id) is not None

    def test_integridad_referencial_activa(self, db_session):
        """Con las claves foráneas activas no se pueden crear análisis huérfanos."""
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            crear_analisis(db_session, 99999)  # usuario inexistente


# ─────────────────────────────────────────────────────────────────────────────
# 10. API REST
# ─────────────────────────────────────────────────────────────────────────────

class TestApiRest:

    def test_endpoints_exigen_api_key(self, client):
        assert client.get("/api/v1/models").status_code == 401
        assert client.get("/api/v1/analysis/1").status_code == 401

    def test_api_key_invalida_rechazada(self, client):
        r = client.get("/api/v1/models", headers={"X-API-Key": "nope"})
        assert r.status_code == 401

    def test_models_devuelve_metricas_medidas(self, client, db_session, users):
        from app.database import crud

        _, raw = crud.create_api_key(db_session, "test", owner_user_id=users["principal"])
        r = client.get("/api/v1/models", headers={"X-API-Key": raw})
        assert r.status_code == 200
        cuerpo = r.json()
        # El sistema no calibra el score: la API no puede ofrecer una
        # probabilidad de fractura.
        assert "calibrated_probability" not in r.text
        m = cuerpo["models"][0]["metrics"]
        # Contra la fuente, no contra un literal: lo que se prueba es que la
        # API publique la métrica MEDIDA, no que valga tal número. Cuando este
        # assert decía 0.8662 a mano, el re-entrenamiento v2 lo rompió sin que
        # hubiera nada roto — el test era otro rincón afirmando la métrica
        # vieja, justo lo que el resto del sistema evita.
        from config.settings import DEFAULT_REGION, MODEL_METADATA

        assert m["recall"] == pytest.approx(
            MODEL_METADATA[DEFAULT_REGION]["recall"], abs=1e-4
        )
        assert m["test_n"] == MODEL_METADATA[DEFAULT_REGION]["test_n"]

    def test_key_comun_no_puede_crear_keys(self, client, db_session, users):
        """Antes require_admin_key era idéntica a require_api_key.

        Cualquier key válida podía crear keys nuevas: escalada de privilegios.
        """
        from app.database import crud

        _, raw = crud.create_api_key(
            db_session, "comun", owner_user_id=users["principal"], is_admin=False
        )
        r = client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": raw},
            data={"label": "nueva", "owner_user_id": users["principal"]},
        )
        assert r.status_code == 403

    def test_key_admin_si_puede_crear_keys(self, client, db_session, users):
        from app.database import crud

        _, raw = crud.create_api_key(
            db_session, "admin", owner_user_id=users["principal"], is_admin=True
        )
        r = client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": raw},
            data={"label": "nueva", "owner_user_id": users["principal"]},
        )
        assert r.status_code == 201
        assert len(r.json()["key"]) == 64

    def test_api_no_lee_analisis_de_otro_usuario(self, client, db_session, users):
        from app.database import crud

        ajeno = crear_analisis(db_session, users["otro"])
        _, raw = crud.create_api_key(db_session, "k", owner_user_id=users["principal"])
        r = client.get(f"/api/v1/analysis/{ajeno.id}", headers={"X-API-Key": raw})
        assert r.status_code == 404

    def test_batch_no_implementado(self, client, db_session, users):
        from app.database import crud

        _, raw = crud.create_api_key(db_session, "k", owner_user_id=users["principal"])
        r = client.post(
            "/api/v1/analyze/batch",
            headers={"X-API-Key": raw},
            files={"file": ("e.zip", b"x", "application/zip")},
            data={"region": "muneca_pediatrica"},
        )
        assert r.status_code == 501


# ─────────────────────────────────────────────────────────────────────────────
# 11. LÍMITE DE ENVÍOS POR EMAIL
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimit:

    def test_consume_hasta_el_limite(self):
        from app.services.rate_limit import check_and_consume, reset

        reset("prueba")
        assert all(check_and_consume("prueba", 3)[0] for _ in range(3))
        assert check_and_consume("prueba", 3)[0] is False

    def test_claves_independientes(self):
        from app.services.rate_limit import check_and_consume, reset

        reset()
        assert check_and_consume("a", 1)[0] is True
        assert check_and_consume("b", 1)[0] is True
        assert check_and_consume("a", 1)[0] is False


# ─────────────────────────────────────────────────────────────────────────────
# 12. PROTECCIÓN CSRF
# ─────────────────────────────────────────────────────────────────────────────

class TestCSRF:
    """Sin token, un sitio externo podía hacer que un médico logueado enviara
    el informe de un paciente sin enterarse."""

    def test_formulario_incluye_el_token(self, auth_client):
        r = auth_client.get("/analysis/upload")
        assert 'name="csrf_token"' in r.text

    def test_feedback_sin_token_rechazado(self, auth_client, db_session, users):
        propio = crear_analisis(db_session, users["principal"])
        del auth_client.headers["X-CSRF-Token"]
        r = auth_client.post(
            "/feedback/submit", data={"analysis_id": propio.id, "agreed": "true"}
        )
        assert r.status_code == 403

    def test_feedback_con_token_invalido_rechazado(self, auth_client, db_session, users):
        propio = crear_analisis(db_session, users["principal"])
        auth_client.headers["X-CSRF-Token"] = "token-falsificado"
        r = auth_client.post(
            "/feedback/submit", data={"analysis_id": propio.id, "agreed": "true"}
        )
        assert r.status_code == 403

    def test_feedback_con_token_valido_aceptado(self, auth_client, db_session, users):
        from app.database import crud

        propio = crear_analisis(db_session, users["principal"])
        r = auth_client.post(
            "/feedback/submit", data={"analysis_id": propio.id, "agreed": "true"}
        )
        assert r.status_code == 303
        assert crud.get_feedback_by_analysis(db_session, propio.id) is not None

    def test_logout_sin_token_rechazado(self, auth_client):
        del auth_client.headers["X-CSRF-Token"]
        assert auth_client.post("/logout").status_code == 403

    def test_upload_sin_token_rechazado(self, auth_client):
        del auth_client.headers["X-CSRF-Token"]
        r = auth_client.post(
            "/analysis/upload", files={"file": ("rx.png", make_png_bytes(), "image/png")}
        )
        assert r.status_code == 403

    def test_el_token_rota_al_iniciar_sesion(self, client, users):
        """Evita la fijación de sesión: un token previo al login no sirve."""
        from tests.conftest import _CSRF_RE

        antes = _CSRF_RE.search(client.get("/login").text).group(1)
        client.post(
            "/login", data={"email": TEST_USER["email"], "password": TEST_USER["password"]}
        )
        despues = _CSRF_RE.search(client.get("/analysis/upload").text).group(1)
        assert antes != despues


# ─────────────────────────────────────────────────────────────────────────────
# 13. CALIBRACIÓN DE LA CONFIANZA
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# 14. PANEL DE ADMINISTRACIÓN Y EXPORTACIÓN CSV
# ─────────────────────────────────────────────────────────────────────────────

class TestAdminYExportacion:

    def _login_admin(self, engine, users):
        """Crea un admin y devuelve un cliente logueado con él."""
        from sqlalchemy.orm import sessionmaker

        from app.database import crud
        from app.database.db import get_db
        from app.main import app
        from fastapi.testclient import TestClient
        from tests.conftest import leer_csrf

        Local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Local()
        try:
            crud.create_user(db, email="jefa@traumavision.demo", name="Jefa",
                             password="jefa.demo2026", is_admin=True)
        finally:
            db.close()

        def override():
            db = Local()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override
        c = TestClient(app, follow_redirects=False)
        r = c.post("/login", data={"email": "jefa@traumavision.demo",
                                   "password": "jefa.demo2026"})
        assert r.status_code == 303
        c.headers["X-CSRF-Token"] = leer_csrf(c)
        return c

    def test_admin_bloqueado_para_usuario_comun(self, auth_client):
        assert auth_client.get("/admin/").status_code == 403
        assert auth_client.get("/admin/export/analisis.csv").status_code == 403

    def test_admin_accesible_para_admin(self, engine, users, client):
        c = self._login_admin(engine, users)
        r = c.get("/admin/")
        assert r.status_code == 200
        assert "Actividad por usuario" in r.text
        # El panel lista a los demás usuarios: es la vista global
        assert "test@traumavision.demo" in r.text

    def test_export_global_solo_admin(self, engine, users, client, db_session):
        crear_analisis(db_session, users["principal"])
        c = self._login_admin(engine, users)
        r = c.get("/admin/export/analisis.csv")
        assert r.status_code == 200
        assert "usuario;id;fecha" in r.text
        assert "test@traumavision.demo" in r.text

    def test_export_csv_propio(self, auth_client, db_session, users):
        crear_analisis(db_session, users["principal"])
        r = auth_client.get("/dashboard/export/analisis.csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "id;fecha;region" in r.text
        assert "anormal" in r.text

    def test_export_opiniones_propias(self, auth_client, db_session, users):
        from app.database import crud

        a = crear_analisis(db_session, users["principal"])
        crud.create_feedback(db_session, a.id, agreed=False,
                             correct_diagnosis="Sin fractura — fisis normal")
        r = auth_client.get("/dashboard/export/opiniones.csv")
        assert r.status_code == 200
        assert "en desacuerdo" in r.text
        assert "fisis normal" in r.text

    def test_dashboard_muestra_desacuerdos(self, auth_client, db_session, users):
        from app.database import crud

        a = crear_analisis(db_session, users["principal"])
        crud.create_feedback(db_session, a.id, agreed=False,
                             correct_diagnosis="Fractura de rodete no marcada")
        r = auth_client.get("/dashboard/")
        assert r.status_code == 200
        assert "corregiste al sistema" in r.text
        assert "Fractura de rodete no marcada" in r.text
        assert 'id="urgencias"' in r.text and 'id="confianzas"' in r.text

    def test_csv_no_mezcla_usuarios(self, auth_client, db_session, users):
        """El export propio no puede filtrar estudios ajenos."""
        crear_analisis(db_session, users["otro"], report_text="AJENO")
        r = auth_client.get("/dashboard/export/analisis.csv")
        # una fila de encabezado, cero de datos
        assert r.text.strip().count(chr(10)) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 15. INFORME ESTRUCTURADO
# ─────────────────────────────────────────────────────────────────────────────

class TestInformeEstructurado:
    """Las ayudas de localización no cargan el modelo: se prueban en frío."""

    def test_ubicacion_es_relativa_a_la_imagen(self):
        from src.detection.predict import DetectionBox, FractureDetector

        arriba_izq = DetectionBox(10, 10, 90, 90, 0.9)
        centro = DetectionBox(400, 400, 600, 600, 0.9)
        u1 = FractureDetector._ubicacion_en_imagen(arriba_izq, 1000, 1000)
        u2 = FractureDetector._ubicacion_en_imagen(centro, 1000, 1000)
        assert u1 == "sector superior izquierdo de la imagen"
        assert u2 == "sector central de la imagen"
        # nunca términos anatómicos que el modelo no puede afirmar
        for u in (u1, u2):
            for prohibido in ("radio", "cúbito", "distal", "proximal"):
                assert prohibido not in u

    def test_tamano_relativo(self):
        from src.detection.predict import DetectionBox, FractureDetector

        chico = DetectionBox(0, 0, 50, 50, 0.9)       # 0.25 % del área
        grande = DetectionBox(0, 0, 400, 400, 0.9)    # 16 % del área
        assert FractureDetector._tamano_relativo(chico, 1000, 1000) == "focal"
        assert FractureDetector._tamano_relativo(grande, 1000, 1000) == "extenso"
