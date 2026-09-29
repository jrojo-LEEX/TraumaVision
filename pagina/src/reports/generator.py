"""
generator.py — Generación de reportes PDF con los resultados del análisis.

¿Qué hace este archivo?
Crea un documento PDF profesional con:
- Los datos del análisis (fecha, usuario)
- La imagen original y la imagen con los hallazgos señalizados
- El reporte textual generado por el sistema
- El disclaimer legal

Es como el informe que genera el radiólogo después de analizar una placa.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from io import BytesIO
from datetime import datetime
from PIL import Image
import os
import tempfile
import unicodedata

from config.settings import (
    APP_NAME,
    LEGAL_DISCLAIMER,
    REGION_NO_INDICADA,
    domain_disclaimer,
)
from config.tiempo import ahora_local, fmt_local


# --- Glifos que Helvetica no sabe dibujar ------------------------------------
# El PDF se arma con Helvetica, la fuente base de reportlab: no se registra
# ninguna TTF. Helvetica sólo tiene WinAnsiEncoding (Latin-1 más comillas,
# rayas, bullet y algún signo). Todo lo demás sale como un CUADRADO NEGRO.
#
# El daño no era sólo estético. Una fila de 41 caracteres de dibujo de caja
# ("─" * 41, el separador del formato viejo) es UNA sola "palabra" que
# reportlab no puede cortar: el párrafo se desbordaba y el informe se iba a
# páginas extra repitiendo basura.
#
# Por qué el saneado vive ACÁ y no sólo en quien escribe el texto: 407 de los
# 600 análisis de la base ya tienen el "─" GUARDADO en `report_text`. Ese
# texto no se vuelve a generar — se lee de la columna y se imprime. El
# generador del PDF es el único punto por el que pasan los dos, el informe
# nuevo y el viejo, así que es el único lugar donde el arreglo los alcanza a
# ambos.
#
# El castellano entero está dentro de WinAnsi (á é í ó ú ñ ¿ ¡ · — – •), así
# que nada de la prosa se toca: sólo se folda lo que no se puede dibujar.
#
# El dibujo de caja NO está en esta tabla: se resuelve por nombre Unicode en
# `_equivalente_de_caja`, y además este archivo no puede llevar uno escrito
# literal — hay un test que barre la fuente para que no vuelva a colarse.
_EQUIVALENCIAS = {
    "→": "->",     # →  flecha derecha (informes viejos: "(x,y)→(x,y)")
    "←": "<-",     # ←
    "↔": "<->",    # ↔
    "⇒": "=>",     # ⇒
    "≥": ">=",     # ≥
    "≤": "<=",     # ≤
    "≠": "!=",     # ≠
    "✓": "[ok]",   # ✓
    "✔": "[ok]",   # ✔
    "✅": "[ok]",   # ✅
    "✗": "[x]",    # ✗
    "✘": "[x]",    # ✘
    "❌": "[x]",    # ❌
    "⚠": "!",      # ⚠
}


def _dibujable(ch: str) -> bool:
    """¿Helvetica tiene glifo para este carácter?"""
    try:
        ch.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def _equivalente_de_caja(ch: str) -> str | None:
    """El ASCII que corresponde a un carácter de dibujo de caja o de bloque.

    Se resuelve por el NOMBRE Unicode y no por una tabla de 128 entradas:
    todo U+2500–U+257F se llama «BOX DRAWINGS ...» y el nombre ya dice si el
    trazo es horizontal, vertical, doble o una esquina.
    """
    nombre = unicodedata.name(ch, "")
    if nombre.startswith("BLOCK "):
        return "-"
    if not nombre.startswith("BOX DRAWINGS"):
        return None
    if "HORIZONTAL" in nombre:
        return "=" if "DOUBLE" in nombre else "-"
    if "VERTICAL" in nombre:
        return "|"
    return "+"


def glifos_seguros(texto: str) -> str:
    """`texto` con todo carácter que Helvetica no pueda dibujar reemplazado.

    Cuatro pasadas, de la más fiel a la más bruta:
      1. lo dibujable queda intacto (toda la prosa en castellano);
      2. el dibujo de caja se resuelve por su nombre Unicode, que dice qué
         TRAZO es: el separador horizontal cae en «-», no en un cuadro;
      3. tabla explícita para flechas y marcas;
      4. descomposición NFKD y, si no queda nada legible, descarte — que es
         lo correcto para un emoji: no tiene lectura en ASCII.
    """
    if not texto:
        return texto

    salida = []
    for ch in texto:
        if _dibujable(ch):
            salida.append(ch)
            continue

        reemplazo = _equivalente_de_caja(ch)
        if reemplazo is None:
            reemplazo = _EQUIVALENCIAS.get(ch)
        if reemplazo is None:
            reemplazo = "".join(
                c
                for c in unicodedata.normalize("NFKD", ch)
                if _dibujable(c) and not unicodedata.combining(c)
            )
        salida.append(reemplazo)
    return "".join(salida)


def generate_pdf_report(
    original_image: Image.Image,
    annotated_image: Image.Image,
    report_text: str,
    doctor_name: str = "No especificado",
    patient_id: str = "Anónimo",
    analysis_id: str = "",
    # El centinela, no None: un `region=None` explícito significa que el
    # registro no guardó su procedencia, y eso lo deja FUERA del dominio
    # validado. Omitir el argumento es otra cosa: informe genérico.
    region=REGION_NO_INDICADA,
    created_at: datetime | None = None,
) -> bytes:
    """
    Genera un informe PDF con los resultados del análisis.

    Retorna los bytes del PDF (para descarga o envío por email).
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    elements = []

    # Los tres colores del informe salen del sistema de marca KIBBO, igual que
    # la pantalla: la guia prohibe el negro puro y el gris neutro. La TINTA
    # (#1a1040) reemplaza al negro en todo el cuerpo, el SECUNDARIO (#5C6074)
    # es el gris que va hacia el violeta y reemplaza al gris de fabrica, y el
    # VIOLETA (#461CCA) firma el titulo. Son los mismos hex que
    # `app/static/css/style.css` declara en su capa --kb-*; si cambian alla,
    # cambian aca, porque el PDF es el artefacto que SALE del sistema.
    KB_TINTA      = colors.HexColor("#1a1040")
    KB_SECUNDARIO = colors.HexColor("#5C6074")
    KB_VIOLETA    = colors.HexColor("#461CCA")

    # El negro de fabrica de reportlab no aparece en ninguna parte del
    # informe: se lo reemplaza de raiz, en el estilo del que heredan todos.
    styles["Normal"].textColor = KB_TINTA

    # Estilo personalizado para el título
    title_style = ParagraphStyle(
        "CustomTitle", parent=styles["Title"],
        fontSize=18, spaceAfter=20, alignment=TA_CENTER,
        textColor=KB_VIOLETA,
    )
    disclaimer_style = ParagraphStyle(
        "Disclaimer", parent=styles["Normal"],
        fontSize=7, textColor=KB_SECUNDARIO, alignment=TA_JUSTIFY,
        spaceBefore=20,
    )
    # La salvedad de dominio NO va en el gris de 7 pt del pie: es la que dice
    # que un informe sin hallazgos no descarta fractura. Se lee al tamaño del
    # cuerpo, en negro, y pegada a los hallazgos que califica.
    scope_style = ParagraphStyle(
        "Scope", parent=styles["Normal"],
        fontSize=8, leading=10, alignment=TA_JUSTIFY,
        borderPadding=6, borderWidth=0.5, borderColor=KB_TINTA,
        spaceBefore=14, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=10, alignment=TA_JUSTIFY, spaceAfter=6,
    )

    # Todo lo que se convierte en Paragraph pasa por acá. `P` es el único
    # constructor de párrafos del archivo justamente para que no exista un
    # camino que se saltee el saneado de glifos.
    def P(texto, estilo):
        return Paragraph(glifos_seguros(texto), estilo)

    # --- Encabezado ---
    elements.append(P(APP_NAME, title_style))
    elements.append(P(
        "Sistema de Soporte a la Decisión Clínica — Detección de Fracturas",
        ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=12, alignment=TA_CENTER),
    ))
    elements.append(Spacer(1, 20))

    # --- Datos del análisis ---
    # Dos instantes distintos que antes eran el mismo:
    #   · la fecha del ANÁLISIS, que es un dato del registro clínico;
    #   · la fecha de IMPRESIÓN, que va al pie.
    # El campo decía "Fecha del análisis" y llevaba la hora de impresión, así
    # que un informe reimpreso una semana después se fechaba solo. Los dos van
    # en la zona de presentación: la columna guarda UTC.
    impreso = ahora_local().strftime("%d/%m/%Y %H:%M:%S")
    fecha_analisis = fmt_local(created_at, "%d/%m/%Y %H:%M") or "sin registrar"
    # La tabla NO pasa por Paragraph: reportlab dibuja el string crudo con la
    # misma Helvetica, así que necesita el mismo saneado. `doctor_name` y
    # `patient_id` los escribe el usuario: son la vía más probable de que
    # entre un glifo raro.
    info_data = [
        [glifos_seguros(a), glifos_seguros(b)]
        for a, b in (
            ("Fecha del análisis:", fecha_analisis),
            ("ID de análisis:", analysis_id or "N/A"),
            ("Profesional:", doctor_name),
            ("Identificador paciente:", patient_id),
        )
    ]
    info_table = Table(info_data, colWidths=[5 * cm, 10 * cm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 20))

    # --- Imagen con hallazgos ---
    elements.append(P("<b>Imagen con hallazgos señalizados:</b>", body_style))
    elements.append(Spacer(1, 10))

    # Guardar la imagen anotada temporalmente para incluirla en el PDF
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        annotated_image.save(tmp.name)
        img = RLImage(tmp.name, width=14 * cm, height=14 * cm, kind="proportional")
        elements.append(img)
        tmp_path = tmp.name

    elements.append(Spacer(1, 15))

    # --- Reporte textual ---
    elements.append(P("<b>Hallazgos del Sistema:</b>", body_style))
    elements.append(Spacer(1, 6))

    # Acá es donde entra el texto GUARDADO en la base, que puede venir de
    # cualquiera de los cuatro formatos de informe que tuvo el sistema.
    for line in report_text.split("\n"):
        if line.strip():
            elements.append(P(line, body_style))

    # --- Alcance y limitaciones del modelo ---
    # Va acá, pegada a los hallazgos, y no en el pie: es la salvedad que
    # califica lo que se acaba de leer. El texto se deriva de la metadata del
    # modelo (config/settings.py) — ningún número está escrito acá.
    elements.append(P(domain_disclaimer(region), scope_style))

    # --- Disclaimer ---
    # La regla de separación era "─" * 80: ochenta cuadrados negros, porque
    # Helvetica no tiene el carácter. En ASCII el guión dibuja la misma regla
    # y se puede además copiar del PDF sin que salga basura.
    elements.append(Spacer(1, 30))
    elements.append(P(
        "-" * 80,
        ParagraphStyle("Line", parent=styles["Normal"], fontSize=6, textColor=KB_SECUNDARIO),
    ))
    elements.append(P(LEGAL_DISCLAIMER, disclaimer_style))
    elements.append(P(
        f"Generado por {APP_NAME} — impreso el {impreso}",
        disclaimer_style,
    ))

    # Construir PDF
    doc.build(elements)

    # Limpiar archivo temporal
    try:
        os.unlink(tmp_path)
    except OSError:
        pass

    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes
