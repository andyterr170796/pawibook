"""Funciones de apoyo: contraseñas, imágenes, fechas, distancias, avatares."""
import hashlib
import hmac
import io
import math
import os
import re
import secrets
import unicodedata
import uuid
import warnings
from datetime import date, datetime

from markupsafe import Markup, escape
from PIL import Image, ImageOps

from catalogos import CATEGORIAS_ENTIDAD, ESPECIES, ICONOS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.abspath(os.getenv("PAWBOOK_UPLOADS") or os.path.join(BASE_DIR, "uploads"))
MAX_BYTES_IMAGEN = 10 * 1024 * 1024  # 10 MB
# Solo formatos de foto comunes. Pillow sabe abrir muchos más (EPS llama a Ghostscript, PSD, TGA...),
# cada uno con su propio historial de fallos: no se le pasa nada que no sea una foto normal.
FORMATOS_IMAGEN = ("JPEG", "PNG", "WEBP", "GIF")
MAX_PIXELES_IMAGEN = 40_000_000  # ~ 8000 x 5000: más que cualquier cámara de celular
Image.MAX_IMAGE_PIXELS = MAX_PIXELES_IMAGEN  # Pillow rechaza "bombas" de descompresión por encima del doble


# ---------------------------------------------------------------- configuración

def cargar_env():
    """Lee el archivo .env (CLAVE=valor) sin dependencias externas."""
    ruta = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            valor = valor.strip().strip('"').strip("'")
            os.environ.setdefault(clave.strip(), valor)


def obtener_secret_key():
    """Clave de sesión: de .env o generada una vez y guardada en .secret_key."""
    clave = os.getenv("PAWBOOK_SECRET_KEY", "").strip()
    if clave:
        # Con una clave corta o de ejemplo cualquiera podría firmar una cookie de sesión ajena.
        if len(clave) < 32:
            raise RuntimeError("PAWBOOK_SECRET_KEY es demasiado corta: usa al menos 32 caracteres aleatorios "
                               "o bórrala del .env para que Pawbook genere una.")
        return clave
    ruta = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return f.read().strip()
    clave = secrets.token_urlsafe(48)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(clave)
    return clave


# ---------------------------------------------------------------- contraseñas

ITERACIONES_PBKDF2 = 600_000  # recomendación OWASP para PBKDF2-HMAC-SHA256
_hash_señuelo = None


def hash_password(password: str) -> str:
    sal = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(sal), ITERACIONES_PBKDF2)
    return f"pbkdf2_sha256${ITERACIONES_PBKDF2}${sal}${dk.hex()}"


def verificar_password(password: str, guardado: str) -> bool:
    try:
        _, iteraciones, sal, hash_hex = guardado.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(sal), int(iteraciones))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def necesita_rehash(guardado: str) -> bool:
    """Hashes creados con menos iteraciones se rehacen la próxima vez que la persona inicia sesión."""
    try:
        return int(guardado.split("$")[1]) < ITERACIONES_PBKDF2
    except (IndexError, ValueError, AttributeError):
        return True


def gastar_verificacion(password: str):
    """Misma demora que una verificación real cuando el correo no existe: sin ella, la respuesta más rápida
    delataría qué correos tienen cuenta."""
    global _hash_señuelo
    if _hash_señuelo is None:
        _hash_señuelo = hash_password(secrets.token_hex(16))
    verificar_password(password, _hash_señuelo)


# ---------------------------------------------------------------- texto

def slugify(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:40] or "perfil"


def contar_palabras(texto: str) -> int:
    return len(re.findall(r"\S+", texto or ""))


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar búsquedas."""
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return texto.lower().strip()


def limpiar_tags(texto: str, maximo: int = 15) -> str:
    vistos, tags = set(), []
    for t in re.split(r"[,#\n]+", texto or ""):
        t = re.sub(r"\s+", " ", t).strip().lower()[:25]
        if t and t not in vistos:
            vistos.add(t)
            tags.append(t)
    return ",".join(tags[:maximo])


def url_segura(url: str) -> str:
    """Acepta solo enlaces http(s); si falta el esquema agrega https://."""
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url[:300]


# ---------------------------------------------------------------- imágenes

async def guardar_imagen(upload, carpeta: str, max_lado: int = 1600, cuadrada: bool = False):
    """Valida y guarda una imagen subida como WebP (sin metadatos EXIF/GPS). Devuelve la ruta pública o None."""
    if upload is None or not getattr(upload, "filename", ""):
        return None
    datos = await upload.read(MAX_BYTES_IMAGEN + 1)
    if not datos:
        return None
    if len(datos) > MAX_BYTES_IMAGEN:
        raise ValueError("La imagen supera los 10 MB.")
    no_valida = "El archivo no es una imagen válida. Usa una foto JPG, PNG, WEBP o GIF."
    muy_grande = "La imagen tiene demasiados píxeles. Usa una foto de menos de 40 megapíxeles."
    try:
        # El formato se decide por el contenido, no por la extensión ni por lo que diga el navegador.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)  # el tope se aplica abajo
            img = Image.open(io.BytesIO(datos), formats=FORMATOS_IMAGEN)
        pixeles = img.width * img.height
    except Image.DecompressionBombError:
        raise ValueError(muy_grande)
    except Exception:
        raise ValueError(no_valida)
    if pixeles > MAX_PIXELES_IMAGEN:  # se mide antes de descomprimir
        raise ValueError(muy_grande)
    try:
        img.load()
    except Exception:
        raise ValueError(no_valida)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    if cuadrada:
        img = ImageOps.fit(img, (max_lado, max_lado), Image.LANCZOS)
    else:
        img.thumbnail((max_lado, max_lado), Image.LANCZOS)
    destino = os.path.join(UPLOADS_DIR, carpeta)
    os.makedirs(destino, exist_ok=True)
    nombre = f"{uuid.uuid4().hex}.webp"
    img.save(os.path.join(destino, nombre), "WEBP", quality=85, method=4)
    return f"/uploads/{carpeta}/{nombre}"


def borrar_archivo(ruta_publica: str):
    if not ruta_publica or not ruta_publica.startswith("/uploads/"):
        return
    ruta = os.path.abspath(os.path.join(UPLOADS_DIR, ruta_publica[len("/uploads/"):]))
    # Solo archivos dentro de uploads/ (nada de "../" ni de carpetas vecinas como "uploads_otra").
    try:
        dentro = os.path.commonpath([ruta, UPLOADS_DIR]) == UPLOADS_DIR and ruta != UPLOADS_DIR
    except ValueError:  # otra unidad de disco
        dentro = False
    if dentro and os.path.isfile(ruta):
        try:
            os.remove(ruta)
        except OSError:
            pass


# ---------------------------------------------------------------- fechas

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def edad_anios(perfil, hoy: date = None):
    """Edad en años (float) a partir del cumpleaños o la edad aproximada."""
    hoy = hoy or date.today()
    if perfil.fecha_nacimiento:
        return (hoy - perfil.fecha_nacimiento).days / 365.25
    if perfil.edad_aprox is not None:
        return float(perfil.edad_aprox)
    return None


def edad_texto(perfil) -> str:
    hoy = date.today()
    if perfil.fecha_nacimiento:
        fn = perfil.fecha_nacimiento
        meses = (hoy.year - fn.year) * 12 + (hoy.month - fn.month) - (1 if hoy.day < fn.day else 0)
        if meses < 0:
            return ""
        if meses < 1:
            return "Recién nacido"
        if meses < 12:
            return f"{meses} {'mes' if meses == 1 else 'meses'}"
        anios = meses // 12
        return f"{anios} {'año' if anios == 1 else 'años'}"
    if perfil.edad_aprox is not None:
        return f"~{perfil.edad_aprox} {'año' if perfil.edad_aprox == 1 else 'años'}"
    return ""


def proximo_cumpleanos(fecha_nac: date, hoy: date = None):
    """Fecha del próximo cumpleaños (hoy incluido) y días que faltan."""
    if not fecha_nac:
        return None, None
    hoy = hoy or date.today()
    for anio in (hoy.year, hoy.year + 1):
        try:
            c = fecha_nac.replace(year=anio)
        except ValueError:  # 29 de febrero
            c = date(anio, 3, 1)
        if c >= hoy:
            return c, (c - hoy).days
    return None, None


def cumple_en_fecha(fecha_nac: date, dia: date) -> bool:
    if not fecha_nac:
        return False
    if fecha_nac.month == 2 and fecha_nac.day == 29:
        try:
            date(dia.year, 2, 29)
            return dia.month == 2 and dia.day == 29
        except ValueError:
            return dia.month == 3 and dia.day == 1
    return fecha_nac.month == dia.month and fecha_nac.day == dia.day


def hace(dt: datetime) -> str:
    if not dt:
        return ""
    seg = (datetime.now() - dt).total_seconds()
    if seg < 60:
        return "ahora"
    if seg < 3600:
        return f"hace {int(seg // 60)} min"
    if seg < 86400:
        h = int(seg // 3600)
        return f"hace {h} h"
    dias = int(seg // 86400)
    if dias == 1:
        return "ayer"
    if dias < 7:
        return f"hace {dias} días"
    return fecha_corta(dt.date() if isinstance(dt, datetime) else dt)


def fecha_corta(d: date) -> str:
    if not d:
        return ""
    texto = f"{d.day} {MESES[d.month - 1][:3]}"
    if d.year != date.today().year:
        texto += f" {d.year}"
    return texto


def fecha_larga(d: date) -> str:
    if not d:
        return ""
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def dias_texto(dias: int) -> str:
    if dias == 0:
        return "hoy"
    if dias == 1:
        return "mañana"
    if dias < 0:
        return f"hace {-dias} días"
    return f"en {dias} días"


# ---------------------------------------------------------------- distancia

def distancia_km(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def coordenada_aproximada(valor, decimales=3):
    """Redondea coordenadas de mascotas (~100 m) por privacidad."""
    if valor is None:
        return None
    return round(float(valor), decimales)


def a_float(valor):
    try:
        v = float(str(valor).replace(",", "."))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def a_int(valor):
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def a_fecha(valor):
    try:
        return date.fromisoformat(str(valor).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- HTML

COLORES_AVATAR = [
    ("#E7F0FF", "#BFD5FF"), ("#FFF3D6", "#FFD98A"), ("#E6F7EC", "#B5E3C3"),
    ("#FDE8EC", "#F8C2CD"), ("#EFE8FD", "#D3C2F8"), ("#E3F6F8", "#B0E2E8"),
]


def emoji_perfil(perfil) -> str:
    if perfil.tipo == "entidad":
        return CATEGORIAS_ENTIDAD.get(perfil.categoria or "otro", ("", "⭐"))[1]
    return ESPECIES.get(perfil.especie or "otro", ("", "🐾"))[1]


def icono(nombre: str, tam: int = 20, clase: str = "") -> Markup:
    trazo = ICONOS.get(nombre, "")
    return Markup(
        f'<svg class="ico {escape(clase)}" width="{tam}" height="{tam}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{trazo}</svg>'
    )


def avatar(perfil, tam: int = 44, clase: str = "") -> Markup:
    if perfil is None:
        return Markup("")
    nombre = escape(perfil.nombre)
    if perfil.foto:
        return Markup(
            f'<img class="avatar {escape(clase)}" src="{escape(perfil.foto)}" alt="{nombre}" '
            f'width="{tam}" height="{tam}" style="width:{tam}px;height:{tam}px" loading="lazy">'
        )
    c1, c2 = COLORES_AVATAR[(perfil.id or 0) % len(COLORES_AVATAR)]
    return Markup(
        f'<span class="avatar avatar-emoji {escape(clase)}" role="img" aria-label="{nombre}" '
        f'style="width:{tam}px;height:{tam}px;font-size:{int(tam * 0.52)}px;'
        f'background:linear-gradient(135deg,{c1},{c2})">{emoji_perfil(perfil)}</span>'
    )


def enlazar_texto(texto: str) -> Markup:
    """Escapa el texto, convierte URLs en enlaces y saltos de línea en <br>."""
    seguro = str(escape(texto or ""))
    seguro = re.sub(
        r"(https?://[^\s<]+)",
        r'<a href="\1" target="_blank" rel="noopener nofollow">\1</a>',
        seguro,
    )
    seguro = re.sub(r"(^|\s)#([\wáéíóúñÁÉÍÓÚÑ]+)", r'\1<a href="/buscar?q=\2" class="hashtag">#\2</a>', seguro)
    return Markup(seguro.replace("\n", "<br>"))
