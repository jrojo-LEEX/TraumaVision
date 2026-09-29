"""
email_service.py — Servicio de envío de reportes por email.

¿Qué hace este archivo?
Envía el reporte PDF generado al email que indique el médico.
Usa el protocolo SMTP (Simple Mail Transfer Protocol), que es como
el "cartero" de internet para enviar emails.

Es el ÚNICO camino por el que una radiografía de paciente sale del sistema,
y por eso tiene dos exigencias que el resto de los servicios no tienen
(auditoría 2026-09-01, 04_web H3):

  1. El canal se AUTENTICA, no sólo se cifra. `starttls()` sin contexto usa
     `CERT_NONE` y no comprueba el nombre del servidor: cualquiera en la red
     puede hacerse pasar por el servidor de correo y leer el PDF y la clave
     de la cuenta. `ssl.create_default_context()` exige certificado válido y
     hostname coincidente.
  2. Cada envío deja RASTRO: análisis, usuario que lo pidió, dirección de
     destino y resultado, salga bien o mal. Nunca la contraseña.
"""

import logging
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config.settings import APP_NAME, SMTP_EMAIL, SMTP_PASSWORD, SMTP_PORT, SMTP_SERVER

# Registro de auditoría de envíos. Va por `logging` y no por `print` para
# que quien despliegue pueda mandarlo a un archivo o a syslog sin tocar
# código. Es el único lugar del sistema donde se anota que un dato de
# paciente salió del perímetro.
logger = logging.getLogger("traumavision.email")

# Segundos de espera máxima por el servidor de correo. Sin tope, un SMTP que
# no contesta deja el hilo (y con él la respuesta al médico) colgado
# indefinidamente.
SMTP_TIMEOUT_SEGUNDOS = 20


def send_report_email(
    to_email: str,
    subject: str,
    body_text: str,
    pdf_bytes: bytes = None,
    pdf_filename: str = "reporte_traumavision.pdf",
    analysis_id: int | None = None,
    usuario: str | None = None,
) -> bool:
    """
    Envía un email con el reporte adjunto.

    `analysis_id` y `usuario` no viajan en el correo: son para el registro de
    auditoría (quién sacó qué estudio y adónde).

    Retorna True si se envió exitosamente, False si hubo error.
    """
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        logger.warning(
            "Envío NO realizado (SMTP sin configurar en .env): "
            "análisis=%s usuario=%s destino=%s",
            analysis_id, usuario, to_email,
        )
        return False

    msg = MIMEMultipart()
    msg["From"] = f"{APP_NAME} <{SMTP_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    # Cuerpo del email
    msg.attach(MIMEText(body_text, "plain"))

    # Adjuntar PDF si se proporcionó
    if pdf_bytes:
        pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_attachment.add_header(
            "Content-Disposition", "attachment", filename=pdf_filename
        )
        msg.attach(pdf_attachment)

    try:
        # Contexto por defecto de la biblioteca estándar: CERT_REQUIRED,
        # check_hostname=True y las CA del sistema. Es lo que STARTTLS existe
        # para garantizar; sin `context` smtplib cifra pero no verifica.
        contexto = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=SMTP_TIMEOUT_SEGUNDOS) as server:
            server.starttls(context=contexto)
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
    except Exception as exc:
        # Se registra la CLASE del error y su texto, nunca las credenciales.
        # `smtplib` no las incluye en sus excepciones, pero no se confía en
        # eso: el mensaje se arma acá con lo que se decide mostrar.
        logger.warning(
            "Envío FALLIDO: análisis=%s usuario=%s destino=%s error=%s: %s",
            analysis_id, usuario, to_email, type(exc).__name__, exc,
        )
        return False

    logger.info(
        "Informe enviado: análisis=%s usuario=%s destino=%s adjunto=%s",
        analysis_id, usuario, to_email, pdf_filename if pdf_bytes else "ninguno",
    )
    return True
