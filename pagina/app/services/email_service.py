"""
email_service.py — Envía el informe PDF por mail.

Usa SMTP con STARTTLS y verifica el certificado del servidor, así el PDF
(que lleva la radiografía) viaja cifrado y a quien corresponde. Cada envío
queda anotado en el log: análisis, usuario, destino y resultado. Nunca la
contraseña.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from config.settings import APP_NAME, SMTP_EMAIL, SMTP_PASSWORD, SMTP_PORT, SMTP_SERVER

logger = logging.getLogger("traumavision.email")


def enviar_informe(destino: str, analysis_id: int, usuario: str, pdf: bytes) -> bool:
    """Manda el PDF como adjunto. Devuelve True si salió bien."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        return False

    mensaje = EmailMessage()
    mensaje["From"] = f"{APP_NAME} <{SMTP_EMAIL}>"
    mensaje["To"] = destino
    mensaje["Subject"] = f"Informe TraumaVision #{analysis_id}"
    mensaje.set_content(
        f"Te comparto el informe del análisis #{analysis_id}, generado por {usuario}.\n\n"
        "Es un resultado automatizado de soporte a la decisión clínica: "
        "debe confirmarse con lectura médica.\n"
    )
    mensaje.add_attachment(pdf, maintype="application", subtype="pdf",
                           filename=f"traumavision_informe_{analysis_id}.pdf")

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as servidor:
            servidor.starttls(context=ssl.create_default_context())
            servidor.login(SMTP_EMAIL, SMTP_PASSWORD)
            servidor.send_message(mensaje)
    except Exception as error:
        logger.warning("Envío fallido: análisis=%s usuario=%s destino=%s error=%s",
                       analysis_id, usuario, destino, type(error).__name__)
        return False

    logger.info("Informe enviado: análisis=%s usuario=%s destino=%s", analysis_id, usuario, destino)
    return True
