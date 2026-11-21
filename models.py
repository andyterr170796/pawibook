"""Modelos de datos de Pawbook (SQLAlchemy + SQLite)."""
import os
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, create_engine, event,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("PAWBOOK_DB") or os.path.join(BASE_DIR, "pawbook.db")

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


class Usuario(Base):
    """Cuenta de acceso (dueño). Una cuenta puede manejar varios perfiles."""
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(120), nullable=False)
    email = Column(String(200), unique=True, index=True, nullable=False)
    password_hash = Column(String(300), nullable=False)
    es_admin = Column(Boolean, default=False)
    perfil_activo_id = Column(Integer, nullable=True)
    # Sube al cambiar la contraseña o cerrar las otras sesiones: una cookie con otra versión deja de valer.
    version_sesion = Column(Integer, nullable=False, default=0, server_default="0")
    creado = Column(DateTime, default=datetime.now)

    perfiles = relationship("Perfil", back_populates="usuario", cascade="all, delete-orphan",
                            order_by="Perfil.id")


class TokenRecuperacion(Base):
    """Enlace de un solo uso para restablecer la contraseña. Solo se guarda el SHA-256 del token."""
    __tablename__ = "tokens_recuperacion"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    expira = Column(DateTime, nullable=False)
    usado = Column(DateTime)
    ip = Column(String(64))
    creado = Column(DateTime, default=datetime.now)

    usuario = relationship("Usuario")


class Perfil(Base):
    """Perfil público: una mascota o una entidad (veterinaria, tienda, refugio...)."""
    __tablename__ = "perfiles"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), index=True, nullable=False)
    tipo = Column(String(20), nullable=False)  # 'mascota' | 'entidad'
    handle = Column(String(60), unique=True, index=True, nullable=False)
    nombre = Column(String(120), nullable=False)
    foto = Column(String(200))
    portada = Column(String(200))
    descripcion = Column(Text, default="")
    pais = Column(String(80), default="Perú")
    ciudad = Column(String(120), default="")
    distrito = Column(String(120), default="")
    lat = Column(Float)
    lng = Column(Float)
    mostrar_en_mapa = Column(Boolean, default=True)
    creado = Column(DateTime, default=datetime.now)

    # --- Mascota ---
    especie = Column(String(40))
    raza = Column(String(120))
    sexo = Column(String(10))  # 'macho' | 'hembra'
    fecha_nacimiento = Column(Date)
    edad_aprox = Column(Integer)  # años, si no se conoce el cumpleaños
    tags = Column(Text, default="")
    busca_pareja = Column(Boolean, default=False)

    # --- Entidad ---
    categoria = Column(String(40))
    direccion = Column(String(250))
    horario = Column(String(250))
    telefono = Column(String(60))
    email_contacto = Column(String(200))
    web = Column(String(250))
    verificada = Column(Boolean, default=False)

    usuario = relationship("Usuario", back_populates="perfiles")
    publicaciones = relationship("Publicacion", back_populates="autor", cascade="all, delete-orphan")

    @property
    def es_mascota(self):
        return self.tipo == "mascota"

    @property
    def es_entidad(self):
        return self.tipo == "entidad"

    @property
    def lista_tags(self):
        """Mascotas: tags. Restaurantes pet friendly: claves de AMENIDADES_PET_FRIENDLY."""
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]


class Seguimiento(Base):
    __tablename__ = "seguimientos"
    id = Column(Integer, primary_key=True)
    seguidor_id = Column(Integer, ForeignKey("perfiles.id", ondelete="CASCADE"), index=True, nullable=False)
    seguido_id = Column(Integer, ForeignKey("perfiles.id", ondelete="CASCADE"), index=True, nullable=False)
    creado = Column(DateTime, default=datetime.now)
    __table_args__ = (UniqueConstraint("seguidor_id", "seguido_id"),)

    seguidor = relationship("Perfil", foreign_keys=[seguidor_id])
    seguido = relationship("Perfil", foreign_keys=[seguido_id])


class Publicacion(Base):
    __tablename__ = "publicaciones"
    id = Column(Integer, primary_key=True)
    perfil_id = Column(Integer, ForeignKey("perfiles.id", ondelete="CASCADE"), index=True, nullable=False)
    texto = Column(Text, default="")
    imagen = Column(String(200))
    creado = Column(DateTime, default=datetime.now, index=True)

    autor = relationship("Perfil", back_populates="publicaciones")
    likes = relationship("MeGusta", cascade="all, delete-orphan")
    comentarios = relationship("Comentario", cascade="all, delete-orphan", order_by="Comentario.creado")


class MeGusta(Base):
    __tablename__ = "me_gusta"
    id = Column(Integer, primary_key=True)
    publicacion_id = Column(Integer, ForeignKey("publicaciones.id", ondelete="CASCADE"), index=True, nullable=False)
    perfil_id = Column(Integer, ForeignKey("perfiles.id", ondelete="CASCADE"), nullable=False)
    creado = Column(DateTime, default=datetime.now)
    __table_args__ = (UniqueConstraint("publicacion_id", "perfil_id"),)


class Comentario(Base):
    __tablename__ = "comentarios"
    id = Column(Integer, primary_key=True)
    publicacion_id = Column(Integer, ForeignKey("publicaciones.id", ondelete="CASCADE"), index=True, nullable=False)
    perfil_id = Column(Integer, ForeignKey("perfiles.id", ondelete="CASCADE"), nullable=False)
    texto = Column(Text, nullable=False)
    creado = Column(DateTime, default=datetime.now)

    autor = relationship("Perfil")


class Evento(Base):
    """Evento del calendario de una mascota (cita veterinaria, vacuna, etc.)."""
    __tablename__ = "eventos"
    id = Column(Integer, primary_key=True)
    perfil_id = Column(Integer, ForeignKey("perfiles.id", ondelete="CASCADE"), index=True, nullable=False)
    tipo = Column(String(30), nullable=False)
    titulo = Column(String(200), nullable=False)
    fecha = Column(Date, nullable=False, index=True)
    hora = Column(String(5))  # 'HH:MM'
    lugar = Column(String(200))
    notas = Column(Text)
    alerta_dias = Column(Integer)  # None = sin alerta; 0 = el mismo día
    alerta_enviada = Column(Boolean, default=False)
    creado = Column(DateTime, default=datetime.now)

    mascota = relationship("Perfil")


class Lugar(Base):
    """Lugares del mapa que no son perfiles (parques, etc.)."""
    __tablename__ = "lugares"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    tipo = Column(String(30), nullable=False)  # 'parque' | 'veterinaria' | 'tienda' | 'otro'
    direccion = Column(String(250))
    distrito = Column(String(120))
    descripcion = Column(Text)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    creado = Column(DateTime, default=datetime.now)


class Anuncio(Base):
    """Anuncio pagado (veterinarias, marcas, tiendas) o gratuito (adopción, caridad, campañas)."""
    __tablename__ = "anuncios"
    id = Column(Integer, primary_key=True)
    perfil_id = Column(Integer, ForeignKey("perfiles.id", ondelete="CASCADE"), index=True, nullable=False)
    tipo = Column(String(20), nullable=False)  # 'pagado' | 'gratuito'
    categoria = Column(String(40), nullable=False)
    titulo = Column(String(120), nullable=False)
    texto = Column(Text, default="")
    imagen = Column(String(200))
    enlace = Column(String(300))
    plan = Column(String(30))
    fecha_inicio = Column(Date)
    fecha_fin = Column(Date)
    estado = Column(String(20), default="pendiente")  # pendiente | activo | pausado | rechazado
    impresiones = Column(Integer, default=0)
    clics = Column(Integer, default=0)
    creado = Column(DateTime, default=datetime.now)

    anunciante = relationship("Perfil")


class Notificacion(Base):
    __tablename__ = "notificaciones"
    id = Column(Integer, primary_key=True)
    perfil_id = Column(Integer, ForeignKey("perfiles.id", ondelete="CASCADE"), index=True, nullable=False)
    actor_id = Column(Integer, ForeignKey("perfiles.id", ondelete="CASCADE"), nullable=True)
    tipo = Column(String(30), nullable=False)
    texto = Column(String(400), nullable=False)
    enlace = Column(String(300))
    clave = Column(String(120), index=True)  # evita duplicados (recordatorios, cumpleaños)
    leida = Column(Boolean, default=False)
    creado = Column(DateTime, default=datetime.now, index=True)

    perfil = relationship("Perfil", foreign_keys=[perfil_id])
    actor = relationship("Perfil", foreign_keys=[actor_id])


class ReportePerdido(Base):
    """Aviso de mascota perdida (la busca su familia) o encontrada (alguien la tiene y busca a su familia)."""
    __tablename__ = "reportes_perdidos"
    # AUTOINCREMENT: un id borrado no se reutiliza, así las claves de notificación y los enlaces viejos
    # (/perdidos/{id}) nunca apuntan a otro aviso.
    __table_args__ = {"sqlite_autoincrement": True}
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), index=True, nullable=False)
    autor_id = Column(Integer, ForeignKey("perfiles.id", ondelete="SET NULL"), nullable=True)
    mascota_id = Column(Integer, ForeignKey("perfiles.id", ondelete="SET NULL"), index=True, nullable=True)
    tipo = Column(String(12), nullable=False)  # 'perdido' | 'encontrado'
    estado = Column(String(12), default="activo", index=True)  # 'activo' | 'resuelto'
    nombre = Column(String(120), default="")
    especie = Column(String(40))
    raza = Column(String(120))
    sexo = Column(String(10))
    color = Column(String(150))  # color y señas particulares
    descripcion = Column(Text, default="")
    foto = Column(String(200))
    fecha = Column(Date)  # visto por última vez / encontrado
    hora = Column(String(5))
    distrito = Column(String(120))
    referencia = Column(String(250))
    lat = Column(Float)  # redondeadas (~100 m)
    lng = Column(Float)
    telefono = Column(String(60))
    recompensa = Column(String(120))
    resuelto_en = Column(DateTime)
    creado = Column(DateTime, default=datetime.now, index=True)

    autor = relationship("Perfil", foreign_keys=[autor_id])
    mascota = relationship("Perfil", foreign_keys=[mascota_id])

    @property
    def es_perdido(self):
        return self.tipo == "perdido"

    @property
    def activo(self):
        return self.estado == "activo"

    @property
    def foto_mostrar(self):
        """Foto del aviso o, si no subieron una, la del perfil de la mascota."""
        return self.foto or (self.mascota.foto if self.mascota else None)


class InteresPareja(Base):
    __tablename__ = "interes_pareja"
    id = Column(Integer, primary_key=True)
    de_id = Column(Integer, ForeignKey("perfiles.id", ondelete="CASCADE"), index=True, nullable=False)
    para_id = Column(Integer, ForeignKey("perfiles.id", ondelete="CASCADE"), index=True, nullable=False)
    creado = Column(DateTime, default=datetime.now)
    __table_args__ = (UniqueConstraint("de_id", "para_id"),)


def crear_tablas():
    Base.metadata.create_all(engine)
