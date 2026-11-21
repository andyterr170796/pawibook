# Pawbook 🐾

Red social para mascotas y entidades (veterinarias, tiendas, refugios, restaurantes pet friendly…): perfiles, amigos, búsqueda, pareja, calendario con alertas, mapa, perdidos y encontrados, anuncios y el asistente **Pawi**.

FastAPI + SQLite + Jinja2, sin paso de compilación. Corre en una PC y se publica con ngrok.

## Ejecutar

1. Instala Python 3.11 o superior.
2. Copia `.env.example` como `.env` y completa lo que uses (OpenAI para Pawi, Resend para correos).
3. Doble clic en `iniciar_local.bat` (http://localhost:8001) o en `iniciar_ngrok.bat` (enlace público https).

La primera vez instala las dependencias de `requirements.txt` y crea la base `pawbook.db` con una cuenta administradora (`credenciales_admin.txt`) y datos de demostración (`PAWBOOK_DEMO=1`).

## Correos con Resend

Pawbook envía la recuperación de contraseña, la bienvenida y el aviso de "tu contraseña cambió".

1. Crea una API key en [resend.com/api-keys](https://resend.com/api-keys) y ponla en `.env` como `RESEND_API_KEY`.
2. Verifica tu dominio en Resend (Domains) y define el remitente: `RESEND_FROM=Pawbook <notificaciones@tu-dominio.com>`.
   Sin dominio verificado se usa `onboarding@resend.dev`, que solo entrega al correo dueño de la cuenta de Resend.
3. Prueba el envío: `python correos.py tu@correo.com`.

Los enlaces de los correos apuntan al túnel de ngrok activo o a `PAWBOOK_URL_PUBLICA`; nunca se arman con la cabecera `Host` de la petición.

## Seguridad

- Cabeceras de seguridad (CSP `frame-ancestors`/`form-action`, `nosniff`, `X-Frame-Options`, `Referrer-Policy`, HSTS por HTTPS).
- Todo envío que cambia datos y viene de otro sitio se rechaza (CSRF); la cookie de sesión es `HttpOnly`, `SameSite=Lax` y `Secure` por HTTPS.
- Límite de intentos: inicio de sesión, registro, recuperación de contraseña y mensajes a Pawi.
- Contraseñas con PBKDF2-SHA256 (600 000 iteraciones), política mínima y cierre de las demás sesiones al cambiarlas.
- Recuperación con enlace de un solo uso (60 min); solo se guarda su hash. La respuesta es la misma exista o no la cuenta.
- Fotos: solo JPEG/PNG/WEBP/GIF reales, máximo 10 MB y 40 MP; se re-guardan como WebP sin metadatos (EXIF/GPS).
- Coordenadas de mascotas redondeadas (~100 m). Registro de eventos en `logs/seguridad.log`.

Pruebas: `python -m unittest discover -s pruebas -v` (también corren en GitHub Actions en cada push).

## Archivos que nunca van al repositorio

`.env`, `.secret_key`, `credenciales_admin.txt`, `pawbook.db*`, `uploads/` y `logs/` (ver `.gitignore`).
