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
        <h1 style="color: #ffffff; margin: 0; font-size: 18px;">Escuela de Posgrado · UAGRM</h1>
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


def build_email_verification_email(nombre: str, verify_link: str, horas: int) -> str:
    """Plantilla HTML del correo de verificación de correo (ISSUE-A-VERIFICACION)."""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 520px; margin: 0 auto; color: #1f2937;">
      <div style="background: #8a1f2f; padding: 20px; text-align: center; border-radius: 12px 12px 0 0;">
        <h1 style="color: #ffffff; margin: 0; font-size: 18px;">Escuela de Posgrado · UAGRM</h1>
        <p style="color: #f3d2d7; margin: 4px 0 0; font-size: 13px;">Contaduría Pública</p>
      </div>
      <div style="border: 1px solid #e5e7eb; border-top: none; padding: 24px; border-radius: 0 0 12px 12px;">
        <p style="font-size: 15px;">Hola <strong>{nombre}</strong>,</p>
        <p style="font-size: 14px; line-height: 1.6;">
          Confirma que este es tu correo electrónico haciendo clic en el siguiente botón.
          Así podremos contactarte de forma confiable sobre tus inscripciones, pagos y notificaciones importantes.
        </p>
        <div style="text-align: center; margin: 24px 0;">
          <a href="{verify_link}" style="background: #8a1f2f; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
            Verificar mi correo
          </a>
        </div>
        <p style="font-size: 12px; color: #6b7280; line-height: 1.6;">
          Este enlace vence en {horas} horas. Si no reconoces esta solicitud, puedes ignorar este correo con seguridad
          (tu cuenta seguirá funcionando normalmente sin la verificación).
        </p>
        <p style="font-size: 12px; color: #9ca3af; word-break: break-all;">
          Si el botón no funciona, copia y pega este enlace:<br />{verify_link}
        </p>
      </div>
    </div>
    """


def build_nota_validada_email(nombre: str, curso_nombre: str, modulo_nombre: str, nota: float, portal_link: str) -> str:
    """Plantilla HTML del correo de notificación al estudiante cuando CPD valida su nota (ISSUE-Q-CORREO-NOTA)."""
    aprobado = nota >= 64.0
    color_estado = "#008244" if aprobado else "#C8102E"
    texto_estado = "Aprobado" if aprobado else "Reprobado"
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 520px; margin: 0 auto; color: #1f2937;">
      <div style="background: #8a1f2f; padding: 20px; text-align: center; border-radius: 12px 12px 0 0;">
        <h1 style="color: #ffffff; margin: 0; font-size: 18px;">Escuela de Posgrado · UAGRM</h1>
        <p style="color: #f3d2d7; margin: 4px 0 0; font-size: 13px;">Contaduría Pública</p>
      </div>
      <div style="border: 1px solid #e5e7eb; border-top: none; padding: 24px; border-radius: 0 0 12px 12px;">
        <p style="font-size: 15px;">Hola <strong>{nombre}</strong>,</p>
        <p style="font-size: 14px; line-height: 1.6;">
          Tu calificación del módulo <strong>{modulo_nombre}</strong> del programa
          <strong>{curso_nombre}</strong> ya fue validada oficialmente por Gestión Académica (CPD).
        </p>
        <div style="background: #f9fafb; border-radius: 10px; padding: 16px; margin: 20px 0; text-align: center;">
          <p style="margin: 0 0 6px; font-size: 13px; color: #6b7280;">Calificación oficial</p>
          <p style="margin: 0; font-size: 28px; font-weight: bold; color: {color_estado};">{nota:.2f}</p>
          <p style="margin: 6px 0 0; font-size: 13px; font-weight: bold; color: {color_estado};">{texto_estado}</p>
        </div>
        <div style="text-align: center; margin: 24px 0;">
          <a href="{portal_link}" style="background: #8a1f2f; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
            Ver mi libreta
          </a>
        </div>
      </div>
    </div>
    """


def build_recordatorio_pago_email(nombre: str, mensaje: str, portal_link: str) -> str:
    """Plantilla HTML del recordatorio de pago manual enviado por Cobranza (ISSUE-P-RECORDATORIO-PAGO)."""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 520px; margin: 0 auto; color: #1f2937;">
      <div style="background: #8a1f2f; padding: 20px; text-align: center; border-radius: 12px 12px 0 0;">
        <h1 style="color: #ffffff; margin: 0; font-size: 18px;">Escuela de Posgrado · UAGRM</h1>
        <p style="color: #f3d2d7; margin: 4px 0 0; font-size: 13px;">Contaduría Pública</p>
      </div>
      <div style="border: 1px solid #e5e7eb; border-top: none; padding: 24px; border-radius: 0 0 12px 12px;">
        <p style="font-size: 15px;">Hola <strong>{nombre}</strong>,</p>
        <p style="font-size: 14px; line-height: 1.6;">
          El área de Cobranzas de Posgrado te envía el siguiente recordatorio:
        </p>
        <div style="background: #f9fafb; border-left: 4px solid #8a1f2f; border-radius: 8px; padding: 16px; margin: 20px 0;">
          <p style="margin: 0; font-size: 14px; line-height: 1.6; white-space: pre-line;">{mensaje}</p>
        </div>
        <div style="text-align: center; margin: 24px 0;">
          <a href="{portal_link}" style="background: #8a1f2f; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
            Ir a Mis Pagos
          </a>
        </div>
      </div>
    </div>
    """


def build_pago_aprobado_email(nombre: str, concepto: str, monto: float, portal_link: str) -> str:
    """Plantilla HTML del correo al estudiante cuando su pago es aprobado/conciliado."""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 520px; margin: 0 auto; color: #1f2937;">
      <div style="background: #8a1f2f; padding: 20px; text-align: center; border-radius: 12px 12px 0 0;">
        <h1 style="color: #ffffff; margin: 0; font-size: 18px;">Escuela de Posgrado · UAGRM</h1>
        <p style="color: #f3d2d7; margin: 4px 0 0; font-size: 13px;">Contaduría Pública</p>
      </div>
      <div style="border: 1px solid #e5e7eb; border-top: none; padding: 24px; border-radius: 0 0 12px 12px;">
        <p style="font-size: 15px;">Hola <strong>{nombre}</strong>,</p>
        <p style="font-size: 14px; line-height: 1.6;">
          Tu pago fue <strong style="color: #008244;">aprobado y conciliado</strong> correctamente.
        </p>
        <div style="background: #f9fafb; border-radius: 10px; padding: 16px; margin: 18px 0;">
          <p style="margin: 0 0 6px; font-size: 13px; color: #6b7280;">Concepto</p>
          <p style="margin: 0 0 12px; font-size: 16px; font-weight: bold;">{concepto}</p>
          <p style="margin: 0 0 6px; font-size: 13px; color: #6b7280;">Monto</p>
          <p style="margin: 0; font-size: 18px; font-weight: bold; color: #008244;">Bs {monto:,.2f}</p>
        </div>
        <div style="text-align: center; margin: 24px 0;">
          <a href="{portal_link}" style="background: #8a1f2f; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
            Ver Mis Pagos
          </a>
        </div>
        <p style="font-size: 12px; color: #9ca3af;">Si no reconoces este pago, contacta con la unidad de Posgrado.</p>
      </div>
    </div>
    """


def build_comunicado_email(nombre: str, asunto: str, mensaje: str, programa: str, portal_link: str) -> str:
    """Plantilla HTML de un comunicado del Encargado de Programa/CPD a los estudiantes."""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 520px; margin: 0 auto; color: #1f2937;">
      <div style="background: #8a1f2f; padding: 20px; text-align: center; border-radius: 12px 12px 0 0;">
        <h1 style="color: #ffffff; margin: 0; font-size: 18px;">Escuela de Posgrado · UAGRM</h1>
        <p style="color: #f3d2d7; margin: 4px 0 0; font-size: 13px;">Contaduría Pública</p>
      </div>
      <div style="border: 1px solid #e5e7eb; border-top: none; padding: 24px; border-radius: 0 0 12px 12px;">
        <p style="margin: 0 0 4px; font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: .5px;">Programa: {programa}</p>
        <h2 style="margin: 0 0 16px; font-size: 17px; color: #8a1f2f;">{asunto}</h2>
        <p style="font-size: 15px;">Hola <strong>{nombre}</strong>,</p>
        <div style="background: #f9fafb; border-left: 4px solid #8a1f2f; border-radius: 8px; padding: 16px; margin: 16px 0;">
          <p style="margin: 0; font-size: 14px; line-height: 1.6; white-space: pre-line;">{mensaje}</p>
        </div>
        <div style="text-align: center; margin: 24px 0;">
          <a href="{portal_link}" style="background: #8a1f2f; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
            Ingresar al Portal
          </a>
        </div>
        <p style="font-size: 12px; color: #9ca3af;">Este es un comunicado institucional de la Unidad de Posgrado.</p>
      </div>
    </div>
    """


def build_enrollment_approved_email(nombre: str, curso_nombre: str, total_a_pagar: float, matricula: float, portal_link: str) -> str:
    """Plantilla HTML del correo de aprobación de inscripción (ISSUE-R-SOLICITUD-INSCRIPCION)."""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 520px; margin: 0 auto; color: #1f2937;">
      <div style="background: #8a1f2f; padding: 20px; text-align: center; border-radius: 12px 12px 0 0;">
        <h1 style="color: #ffffff; margin: 0; font-size: 18px;">Escuela de Posgrado · UAGRM</h1>
        <p style="color: #f3d2d7; margin: 4px 0 0; font-size: 13px;">Contaduría Pública</p>
      </div>
      <div style="border: 1px solid #e5e7eb; border-top: none; padding: 24px; border-radius: 0 0 12px 12px;">
        <p style="font-size: 15px;">Hola <strong>{nombre}</strong>,</p>
        <p style="font-size: 14px; line-height: 1.6;">
          Tu solicitud de inscripción al programa <strong>{curso_nombre}</strong> fue
          <strong style="color: #008244;">aprobada</strong>. Ya puedes ingresar al portal para
          revisar tus módulos y proceder con el pago de tu matrícula.
        </p>
        <div style="background: #f9fafb; border-radius: 10px; padding: 16px; margin: 20px 0;">
          <p style="margin: 0 0 6px; font-size: 13px; color: #6b7280;">Matrícula institucional</p>
          <p style="margin: 0 0 12px; font-size: 18px; font-weight: bold; color: #1f2937;">Bs {matricula:,.2f}</p>
          <p style="margin: 0 0 6px; font-size: 13px; color: #6b7280;">Inversión total del programa</p>
          <p style="margin: 0; font-size: 18px; font-weight: bold; color: #1f2937;">Bs {total_a_pagar:,.2f}</p>
        </div>
        <p style="font-size: 13px; color: #6b7280; line-height: 1.6;">
          Recuerda que el acceso académico completo se habilita una vez cancelada la matrícula.
        </p>
        <div style="text-align: center; margin: 24px 0;">
          <a href="{portal_link}" style="background: #8a1f2f; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
            Ir al Portal
          </a>
        </div>
      </div>
    </div>
    """
