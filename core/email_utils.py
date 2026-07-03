"""
Utilidad de Envío de Correo
===========================

Envío de correos usando smtplib (biblioteca estándar) de forma asíncrona
mediante asyncio.to_thread. Si SMTP no está configurado, registra el contenido
en los logs (fallback de desarrollo) en lugar de fallar.
"""

import asyncio
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from core.config import settings


def _smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)


def _send_sync(to_email: str, subject: str, html_body: str) -> bool:
    if not _smtp_configured():
        # Fallback de desarrollo: no hay SMTP, se registra en consola para pruebas
        print("=" * 70)
        print(f"[EMAIL:DEV] SMTP no configurado. Correo NO enviado a: {to_email}")
        print(f"[EMAIL:DEV] Asunto: {subject}")
        print(f"[EMAIL:DEV] Contenido HTML:\n{html_body}")
        print("=" * 70)
        return False

    from_addr = settings.SMTP_FROM or settings.SMTP_USER
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{from_addr}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    if settings.SMTP_USE_TLS:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
            server.starttls(context=context)
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(from_addr, [to_email], msg.as_string())
    else:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=20) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(from_addr, [to_email], msg.as_string())
    return True


async def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Envía un correo de forma asíncrona. Devuelve True si se envió por SMTP."""
    try:
        return await asyncio.to_thread(_send_sync, to_email, subject, html_body)
    except Exception as e:
        print(f"[EMAIL:ERROR] No se pudo enviar el correo a {to_email}: {e}")
        return False


def build_password_reset_email(nombre: str, reset_link: str, minutos: int) -> str:
    """Plantilla HTML del correo de restablecimiento de contraseña (marca UAGRM)."""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 520px; margin: 0 auto; color: #1f2937;">
      <div style="background: #8a1f2f; padding: 20px; text-align: center; border-radius: 12px 12px 0 0;">
        <h1 style="color: #ffffff; margin: 0; font-size: 18px;">Escuela de Postgrado · UAGRM</h1>
        <p style="color: #f3d2d7; margin: 4px 0 0; font-size: 13px;">Contaduría Pública</p>
      </div>
      <div style="border: 1px solid #e5e7eb; border-top: none; padding: 24px; border-radius: 0 0 12px 12px;">
        <p style="font-size: 15px;">Hola <strong>{nombre}</strong>,</p>
        <p style="font-size: 14px; line-height: 1.6;">
          Recibimos una solicitud para restablecer la contraseña de tu cuenta.
          Haz clic en el siguiente botón para crear una nueva contraseña:
        </p>
        <div style="text-align: center; margin: 24px 0;">
          <a href="{reset_link}" style="background: #8a1f2f; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
            Restablecer contraseña
          </a>
        </div>
        <p style="font-size: 12px; color: #6b7280; line-height: 1.6;">
          Este enlace vence en {minutos} minutos. Si no solicitaste este cambio, ignora este correo.
        </p>
        <p style="font-size: 12px; color: #9ca3af; word-break: break-all;">
          Si el botón no funciona, copia y pega este enlace:<br />{reset_link}
        </p>
      </div>
    </div>
    """
