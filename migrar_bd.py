"""Actualiza una base pawbook.db existente a la versión con las protecciones de seguridad.

Uso:  python migrar_bd.py      (también lo ejecuta main.py al iniciar; si no hay nada pendiente no hace nada)

Antes de cambiar algo crea un respaldo pawbook.db-respaldo-AAAA-MM-DD-HHMMSS junto a la base.
Cambios:
  1. usuarios.version_sesion (ALTER TABLE): permite cerrar las sesiones al cambiar la contraseña.
  2. Tablas nuevas (tokens_recuperacion): las crea create_all().
  3. Cuentas de demostración que aún tienen la contraseña de ejemplo publicada en el código: reciben una
     contraseña aleatoria. La cuenta demo se sigue usando con el botón "Explorar con la cuenta demo".
"""
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime

from utilidades import cargar_env

cargar_env()  # PAWBOOK_DB puede venir del .env

from sqlalchemy import inspect, text  # noqa: E402

from models import DB_PATH, Usuario, SessionLocal, crear_tablas, engine  # noqa: E402

COLUMNAS_NUEVAS = [
    ("usuarios", "version_sesion", "INTEGER NOT NULL DEFAULT 0"),
]
PASSWORD_DEMO_ANTIGUA = "pawbook123"


def pendientes() -> list:
    """Columnas que faltan en la base actual (las tablas que no existen las crea create_all)."""
    insp = inspect(engine)
    tablas = set(insp.get_table_names())
    faltan = []
    for tabla, columna, tipo in COLUMNAS_NUEVAS:
        if tabla in tablas and columna not in {c["name"] for c in insp.get_columns(tabla)}:
            faltan.append((tabla, columna, tipo))
    return faltan


def respaldar() -> str:
    """Copia consistente (API de respaldo de SQLite, incluye lo que esté en el WAL)."""
    destino = f"{DB_PATH}-respaldo-{datetime.now():%Y-%m-%d-%H%M%S}"
    with closing(sqlite3.connect(DB_PATH)) as origen, closing(sqlite3.connect(destino)) as copia:
        origen.backup(copia)
    return destino


def _asegurar_cuentas_demo():
    from seed import DEMO_EMAIL
    from utilidades import hash_password, verificar_password

    with SessionLocal() as db:
        cuentas = db.query(Usuario).filter(
            (Usuario.email == DEMO_EMAIL) | (Usuario.email.like("%@pawbook.demo"))).all()
        cambiadas = 0
        for u in cuentas:
            if verificar_password(PASSWORD_DEMO_ANTIGUA, u.password_hash):
                u.password_hash = hash_password(secrets.token_urlsafe(24))
                u.version_sesion = (u.version_sesion or 0) + 1
                cambiadas += 1
        db.commit()
    return cambiadas


def migrar(silencioso: bool = False) -> bool:
    """Aplica lo pendiente. Devuelve True si cambió algo."""
    if not os.path.exists(DB_PATH):
        crear_tablas()
        return False
    faltan = pendientes()
    if not faltan:
        crear_tablas()
        return False
    ruta = respaldar()
    with engine.begin() as con:
        for tabla, columna, tipo in faltan:
            con.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}"))
    crear_tablas()
    demo = _asegurar_cuentas_demo()
    if not silencioso:
        print(f"  [migración] Respaldo creado: {os.path.basename(ruta)}")
        print(f"  [migración] Columnas agregadas: {', '.join(f'{t}.{c}' for t, c, _ in faltan)}")
        if demo:
            print(f"  [migración] {demo} cuenta(s) demo con la contraseña de ejemplo recibieron una aleatoria.")
    return True


if __name__ == "__main__":
    if not migrar():
        print("La base de datos ya está al día. No se cambió nada.")
