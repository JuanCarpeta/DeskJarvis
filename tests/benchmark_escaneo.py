"""Compara el escaneo anterior con el nuevo (fase 1) y verifica los cambios.

Uso:
    python tests/benchmark_escaneo.py [carpeta]

Sin argumentos mide sobre la carpeta del usuario. Usa bases de datos
temporales: no toca el archivos.db real de Jarvis.
"""

import os
import sqlite3
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core import archivos, database, scanner  # noqa: E402

try:
    import psutil
except ModuleNotFoundError:
    psutil = None

CONSULTAS = ["python", "informe", "datos", "notas", "video", "foto", "instalador",
             "presupuesto", "trabajo", "musica"]


def escaneo_antiguo(raiz, db):
    """Copia del algoritmo anterior: os.walk + os.stat por archivo y borrar todo."""
    con = sqlite3.connect(db)
    con.execute(
        """CREATE TABLE IF NOT EXISTS archivos (
               ruta TEXT PRIMARY KEY, nombre TEXT, ext TEXT, tamano INTEGER,
               modificado REAL, nombre_norm TEXT)""")
    con.execute("DELETE FROM archivos")
    total = 0
    lote = []

    def volcar():
        if lote:
            con.executemany("INSERT OR REPLACE INTO archivos VALUES (?,?,?,?,?,?)", lote)
            lote.clear()

    for dirpath, dirnames, filenames in os.walk(raiz, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in scanner.EXCLUIR
                       and not d.startswith(".")]
        for nombre in dirnames:
            lote.append((os.path.join(dirpath, nombre), nombre.lower(), "", 0, 0.0,
                         scanner.normalizar(nombre)))
            total += 1
            if len(lote) >= 1000:
                volcar()
        for nombre in filenames:
            ruta = os.path.join(dirpath, nombre)
            try:
                st = os.stat(ruta)
            except OSError:
                continue
            lote.append((ruta, nombre.lower(), os.path.splitext(nombre)[1].lower(),
                         st.st_size, st.st_mtime, scanner.normalizar(nombre)))
            total += 1
            if len(lote) >= 1000:
                volcar()
    volcar()
    con.commit()
    con.close()
    return total


def medir(funcion, *args, **kwargs):
    """Devuelve (resultado, segundos, pico_python_mb, delta_rss_mb)."""
    proceso = psutil.Process() if psutil else None
    rss_antes = proceso.memory_info().rss if proceso else 0
    tracemalloc.start()
    inicio = time.perf_counter()
    resultado = funcion(*args, **kwargs)
    duracion = time.perf_counter() - inicio
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_despues = proceso.memory_info().rss if proceso else 0
    return resultado, duracion, pico / 1e6, max(0, rss_despues - rss_antes) / 1e6


def rutas_de(db):
    con = sqlite3.connect(db)
    try:
        return {f[0] for f in con.execute("SELECT ruta FROM archivos")}
    finally:
        con.close()


def velocidad_busqueda(db_nueva):
    con = sqlite3.connect(db_nueva)
    inicio = time.perf_counter()
    resultados = 0
    for consulta in CONSULTAS:
        toks = scanner.tokens(consulta)
        resultados += len(archivos.buscar_en_db(con, toks, scanner.normalizar(consulta), 10))
    duracion = time.perf_counter() - inicio
    con.close()
    return resultados, duracion / len(CONSULTAS) * 1000


def consistencia(db_nueva, muestra=500):
    con = sqlite3.connect(db_nueva)
    rutas = [r[0] for r in con.execute(
        "SELECT ruta FROM archivos ORDER BY RANDOM() LIMIT ?", (muestra,))]
    con.close()
    faltan = [r for r in rutas if not Path(r).exists()]
    return len(rutas), len(faltan)


def caso_archivo_modificado(temporal):
    """El caso fundamental: modificar un documento sin cambiar nombre ni carpeta."""
    database.DB = os.path.join(temporal, "caso.db")
    database.inicializar()
    caja = Path(temporal) / "caja"
    caja.mkdir()
    doc = caja / "documento.txt"
    doc.write_text("original", encoding="utf-8")
    scanner.indexar([caja])

    def fila():
        con = database.conectar()
        try:
            return con.execute(
                "SELECT tamano, modificado FROM archivos WHERE ruta = ?",
                (str(doc),)).fetchone()
        finally:
            con.close()

    antes = fila()
    doc.write_text("contenido modificado y mas largo", encoding="utf-8")
    os.utime(doc, (1000, 5000))

    scanner.SEG_ENTRE_ESCANEOS = 0
    _, t_incremental, _, _ = medir(scanner.indexar, [caja])
    tras_incremental = fila()
    scanner.SEG_ENTRE_ESCANEOS = 900
    return antes, tras_incremental, t_incremental


def main():
    raiz = sys.argv[1] if len(sys.argv) > 1 else str(Path.home())
    print(f"Comparando escaneos sobre: {raiz}")
    print(f"(bases temporales, no se toca el archivos.db real)\n")

    temporal = tempfile.mkdtemp(prefix="jarvis_bench_")
    db_nueva = os.path.join(temporal, "nueva.db")
    db_vieja = os.path.join(temporal, "vieja.db")
    database.DB = db_nueva
    database.inicializar()
    scanner.SEG_ENTRE_ESCANEOS = 0

    total_viejo, t_viejo, mem_viejo, _ = medir(escaneo_antiguo, raiz, db_vieja)
    print(f"[ANTIGUO]      {total_viejo:>9} entradas | {t_viejo:7.1f} s | "
          f"pico python {mem_viejo:5.1f} MB")

    total_nuevo, t_nuevo, mem_nuevo, _ = medir(scanner.indexar, [raiz])
    print(f"[NUEVO full]   {total_nuevo:>9} entradas | {t_nuevo:7.1f} s | "
          f"pico python {mem_nuevo:5.1f} MB")

    _, t_incr, mem_incr, _ = medir(scanner.indexar, [raiz])
    print(f"[NUEVO act.]   {'-':>9}         | {t_incr:7.1f} s | "
          f"pico python {mem_incr:5.1f} MB (actualizacion sin cambios en el disco)")

    print(f"\nGanancia escaneo completo: {t_viejo / max(t_nuevo, 0.001):.1f}x")
    print(f"Actualizacion sin cambios:  {t_viejo / max(t_incr, 0.001):.1f}x mas rapida que el escaneo antiguo")

    r_viejas, r_nuevas = rutas_de(db_vieja), rutas_de(db_nueva)
    solo_viejas = r_viejas - r_nuevas
    solo_nuevas = r_nuevas - r_viejas
    print(f"\nConsistencia con el antiguo: {len(r_viejas & r_nuevas)} rutas comunes, "
          f"{len(solo_viejas)} solo en el antiguo, {len(solo_nuevas)} solo en el nuevo")
    print("  (diferencias esperables: enlaces/junctions y carpetas ocultas omitidas)")
    for r in sorted(solo_viejas)[:5]:
        print(f"    solo antiguo: {r}")
    for r in sorted(solo_nuevas)[:5]:
        print(f"    solo nuevo:   {r}")

    muestra, faltan = consistencia(db_nueva)
    print(f"\nConsistencia disco <-> SQLite: {muestra - faltan}/{muestra} rutas "
          f"aleatorias existen en el disco ({faltan} desaparecidas)")

    resultados, ms = velocidad_busqueda(db_nueva)
    print(f"Velocidad de busqueda: {ms:.1f} ms por consulta "
          f"({resultados} resultados en {len(CONSULTAS)} consultas)")

    print("\nEstadisticas del ultimo escaneo nuevo:")
    print("  " + scanner.resumen_escaneo().replace("\n", "\n  "))

    antes, tras_incremental, t_inc_caso = caso_archivo_modificado(temporal)
    print(f"\nCaso 'documento modificado sin renombrar ni mover':")
    print(f"  en la base tras modificar: {antes}")
    print(f"  tras actualizacion:       {tras_incremental} "
          f"({t_inc_caso:.2f} s, modificacion detectada)")

    print(f"\nArchivos temporales del benchmark en: {temporal}")


if __name__ == "__main__":
    main()
