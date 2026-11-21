"""Protecciones HTTP de Pawbook (mismo esquema que la Suite Zoria).

- Cabeceras de seguridad en todas las respuestas (nosniff, marco, referer, CSP, HSTS en HTTPS).
- Rechazo de peticiones que cambian datos y vienen de otro sitio (CSRF): la cookie de sesión ya es
  SameSite=Lax; esto agrega una segunda barrera mirando Origin / Sec-Fetch-Site.
- Límite de tamaño del cuerpo de las peticiones (antes de que se guarde un archivo enorme).
- Cookie de sesión con Secure cuando la visita llega por HTTPS (ngrok), sin romper http://localhost.
- Límite de intentos en memoria (login, recuperación de contraseña, Pawi...).
- Política de contraseñas y registro de eventos de seguridad en logs/seguridad.log.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from typing import Optional
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.responses import HTMLResponse, JSONResponse

METODOS_QUE_CAMBIAN = {"POST", "PUT", "PATCH", "DELETE"}

# Los scripts en línea siguen permitidos (las plantillas los usan); esto impide incrustar Pawbook en otros
# sitios, plugins, <base> ajeno y formularios que envíen a otro dominio.
CONTENT_SECURITY_POLICY = "frame-ancestors 'self'; base-uri 'self'; object-src 'none'; form-action 'self'"
# La ubicación la usan el mapa y los formularios ("usar mi ubicación"); lo demás no se necesita.
PERMISSIONS_POLICY = "geolocation=(self), camera=(), microphone=(), payment=(), usb=()"

MAX_CUERPO_MB = int(os.getenv("PAWBOOK_MAX_SUBIDA_MB", "25"))


# =================================================================== registro de seguridad

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_log = logging.getLogger("pawbook.seguridad")


def _configurar_log():
    if _log.handlers:
        return
    _log.setLevel(logging.INFO)
    _log.propagate = False
    try:
        carpeta = os.getenv("PAWBOOK_LOGS") or os.path.join(BASE_DIR, "logs")
        os.makedirs(carpeta, exist_ok=True)
        manejador = RotatingFileHandler(os.path.join(carpeta, "seguridad.log"), maxBytes=1024 * 1024,
                                        backupCount=3, encoding="utf-8")
    except OSError:
        manejador = logging.StreamHandler()
    manejador.setFormatter(logging.Formatter("[%(asctime)s] %(message)s"))
    _log.addHandler(manejador)


def ocultar_email(email: str) -> str:
    """a***@gmail.com: suficiente para revisar un incidente sin guardar el correo completo."""
    email = (email or "").strip()
    if "@" not in email:
        return email[:2] + "***" if email else ""
    usuario, dominio = email.split("@", 1)
    return f"{usuario[:1]}***@{dominio[:60]}"


def registrar(evento: str, request: Optional[Request] = None, **datos):
    """Escribe un evento de seguridad (login fallido, bloqueo, recuperación...)."""
    _configurar_log()
    partes = [evento]
    if request is not None:
        partes.append(f"ip={ip_cliente(request)}")
    partes += [f"{k}={str(v)[:120]}" for k, v in datos.items() if v is not None]
    _log.info(" ".join(partes))


# =================================================================== IP y límite de intentos

def ip_cliente(request: Request) -> str:
    """IP de quien hace la petición.

    Uvicorn solo confía en X-Forwarded-For cuando la conexión viene del propio equipo (el agente de
    ngrok), así que request.client ya trae la IP real del visitante y no un valor inventado por él.
    """
    return (request.client.host if request.client else "desconocida")[:64]


def huella(valor: str) -> str:
    """Resumen corto para usar un correo como clave del límite sin guardarlo tal cual."""
    return hashlib.sha256((valor or "").strip().casefold().encode("utf-8", "ignore")).hexdigest()[:32]


@dataclass(frozen=True)
class Regla:
    ambito: str
    limite: int
    ventana_seg: int


class LimitadorEnMemoria:
    """Ventana fija por (ámbito, clave). Sirve para una sola instancia del servidor, que es como corre
    Pawbook (un proceso local publicado con ngrok)."""

    def __init__(self) -> None:
        self._cubetas: dict[tuple[str, str, int, int], int] = {}
        self._candado = threading.Lock()
        self._consultas = 0

    def consumir(self, regla: Regla, clave: str) -> tuple[bool, int]:
        ahora = time.time()
        ventana = int(ahora // regla.ventana_seg)
        cubeta = (regla.ambito, clave, regla.ventana_seg, ventana)
        reintentar = max(1, math.ceil(regla.ventana_seg - (ahora % regla.ventana_seg)))
        with self._candado:
            self._consultas += 1
            cuenta = self._cubetas.get(cubeta, 0) + 1
            self._cubetas[cubeta] = cuenta
            if self._consultas % 1000 == 0:  # limpia ventanas viejas
                self._cubetas = {c: v for c, v in self._cubetas.items() if c[3] >= int(ahora // c[2]) - 1}
        return cuenta <= regla.limite, reintentar

    def reiniciar(self):
        with self._candado:
            self._cubetas.clear()


limitador = LimitadorEnMemoria()

MENSAJE_LIMITE = "Demasiados intentos. Espera un momento antes de volver a intentarlo."


def limitar(request: Request, ambito: str, clave: str, limite: int, ventana_seg: int,
            mensaje: str = MENSAJE_LIMITE):
    """Lanza 429 si `clave` superó `limite` intentos en la ventana."""
    permitido, reintentar = limitador.consumir(Regla(ambito, limite, ventana_seg), clave)
    if not permitido:
        registrar("limite_superado", request, ambito=ambito)
        raise HTTPException(429, mensaje, headers={"Retry-After": str(reintentar)})


# =================================================================== contraseñas

PASSWORD_MIN = 8
PASSWORD_MAX = 128


def error_password(password: str) -> Optional[str]:
    """Reglas para toda contraseña que elige una persona. Devuelve el problema o None."""
    if len(password) < PASSWORD_MIN:
        return f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres."
    if len(password) > PASSWORD_MAX:
        return f"La contraseña es demasiado larga (máximo {PASSWORD_MAX} caracteres)."
    if not any(c.isupper() for c in password):
        return "Incluye al menos una letra mayúscula en la contraseña."
    if not any(c.islower() for c in password):
        return "Incluye al menos una letra minúscula en la contraseña."
    if not any(c.isdigit() for c in password):
        return "Incluye al menos un número en la contraseña."
    return None


# =================================================================== origen (CSRF)

def es_origen_ajeno(request: Request, permitidos: set) -> bool:
    origen = request.headers.get("origin")
    if origen:
        if origen.strip().lower() == "null":  # iframes con sandbox, redirecciones raras
            return True
        netloc = urlsplit(origen).netloc.lower()
        propios = {request.headers.get("host", "").lower(), request.headers.get("x-forwarded-host", "").lower()}
        if netloc and netloc in propios - {""}:
            return False
        return origen.rstrip("/").lower() not in permitidos
    # Sin Origin (herramientas, pruebas): los navegadores actuales igual avisan si viene de otro sitio.
    return request.headers.get("sec-fetch-site", "").lower() == "cross-site"


def instalar_protecciones(app, origenes_permitidos: set):
    """Cabeceras de seguridad, rechazo de otros orígenes y límite general de escrituras por IP."""

    @app.middleware("http")
    async def _cabeceras_y_origen(request: Request, call_next):
        if request.method in METODOS_QUE_CAMBIAN:
            if es_origen_ajeno(request, origenes_permitidos):
                registrar("origen_rechazado", request, ruta=request.url.path,
                          origen=request.headers.get("origin") or request.headers.get("sec-fetch-site"))
                return JSONResponse({"detail": "Solicitud rechazada: origen no permitido."}, status_code=403)
            permitido, reintentar = limitador.consumir(Regla("escritura", 120, 60), ip_cliente(request))
            if not permitido:
                registrar("limite_superado", request, ambito="escritura")
                return JSONResponse({"detail": MENSAJE_LIMITE}, status_code=429,
                                    headers={"Retry-After": str(reintentar)})
        respuesta = await call_next(request)
        h = respuesta.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        h.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.url.scheme == "https":
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return respuesta


# =================================================================== middlewares ASGI

class LimiteCuerpo:
    """Corta peticiones cuyo cuerpo supera MAX_CUERPO_MB (las fotos se validan aparte, a 10 MB c/u)."""

    def __init__(self, app, max_bytes: int = MAX_CUERPO_MB * 1024 * 1024):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cabeceras = dict(scope.get("headers") or [])
        largo = cabeceras.get(b"content-length", b"").strip()
        if largo:
            if largo.isdigit() and int(largo) > self.max_bytes:
                return await self._demasiado_grande(scope, receive, send)
            # Con Content-Length el servidor (uvicorn) no entrega más bytes que los anunciados.
            return await self.app(scope, receive, send)
        if b"transfer-encoding" not in cabeceras:
            return await self.app(scope, receive, send)  # sin cuerpo
        # Cuerpo "por partes" (chunked): se lee hasta el tope antes de pasar la petición a la app.
        mensajes, total = [], 0
        while True:
            mensaje = await receive()
            if mensaje["type"] != "http.request":
                mensajes.append(mensaje)
                break
            total += len(mensaje.get("body", b""))
            if total > self.max_bytes:
                return await self._demasiado_grande(scope, receive, send)
            mensajes.append(mensaje)
            if not mensaje.get("more_body"):
                break

        async def repetir():
            return mensajes.pop(0) if mensajes else await receive()

        await self.app(scope, repetir, send)

    def _texto(self):
        return (f"El envío es demasiado grande (máximo {max(1, self.max_bytes // (1024 * 1024))} MB). "
                "Vuelve atrás e intenta con fotos más livianas.")

    async def _demasiado_grande(self, scope, receive, send):
        if scope.get("path", "").startswith("/api/"):
            respuesta = JSONResponse({"detail": self._texto()}, status_code=413)
        else:
            respuesta = HTMLResponse(
                '<!doctype html><html lang="es"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                "<title>Envío demasiado grande · Pawbook</title>"
                '<body style="font-family:system-ui,sans-serif;color:#162034;max-width:560px;margin:60px auto;'
                'padding:0 16px"><h1 style="color:#023E90">El envío es demasiado grande</h1>'
                f"<p>{self._texto()}</p>"
                '<p><a href="/" style="color:#023E90;font-weight:700">Volver al inicio</a></p></body></html>',
                status_code=413)
        respuesta.headers["Connection"] = "close"
        await respuesta(scope, receive, send)


class CookieSegura:
    """Agrega `Secure` a la cookie de sesión cuando la visita llega por HTTPS.

    Starlette solo permite fijarlo para siempre (https_only); Pawbook se usa a la vez en
    http://localhost y por ngrok (https), así que se decide en cada respuesta.
    """

    def __init__(self, app, nombre_cookie: str):
        self.app = app
        self.prefijo = nombre_cookie.encode("latin-1") + b"="

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("scheme") != "https":
            return await self.app(scope, receive, send)

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                cabeceras = []
                for nombre, valor in mensaje.get("headers", []):
                    if (nombre.lower() == b"set-cookie" and valor.startswith(self.prefijo)
                            and b"secure" not in valor.lower()):
                        valor += b"; secure"
                    cabeceras.append((nombre, valor))
                mensaje["headers"] = cabeceras
            await send(mensaje)

        await self.app(scope, receive, enviar)
