"""Acceso a archivos.db: esquema, transacciones y metadatos."""

import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "archivos.db")

LOTE = 5000
# Subir esto obliga a reconstruir la base (por ejemplo al cambiar que se guarda)
VERSION_INDICE = "3"


def conectar():
    con = sqlite3.connect(DB)
    # WAL permite escribir sin bloquear lecturas; NORMAL acelera las escrituras.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=5000")
    _asegurar_esquema(con)
    return con


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
    con.commit()
    return con


def leer_meta(con, clave, defecto=None):
    fila = con.execute("SELECT valor FROM meta WHERE clave = ?", (clave,)).fetchone()
    return fila[0] if fila else defecto


def escribir_meta(con, clave, valor):
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (clave, str(valor)))


def version_indice(con):
    return leer_meta(con, "version_indice", "")


def contar(con, tabla):
    return con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
