"""Correos de Pawbook enviados con Resend (https://resend.com), igual que en la Suite Zoria.

Configuración en .env:
    RESEND_API_KEY=re_...                      (secreto: nunca va al código ni a Git)
    RESEND_FROM=Pawbook <notificaciones@tu-dominio.com>   (dominio verificado en Resend)
    RESEND_REPLY_TO=soporte@tu-dominio.com     (opcional: a dónde llegan las respuestas)

Sin dominio verificado, Resend solo entrega desde onboarding@resend.dev y únicamente al correo
dueño de la cuenta de Resend (sirve para probar).

Los correos se envían en un hilo aparte: la página responde enseguida y, en "olvidé mi contraseña",
el tiempo de respuesta no delata si el correo está registrado.
"""
import html
import json
import os
import threading
import urllib.error
import urllib.request
from typing import Optional

import seguridad

API_RESEND = "https://api.resend.com/emails"
REMITENTE_PRUEBAS = "Pawbook <onboarding@resend.dev>"

# Dominios de cuentas ficticias (demo, admin local, ejemplos): enviarles correos solo genera rebotes y
# daña la reputación del remitente en Resend.
DOMINIOS_SIN_ENVIO = {"pawbook.demo", "pawbook.local", "pawbook.pe", "example.com", "example.org",
                      "example.net", "localhost"}
SUFIJOS_SIN_ENVIO = (".local", ".demo", ".test", ".invalid", ".example", ".localhost")

# Estados que devuelve enviar()
ENVIADO, NO_CONFIGURADO, OMITIDO, FALLIDO = "ENVIADO", "NO_CONFIGURADO", "OMITIDO", "FALLIDO"


def _clave() -> str:
    return os.getenv("RESEND_API_KEY", "").strip()


def configurado() -> bool:
    return bool(_clave())


def remitente() -> str:
    return os.getenv("RESEND_FROM", "").strip() or REMITENTE_PRUEBAS


def es_destino_entregable(email: str) -> bool:
    email = (email or "").strip().lower()
    if email.count("@") != 1:
        return False
    dominio = email.split("@", 1)[1]
    return bool(dominio) and dominio not in DOMINIOS_SIN_ENVIO and not dominio.endswith(SUFIJOS_SIN_ENVIO)


def enviar(destino: str, asunto: str, html_cuerpo: str, texto: str) -> str:
    """Envía un correo con Resend. No lanza excepciones: devuelve el estado y lo registra."""
    if not es_destino_entregable(destino):
        seguridad.registrar("correo_omitido", destino=seguridad.ocultar_email(destino), asunto=asunto)
        return OMITIDO
    if not configurado():
        seguridad.registrar("correo_no_configurado", destino=seguridad.ocultar_email(destino), asunto=asunto)
        return NO_CONFIGURADO
    datos = {"from": remitente(), "to": [destino], "subject": asunto, "html": html_cuerpo, "text": texto}
    responder_a = os.getenv("RESEND_REPLY_TO", "").strip()
    if responder_a:
        datos["reply_to"] = responder_a
    peticion = urllib.request.Request(
        API_RESEND, data=json.dumps(datos).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {_clave()}", "Content-Type": "application/json",
                 "User-Agent": "Pawbook/1.0"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
            r.read()
        seguridad.registrar("correo_enviado", destino=seguridad.ocultar_email(destino), asunto=asunto)
        return ENVIADO
    except urllib.error.HTTPError as e:
        detalle = e.read()[:300].decode("utf-8", "replace")
        seguridad.registrar("correo_fallido", destino=seguridad.ocultar_email(destino), asunto=asunto,
                            estado=e.code, detalle=detalle)
        print(f"  [correo] Resend rechazó el envío ({e.code}): {detalle}")
    except Exception as e:  # red caída, DNS, tiempo de espera
        seguridad.registrar("correo_fallido", destino=seguridad.ocultar_email(destino), asunto=asunto,
                            detalle=type(e).__name__)
        print(f"  [correo] No se pudo enviar con Resend: {type(e).__name__}")
    return FALLIDO


def enviar_en_segundo_plano(destino: str, asunto: str, html_cuerpo: str, texto: str):
    threading.Thread(target=enviar, args=(destino, asunto, html_cuerpo, texto), daemon=True).start()


# =================================================================== plantillas

def _plantilla(titulo: str, cuerpo_html: str, url_base: str) -> str:
    """Marco común: cabecera con los colores del logo y pie de correo de servicio."""
    inicio = html.escape(url_base or "")
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;background:#F4F7FC;padding:24px 12px">
  <div style="font-family:Arial,Helvetica,sans-serif;color:#162034;max-width:560px;margin:auto">
    <div style="background:#023E90;color:#fff;padding:22px 24px;border-radius:14px 14px 0 0">
      <div style="font-size:22px;font-weight:700">🐾 Paw<span style="color:#F5A301">book</span></div>
      <div style="margin-top:6px;font-size:17px">{html.escape(titulo)}</div>
    </div>
    <div style="background:#fff;padding:24px;border:1px solid #E3E8F1;border-top:0;border-radius:0 0 14px 14px;
                font-size:15px;line-height:1.55">
      {cuerpo_html}
    </div>
    <p style="color:#8792A4;font-size:12px;line-height:1.5;margin:14px 6px 0">
      Correo de servicio de Pawbook: lo recibes por tu cuenta, no es publicidad.
      {f'<a href="{inicio}" style="color:#535E70">{inicio}</a>' if inicio else ''}
    </p>
  </div>
</body></html>"""


def _boton(texto: str, enlace: str) -> str:
    return (f'<p style="margin:22px 0"><a href="{html.escape(enlace)}" style="display:inline-block;padding:12px 20px;'
            f'border-radius:10px;background:#F5A301;color:#0A1F44;text-decoration:none;font-weight:700">'
            f'{html.escape(texto)}</a></p>')


def correo_recuperacion(nombre: str, enlace: str, minutos: int, url_base: str) -> tuple:
    asunto = "Restablece tu contraseña de Pawbook"
    cuerpo = (
        f"<p>Hola {html.escape(nombre)}, recibimos una solicitud para cambiar la contraseña de tu cuenta.</p>"
        + _boton("Crear nueva contraseña", enlace)
        + f'<p style="color:#535E70;font-size:13px">El enlace vence en {minutos} minutos y solo se puede usar una vez. '
          "Si no lo pediste tú, ignora este mensaje: tu contraseña no cambiará.</p>"
          f'<p style="color:#8792A4;font-size:12px;word-break:break-all">Si el botón no funciona, copia este enlace:<br>'
          f"{html.escape(enlace)}</p>"
    )
    texto = (f"Hola {nombre},\n\nRestablece tu contraseña de Pawbook aquí:\n{enlace}\n\n"
             f"El enlace vence en {minutos} minutos y solo se puede usar una vez. "
             "Si no lo pediste tú, ignora este mensaje.")
    return asunto, _plantilla("Restablecer contraseña", cuerpo, url_base), texto


def correo_bienvenida(nombre: str, url_base: str) -> tuple:
    asunto = "¡Bienvenido a Pawbook! 🐾"
    enlace = f"{url_base}/perfil/nuevo"
    cuerpo = (
        f"<p>Hola {html.escape(nombre)}, ¡qué bueno tenerte en Pawbook!</p>"
        "<p>Crea el perfil de tu mascota para hacer amigos en tu barrio, llevar su calendario de vacunas y "
        "citas, y recibir alertas de mascotas perdidas cerca de ti.</p>"
        + _boton("Crear el perfil de mi mascota", enlace)
        + '<p style="color:#535E70;font-size:13px">Si no creaste esta cuenta, escríbenos respondiendo este correo.</p>'
    )
    texto = (f"Hola {nombre}, ¡bienvenido a Pawbook!\n\nCrea el perfil de tu mascota aquí:\n{enlace}\n\n"
             "Si no creaste esta cuenta, responde este correo.")
    return asunto, _plantilla("Tu cuenta está lista", cuerpo, url_base), texto


def correo_password_cambiada(nombre: str, url_base: str) -> tuple:
    asunto = "Tu contraseña de Pawbook cambió"
    enlace = f"{url_base}/recuperar"
    cuerpo = (
        f"<p>Hola {html.escape(nombre)}, la contraseña de tu cuenta de Pawbook acaba de cambiar y cerramos las "
        "sesiones abiertas en otros dispositivos.</p>"
        "<p><b>¿No fuiste tú?</b> Restablece tu contraseña ahora mismo:</p>"
        + _boton("Restablecer contraseña", enlace)
    )
    texto = (f"Hola {nombre}, la contraseña de tu cuenta de Pawbook acaba de cambiar.\n\n"
             f"Si no fuiste tú, restablécela ahora: {enlace}")
    return asunto, _plantilla("Aviso de seguridad", cuerpo, url_base), texto


def enviar_prueba(destino: str, url_base: str = "") -> str:
    cuerpo = "<p>Si lees esto, Pawbook ya puede enviar correos con Resend. ✅</p>"
    return enviar(destino, "Prueba de correo de Pawbook", _plantilla("Prueba de envío", cuerpo, url_base),
                  "Si lees esto, Pawbook ya puede enviar correos con Resend.")


if __name__ == "__main__":
    # Comprueba la configuración:  python correos.py tu@correo.com
    import sys

    from utilidades import cargar_env

    cargar_env()
    if len(sys.argv) != 2:
        sys.exit("Uso: python correos.py tu@correo.com")
    print("Remitente:", remitente(), "| Resend configurado:", "sí" if configurado() else "no (falta RESEND_API_KEY)")
    print("Resultado:", enviar_prueba(sys.argv[1]))
