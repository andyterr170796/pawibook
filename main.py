"""Pawbook — red social para mascotas (FastAPI + SQLite + Jinja2).

Ejecutar:  python main.py            (local, http://localhost:8001)
           python main.py --ngrok    (además publica un enlace https con ngrok)
"""
import hashlib
import os
import random
import re
import secrets
import sys
from datetime import date, datetime, timedelta
from typing import List, Optional
from urllib.parse import quote, urlsplit

from utilidades import cargar_env

cargar_env()

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

import asistente
import catalogos as cat
import correos
import seguridad
from models import (
    Anuncio, Comentario, Evento, InteresPareja, Lugar, MeGusta, Notificacion, Perfil, Publicacion,
    ReportePerdido, SessionLocal, Seguimiento, TokenRecuperacion, Usuario,
)
from seed import DEMO_EMAIL
from utilidades import (
    BASE_DIR, UPLOADS_DIR, a_fecha, a_float, a_int, avatar, borrar_archivo, contar_palabras,
    coordenada_aproximada, cumple_en_fecha, dias_texto, distancia_km, edad_anios, edad_texto,
    emoji_perfil, enlazar_texto, fecha_corta, fecha_larga, gastar_verificacion, guardar_imagen, hace,
    hash_password, icono, limpiar_tags, MESES, necesita_rehash, normalizar, obtener_secret_key,
    proximo_cumpleanos, slugify, url_segura, verificar_password,
)

PUERTO = int(os.getenv("PAWBOOK_PUERTO", "8001"))
os.makedirs(UPLOADS_DIR, exist_ok=True)

SESION_COOKIE = "pawbook_sesion"
LIMITE_LOGIN_POR_MINUTO = int(os.getenv("PAWBOOK_LIMITE_LOGIN", "5"))
LIMITE_PAWI_POR_MINUTO = int(os.getenv("PAWBOOK_LIMITE_PAWI_MINUTO", "10"))
LIMITE_PAWI_POR_DIA = int(os.getenv("PAWBOOK_LIMITE_PAWI_DIA", "100"))
MINUTOS_RECUPERACION = 60

app = FastAPI(title="Pawbook", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware, secret_key=obtener_secret_key(), session_cookie=SESION_COOKIE,
    max_age=60 * 60 * 24 * 30, same_site="lax",
)
app.add_middleware(seguridad.CookieSegura, nombre_cookie=SESION_COOKIE)

# Orígenes aceptados además del propio host (se completa al abrir ngrok). Ver seguridad.es_origen_ajeno.
ORIGENES_PERMITIDOS = {f"http://localhost:{PUERTO}", f"http://127.0.0.1:{PUERTO}"}
ORIGENES_PERMITIDOS.update(o.strip().rstrip("/").lower() for o in
                           (os.getenv("PAWBOOK_ORIGENES", "") + "," + os.getenv("PAWBOOK_URL_PUBLICA", "")).split(",")
                           if o.strip())
seguridad.instalar_protecciones(app, ORIGENES_PERMITIDOS)
app.add_middleware(seguridad.LimiteCuerpo)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.globals.update(
    icono=icono, avatar=avatar, cat=cat, edad_texto=edad_texto, emoji_perfil=emoji_perfil,
    proximo_cumpleanos=proximo_cumpleanos, dias_texto=dias_texto, fecha_larga=fecha_larga,
    fecha_corta=fecha_corta, MESES=MESES,
)
templates.env.filters.update(hace=hace, enlazar=enlazar_texto, fecha_corta=fecha_corta, fecha_larga=fecha_larga)


# =================================================================== infraestructura

class RedirigirA(Exception):
    def __init__(self, url: str):
        self.url = url


@app.exception_handler(RedirigirA)
async def _redirigir(request: Request, exc: RedirigirA):
    return RedirectResponse(exc.url, status_code=303)


@app.exception_handler(404)
async def _no_encontrado(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "No encontrado"}, status_code=404)
    with SessionLocal() as db:
        u = usuario_sesion(request, db)
        p = perfil_activo(u, db) if u else None
        resp = render(request, db, "error.html", u, p, titulo="No encontramos esta página",
                      mensaje="Puede que el enlace esté mal escrito o que el perfil ya no exista.")
        resp.status_code = 404
        return resp


@app.exception_handler(429)
async def _limite(request: Request, exc):
    """Demasiados intentos: página amable en vez de JSON (en /api/ sí JSON)."""
    detalle = getattr(exc, "detail", None) or seguridad.MENSAJE_LIMITE
    cabeceras = getattr(exc, "headers", None) or {}
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": detalle}, status_code=exc.status_code, headers=cabeceras)
    with SessionLocal() as db:
        u = usuario_sesion(request, db)
        p = perfil_activo(u, db) if u else None
        resp = render(request, db, "error.html", u, p, titulo="Espera un momento", mensaje=detalle)
        resp.status_code = exc.status_code
        resp.headers.update(cabeceras)
        return resp


def obtener_db(request: Request) -> Session:
    return request.state.db


@app.middleware("http")
async def _sesion_db(request: Request, call_next):
    if request.url.path.startswith(("/static/", "/uploads/")):
        return await call_next(request)
    db = SessionLocal()
    request.state.db = db
    try:
        respuesta = await call_next(request)
    finally:
        db.close()
    return respuesta


def flash(request: Request, texto: str, tipo: str = "ok"):
    request.session["flash"] = {"texto": texto, "tipo": tipo}


def volver(request: Request, por_defecto: str = "/") -> str:
    """Página desde la que vino el formulario, solo si es de este mismo sitio (nunca otro dominio)."""
    ref = urlsplit(request.headers.get("referer") or "")
    host = (request.headers.get("host") or "").lower()
    if ref.scheme in ("http", "https") and host and ref.netloc.lower() == host:
        return siguiente_seguro((ref.path or "/") + (f"?{ref.query}" if ref.query else ""))
    return por_defecto


def siguiente_seguro(url: Optional[str]) -> str:
    """Solo rutas internas: "/algo". Bloquea "//otro.com", "/\\otro.com" y caracteres de control,
    que el navegador convertiría en un salto a otro dominio."""
    if (url and url.startswith("/") and not url.startswith("//") and "\\" not in url
            and not any(ord(c) < 32 or ord(c) == 127 for c in url)):
        return url
    return "/"


def url_publica() -> str:
    """Dirección base para los enlaces que salen por correo.

    Nunca se arma con la cabecera Host de la petición: alguien podría pedir la recuperación de una cuenta
    ajena con "Host: sitio-malicioso" y el enlace con el token llegaría apuntando a su sitio.
    """
    for candidata in (os.getenv("PAWBOOK_URL_PUBLICA"), URL_TUNEL):
        if candidata and candidata.strip():
            return candidata.strip().rstrip("/")
    return f"http://localhost:{PUERTO}"


URL_TUNEL = None  # enlace https de ngrok, se fija al abrir el túnel


def es_cuenta_demo(u: Usuario) -> bool:
    """Cuentas compartidas o ficticias: no cambian contraseña ni reciben correos."""
    return u.email == DEMO_EMAIL or u.email.endswith("@pawbook.demo")


def iniciar_sesion(request: Request, u: Usuario):
    request.session.clear()
    request.session["uid"] = u.id
    request.session["ver"] = u.version_sesion or 0


def usuario_sesion(request: Request, db: Session) -> Optional[Usuario]:
    uid = request.session.get("uid")
    if not uid:
        return None
    u = db.get(Usuario, uid)
    # Al cambiar la contraseña sube version_sesion: las cookies emitidas antes dejan de valer.
    if not u or request.session.get("ver", 0) != (u.version_sesion or 0):
        request.session.clear()
        return None
    return u


def requiere_usuario(request: Request, db: Session) -> Usuario:
    u = usuario_sesion(request, db)
    if not u:
        raise RedirigirA("/login?next=" + quote(str(request.url.path)))
    return u


def perfil_activo(u: Optional[Usuario], db: Session) -> Optional[Perfil]:
    if not u:
        return None
    if u.perfil_activo_id:
        p = db.get(Perfil, u.perfil_activo_id)
        if p and p.usuario_id == u.id:
            return p
    if u.perfiles:
        u.perfil_activo_id = u.perfiles[0].id
        db.commit()
        return u.perfiles[0]
    return None


def requiere_perfil(request: Request, db: Session):
    u = requiere_usuario(request, db)
    p = perfil_activo(u, db)
    if not p:
        raise RedirigirA("/perfil/nuevo")
    procesar_recordatorios(request, db, u)
    return u, p


def requiere_api(request: Request, db: Session):
    u = usuario_sesion(request, db)
    if not u:
        raise HTTPException(401, "Inicia sesión para continuar.")
    p = perfil_activo(u, db)
    if not p:
        raise HTTPException(400, "Primero crea un perfil.")
    return u, p


def render(request: Request, db: Session, plantilla: str, u=None, p=None, **ctx):
    sin_leer = 0
    pendientes_admin = 0
    if u:
        ids = [x.id for x in u.perfiles]
        if ids:
            sin_leer = db.query(func.count(Notificacion.id)).filter(
                Notificacion.perfil_id.in_(ids), Notificacion.leida.is_(False)).scalar()
        if u.es_admin:
            pendientes_admin = db.query(func.count(Anuncio.id)).filter(Anuncio.estado == "pendiente").scalar()
    datos = {
        "usuario": u, "perfil": p, "mis_perfiles": list(u.perfiles) if u else [],
        "notif_sin_leer": sin_leer, "pendientes_admin": pendientes_admin,
        "flash": request.session.pop("flash", None), "hoy": date.today(),
        "asistente_activo": asistente.disponible(), "ruta": request.url.path,
    }
    datos.update(ctx)
    return templates.TemplateResponse(request, plantilla, datos)


def notificar(db: Session, perfil_id: int, tipo: str, texto: str, enlace: str = None,
              actor_id: int = None, clave: str = None):
    if actor_id and actor_id == perfil_id:
        return
    if clave and db.query(Notificacion.id).filter(Notificacion.clave == clave).first():
        return
    db.add(Notificacion(perfil_id=perfil_id, tipo=tipo, texto=texto[:400], enlace=enlace,
                        actor_id=actor_id, clave=clave))


def ids_seguidos(db: Session, perfil_id: int) -> set:
    return {i for (i,) in db.query(Seguimiento.seguido_id).filter(Seguimiento.seguidor_id == perfil_id)}


def procesar_recordatorios(request: Request, db: Session, u: Usuario):
    """Crea notificaciones de alertas del calendario y cumpleaños (como máximo cada 10 minutos)."""
    ahora = datetime.now().timestamp()
    if ahora - request.session.get("ult_recordatorio", 0) < 600:
        return
    request.session["ult_recordatorio"] = ahora
    hoy = date.today()
    mascotas = [p for p in u.perfiles if p.es_mascota]
    if not mascotas:
        return
    ids = [m.id for m in mascotas]
    nombres = {m.id: m.nombre for m in mascotas}

    eventos = db.query(Evento).filter(
        Evento.perfil_id.in_(ids), Evento.alerta_dias.isnot(None), Evento.alerta_enviada.is_(False),
        Evento.fecha >= hoy).all()
    for e in eventos:
        if e.fecha - timedelta(days=e.alerta_dias) <= hoy:
            emoji = cat.TIPOS_EVENTO.get(e.tipo, ("", "📌"))[1]
            cuando = dias_texto((e.fecha - hoy).days)
            notificar(db, e.perfil_id, "recordatorio",
                      f"{emoji} Recordatorio: {e.titulo} de {nombres[e.perfil_id]} es {cuando}"
                      + (f" a las {e.hora}" if e.hora else "") + ".",
                      f"/calendario?mes={e.fecha:%Y-%m}")
            e.alerta_enviada = True

    for m in mascotas:
        cumple, dias = proximo_cumpleanos(m.fecha_nacimiento, hoy)
        if cumple and dias == 0:
            anios = cumple.year - m.fecha_nacimiento.year
            notificar(db, m.id, "cumpleanos", f"🎂 ¡Hoy {m.nombre} cumple {anios} {'año' if anios == 1 else 'años'}! "
                      "Comparte una foto para celebrarlo.", "/", clave=f"cumple-propio:{m.id}:{hoy.year}")
        elif cumple and dias == 7:
            notificar(db, m.id, "cumpleanos", f"🎁 En una semana es el cumpleaños de {m.nombre}.",
                      f"/calendario?mes={cumple:%Y-%m}", clave=f"cumple-semana:{m.id}:{hoy.year}")

    amigos = (db.query(Seguimiento.seguidor_id, Perfil)
              .join(Perfil, Perfil.id == Seguimiento.seguido_id)
              .filter(Seguimiento.seguidor_id.in_(ids), Perfil.tipo == "mascota",
                      Perfil.fecha_nacimiento.isnot(None)).all())
    for seguidor_id, amigo in amigos:
        if cumple_en_fecha(amigo.fecha_nacimiento, hoy):
            notificar(db, seguidor_id, "cumpleanos", f"🎂 Hoy es el cumpleaños de {amigo.nombre}. ¡Salúdalo!",
                      f"/p/{amigo.handle}", actor_id=amigo.id, clave=f"cumple:{seguidor_id}:{amigo.id}:{hoy.year}")
    db.commit()


def handle_unico(db: Session, nombre: str, excluir_id: int = None) -> str:
    base = slugify(nombre)
    candidato, n = base, 1
    while True:
        q = db.query(Perfil.id).filter(Perfil.handle == candidato)
        if excluir_id:
            q = q.filter(Perfil.id != excluir_id)
        if not q.first():
            return candidato
        n += 1
        candidato = f"{base}-{n}"


def preparar_publicaciones(db: Session, posts: list, p: Optional[Perfil]):
    """Agrega n_likes y me_gusta a cada publicación."""
    ids = [x.id for x in posts]
    conteo, mios = {}, set()
    if ids:
        conteo = dict(db.query(MeGusta.publicacion_id, func.count(MeGusta.id))
                      .filter(MeGusta.publicacion_id.in_(ids)).group_by(MeGusta.publicacion_id).all())
        if p:
            mios = {i for (i,) in db.query(MeGusta.publicacion_id)
                    .filter(MeGusta.perfil_id == p.id, MeGusta.publicacion_id.in_(ids))}
    for x in posts:
        x.n_likes = conteo.get(x.id, 0)
        x.me_gusta = x.id in mios
    return posts


def consulta_publicaciones(db: Session):
    return db.query(Publicacion).options(
        selectinload(Publicacion.autor),
        selectinload(Publicacion.comentarios).selectinload(Comentario.autor),
    )


def anuncios_activos(db: Session, tipo: str, limite: int, contar: bool = True):
    hoy = date.today()
    lista = (db.query(Anuncio).options(selectinload(Anuncio.anunciante))
             .filter(Anuncio.tipo == tipo, Anuncio.estado == "activo",
                     (Anuncio.fecha_inicio.is_(None)) | (Anuncio.fecha_inicio <= hoy),
                     (Anuncio.fecha_fin.is_(None)) | (Anuncio.fecha_fin >= hoy)).all())
    random.shuffle(lista)
    lista = lista[:limite]
    if contar:
        for a in lista:
            a.impresiones = (a.impresiones or 0) + 1
        db.commit()
    return lista


def mis_mascotas(u: Usuario):
    return [x for x in u.perfiles if x.es_mascota]


# =================================================================== acceso

@app.get("/", response_class=HTMLResponse)
def inicio(request: Request, antes: Optional[int] = None):
    db = obtener_db(request)
    u = usuario_sesion(request, db)
    if not u:
        hay_demo = db.query(Usuario.id).filter(Usuario.email == DEMO_EMAIL).first() is not None
        n_mascotas = db.query(func.count(Perfil.id)).filter(Perfil.tipo == "mascota").scalar()
        n_entidades = db.query(func.count(Perfil.id)).filter(Perfil.tipo == "entidad").scalar()
        return render(request, db, "landing.html", hay_demo=hay_demo, n_mascotas=n_mascotas, n_entidades=n_entidades)
    u, p = requiere_perfil(request, db)

    seguidos = ids_seguidos(db, p.id)
    autores = seguidos | {x.id for x in u.perfiles}
    q = consulta_publicaciones(db).filter(Publicacion.perfil_id.in_(autores))
    if antes:
        q = q.filter(Publicacion.id < antes)
    posts = q.order_by(Publicacion.id.desc()).limit(20).all()
    descubre = []
    if not antes and len(posts) < 8:
        descubre = (consulta_publicaciones(db).filter(~Publicacion.perfil_id.in_(autores))
                    .order_by(Publicacion.id.desc()).limit(12).all())
    preparar_publicaciones(db, posts + descubre, p)

    hoy = date.today()
    proximos = proximos_eventos(db, u, hoy, dias=30, limite=4)
    patrocinados = anuncios_activos(db, "pagado", 2)
    campanas = anuncios_activos(db, "gratuito", 3)
    sugerencias = sugerir_perfiles(db, u, p, seguidos, 5)
    return render(request, db, "feed.html", u, p, posts=posts, descubre=descubre, proximos=proximos,
                  avisos_cerca=avisos_cercanos(db, p, 3),
                  patrocinado_lateral=patrocinados[0] if patrocinados else None,
                  patrocinado_feed=patrocinados[1] if len(patrocinados) > 1 else None,
                  campanas=campanas, sugerencias=sugerencias,
                  mas_antiguo=posts[-1].id if len(posts) == 20 else None)


def proximos_eventos(db: Session, u: Usuario, hoy: date, dias: int = 30, limite: int = 6):
    mascotas = mis_mascotas(u)
    ids = [m.id for m in mascotas]
    items = []
    if ids:
        for e in (db.query(Evento).options(selectinload(Evento.mascota))
                  .filter(Evento.perfil_id.in_(ids), Evento.fecha >= hoy,
                          Evento.fecha <= hoy + timedelta(days=dias)).order_by(Evento.fecha, Evento.hora).all()):
            items.append({"fecha": e.fecha, "hora": e.hora, "titulo": e.titulo, "mascota": e.mascota,
                          "tipo": e.tipo, "dias": (e.fecha - hoy).days})
        amigos = (db.query(Perfil).join(Seguimiento, Seguimiento.seguido_id == Perfil.id)
                  .filter(Seguimiento.seguidor_id.in_(ids), Perfil.tipo == "mascota",
                          Perfil.fecha_nacimiento.isnot(None)).distinct().all())
        for m in mascotas + amigos:
            cumple, faltan = proximo_cumpleanos(m.fecha_nacimiento, hoy)
            if cumple and faltan <= dias:
                propio = m.usuario_id == u.id
                items.append({"fecha": cumple, "hora": None, "mascota": m, "tipo": "cumpleanos", "dias": faltan,
                              "titulo": f"Cumpleaños de {m.nombre}" + ("" if propio else " (amigo)")})
    items.sort(key=lambda x: (x["fecha"], x["hora"] or ""))
    return items[:limite]


def sugerir_perfiles(db: Session, u: Usuario, p: Perfil, seguidos: set, limite: int):
    mios = {x.id for x in u.perfiles}
    candidatos = (db.query(Perfil).filter(~Perfil.id.in_(seguidos | mios)).order_by(Perfil.id.desc()).limit(300).all())

    def puntaje(c):
        s = 0
        if p.distrito and c.distrito and normalizar(c.distrito) == normalizar(p.distrito):
            s += 3
        if p.es_mascota and c.es_mascota and c.especie == p.especie:
            s += 1
            if c.raza and p.raza and normalizar(c.raza) == normalizar(p.raza):
                s += 2
        d = distancia_km(p.lat, p.lng, c.lat, c.lng)
        if d is not None and d < 5:
            s += 2
        if c.es_entidad and c.verificada:
            s += 1
        return s + random.random()

    candidatos.sort(key=puntaje, reverse=True)
    return candidatos[:limite]


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    db = obtener_db(request)
    if usuario_sesion(request, db):
        return RedirectResponse("/", 303)
    hay_demo = db.query(Usuario.id).filter(Usuario.email == DEMO_EMAIL).first() is not None
    return render(request, db, "login.html", next=siguiente_seguro(next), hay_demo=hay_demo)


def intentos_agotados(request: Request, *reglas) -> bool:
    """Consume un intento en cada regla (ámbito, clave, límite, ventana_seg); True si alguna se pasó."""
    agotado = False
    for ambito, clave, limite, ventana in reglas:
        permitido, _ = seguridad.limitador.consumir(seguridad.Regla(ambito, limite, ventana), clave)
        if not permitido:
            seguridad.registrar("limite_superado", request, ambito=ambito)
            agotado = True
    return agotado


def con_estado(respuesta, codigo: int):
    respuesta.status_code = codigo
    return respuesta


@app.post("/login")
async def login(request: Request):
    db = obtener_db(request)
    form = await request.form()
    email = (form.get("email") or "").strip().lower()[:200]
    password = (form.get("password") or "")[:1024]
    destino = siguiente_seguro(form.get("next"))
    hay_demo = db.query(Usuario.id).filter(Usuario.email == DEMO_EMAIL).first() is not None
    if intentos_agotados(request, ("login-ip", seguridad.ip_cliente(request), LIMITE_LOGIN_POR_MINUTO, 60),
                         ("login-cuenta", seguridad.huella(email), LIMITE_LOGIN_POR_MINUTO, 60)):
        return con_estado(render(request, db, "login.html", next=destino, error=seguridad.MENSAJE_LIMITE,
                                 email=email, hay_demo=hay_demo), 429)
    u = db.query(Usuario).filter(Usuario.email == email).first()
    if u:
        correcta = verificar_password(password, u.password_hash)
    else:
        gastar_verificacion(password)  # misma demora: no delata si el correo tiene cuenta
        correcta = False
    if not correcta:
        seguridad.registrar("login_fallido", request, email=seguridad.ocultar_email(email),
                            cuenta="si" if u else "no")
        return con_estado(render(request, db, "login.html", next=destino, error="Correo o contraseña incorrectos.",
                                 email=email, hay_demo=hay_demo), 401)
    if necesita_rehash(u.password_hash):
        u.password_hash = hash_password(password)
        db.commit()
    seguridad.registrar("login_ok", request, usuario=u.id)
    iniciar_sesion(request, u)
    return RedirectResponse(destino, 303)


@app.post("/login/demo")
def login_demo(request: Request):
    db = obtener_db(request)
    u = db.query(Usuario).filter(Usuario.email == DEMO_EMAIL).first()
    if not u:
        raise HTTPException(404)
    iniciar_sesion(request, u)
    return RedirectResponse("/", 303)


@app.get("/registro", response_class=HTMLResponse)
def registro_form(request: Request):
    db = obtener_db(request)
    if usuario_sesion(request, db):
        return RedirectResponse("/", 303)
    return render(request, db, "registro.html", datos={})


CORREO_VALIDO = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]{2,}$")


@app.post("/registro")
async def registro(request: Request):
    db = obtener_db(request)
    form = await request.form()
    datos = {"nombre": (form.get("nombre") or "").strip()[:120],
             "email": (form.get("email") or "").strip().lower()[:200]}
    password = form.get("password") or ""
    if intentos_agotados(request, ("registro-ip", seguridad.ip_cliente(request), 5, 3600)):
        return con_estado(render(request, db, "registro.html", datos=datos, error=seguridad.MENSAJE_LIMITE), 429)
    error = None
    if len(datos["nombre"]) < 2:
        error = "Escribe tu nombre."
    elif not CORREO_VALIDO.match(datos["email"]):
        error = "El correo no es válido."
    elif seguridad.error_password(password):
        error = seguridad.error_password(password)
    elif password != (form.get("password2") or ""):
        error = "Las contraseñas no coinciden."
    elif db.query(Usuario.id).filter(Usuario.email == datos["email"]).first():
        error = "Ya existe una cuenta con ese correo. Si es tuya, usa «¿Olvidaste tu contraseña?»."
    if error:
        return render(request, db, "registro.html", datos=datos, error=error)
    u = Usuario(nombre=datos["nombre"], email=datos["email"], password_hash=hash_password(password))
    db.add(u)
    db.commit()
    seguridad.registrar("registro", request, usuario=u.id)
    base = url_publica()
    correos.enviar_en_segundo_plano(u.email, *correos.correo_bienvenida(u.nombre, base))
    iniciar_sesion(request, u)
    return RedirectResponse("/perfil/nuevo?bienvenida=1", 303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", 303)


@app.get("/logout")
def logout_get():
    # Cerrar sesión cambia datos: solo por POST (un enlace en otra web no puede sacarte de tu cuenta).
    return RedirectResponse("/", 303)


# =================================================================== cuenta y contraseña

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_vigente(db: Session, token: str) -> Optional[TokenRecuperacion]:
    if not token or len(token) > 200:
        return None
    t = (db.query(TokenRecuperacion)
         .filter(TokenRecuperacion.token_hash == hash_token(token), TokenRecuperacion.usado.is_(None),
                 TokenRecuperacion.expira > datetime.now()).first())
    return t if t and t.usuario else None


def sin_cache(respuesta, sin_referer: bool = False):
    """Páginas con datos de acceso: que el navegador no las guarde ni filtre el token en el Referer."""
    respuesta.headers["Cache-Control"] = "no-store"
    if sin_referer:
        respuesta.headers["Referrer-Policy"] = "no-referrer"
    return respuesta


def avisar_cambio_password(u: Usuario):
    correos.enviar_en_segundo_plano(u.email, *correos.correo_password_cambiada(u.nombre, url_publica()))


@app.get("/recuperar", response_class=HTMLResponse)
def recuperar_form(request: Request):
    db = obtener_db(request)
    return render(request, db, "recuperar.html", correo_activo=correos.configurado())


@app.post("/recuperar")
async def recuperar(request: Request):
    db = obtener_db(request)
    form = await request.form()
    email = (form.get("email") or "").strip().lower()[:200]
    if intentos_agotados(request, ("recuperar-ip", seguridad.ip_cliente(request), 5, 3600),
                         ("recuperar-cuenta", seguridad.huella(email), 3, 3600)):
        return con_estado(render(request, db, "recuperar.html", correo_activo=correos.configurado(),
                                 error=seguridad.MENSAJE_LIMITE, email=email), 429)
    u = db.query(Usuario).filter(Usuario.email == email).first() if email else None
    if u and not es_cuenta_demo(u) and correos.es_destino_entregable(u.email):
        ahora = datetime.now()
        # Un enlace nuevo anula los anteriores que no se usaron.
        db.query(TokenRecuperacion).filter(TokenRecuperacion.usuario_id == u.id, TokenRecuperacion.usado.is_(None)
                                           ).update({"usado": ahora}, synchronize_session=False)
        token = secrets.token_urlsafe(32)
        db.add(TokenRecuperacion(usuario_id=u.id, token_hash=hash_token(token), ip=seguridad.ip_cliente(request),
                                 expira=ahora + timedelta(minutes=MINUTOS_RECUPERACION)))
        db.commit()
        base = url_publica()
        enlace = f"{base}/restablecer?token={quote(token)}"
        correos.enviar_en_segundo_plano(u.email, *correos.correo_recuperacion(u.nombre, enlace,
                                                                              MINUTOS_RECUPERACION, base))
        seguridad.registrar("recuperacion_solicitada", request, usuario=u.id)
    else:
        seguridad.registrar("recuperacion_sin_cuenta", request, email=seguridad.ocultar_email(email))
    # Misma respuesta exista o no la cuenta: no se puede usar para averiguar qué correos están registrados.
    return render(request, db, "recuperar.html", correo_activo=correos.configurado(), enviado=True, email=email)


@app.get("/restablecer", response_class=HTMLResponse)
def restablecer_form(request: Request, token: str = ""):
    db = obtener_db(request)
    vigente = token_vigente(db, token) is not None
    return sin_cache(render(request, db, "restablecer.html", token=token if vigente else "", valido=vigente), True)


@app.post("/restablecer")
async def restablecer(request: Request):
    db = obtener_db(request)
    form = await request.form()
    token = form.get("token") or ""
    password = form.get("password") or ""
    if intentos_agotados(request, ("restablecer-ip", seguridad.ip_cliente(request), 10, 900)):
        return sin_cache(con_estado(render(request, db, "restablecer.html", token=token, valido=True,
                                           error=seguridad.MENSAJE_LIMITE), 429), True)
    t = token_vigente(db, token)
    if not t:
        return sin_cache(render(request, db, "restablecer.html", token="", valido=False), True)
    u = t.usuario
    error = seguridad.error_password(password)
    if not error and password != (form.get("password2") or ""):
        error = "Las contraseñas no coinciden."
    if not error and verificar_password(password, u.password_hash):
        error = "La nueva contraseña debe ser distinta de la actual."
    if error:
        return sin_cache(render(request, db, "restablecer.html", token=token, valido=True, error=error), True)
    ahora = datetime.now()
    u.password_hash = hash_password(password)
    u.version_sesion = (u.version_sesion or 0) + 1  # cierra todas las sesiones abiertas
    db.query(TokenRecuperacion).filter(TokenRecuperacion.usuario_id == u.id, TokenRecuperacion.usado.is_(None)
                                       ).update({"usado": ahora}, synchronize_session=False)
    db.commit()
    seguridad.registrar("recuperacion_completada", request, usuario=u.id)
    avisar_cambio_password(u)
    request.session.clear()
    flash(request, "Listo, tu contraseña cambió. Ya puedes iniciar sesión con la nueva.")
    return RedirectResponse("/login", 303)


@app.get("/cuenta", response_class=HTMLResponse)
def cuenta(request: Request):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    return sin_cache(render(request, db, "cuenta.html", u, perfil_activo(u, db), es_demo=es_cuenta_demo(u),
                            correo_activo=correos.configurado()))


@app.post("/cuenta/password")
async def cambiar_password(request: Request):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    p = perfil_activo(u, db)
    form = await request.form()

    def con_error(texto, codigo=400):
        return sin_cache(con_estado(render(request, db, "cuenta.html", u, p, es_demo=es_cuenta_demo(u),
                                           correo_activo=correos.configurado(), error=texto), codigo))

    if es_cuenta_demo(u):
        return con_error("La cuenta demo es compartida: su contraseña no se puede cambiar.", 403)
    if intentos_agotados(request, ("cambio-password", f"u:{u.id}", 10, 900)):
        return con_error(seguridad.MENSAJE_LIMITE, 429)
    actual = (form.get("actual") or "")[:1024]
    nueva = form.get("password") or ""
    if not verificar_password(actual, u.password_hash):
        seguridad.registrar("cambio_password_fallido", request, usuario=u.id)
        return con_error("La contraseña actual no es correcta.")
    error = seguridad.error_password(nueva)
    if not error and nueva != (form.get("password2") or ""):
        error = "Las contraseñas nuevas no coinciden."
    if not error and nueva == actual:
        error = "La nueva contraseña debe ser distinta de la actual."
    if error:
        return con_error(error)
    u.password_hash = hash_password(nueva)
    u.version_sesion = (u.version_sesion or 0) + 1  # las demás sesiones se cierran...
    db.commit()
    request.session["ver"] = u.version_sesion  # ...y esta sigue abierta
    seguridad.registrar("password_cambiada", request, usuario=u.id)
    avisar_cambio_password(u)
    flash(request, "Contraseña actualizada. Cerramos tu sesión en los demás dispositivos.")
    return RedirectResponse("/cuenta", 303)


@app.post("/cuenta/cerrar-sesiones")
def cerrar_otras_sesiones(request: Request):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    if es_cuenta_demo(u):
        flash(request, "La cuenta demo es compartida: no se pueden cerrar sus sesiones.", "error")
        return RedirectResponse("/cuenta", 303)
    u.version_sesion = (u.version_sesion or 0) + 1
    db.commit()
    request.session["ver"] = u.version_sesion
    seguridad.registrar("sesiones_cerradas", request, usuario=u.id)
    flash(request, "Cerramos tu sesión en todos los demás dispositivos.")
    return RedirectResponse("/cuenta", 303)


# =================================================================== publicaciones

@app.post("/publicar")
async def publicar(request: Request):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    form = await request.form()
    texto = (form.get("texto") or "").strip()[:3000]
    try:
        imagen = await guardar_imagen(form.get("imagen"), "posts", 1600)
    except ValueError as e:
        flash(request, str(e), "error")
        return RedirectResponse(volver(request), 303)
    if not texto and not imagen:
        flash(request, "Escribe algo o agrega una foto.", "error")
        return RedirectResponse(volver(request), 303)
    db.add(Publicacion(perfil_id=p.id, texto=texto, imagen=imagen))
    db.commit()
    flash(request, "¡Publicado!")
    return RedirectResponse(volver(request), 303)


@app.post("/publicacion/{pid}/eliminar")
def eliminar_publicacion(request: Request, pid: int):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    post = db.get(Publicacion, pid)
    if not post or post.perfil_id not in {x.id for x in u.perfiles}:
        raise HTTPException(404)
    borrar_archivo(post.imagen)
    db.delete(post)
    db.commit()
    flash(request, "Publicación eliminada.")
    return RedirectResponse(volver(request), 303)


@app.post("/api/publicacion/{pid}/like")
def like(request: Request, pid: int):
    db = obtener_db(request)
    u, p = requiere_api(request, db)
    post = db.get(Publicacion, pid)
    if not post:
        raise HTTPException(404)
    existente = db.query(MeGusta).filter(MeGusta.publicacion_id == pid, MeGusta.perfil_id == p.id).first()
    if existente:
        db.delete(existente)
        activo = False
    else:
        db.add(MeGusta(publicacion_id=pid, perfil_id=p.id))
        activo = True
        notificar(db, post.perfil_id, "like", f"A {p.nombre} le gusta tu publicación.", f"/p/{post.autor.handle}#post-{pid}",
                  actor_id=p.id, clave=f"like:{pid}:{p.id}")
    db.commit()
    total = db.query(func.count(MeGusta.id)).filter(MeGusta.publicacion_id == pid).scalar()
    return {"me_gusta": activo, "total": total}


@app.post("/api/publicacion/{pid}/comentar")
async def comentar(request: Request, pid: int):
    db = obtener_db(request)
    u, p = requiere_api(request, db)
    post = db.get(Publicacion, pid)
    if not post:
        raise HTTPException(404)
    try:
        body = await request.json()
    except ValueError:
        body = None
    texto = body.get("texto") if isinstance(body, dict) else None
    texto = (texto if isinstance(texto, str) else "").strip()[:1000]
    if not texto:
        raise HTTPException(400, "El comentario está vacío.")
    c = Comentario(publicacion_id=pid, perfil_id=p.id, texto=texto)
    db.add(c)
    notificar(db, post.perfil_id, "comentario", f"{p.nombre} comentó: “{texto[:80]}”",
              f"/p/{post.autor.handle}#post-{pid}", actor_id=p.id)
    db.commit()
    return {"id": c.id, "texto": texto, "autor": p.nombre, "handle": p.handle,
            "avatar": str(avatar(p, 32)), "hace": "ahora"}


@app.post("/api/comentario/{cid}/eliminar")
def eliminar_comentario(request: Request, cid: int):
    db = obtener_db(request)
    u, p = requiere_api(request, db)
    c = db.get(Comentario, cid)
    if not c:
        raise HTTPException(404)
    mios = {x.id for x in u.perfiles}
    post = db.get(Publicacion, c.publicacion_id)
    if c.perfil_id not in mios and (not post or post.perfil_id not in mios):
        raise HTTPException(403)
    db.delete(c)
    db.commit()
    return {"ok": True}


# =================================================================== perfiles

@app.get("/p/{handle}", response_class=HTMLResponse)
def ver_perfil(request: Request, handle: str, antes: Optional[int] = None):
    db = obtener_db(request)
    u = usuario_sesion(request, db)
    p = perfil_activo(u, db) if u else None
    perfil = db.query(Perfil).filter(Perfil.handle == handle).first()
    if not perfil:
        raise HTTPException(404)
    q = consulta_publicaciones(db).filter(Publicacion.perfil_id == perfil.id)
    if antes:
        q = q.filter(Publicacion.id < antes)
    posts = preparar_publicaciones(db, q.order_by(Publicacion.id.desc()).limit(20).all(), p)
    seguidores = db.query(func.count(Seguimiento.id)).filter(Seguimiento.seguido_id == perfil.id).scalar()
    siguiendo_n = db.query(func.count(Seguimiento.id)).filter(Seguimiento.seguidor_id == perfil.id).scalar()
    lo_sigo = bool(p and db.query(Seguimiento.id).filter(
        Seguimiento.seguidor_id == p.id, Seguimiento.seguido_id == perfil.id).first())
    es_mio = bool(u and perfil.usuario_id == u.id)
    cumple, faltan = proximo_cumpleanos(perfil.fecha_nacimiento) if perfil.es_mascota else (None, None)
    compatible = bool(p and not es_mio and es_compatible(p, perfil))
    interes_enviado = bool(compatible and db.query(InteresPareja.id).filter(
        InteresPareja.de_id == p.id, InteresPareja.para_id == perfil.id).first())
    anuncios = []
    if perfil.es_entidad:
        anuncios = (db.query(Anuncio).filter(Anuncio.perfil_id == perfil.id, Anuncio.estado == "activo")
                    .order_by(Anuncio.id.desc()).limit(3).all())
    distancia = distancia_km(p.lat, p.lng, perfil.lat, perfil.lng) if p and not es_mio else None
    aviso_perdido = None
    if perfil.es_mascota:
        aviso_perdido = (db.query(ReportePerdido).filter(ReportePerdido.mascota_id == perfil.id,
                                                         ReportePerdido.tipo == "perdido",
                                                         ReportePerdido.estado == "activo")
                         .order_by(ReportePerdido.id.desc()).first())
    return render(request, db, "perfil.html", u, p, pf=perfil, posts=posts, seguidores=seguidores,
                  siguiendo_n=siguiendo_n, lo_sigo=lo_sigo, es_mio=es_mio, cumple=cumple, faltan=faltan,
                  compatible=compatible, interes_enviado=interes_enviado, anuncios=anuncios, distancia=distancia,
                  aviso_perdido=aviso_perdido, mas_antiguo=posts[-1].id if len(posts) == 20 else None)


@app.get("/mis-perfiles", response_class=HTMLResponse)
def mis_perfiles(request: Request):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    p = perfil_activo(u, db)
    return render(request, db, "mis_perfiles.html", u, p)


@app.post("/perfil/activar/{pid}")
def activar_perfil(request: Request, pid: int):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    perfil = db.get(Perfil, pid)
    if not perfil or perfil.usuario_id != u.id:
        raise HTTPException(404)
    u.perfil_activo_id = perfil.id
    db.commit()
    flash(request, f"Ahora estás usando Pawbook como {perfil.nombre}.")
    return RedirectResponse(volver(request), 303)


def datos_vacios(tipo: str, categoria: str = None) -> dict:
    return {"tipo": tipo, "pais": "Perú", "ciudad": "Lima", "mostrar_en_mapa": True, "tags": "",
            "especie": "perro", "categoria": categoria if categoria in cat.CATEGORIAS_ENTIDAD else "veterinaria"}


def datos_desde_form(form, tipo: str) -> dict:
    """Datos del formulario de perfil para volver a mostrarlo cuando hay un error."""
    datos = dict(form)
    datos.pop("foto", None)
    datos.pop("portada", None)
    datos["tipo"] = tipo
    if tipo == "entidad":
        datos["tags"] = ",".join(form.getlist("amenidades"))
    return datos


def perfil_a_datos(pf: Perfil) -> dict:
    campos = ["tipo", "nombre", "descripcion", "pais", "ciudad", "distrito", "lat", "lng", "mostrar_en_mapa",
              "especie", "raza", "sexo", "edad_aprox", "tags", "busca_pareja", "categoria", "direccion",
              "horario", "telefono", "email_contacto", "web", "foto", "portada"]
    d = {c: getattr(pf, c) for c in campos}
    d["fecha_nacimiento"] = pf.fecha_nacimiento.isoformat() if pf.fecha_nacimiento else ""
    d["id"] = pf.id
    return d


@app.get("/perfil/nuevo", response_class=HTMLResponse)
def nuevo_perfil_form(request: Request, tipo: Optional[str] = None, bienvenida: int = 0, categoria: str = ""):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    p = perfil_activo(u, db)
    if tipo not in ("mascota", "entidad"):
        return render(request, db, "elegir_tipo.html", u, p, bienvenida=bienvenida)
    return render(request, db, "perfil_form.html", u, p, datos=datos_vacios(tipo, categoria), nuevo=True)


@app.post("/perfil/nuevo")
async def crear_perfil(request: Request):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    form = await request.form()
    tipo = form.get("tipo") if form.get("tipo") in ("mascota", "entidad") else "mascota"
    pf = Perfil(usuario_id=u.id, tipo=tipo)
    error = await aplicar_formulario_perfil(db, pf, form, nuevo=True)
    if error:
        datos = datos_desde_form(form, tipo)
        return render(request, db, "perfil_form.html", u, perfil_activo(u, db), datos=datos, nuevo=True, error=error)
    db.add(pf)
    db.flush()
    u.perfil_activo_id = pf.id
    db.commit()
    if pf.es_mascota and pf.busca_pareja:
        avisar_compatibles(db, pf)
    flash(request, f"¡Bienvenido a Pawbook, {pf.nombre}! 🐾")
    return RedirectResponse(f"/p/{pf.handle}", 303)


@app.get("/perfil/{pid}/editar", response_class=HTMLResponse)
def editar_perfil_form(request: Request, pid: int):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    pf = db.get(Perfil, pid)
    if not pf or pf.usuario_id != u.id:
        raise HTTPException(404)
    return render(request, db, "perfil_form.html", u, perfil_activo(u, db), datos=perfil_a_datos(pf), nuevo=False)


@app.post("/perfil/{pid}/editar")
async def editar_perfil(request: Request, pid: int):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    pf = db.get(Perfil, pid)
    if not pf or pf.usuario_id != u.id:
        raise HTTPException(404)
    form = await request.form()
    buscaba = bool(pf.busca_pareja)
    error = await aplicar_formulario_perfil(db, pf, form, nuevo=False)
    if error:
        db.rollback()
        datos = datos_desde_form(form, pf.tipo)
        datos.update({"id": pf.id, "foto": pf.foto, "portada": pf.portada})
        return render(request, db, "perfil_form.html", u, perfil_activo(u, db), datos=datos, nuevo=False, error=error)
    db.commit()
    if pf.es_mascota and pf.busca_pareja and not buscaba:
        avisar_compatibles(db, pf)
    flash(request, "Perfil actualizado.")
    return RedirectResponse(f"/p/{pf.handle}", 303)


async def aplicar_formulario_perfil(db: Session, pf: Perfil, form, nuevo: bool) -> Optional[str]:
    nombre = (form.get("nombre") or "").strip()[:120]
    if len(nombre) < 2:
        return "Escribe un nombre."
    descripcion = (form.get("descripcion") or "").strip()
    if contar_palabras(descripcion) > 500:
        return f"La descripción tiene {contar_palabras(descripcion)} palabras; el máximo es 500."
    pf.nombre = nombre
    pf.descripcion = descripcion
    pf.pais = (form.get("pais") or "Perú")[:80]
    pf.ciudad = (form.get("ciudad") or "").strip()[:120]
    pf.distrito = (form.get("distrito") or "").strip()[:120]
    lat, lng = a_float(form.get("lat")), a_float(form.get("lng"))
    if lat is not None and not (-90 <= lat <= 90) or lng is not None and not (-180 <= lng <= 180):
        lat = lng = None
    pf.mostrar_en_mapa = form.get("mostrar_en_mapa") == "1"

    if pf.tipo == "mascota":
        pf.lat, pf.lng = coordenada_aproximada(lat), coordenada_aproximada(lng)
        pf.especie = form.get("especie") if form.get("especie") in cat.ESPECIES else "otro"
        pf.raza = (form.get("raza") or "").strip()[:120]
        pf.sexo = form.get("sexo") if form.get("sexo") in cat.SEXOS else None
        fn = a_fecha(form.get("fecha_nacimiento"))
        if fn and fn > date.today():
            return "La fecha de cumpleaños no puede ser futura."
        pf.fecha_nacimiento = fn
        edad = a_int(form.get("edad_aprox"))
        pf.edad_aprox = edad if edad is not None and 0 <= edad <= 60 else None
        pf.tags = limpiar_tags(form.get("tags") or "")
        pf.busca_pareja = form.get("busca_pareja") == "1"
    else:
        pf.lat, pf.lng = lat, lng
        pf.categoria = form.get("categoria") if form.get("categoria") in cat.CATEGORIAS_ENTIDAD else "otro"
        pf.direccion = (form.get("direccion") or "").strip()[:250]
        pf.horario = (form.get("horario") or "").strip()[:250]
        pf.telefono = (form.get("telefono") or "").strip()[:60]
        pf.email_contacto = (form.get("email_contacto") or "").strip()[:200]
        pf.web = url_segura(form.get("web"))
        # En entidades, `tags` guarda lo que ofrece un restaurante pet friendly
        pf.tags = (",".join(a for a in form.getlist("amenidades") if a in cat.AMENIDADES_PET_FRIENDLY)
                   if pf.categoria == "restaurante" else "")

    try:
        foto = await guardar_imagen(form.get("foto"), "perfiles", 600, cuadrada=True)
        portada = await guardar_imagen(form.get("portada"), "portadas", 1600)
    except ValueError as e:
        return str(e)
    if foto:
        borrar_archivo(pf.foto)
        pf.foto = foto
    elif form.get("quitar_foto") == "1":
        borrar_archivo(pf.foto)
        pf.foto = None
    if portada:
        borrar_archivo(pf.portada)
        pf.portada = portada
    elif form.get("quitar_portada") == "1":
        borrar_archivo(pf.portada)
        pf.portada = None

    if nuevo or not pf.handle:
        pf.handle = handle_unico(db, nombre)
    return None


@app.post("/perfil/{pid}/eliminar")
async def eliminar_perfil(request: Request, pid: int):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    pf = db.get(Perfil, pid)
    if not pf or pf.usuario_id != u.id:
        raise HTTPException(404)
    form = await request.form()
    if (form.get("confirmar") or "").strip().lower() != pf.nombre.strip().lower():
        flash(request, "Para eliminar escribe el nombre exacto del perfil.", "error")
        return RedirectResponse(f"/perfil/{pid}/editar", 303)
    for post in pf.publicaciones:
        borrar_archivo(post.imagen)
    borrar_archivo(pf.foto)
    borrar_archivo(pf.portada)
    nombre = pf.nombre
    db.delete(pf)
    if u.perfil_activo_id == pid:
        u.perfil_activo_id = None
    db.commit()
    flash(request, f"Se eliminó el perfil de {nombre}.")
    return RedirectResponse("/mis-perfiles", 303)


# =================================================================== seguir / amigos

@app.post("/api/seguir/{pid}")
def seguir(request: Request, pid: int):
    db = obtener_db(request)
    u, p = requiere_api(request, db)
    destino = db.get(Perfil, pid)
    if not destino or destino.id == p.id:
        raise HTTPException(400, "No puedes seguir este perfil.")
    s = db.query(Seguimiento).filter(Seguimiento.seguidor_id == p.id, Seguimiento.seguido_id == pid).first()
    if s:
        db.delete(s)
        siguiendo = False
    else:
        db.add(Seguimiento(seguidor_id=p.id, seguido_id=pid))
        siguiendo = True
        notificar(db, pid, "seguidor", f"{p.nombre} empezó a seguirte.", f"/p/{p.handle}", actor_id=p.id,
                  clave=f"sigue:{p.id}:{pid}")
    db.commit()
    total = db.query(func.count(Seguimiento.id)).filter(Seguimiento.seguido_id == pid).scalar()
    return {"siguiendo": siguiendo, "seguidores": total}


@app.get("/amigos", response_class=HTMLResponse)
def amigos(request: Request, tab: str = "amigos"):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    seguidos = (db.query(Perfil).join(Seguimiento, Seguimiento.seguido_id == Perfil.id)
                .filter(Seguimiento.seguidor_id == p.id).order_by(Perfil.nombre).all())
    seguidores = (db.query(Perfil).join(Seguimiento, Seguimiento.seguidor_id == Perfil.id)
                  .filter(Seguimiento.seguido_id == p.id).order_by(Perfil.nombre).all())
    ids_sigo = {x.id for x in seguidos}
    listas = {
        "amigos": [x for x in seguidos if x.es_mascota],
        "entidades": [x for x in seguidos if x.es_entidad],
        "seguidores": seguidores,
    }
    if tab not in listas:
        tab = "amigos"
    return render(request, db, "amigos.html", u, p, tab=tab, lista=listas[tab],
                  conteos={k: len(v) for k, v in listas.items()}, ids_sigo=ids_sigo)


# =================================================================== búsqueda

@app.get("/buscar", response_class=HTMLResponse)
def buscar(request: Request, q: str = "", tipo: str = "mascota", especie: str = "", raza: str = "", sexo: str = "",
           edad_min: str = "", edad_max: str = "", cerca: str = "", categoria: str = "", pais: str = ""):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    mios = {x.id for x in u.perfiles}
    consulta = db.query(Perfil).filter(~Perfil.id.in_(mios))
    if tipo in ("mascota", "entidad"):
        consulta = consulta.filter(Perfil.tipo == tipo)
    if tipo == "mascota":
        if especie in cat.ESPECIES:
            consulta = consulta.filter(Perfil.especie == especie)
        if sexo in cat.SEXOS:
            consulta = consulta.filter(Perfil.sexo == sexo)
    if tipo == "entidad" and categoria in cat.CATEGORIAS_ENTIDAD:
        consulta = consulta.filter(Perfil.categoria == categoria)
    if pais:
        consulta = consulta.filter(Perfil.pais == pais)
    candidatos = consulta.all()

    terminos = normalizar(q).lstrip("#").split()
    raza_n = normalizar(raza)
    e_min, e_max = a_float(edad_min), a_float(edad_max)
    radio = a_float(cerca) if cerca not in ("", "distrito") else None
    resultados = []
    for c in candidatos:
        if terminos:
            bolsa = normalizar(" ".join(filter(None, [
                c.nombre, c.handle, c.raza, c.tags, c.distrito, c.ciudad, c.descripcion, c.direccion,
                cat.CATEGORIAS_ENTIDAD.get(c.categoria or "", ("",))[0], cat.ESPECIES.get(c.especie or "", ("",))[0],
            ])))
            if not all(t in bolsa for t in terminos):
                continue
        if raza_n and raza_n not in normalizar(c.raza):
            continue
        if c.es_mascota and (e_min is not None or e_max is not None):
            edad = edad_anios(c)
            if edad is None or (e_min is not None and edad < e_min) or (e_max is not None and edad > e_max + 0.999):
                continue
        c.distancia = distancia_km(p.lat, p.lng, c.lat, c.lng)
        if cerca == "distrito":
            if not p.distrito or normalizar(c.distrito) != normalizar(p.distrito):
                continue
        elif radio is not None:
            if c.distancia is None or c.distancia > radio:
                continue
        resultados.append(c)
    if cerca or radio:
        resultados.sort(key=lambda c: (c.distancia is None, c.distancia or 0))
    else:
        resultados.sort(key=lambda c: (-(c.verificada or 0), c.nombre.lower()))
    filtros = {"q": q, "tipo": tipo, "especie": especie, "raza": raza, "sexo": sexo, "edad_min": edad_min,
               "edad_max": edad_max, "cerca": cerca, "categoria": categoria, "pais": pais}
    return render(request, db, "buscar.html", u, p, resultados=resultados[:60], total=len(resultados),
                  f=filtros, ids_sigo=ids_seguidos(db, p.id), sin_ubicacion=(p.lat is None))


# =================================================================== pareja

def es_compatible(a: Perfil, b: Perfil) -> bool:
    if not (a and b and a.es_mascota and b.es_mascota):
        return False
    if a.usuario_id == b.usuario_id or not (a.busca_pareja and b.busca_pareja):
        return False
    if a.especie != b.especie or not a.sexo or not b.sexo or a.sexo == b.sexo:
        return False
    for m in (a, b):
        edad = edad_anios(m)
        if edad is not None and edad < 1:
            return False
    return True


def candidatos_pareja(db: Session, pet: Perfil):
    lista = db.query(Perfil).filter(Perfil.tipo == "mascota", Perfil.especie == pet.especie,
                                    Perfil.busca_pareja.is_(True), Perfil.usuario_id != pet.usuario_id).all()
    return [c for c in lista if es_compatible(pet, c)]


def avisar_compatibles(db: Session, pet: Perfil):
    for c in candidatos_pareja(db, pet):
        misma_raza = c.raza and pet.raza and normalizar(c.raza) == normalizar(pet.raza)
        notificar(db, c.id, "pareja",
                  f"💞 {pet.nombre} ({pet.raza or cat.ESPECIES.get(pet.especie, ('',))[0]}) también busca pareja"
                  + (" y es de tu misma raza." if misma_raza else "."),
                  "/pareja", actor_id=pet.id, clave=f"pareja-nueva:{pet.id}:{c.id}")
    db.commit()


@app.get("/pareja", response_class=HTMLResponse)
def pareja(request: Request, misma_raza: int = 0, cerca: str = ""):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    candidatos, recibidos, enviados_ids, matches = [], [], set(), set()
    edad = edad_anios(p) if p.es_mascota else None
    if p.es_mascota and p.busca_pareja:
        candidatos = candidatos_pareja(db, p)
        for c in candidatos:
            c.distancia = distancia_km(p.lat, p.lng, c.lat, c.lng)
            c.misma_raza = bool(c.raza and p.raza and normalizar(c.raza) == normalizar(p.raza))
        if misma_raza:
            candidatos = [c for c in candidatos if c.misma_raza]
        radio = a_float(cerca)
        if radio:
            candidatos = [c for c in candidatos if c.distancia is not None and c.distancia <= radio]
        candidatos.sort(key=lambda c: (not c.misma_raza, c.distancia is None, c.distancia or 0))
        enviados_ids = {i for (i,) in db.query(InteresPareja.para_id).filter(InteresPareja.de_id == p.id)}
        recibidos_ids = {i for (i,) in db.query(InteresPareja.de_id).filter(InteresPareja.para_id == p.id)}
        matches = enviados_ids & recibidos_ids
        if recibidos_ids:
            recibidos = db.query(Perfil).filter(Perfil.id.in_(recibidos_ids)).all()
    return render(request, db, "pareja.html", u, p, candidatos=candidatos, recibidos=recibidos,
                  enviados_ids=enviados_ids, matches=matches, misma_raza=misma_raza, cerca=cerca, edad=edad)


@app.post("/pareja/estado")
async def pareja_estado(request: Request):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    if not p.es_mascota:
        raise HTTPException(400)
    form = await request.form()
    activar = form.get("activar") == "1"
    if activar and not p.sexo:
        flash(request, "Indica el sexo de tu mascota en su perfil para activar la búsqueda de pareja.", "error")
        return RedirectResponse(f"/perfil/{p.id}/editar", 303)
    p.busca_pareja = activar
    db.commit()
    if activar:
        avisar_compatibles(db, p)
        flash(request, f"Búsqueda de pareja activada para {p.nombre}. Te avisaremos cuando haya mascotas compatibles.")
    else:
        flash(request, "Búsqueda de pareja desactivada.")
    return RedirectResponse("/pareja", 303)


@app.post("/api/pareja/interes/{pid}")
def pareja_interes(request: Request, pid: int):
    db = obtener_db(request)
    u, p = requiere_api(request, db)
    otro = db.get(Perfil, pid)
    if not otro or not es_compatible(p, otro):
        raise HTTPException(400, "Estas mascotas no son compatibles o alguna desactivó la búsqueda.")
    if not db.query(InteresPareja.id).filter(InteresPareja.de_id == p.id, InteresPareja.para_id == pid).first():
        db.add(InteresPareja(de_id=p.id, para_id=pid))
        notificar(db, pid, "pareja", f"💞 A {p.nombre} le interesa conocer a {otro.nombre}.", f"/p/{p.handle}",
                  actor_id=p.id, clave=f"interes:{p.id}:{pid}")
    mutuo = db.query(InteresPareja.id).filter(InteresPareja.de_id == pid, InteresPareja.para_id == p.id).first()
    if mutuo:
        notificar(db, pid, "match", f"🎉 ¡Match! {p.nombre} y {otro.nombre} se interesaron mutuamente.",
                  f"/p/{p.handle}", actor_id=p.id, clave=f"match:{p.id}:{pid}:a")
        notificar(db, p.id, "match", f"🎉 ¡Match! {otro.nombre} y {p.nombre} se interesaron mutuamente.",
                  f"/p/{otro.handle}", actor_id=otro.id, clave=f"match:{p.id}:{pid}:b")
    db.commit()
    return {"estado": "match" if mutuo else "enviado"}


# =================================================================== calendario

@app.get("/calendario", response_class=HTMLResponse)
def calendario(request: Request, mes: str = "", mascota: str = ""):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    mascota = a_int(mascota)
    hoy = date.today()
    try:
        anio, m = (int(x) for x in mes.split("-"))
        primero = date(anio, m, 1)
    except Exception:
        primero = hoy.replace(day=1)
    siguiente = (primero.replace(day=28) + timedelta(days=4)).replace(day=1)
    anterior = (primero - timedelta(days=1)).replace(day=1)

    mascotas = mis_mascotas(u)
    ids = [x.id for x in mascotas if (mascota is None or x.id == mascota)]
    inicio_grilla = primero - timedelta(days=primero.weekday())
    fin_grilla = inicio_grilla + timedelta(days=41)

    por_dia = {}
    if ids:
        for e in (db.query(Evento).options(selectinload(Evento.mascota))
                  .filter(Evento.perfil_id.in_(ids), Evento.fecha >= inicio_grilla, Evento.fecha <= fin_grilla)
                  .order_by(Evento.hora).all()):
            por_dia.setdefault(e.fecha, []).append({"evento": e, "tipo": e.tipo, "titulo": e.titulo,
                                                    "mascota": e.mascota, "hora": e.hora})
        amigos = (db.query(Perfil).join(Seguimiento, Seguimiento.seguido_id == Perfil.id)
                  .filter(Seguimiento.seguidor_id.in_(ids), Perfil.tipo == "mascota",
                          Perfil.fecha_nacimiento.isnot(None)).distinct().all())
        cumpleaneros = [x for x in mascotas if x.id in ids] + amigos
        dia = inicio_grilla
        while dia <= fin_grilla:
            for c in cumpleaneros:
                if c.fecha_nacimiento and cumple_en_fecha(c.fecha_nacimiento, dia) and dia >= c.fecha_nacimiento:
                    anios = dia.year - c.fecha_nacimiento.year
                    propio = c.usuario_id == u.id
                    por_dia.setdefault(dia, []).insert(0, {
                        "evento": None, "tipo": "cumpleanos", "mascota": c, "hora": None,
                        "titulo": f"{c.nombre} cumple {anios}" if propio else f"Cumple {c.nombre} (amigo)"})
            dia += timedelta(days=1)

    semanas, dia = [], inicio_grilla
    for _ in range(6):
        semana = []
        for _ in range(7):
            semana.append({"fecha": dia, "del_mes": dia.month == primero.month, "hoy": dia == hoy,
                           "items": por_dia.get(dia, [])})
            dia += timedelta(days=1)
        semanas.append(semana)
    if all(not d["del_mes"] for d in semanas[-1]):
        semanas.pop()

    proximos = proximos_eventos(db, u, hoy, dias=60, limite=8)
    if mascota:
        proximos = [x for x in proximos if x["mascota"].id == mascota or x["mascota"].usuario_id != u.id]
    return render(request, db, "calendario.html", u, p, semanas=semanas, primero=primero, anterior=anterior,
                  siguiente=siguiente, mascotas=mascotas, filtro_mascota=mascota, proximos=proximos)


@app.post("/calendario/evento")
async def guardar_evento(request: Request):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    form = await request.form()
    mascota = db.get(Perfil, a_int(form.get("mascota_id")))
    if not mascota or mascota.usuario_id != u.id or not mascota.es_mascota:
        flash(request, "Elige una de tus mascotas.", "error")
        return RedirectResponse("/calendario", 303)
    fecha = a_fecha(form.get("fecha"))
    titulo = (form.get("titulo") or "").strip()[:200]
    if not fecha or not titulo:
        flash(request, "El evento necesita título y fecha.", "error")
        return RedirectResponse("/calendario", 303)
    eid = a_int(form.get("evento_id"))
    if eid:
        ev = db.get(Evento, eid)
        if not ev or ev.perfil_id not in {x.id for x in u.perfiles}:
            raise HTTPException(404)
    else:
        ev = Evento()
        db.add(ev)
    alerta = a_int(form.get("alerta_dias"))
    nueva_alerta = alerta if alerta in (0, 1, 3, 7) else None
    if eid and (ev.fecha != fecha or ev.alerta_dias != nueva_alerta):
        ev.alerta_enviada = False
    ev.perfil_id = mascota.id
    ev.tipo = form.get("tipo") if form.get("tipo") in cat.TIPOS_EVENTO else "otro"
    ev.titulo = titulo
    ev.fecha = fecha
    hora = (form.get("hora") or "").strip()
    ev.hora = hora[:5] if len(hora) >= 4 else None
    ev.lugar = (form.get("lugar") or "").strip()[:200] or None
    ev.notas = (form.get("notas") or "").strip()[:1000] or None
    ev.alerta_dias = nueva_alerta
    db.commit()
    request.session["ult_recordatorio"] = 0
    flash(request, "Evento guardado en el calendario." if not eid else "Evento actualizado.")
    return RedirectResponse(f"/calendario?mes={fecha:%Y-%m}", 303)


@app.post("/calendario/evento/{eid}/eliminar")
def eliminar_evento(request: Request, eid: int):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    ev = db.get(Evento, eid)
    if not ev or ev.perfil_id not in {x.id for x in u.perfiles}:
        raise HTTPException(404)
    mes = f"{ev.fecha:%Y-%m}"
    db.delete(ev)
    db.commit()
    flash(request, "Evento eliminado.")
    return RedirectResponse(f"/calendario?mes={mes}", 303)


@app.get("/calendario/evento/{eid}.ics")
def evento_ics(request: Request, eid: int):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    ev = db.get(Evento, eid)
    if not ev or ev.perfil_id not in {x.id for x in u.perfiles}:
        raise HTTPException(404)

    def esc(t):
        return (t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    if ev.hora:
        inicio = datetime.combine(ev.fecha, datetime.strptime(ev.hora, "%H:%M").time())
        dt = f"DTSTART:{inicio:%Y%m%dT%H%M%S}\r\nDTEND:{inicio + timedelta(hours=1):%Y%m%dT%H%M%S}"
    else:
        dt = f"DTSTART;VALUE=DATE:{ev.fecha:%Y%m%d}\r\nDTEND;VALUE=DATE:{ev.fecha + timedelta(days=1):%Y%m%d}"
    alarma = ""
    if ev.alerta_dias is not None:
        alarma = (f"BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:{esc(ev.titulo)}\r\n"
                  f"TRIGGER:-P{max(ev.alerta_dias, 0)}DT{0 if ev.alerta_dias else 2}H\r\nEND:VALARM\r\n")
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Pawbook//ES\r\nBEGIN:VEVENT\r\n"
        f"UID:pawbook-evento-{ev.id}@pawbook\r\nDTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}\r\n{dt}\r\n"
        f"SUMMARY:{esc(ev.titulo)} ({esc(ev.mascota.nombre)})\r\n"
        + (f"LOCATION:{esc(ev.lugar)}\r\n" if ev.lugar else "")
        + (f"DESCRIPTION:{esc(ev.notas)}\r\n" if ev.notas else "")
        + alarma + "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    return Response(ics, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="pawbook-evento-{ev.id}.ics"'})


# =================================================================== mapa

@app.get("/mapa", response_class=HTMLResponse)
def mapa(request: Request):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    return render(request, db, "mapa.html", u, p)


@app.get("/api/mapa")
def api_mapa(request: Request):
    db = obtener_db(request)
    u, p = requiere_api(request, db)
    marcadores = []
    for e in db.query(Perfil).filter(Perfil.tipo == "entidad", Perfil.lat.isnot(None), Perfil.lng.isnot(None),
                                     Perfil.mostrar_en_mapa.is_(True)).all():
        nombre_cat, emoji = cat.CATEGORIAS_ENTIDAD.get(e.categoria or "otro", ("Otro", "⭐"))
        marcadores.append({
            "capa": cat.CATEGORIA_A_CAPA.get(e.categoria or "otro", "servicios"), "nombre": e.nombre,
            "sub": nombre_cat + (" · " + e.direccion if e.direccion else ""), "horario": e.horario or "",
            "lat": e.lat, "lng": e.lng, "url": f"/p/{e.handle}", "emoji": emoji, "verificada": bool(e.verificada),
        })
    for l in db.query(Lugar).all():
        etiqueta, emoji, capa = cat.TIPOS_LUGAR.get(l.tipo, ("Otro", "📍", "servicios"))
        marcadores.append({"capa": capa, "nombre": l.nombre, "sub": etiqueta + (" · " + l.distrito if l.distrito else ""),
                           "horario": l.descripcion or "", "lat": l.lat, "lng": l.lng, "url": None, "emoji": emoji})
    seguidos = ids_seguidos(db, p.id)
    mios = {x.id for x in u.perfiles}
    mascotas = db.query(Perfil).filter(Perfil.tipo == "mascota", Perfil.lat.isnot(None), Perfil.lng.isnot(None),
                                       Perfil.mostrar_en_mapa.is_(True)).all()
    for m in mascotas:
        mismo_distrito = p.distrito and m.distrito and normalizar(m.distrito) == normalizar(p.distrito)
        if m.id in mios or not (m.id in seguidos or mismo_distrito):
            continue
        desfase = ((m.id * 37) % 100 - 50) / 25000  # separa marcadores que caen en el mismo punto
        marcadores.append({
            "capa": "amigos", "nombre": m.nombre,
            "sub": f"{m.raza or cat.ESPECIES.get(m.especie or 'otro', ('',))[0]} · {m.distrito or ''}"
                   + (" · Amigo" if m.id in seguidos else " · Vecino"),
            "horario": "", "lat": m.lat + desfase, "lng": m.lng - desfase, "url": f"/p/{m.handle}",
            "emoji": emoji_perfil(m), "foto": m.foto,
        })
    desde = datetime.now() - timedelta(days=60)
    for r in (db.query(ReportePerdido).options(selectinload(ReportePerdido.mascota))
              .filter(ReportePerdido.estado == "activo", ReportePerdido.lat.isnot(None),
                      ReportePerdido.lng.isnot(None), ReportePerdido.creado >= desde).all()):
        sello = cat.TIPOS_AVISO.get(r.tipo, ("", "📍", ""))
        marcadores.append({
            "capa": "perdidos", "nombre": titulo_aviso(r),
            "sub": " · ".join(x for x in [sello[2], r.distrito, fecha_corta(r.fecha)] if x),
            "horario": r.referencia or "", "lat": r.lat, "lng": r.lng, "url": f"/perdidos/{r.id}",
            "emoji": sello[1], "foto": r.foto_mostrar, "boton": "Ver aviso", "sin_ruta": True,
        })
    centro = [p.lat, p.lng] if p.lat is not None else list(cat.CENTRO_MAPA)
    return {"centro": centro, "marcadores": marcadores, "capas": cat.CAPAS_MAPA}


# =================================================================== anuncios

@app.get("/anuncios", response_class=HTMLResponse)
def mis_anuncios(request: Request):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    anuncios = []
    if p.es_entidad:
        anuncios = db.query(Anuncio).filter(Anuncio.perfil_id == p.id).order_by(Anuncio.id.desc()).all()
    puede_gratis_todo = p.es_entidad and p.categoria in cat.ENTIDADES_ANUNCIO_GRATIS
    return render(request, db, "anuncios.html", u, p, anuncios=anuncios, puede_gratis_todo=puede_gratis_todo)


@app.post("/anuncios/nuevo")
async def crear_anuncio(request: Request):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    if not p.es_entidad:
        raise HTTPException(403)
    form = await request.form()
    tipo = form.get("tipo") if form.get("tipo") in ("pagado", "gratuito") else "pagado"
    titulo = (form.get("titulo") or "").strip()[:120]
    texto = (form.get("texto") or "").strip()[:600]
    if not titulo:
        flash(request, "El anuncio necesita un título.", "error")
        return RedirectResponse("/anuncios", 303)
    if tipo == "gratuito":
        categoria = form.get("categoria_gratuito")
        if categoria not in cat.CATEGORIAS_ANUNCIO_GRATUITO:
            categoria = "adopcion"
        permitido = p.categoria in cat.ENTIDADES_ANUNCIO_GRATIS or categoria in cat.CAMPANAS_GRATIS_PARA_TODOS
        if not permitido:
            flash(request, "Los anuncios gratuitos son para centros de adopción, caridades y campañas gratuitas "
                           "de vacunación o esterilización.", "error")
            return RedirectResponse("/anuncios", 303)
        plan = None
    else:
        categoria = form.get("categoria_pagado")
        if categoria not in cat.CATEGORIAS_ANUNCIO_PAGADO:
            categoria = "promocion"
        plan = form.get("plan") if form.get("plan") in cat.PLANES_ANUNCIO else "semana"
    try:
        imagen = await guardar_imagen(form.get("imagen"), "anuncios", 1200)
    except ValueError as e:
        flash(request, str(e), "error")
        return RedirectResponse("/anuncios", 303)
    fin = a_fecha(form.get("fecha_fin")) if tipo == "gratuito" else None
    db.add(Anuncio(perfil_id=p.id, tipo=tipo, categoria=categoria, titulo=titulo, texto=texto, imagen=imagen,
                   enlace=url_segura(form.get("enlace")), plan=plan, fecha_fin=fin, estado="pendiente"))
    db.commit()
    flash(request, "Anuncio enviado. Quedará visible cuando el equipo de Pawbook lo apruebe"
                   + (" y se confirme el pago." if tipo == "pagado" else "."))
    return RedirectResponse("/anuncios", 303)


@app.post("/anuncios/{aid}/pausar")
def pausar_anuncio(request: Request, aid: int):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    a = db.get(Anuncio, aid)
    if not a or a.perfil_id not in {x.id for x in u.perfiles}:
        raise HTTPException(404)
    if a.estado == "activo":
        a.estado = "pausado"
    elif a.estado == "pausado":
        a.estado = "activo"
    db.commit()
    return RedirectResponse("/anuncios", 303)


@app.post("/anuncios/{aid}/eliminar")
def eliminar_anuncio(request: Request, aid: int):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    a = db.get(Anuncio, aid)
    if not a or a.perfil_id not in {x.id for x in u.perfiles}:
        raise HTTPException(404)
    borrar_archivo(a.imagen)
    db.delete(a)
    db.commit()
    flash(request, "Anuncio eliminado.")
    return RedirectResponse("/anuncios", 303)


@app.get("/anuncio/{aid}/ir")
def ir_anuncio(request: Request, aid: int):
    db = obtener_db(request)
    a = db.get(Anuncio, aid)
    if not a:
        raise HTTPException(404)
    hoy = date.today()
    vigente = (a.estado == "activo" and (a.fecha_inicio is None or a.fecha_inicio <= hoy)
               and (a.fecha_fin is None or a.fecha_fin >= hoy))
    if not vigente:
        # Un anuncio sin aprobar no debe servir para mandar gente a un enlace que nadie revisó.
        return RedirectResponse(f"/p/{a.anunciante.handle}", 303)
    a.clics = (a.clics or 0) + 1
    db.commit()
    return RedirectResponse(a.enlace or f"/p/{a.anunciante.handle}", 303)


# =================================================================== restaurantes pet friendly

@app.get("/pet-friendly", response_class=HTMLResponse)
def pet_friendly(request: Request, q: str = "", distrito: str = "", amenidad: List[str] = Query(default=[])):
    db = obtener_db(request)
    u = usuario_sesion(request, db)
    p = perfil_activo(u, db) if u else None
    filtros_amen = [a for a in amenidad if a in cat.AMENIDADES_PET_FRIENDLY]
    items = []
    for e in db.query(Perfil).filter(Perfil.tipo == "entidad", Perfil.categoria == "restaurante").all():
        items.append({"perfil": e, "nombre": e.nombre, "distrito": e.distrito, "direccion": e.direccion,
                      "horario": e.horario, "descripcion": e.descripcion, "lat": e.lat, "lng": e.lng,
                      "verificada": bool(e.verificada),
                      "amenidades": [a for a in e.lista_tags if a in cat.AMENIDADES_PET_FRIENDLY]})
    for l in db.query(Lugar).filter(Lugar.tipo == "restaurante").all():
        items.append({"perfil": None, "nombre": l.nombre, "distrito": l.distrito, "direccion": l.direccion,
                      "horario": "", "descripcion": l.descripcion, "lat": l.lat, "lng": l.lng,
                      "verificada": False, "amenidades": []})
    distritos = sorted({x["distrito"] for x in items if x["distrito"]}, key=normalizar)

    terminos = normalizar(q).split()
    resultados = []
    for x in items:
        if terminos:
            bolsa = normalizar(" ".join(filter(None, [x["nombre"], x["distrito"], x["direccion"], x["descripcion"]])))
            if not all(t in bolsa for t in terminos):
                continue
        if distrito and normalizar(x["distrito"]) != normalizar(distrito):
            continue
        if any(a not in x["amenidades"] for a in filtros_amen):
            continue
        x["distancia"] = distancia_km(p.lat, p.lng, x["lat"], x["lng"]) if p else None
        resultados.append(x)
    if any(x["distancia"] is not None for x in resultados):
        resultados.sort(key=lambda x: (x["distancia"] is None, x["distancia"] or 0))
    else:
        resultados.sort(key=lambda x: (not x["verificada"], normalizar(x["nombre"])))
    return render(request, db, "pet_friendly.html", u, p, resultados=resultados, distritos=distritos,
                  f={"q": q, "distrito": distrito, "amenidad": filtros_amen},
                  ids_sigo=ids_seguidos(db, p.id) if p else set())


# =================================================================== mascotas perdidas y encontradas

FEMENINO_ESPECIE = {"perro": "perrita", "gato": "gata", "conejo": "coneja"}


def sustantivo_especie(especie: str, sexo: str):
    """Sustantivo y género para redactar avisos con la concordancia correcta: ('perrita', 'f'), ('gato', 'm')."""
    e = especie if especie in cat.ESPECIES else "otro"
    if e == "otro":
        return "mascota", "f"
    if sexo == "hembra" and e in FEMENINO_ESPECIE:
        return FEMENINO_ESPECIE[e], "f"
    return cat.ESPECIES[e][0].lower(), ("f" if e in ("ave", "tortuga") else "m")


def titulo_aviso(r: ReportePerdido) -> str:
    sust, g = sustantivo_especie(r.especie, r.sexo)
    o = "a" if g == "f" else "o"
    if r.es_perdido:
        return f"Se busca a {r.nombre}" if r.activo else f"¡{r.nombre} volvió a casa!"
    if r.activo:
        return f"{sust.capitalize()} encontrad{o}" + (f" en {r.distrito}" if r.distrito else "")
    return f"{sust.capitalize()} reunid{o} con su familia"


templates.env.globals["titulo_aviso"] = titulo_aviso


def es_cercano(lat1, lng1, distrito1, lat2, lng2, distrito2, radio_km: float) -> bool:
    d = distancia_km(lat1, lng1, lat2, lng2)
    if d is not None and d <= radio_km:
        return True
    return bool(distrito1 and distrito2 and normalizar(distrito1) == normalizar(distrito2))


def consulta_avisos(db: Session):
    return db.query(ReportePerdido).options(selectinload(ReportePerdido.mascota), selectinload(ReportePerdido.autor))


def avisos_cercanos(db: Session, p: Perfil, limite: int = 3):
    desde = datetime.now() - timedelta(days=45)
    lista = (consulta_avisos(db).filter(ReportePerdido.estado == "activo", ReportePerdido.creado >= desde)
             .order_by(ReportePerdido.id.desc()).limit(200).all())
    return [r for r in lista if es_cercano(p.lat, p.lng, p.distrito, r.lat, r.lng, r.distrito,
                                           cat.RADIO_COINCIDENCIA_KM)][:limite]


def coincidencias(db: Session, r: ReportePerdido, limite: int = 6):
    """Avisos del tipo contrario (perdido <-> encontrado) que podrían ser la misma mascota."""
    opuesto = "encontrado" if r.es_perdido else "perdido"
    q = consulta_avisos(db).filter(ReportePerdido.tipo == opuesto, ReportePerdido.estado == "activo",
                                   ReportePerdido.id != r.id, ReportePerdido.usuario_id != r.usuario_id,
                                   ReportePerdido.creado >= datetime.now() - timedelta(days=90))
    if r.especie and r.especie != "otro":
        q = q.filter(ReportePerdido.especie == r.especie)
    lista = [x for x in q.order_by(ReportePerdido.id.desc()).limit(200).all()
             if not (r.sexo and x.sexo and r.sexo != x.sexo)
             and es_cercano(r.lat, r.lng, r.distrito, x.lat, x.lng, x.distrito, cat.RADIO_COINCIDENCIA_KM)]
    return lista[:limite]


def avisar_reporte(db: Session, r: ReportePerdido):
    """Notifica a quienes siguen a la mascota, a los vecinos de la zona y a avisos que podrían coincidir.
    Una notificación por cuenta (no por perfil) para no repetir avisos."""
    sust, g = sustantivo_especie(r.especie, r.sexo)
    un = "una" if g == "f" else "un"
    lo = "La" if g == "f" else "Lo"
    zona = r.distrito or "tu zona"
    destinos = {}  # usuario_id -> perfil_id

    if r.es_perdido and r.mascota_id:
        for pid, uid in (db.query(Perfil.id, Perfil.usuario_id)
                         .join(Seguimiento, Seguimiento.seguidor_id == Perfil.id)
                         .filter(Seguimiento.seguido_id == r.mascota_id)):
            if uid != r.usuario_id and uid not in destinos:
                destinos[uid] = pid
                notificar(db, pid, "perdido", f"🚨 Tu amigo {r.nombre} se perdió en {zona}. ¿{lo} has visto?",
                          f"/perdidos/{r.id}", actor_id=r.mascota_id, clave=f"aviso:{r.id}:{uid}")

    for v in db.query(Perfil).filter(Perfil.usuario_id != r.usuario_id).all():
        if v.usuario_id in destinos or not es_cercano(r.lat, r.lng, r.distrito, v.lat, v.lng, v.distrito,
                                                      cat.RADIO_AVISO_KM):
            continue
        destinos[v.usuario_id] = v.id
        if r.es_perdido:
            texto = f"🚨 Se busca a {r.nombre} ({sust}), se perdió en {zona}. ¿{lo} has visto?"
        else:
            texto = f"🔎 Encontraron {un} {sust} en {zona}. ¿Sabes quién es su familia?"
        notificar(db, v.id, "perdido", texto, f"/perdidos/{r.id}", clave=f"aviso:{r.id}:{v.usuario_id}")

    for x in coincidencias(db, r, limite=20):
        destino = x.mascota_id or x.autor_id
        if not destino:
            continue
        if r.es_perdido:
            texto = f"🚨 Una familia busca a {r.nombre} ({sust}) cerca de donde encontraste una mascota. ¿Será?"
        else:
            texto = f"🔎 Encontraron {un} {sust} en {zona} que podría ser {x.nombre}. Revisa el aviso."
        notificar(db, destino, "perdido", texto, f"/perdidos/{r.id}", clave=f"coincide:{r.id}:{x.id}")
    db.commit()


def aviso_a_datos(r: ReportePerdido) -> dict:
    campos = ["id", "tipo", "nombre", "especie", "raza", "sexo", "color", "descripcion", "foto", "hora", "distrito",
              "referencia", "lat", "lng", "telefono", "recompensa", "mascota_id"]
    d = {c: getattr(r, c) for c in campos}
    d["fecha"] = r.fecha.isoformat() if r.fecha else ""
    return d


async def aplicar_formulario_aviso(db: Session, r: ReportePerdido, form, u: Usuario) -> Optional[str]:
    r.tipo = form.get("tipo") if form.get("tipo") in cat.TIPOS_AVISO else "perdido"
    mascota = None
    if r.tipo == "perdido":
        m = db.get(Perfil, a_int(form.get("mascota_id")) or 0)
        if m and m.usuario_id == u.id and m.es_mascota:
            mascota = m
    r.mascota_id = mascota.id if mascota else None
    r.nombre = (form.get("nombre") or "").strip()[:120] or (mascota.nombre if mascota else "")
    if r.tipo == "perdido" and not r.nombre:
        return "Escribe el nombre de tu mascota."
    especie = form.get("especie")
    r.especie = especie if especie in cat.ESPECIES else (mascota.especie if mascota else "otro")
    r.raza = ((form.get("raza") or "").strip() or (mascota.raza if mascota else "") or "")[:120]
    r.sexo = form.get("sexo") if form.get("sexo") in cat.SEXOS else None
    r.color = (form.get("color") or "").strip()[:150]
    r.descripcion = (form.get("descripcion") or "").strip()[:1500]
    fecha = a_fecha(form.get("fecha")) or date.today()
    if fecha > date.today():
        return "La fecha no puede ser futura."
    r.fecha = fecha
    hora = (form.get("hora") or "").strip()
    r.hora = hora[:5] if len(hora) >= 4 else None
    r.distrito = (form.get("distrito") or "").strip()[:120]
    r.referencia = (form.get("referencia") or "").strip()[:250]
    lat, lng = a_float(form.get("lat")), a_float(form.get("lng"))
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        lat = lng = None
    r.lat, r.lng = coordenada_aproximada(lat), coordenada_aproximada(lng)
    if not r.distrito and r.lat is None:
        return "Indica el distrito o marca en el mapa dónde fue."
    telefono = (form.get("telefono") or "").strip()[:60]
    if len(re.sub(r"\D", "", telefono)) < 6:
        return "Deja un teléfono o WhatsApp para que puedan contactarte."
    r.telefono = telefono
    r.recompensa = ((form.get("recompensa") or "").strip()[:120] or None) if r.tipo == "perdido" else None
    try:
        foto = await guardar_imagen(form.get("foto"), "perdidos", 1200)
    except ValueError as e:
        return str(e)
    if foto:
        borrar_archivo(r.foto)
        r.foto = foto
    elif form.get("quitar_foto") == "1":
        borrar_archivo(r.foto)
        r.foto = None
    return None


def requiere_aviso_propio(request: Request, db: Session, rid: int):
    u = requiere_usuario(request, db)
    r = db.get(ReportePerdido, rid)
    if not r or r.usuario_id != u.id:
        raise HTTPException(404)
    return u, r


@app.get("/perdidos", response_class=HTMLResponse)
def perdidos(request: Request, tab: str = "perdido", especie: str = "", distrito: str = "", cerca: str = ""):
    db = obtener_db(request)
    u = usuario_sesion(request, db)
    p = perfil_activo(u, db) if u else None
    if tab not in ("perdido", "encontrado", "reunidos"):
        tab = "perdido"
    conteos = dict(db.query(ReportePerdido.tipo, func.count(ReportePerdido.id))
                   .filter(ReportePerdido.estado == "activo").group_by(ReportePerdido.tipo).all())
    conteos["reunidos"] = db.query(func.count(ReportePerdido.id)).filter(ReportePerdido.estado == "resuelto").scalar()
    q = consulta_avisos(db)
    if tab == "reunidos":
        q = q.filter(ReportePerdido.estado == "resuelto").order_by(ReportePerdido.resuelto_en.desc(),
                                                                   ReportePerdido.id.desc())
    else:
        q = q.filter(ReportePerdido.tipo == tab, ReportePerdido.estado == "activo").order_by(
            ReportePerdido.fecha.desc(), ReportePerdido.id.desc())
    if especie in cat.ESPECIES:
        q = q.filter(ReportePerdido.especie == especie)
    lista = q.limit(300).all()
    if distrito:
        lista = [r for r in lista if normalizar(distrito) in normalizar(r.distrito)]
    radio = a_float(cerca)
    for r in lista:
        r.distancia = distancia_km(p.lat, p.lng, r.lat, r.lng) if p else None
    if p and cerca == "distrito":
        lista = [r for r in lista if p.distrito and normalizar(r.distrito) == normalizar(p.distrito)]
    elif p and radio:
        lista = [r for r in lista if es_cercano(p.lat, p.lng, p.distrito, r.lat, r.lng, r.distrito, radio)]
    return render(request, db, "perdidos.html", u, p, lista=lista[:60], total=len(lista), tab=tab, conteos=conteos,
                  f={"especie": especie, "distrito": distrito, "cerca": cerca})


@app.get("/perdidos/nuevo", response_class=HTMLResponse)
def nuevo_aviso_form(request: Request, tipo: str = "perdido", mascota: Optional[int] = None):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    p = perfil_activo(u, db)
    ultimo = (db.query(ReportePerdido.telefono).filter(ReportePerdido.usuario_id == u.id)
              .order_by(ReportePerdido.id.desc()).first())
    telefono = ultimo[0] if ultimo else (p.telefono if p and p.es_entidad else "")
    datos = {"tipo": tipo if tipo in cat.TIPOS_AVISO else "perdido", "fecha": date.today().isoformat(),
             "especie": "perro", "telefono": telefono or "", "distrito": p.distrito if p else ""}
    elegida = next((m for m in mis_mascotas(u) if m.id == mascota), None)
    if elegida:
        datos.update({"tipo": "perdido", "mascota_id": elegida.id, "nombre": elegida.nombre,
                      "especie": elegida.especie, "raza": elegida.raza, "sexo": elegida.sexo,
                      "distrito": elegida.distrito or datos["distrito"]})
    return render(request, db, "perdido_form.html", u, p, datos=datos, nuevo=True, mascotas=mis_mascotas(u))


@app.post("/perdidos/nuevo")
async def crear_aviso(request: Request):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    p = perfil_activo(u, db)
    form = await request.form()
    r = ReportePerdido(usuario_id=u.id, autor_id=p.id if p else None)
    error = await aplicar_formulario_aviso(db, r, form, u)
    if error:
        datos = dict(form)
        datos.pop("foto", None)
        return render(request, db, "perdido_form.html", u, p, datos=datos, nuevo=True, mascotas=mis_mascotas(u),
                      error=error)
    db.add(r)
    db.commit()
    avisar_reporte(db, r)
    n = len(coincidencias(db, r))
    flash(request, "Aviso publicado. Avisamos a los vecinos de la zona y a sus amigos en Pawbook."
          + (f" Hay {n} aviso(s) que podrían coincidir: revísalos abajo." if n else "")
          + " Comparte el enlace para llegar a más personas.")
    return RedirectResponse(f"/perdidos/{r.id}", 303)


@app.get("/perdidos/{rid}", response_class=HTMLResponse)
def ver_aviso(request: Request, rid: int):
    db = obtener_db(request)
    u = usuario_sesion(request, db)
    p = perfil_activo(u, db) if u else None
    r = consulta_avisos(db).filter(ReportePerdido.id == rid).first()
    if not r:
        raise HTTPException(404)
    es_mio = bool(u and r.usuario_id == u.id)
    return render(request, db, "perdido.html", u, p, r=r, es_mio=es_mio, es_admin=bool(u and u.es_admin),
                  parecidos=coincidencias(db, r) if r.activo else [],
                  distancia=distancia_km(p.lat, p.lng, r.lat, r.lng) if p and not es_mio else None,
                  enlace=str(request.url).split("?")[0])


@app.get("/perdidos/{rid}/editar", response_class=HTMLResponse)
def editar_aviso_form(request: Request, rid: int):
    db = obtener_db(request)
    u, r = requiere_aviso_propio(request, db, rid)
    return render(request, db, "perdido_form.html", u, perfil_activo(u, db), datos=aviso_a_datos(r), nuevo=False,
                  mascotas=mis_mascotas(u))


@app.post("/perdidos/{rid}/editar")
async def editar_aviso(request: Request, rid: int):
    db = obtener_db(request)
    u, r = requiere_aviso_propio(request, db, rid)
    form = await request.form()
    error = await aplicar_formulario_aviso(db, r, form, u)
    if error:
        db.rollback()
        datos = dict(form)
        datos.pop("foto", None)
        datos.update({"id": r.id, "foto": r.foto})
        return render(request, db, "perdido_form.html", u, perfil_activo(u, db), datos=datos, nuevo=False,
                      mascotas=mis_mascotas(u), error=error)
    db.commit()
    flash(request, "Aviso actualizado.")
    return RedirectResponse(f"/perdidos/{r.id}", 303)


@app.post("/perdidos/{rid}/resolver")
def resolver_aviso(request: Request, rid: int):
    db = obtener_db(request)
    u, r = requiere_aviso_propio(request, db, rid)
    if r.activo:
        r.estado = "resuelto"
        r.resuelto_en = datetime.now()
        # Buenas noticias para todos los que recibieron la alerta
        avisados = {pid for (pid,) in db.query(Notificacion.perfil_id).filter(
            Notificacion.clave.like(f"aviso:{r.id}:%"))}
        texto = (f"🎉 ¡Buenas noticias! {r.nombre} ya volvió a casa. Gracias por ayudar." if r.es_perdido
                 else "🎉 La mascota encontrada ya volvió con su familia. Gracias por ayudar.")
        for pid in avisados:
            notificar(db, pid, "perdido", texto, f"/perdidos/{r.id}", clave=f"aviso-fin:{r.id}:{pid}")
        flash(request, "¡Qué alegría! 🎉 Marcamos el aviso como resuelto y avisamos a quienes ayudaron a buscar.")
    else:
        r.estado = "activo"
        r.resuelto_en = None
        flash(request, "El aviso está activo otra vez.")
    db.commit()
    return RedirectResponse(f"/perdidos/{r.id}", 303)


@app.post("/perdidos/{rid}/eliminar")
def eliminar_aviso(request: Request, rid: int):
    db = obtener_db(request)
    u = requiere_usuario(request, db)
    r = db.get(ReportePerdido, rid)
    if not r or (r.usuario_id != u.id and not u.es_admin):
        raise HTTPException(404)
    borrar_archivo(r.foto)
    # Las notificaciones de este aviso quedarían con un enlace roto
    db.query(Notificacion).filter(Notificacion.enlace == f"/perdidos/{r.id}").delete(synchronize_session=False)
    db.delete(r)
    db.commit()
    flash(request, "Aviso eliminado.")
    return RedirectResponse("/perdidos", 303)


# =================================================================== administración

def requiere_admin(request: Request, db: Session) -> Usuario:
    u = requiere_usuario(request, db)
    if not u.es_admin:
        raise HTTPException(404)
    return u


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    db = obtener_db(request)
    u = requiere_admin(request, db)
    p = perfil_activo(u, db)
    anuncios = db.query(Anuncio).options(selectinload(Anuncio.anunciante)).order_by(
        (Anuncio.estado != "pendiente"), Anuncio.id.desc()).limit(100).all()
    stats = {
        "usuarios": db.query(func.count(Usuario.id)).scalar(),
        "mascotas": db.query(func.count(Perfil.id)).filter(Perfil.tipo == "mascota").scalar(),
        "entidades": db.query(func.count(Perfil.id)).filter(Perfil.tipo == "entidad").scalar(),
        "publicaciones": db.query(func.count(Publicacion.id)).scalar(),
        "anuncios_activos": db.query(func.count(Anuncio.id)).filter(Anuncio.estado == "activo").scalar(),
        "avisos_perdidos": db.query(func.count(ReportePerdido.id)).filter(ReportePerdido.estado == "activo").scalar(),
    }
    entidades = db.query(Perfil).filter(Perfil.tipo == "entidad").order_by(Perfil.verificada, Perfil.nombre).all()
    lugares = db.query(Lugar).order_by(Lugar.tipo, Lugar.nombre).all()
    return render(request, db, "admin.html", u, p, anuncios=anuncios, stats=stats, entidades=entidades, lugares=lugares)


@app.post("/admin/anuncio/{aid}/{accion}")
def admin_anuncio(request: Request, aid: int, accion: str):
    db = obtener_db(request)
    requiere_admin(request, db)
    a = db.get(Anuncio, aid)
    if not a or accion not in ("aprobar", "rechazar"):
        raise HTTPException(404)
    if accion == "aprobar":
        a.estado = "activo"
        a.fecha_inicio = date.today()
        if a.tipo == "pagado":
            a.fecha_fin = date.today() + timedelta(days=cat.PLANES_ANUNCIO.get(a.plan or "semana")[1])
        elif not a.fecha_fin or a.fecha_fin < date.today():
            a.fecha_fin = date.today() + timedelta(days=30)
        notificar(db, a.perfil_id, "anuncio", f"✅ Tu anuncio “{a.titulo}” fue aprobado y ya está visible.", "/anuncios")
    else:
        a.estado = "rechazado"
        notificar(db, a.perfil_id, "anuncio", f"Tu anuncio “{a.titulo}” no fue aprobado. Revisa las condiciones.",
                  "/anuncios")
    db.commit()
    return RedirectResponse("/admin", 303)


@app.post("/admin/perfil/{pid}/verificar")
def admin_verificar(request: Request, pid: int):
    db = obtener_db(request)
    requiere_admin(request, db)
    pf = db.get(Perfil, pid)
    if not pf:
        raise HTTPException(404)
    pf.verificada = not pf.verificada
    db.commit()
    return RedirectResponse("/admin#entidades", 303)


@app.post("/admin/lugar")
async def admin_lugar(request: Request):
    db = obtener_db(request)
    requiere_admin(request, db)
    form = await request.form()
    lat, lng = a_float(form.get("lat")), a_float(form.get("lng"))
    nombre = (form.get("nombre") or "").strip()[:150]
    if not nombre or lat is None or lng is None:
        flash(request, "El lugar necesita nombre y ubicación en el mapa.", "error")
        return RedirectResponse("/admin#lugares", 303)
    db.add(Lugar(nombre=nombre, tipo=form.get("tipo") if form.get("tipo") in cat.TIPOS_LUGAR else "otro",
                 direccion=(form.get("direccion") or "").strip()[:250], distrito=(form.get("distrito") or "").strip()[:120],
                 descripcion=(form.get("descripcion") or "").strip()[:500], lat=lat, lng=lng))
    db.commit()
    flash(request, f"Lugar “{nombre}” agregado al mapa.")
    return RedirectResponse("/admin#lugares", 303)


@app.post("/admin/lugar/{lid}/eliminar")
def admin_lugar_eliminar(request: Request, lid: int):
    db = obtener_db(request)
    requiere_admin(request, db)
    l = db.get(Lugar, lid)
    if l:
        db.delete(l)
        db.commit()
    return RedirectResponse("/admin#lugares", 303)


# =================================================================== notificaciones

@app.get("/notificaciones", response_class=HTMLResponse)
def notificaciones(request: Request):
    db = obtener_db(request)
    u, p = requiere_perfil(request, db)
    ids = [x.id for x in u.perfiles]
    lista = (db.query(Notificacion).options(selectinload(Notificacion.actor), selectinload(Notificacion.perfil))
             .filter(Notificacion.perfil_id.in_(ids)).order_by(Notificacion.id.desc()).limit(100).all())
    nuevas = {n.id for n in lista if not n.leida}
    if nuevas:
        db.query(Notificacion).filter(Notificacion.id.in_(nuevas)).update({"leida": True}, synchronize_session=False)
        db.commit()
    return render(request, db, "notificaciones.html", u, p, lista=lista, nuevas=nuevas, varios=len(ids) > 1)


# =================================================================== asistente

@app.post("/api/asistente")
async def api_asistente(request: Request):
    db = obtener_db(request)
    u = usuario_sesion(request, db)
    if not u:
        raise HTTPException(401, "Inicia sesión para hablar con Pawi.")
    # Cada mensaje cuesta una llamada a OpenAI: tope por minuto y por día para cada cuenta.
    seguridad.limitar(request, "pawi", f"u:{u.id}", LIMITE_PAWI_POR_MINUTO, 60,
                      "Pawi necesita un respiro. Espera un minuto antes de enviar otro mensaje.")
    seguridad.limitar(request, "pawi-dia", f"u:{u.id}", LIMITE_PAWI_POR_DIA, 86400,
                      "Llegaste al límite de mensajes con Pawi por hoy. Vuelve mañana.")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "Mensaje no válido.")
    if not isinstance(body, dict):
        raise HTTPException(400, "Mensaje no válido.")
    mensaje = body.get("mensaje")
    mensaje = (mensaje if isinstance(mensaje, str) else "").strip()
    if not mensaje:
        raise HTTPException(400, "Escribe un mensaje.")
    historial = body.get("historial") if isinstance(body.get("historial"), list) else []
    historial = [m for m in historial if isinstance(m, dict)]
    return StreamingResponse(
        asistente.generar_respuesta(mensaje, historial, u.id, u.perfil_activo_id),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =================================================================== arranque

def inicializar():
    import migrar_bd
    migrar_bd.migrar()  # crea tablas nuevas y, si hace falta, respalda la base y agrega columnas
    import seed
    seed.asegurar_admin()
    if os.getenv("PAWBOOK_DEMO", "1") != "0":
        seed.cargar_demo_si_vacio()
        seed.complementar_demo()


def iniciar_ngrok(puerto: int) -> Optional[str]:
    try:
        from pyngrok import conf, ngrok
    except ImportError:
        print("  [ngrok] Falta pyngrok. Instálalo con:  python -m pip install pyngrok")
        return None
    token = os.getenv("NGROK_AUTHTOKEN", "").strip()
    if token:
        ngrok.set_auth_token(token)
    opciones = {}
    dominio = os.getenv("NGROK_DOMAIN", "").strip().replace("https://", "").replace("http://", "").strip("/")
    if dominio:
        opciones["domain"] = dominio
    try:
        conf.get_default().monitor_thread = False
        tunel = ngrok.connect(str(puerto), "http", **opciones)
        return tunel.public_url.replace("http://", "https://")
    except Exception as e:
        texto = str(e)
        print("\n  [ngrok] No se pudo abrir el túnel:\n   ", texto[:400])
        if "ERR_NGROK_108" in texto or "simultaneous" in texto:
            print("   -> Ya hay otra sesión de ngrok abierta (¿la web UFI?). La cuenta gratuita permite una sola.")
        elif "authtoken" in texto.lower() or "ERR_NGROK_4018" in texto:
            print("   -> Configura tu token:  ngrok config add-authtoken TU_TOKEN   (o NGROK_AUTHTOKEN en .env)")
        elif dominio:
            print(f"   -> Revisa que el dominio {dominio} pertenezca a tu cuenta de ngrok y no esté en uso.")
        print("   La web sigue funcionando en modo local.\n")
        return None


def copiar_portapapeles(texto: str):
    if sys.platform.startswith("win"):
        try:
            import subprocess
            subprocess.run("clip", input=texto, text=True, shell=True, check=False)
            return True
        except Exception:
            return False
    return False


if __name__ == "__main__":
    import argparse
    import threading
    import webbrowser

    import uvicorn

    parser = argparse.ArgumentParser(description="Servidor Pawbook")
    parser.add_argument("--ngrok", action="store_true", help="Publicar con ngrok")
    parser.add_argument("--abrir", action="store_true", help="Abrir el navegador al iniciar")
    args = parser.parse_args()

    host = os.getenv("PAWBOOK_HOST", "127.0.0.1")
    url_local = f"http://localhost:{PUERTO}"

    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        en_uso = s.connect_ex(("127.0.0.1", PUERTO)) == 0
    if en_uso:
        print(f"\n  El puerto {PUERTO} ya está en uso: ¿Pawbook ya está abierto en otra ventana?")
        print(f"  Abre {url_local} o cambia PAWBOOK_PUERTO en el archivo .env.\n")
        if args.abrir:
            webbrowser.open(url_local)
        sys.exit(1)

    inicializar()
    enlace_tunel = iniciar_ngrok(PUERTO) if args.ngrok else None
    if enlace_tunel:
        URL_TUNEL = enlace_tunel  # los correos (recuperar contraseña) enlazan aquí
        ORIGENES_PERMITIDOS.add(enlace_tunel.rstrip("/").lower())

    print("\n" + "=" * 62)
    print("  PAWBOOK - red social para mascotas")
    print("=" * 62)
    print(f"  Local:    {url_local}")
    if enlace_tunel:
        copiado = copiar_portapapeles(enlace_tunel)
        print(f"  Público:  {enlace_tunel}" + ("   (copiado al portapapeles)" if copiado else ""))
        print("  Comparte el enlace público. ngrok muestra un aviso la primera vez: pulsa 'Visit Site'.")
    print(f"  Asistente Pawi: {'activo' if asistente.disponible() else 'sin configurar (falta OPENAI_API_KEY en .env)'}")
    print(f"  Correos (Resend): {'activo · ' + correos.remitente() if correos.configurado() else 'sin configurar (falta RESEND_API_KEY en .env)'}")
    print(f"  Enlaces en correos: {url_publica()}")
    print("  Para detener: Ctrl+C o cierra esta ventana.")
    print("=" * 62 + "\n")

    if args.abrir:
        threading.Timer(1.5, webbrowser.open, [url_local]).start()
    try:
        # Solo se confía en X-Forwarded-For/Proto cuando la conexión viene de este mismo equipo (el agente de
        # ngrok). Con "*" cualquier visitante podría inventarse su IP y saltarse los límites de intentos.
        uvicorn.run(app, host=host, port=PUERTO, proxy_headers=True, forwarded_allow_ips="127.0.0.1,::1",
                    access_log=False, server_header=False)
    finally:
        if enlace_tunel:
            try:
                from pyngrok import ngrok
                ngrok.kill()
            except Exception:
                pass
