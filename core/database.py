"""Acceso a archivos.db: esquema, transacciones y metadatos."""

import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "archivos.db")

LOTE = 5000
# Subir esto obliga a reconstruir la base (por ejemplo al cambiar que se guarda)
VERSION_INDICE = "3"


def conectar():
    """Abre una conexion configurada. No crea tablas ni aplica migraciones."""
    con = sqlite3.connect(DB)
    # NORMAL acelera las escrituras y el timeout evita fallos por bloqueos.
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def inicializar():
    """Crea el esquema y aplica las migraciones. Se llama una vez al arrancar."""
    con = conectar()
    try:
        # WAL persiste en la base: basta con establecerlo al inicializar.
        con.execute("PRAGMA journal_mode=WAL")
        _asegurar_esquema(con)
        con.commit()
    finally:
        con.close()


def _asegurar_esquema(con):
    con.execute(
        """CREATE TABLE IF NOT EXISTS archivos (
               ruta TEXT PRIMARY KEY,
               nombre TEXT,
               ext TEXT,
               tamano INTEGER,
               modificado REAL,
               nombre_norm TEXT,
               padre TEXT
           )"""
    )
    columnas = {c[1] for c in con.execute("PRAGMA table_info(archivos)")}
    for columna in ("nombre_norm", "padre"):
        if columna not in columnas:
            con.execute(f"ALTER TABLE archivos ADD COLUMN {columna} TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_nombre ON archivos(nombre)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_norm ON archivos(nombre_norm)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_padre ON archivos(padre)")
    # La firma de cada carpeta detecta altas, bajas y modificaciones de sus hijos
    con.execute("CREATE TABLE IF NOT EXISTS carpetas (ruta TEXT PRIMARY KEY, firma TEXT)")
    columnas_carpeta = {c[1] for c in con.execute("PRAGMA table_info(carpetas)")}
    if "firma" not in columnas_carpeta:
        # Versiones previas guardaban el mtime: la tabla se regenera al escanear
        con.execute("DROP TABLE carpetas")
        con.execute("CREATE TABLE carpetas (ruta TEXT PRIMARY KEY, firma TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT)")
    con.execute(
        """CREATE TABLE IF NOT EXISTS unidades (
               ruta TEXT PRIMARY KEY,
               ultima_revision REAL,
               estado TEXT
           )"""
    )


def leer_meta(con, clave, defecto=None):
    fila = con.execute("SELECT valor FROM meta WHERE clave = ?", (clave,)).fetchone()
    return fila[0] if fila else defecto


def escribir_meta(con, clave, valor):
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (clave, str(valor)))


def version_indice(con):
    return leer_meta(con, "version_indice", "")


def leer_unidades(con):
    """Rutas indexadas y su estado; vacio en bases creadas antes de esta tabla."""
    try:
        return con.execute("SELECT ruta, estado FROM unidades").fetchall()
    except sqlite3.OperationalError:
        return []


def contar(con, tabla):
    return con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
