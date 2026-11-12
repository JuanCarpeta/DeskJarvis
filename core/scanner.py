"""Recorrido del disco con os.scandir, indexacion incremental y busqueda en vivo.

Estrategia incremental: NTFS no actualiza de forma confiable el mtime de una
carpeta al crear o borrar archivos dentro de ella, asi que cada escaneo
enumera todo el arbol (los metadatos salen gratis del listado de cada
carpeta) y compara por carpeta una firma de sus hijos: nombre, tamano,
mtime en nanosegundos y tipo. Solo se escriben en SQLite las diferencias.
"""

import hashlib
import json
import os
import re
import stat as stat_mod
import time
import unicodedata
from collections import namedtuple
from pathlib import Path

from core import database
from core.scanner_errors import Estadisticas

try:
    import psutil
except ModuleNotFoundError:
    psutil = None

# Segundos minimos entre dos escaneos automaticos (arranques seguidos)
SEG_ENTRE_ESCANEOS = 900
# Segundos maximos de rastreo en vivo si la base no encuentra nada
SEG_BUSQUEDA_VIVA = 15
# Las rutas de Windows por encima de este largo necesitan el prefijo \\?\
LIMITE_RUTA = 259

EXCLUIR = {
    "AppData", "node_modules", ".git", "__pycache__", "venv", ".venv",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "System32", "$Recycle.Bin", "Recovery", "PerfLogs",
    "System Volume Information", "$WinREAgent",
}

# Palabras del lenguaje natural que no sirven para comparar nombres de archivo
PARADAS = {
    "de", "del", "la", "el", "los", "las", "lo", "un", "una", "unos", "unas",
    "archivo", "archivos", "documento", "documentos", "carpeta", "busca",
    "buscar", "buscame", "encuentra", "encuentrame", "hay", "que", "se",
    "llama", "llamado", "llamada", "mi", "mis", "por", "para", "con", "en",
    "y", "o", "donde", "esta", "estan", "favor", "abre", "abreme", "abrir",
    "lee", "leeme", "leer", "muestra", "contenido", "ejecuta", "lanza",
    "ve", "vaya", "vayas", "ir", "vete", "dirigete", "navega", "navegar",
    "lleva", "llevame", "entra", "entrar",
}

_TAG_MOUNT_POINT = getattr(stat_mod, "IO_REPARSE_TAG_MOUNT_POINT", -1)
_TAG_SYMLINK = getattr(stat_mod, "IO_REPARSE_TAG_SYMLINK", -2)

# Cada entrada del disco que entrega el recorrido
Entrada = namedtuple(
    "Entrada", ["ruta", "nombre", "es_carpeta", "tamano", "mtime", "mtime_ns"])


def discos(incluir_extraibles=True):
    """Devuelve las raices de las unidades reales del PC (C:\\, D:\\, ...)."""
    if psutil is None:
        return [Path.home()]
    raices = []
    for p in psutil.disk_partitions(all=False):
        opts = p.opts.lower()
        fstype = p.fstype.lower()
        if "cdrom" in opts or "remote" in opts:
            continue
        if fstype in ("", "iso9660", "udf"):
            continue
        if not incluir_extraibles and "removable" in opts:
            continue
        raices.append(Path(p.mountpoint))
    return raices if raices else [Path.home()]


def normalizar(texto):
    """Minusculas, sin acentos y con espacios alrededor (comparar por palabras)."""
    texto = unicodedata.normalize("NFKD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return " " + texto.strip() + " "


def tokens(consulta):
    return [t for t in normalizar(consulta).split() if len(t) > 1 and t not in PARADAS]


def puntuar(nombre_norm, consulta_norm):
    """Mas puntos si el nombre coincide completo o empieza igual."""
    n = nombre_norm.strip()
    c = consulta_norm.strip()
    if n == c:
        return 100
    if n.startswith(c):
        return 60
    return 0


def _ruta_extendida(ruta):
    r"""Prefijo \\?\ de Windows para acceder a rutas por encima del limite clasico."""
    if os.name != "nt" or len(ruta) <= LIMITE_RUTA or ruta.startswith("\\\\?\\"):
        return ruta
    if ruta.startswith("\\\\"):
        return "\\\\?\\UNC" + ruta[1:]
    return "\\\\?\\" + ruta


def _stat_entrada(entry, estadisticas):
    # En Windows DirEntry.stat sale del propio listado del directorio,
    # sin gastar una consulta extra al sistema por cada archivo.
    try:
        return entry.stat(follow_symlinks=False)
    except OSError as error:
        try:
            return os.stat(_ruta_extendida(entry.path), follow_symlinks=False)
        except OSError:
            estadisticas.registrar_error(error, entry.path)
            return None


def _scandir(ruta, estadisticas):
    try:
        return os.scandir(ruta)
    except OSError as error:
        if len(ruta) > LIMITE_RUTA:
            try:
                return os.scandir(_ruta_extendida(ruta))
            except OSError:
                pass
        estadisticas.registrar_error(error, ruta)
        return None


def _es_enlace(entry, st):
    """Symlinks y junctions se omiten para evitar ciclos y recorridos duplicados.

    Otros reparse points (por ejemplo los archivos de OneDrive) si se indexan.
    """
    try:
        if entry.is_symlink():
            return True
    except OSError:
        pass
    tag = getattr(st, "st_reparse_tag", 0)
    return tag in (_TAG_MOUNT_POINT, _TAG_SYMLINK)


def recorrer(raiz, estadisticas, excluir=None, presupuesto_seg=None):
    """Recorre el arbol bajo raiz con os.scandir generando (carpeta, hijos).

    Se genera un grupo por cada carpeta enumerada, incluidas las vacias:
    si no fuera asi, borrar el ultimo archivo de una carpeta dejaria filas
    viejas en la base. Los hijos vienen con sus metadatos ya consultados.

    - No se entra en enlaces ni junctions (se registran como omitidos).
    - excluir oculta carpetas por nombre (ademas de las ocultas, que empiezan con punto).
    - presupuesto_seg corta el recorrido a mitad (busquedas en vivo).
    """
    excluir = EXCLUIR if excluir is None else excluir
    tope = time.monotonic() + presupuesto_seg if presupuesto_seg else None
    pila = [str(raiz)]
    while pila:
        carpeta = pila.pop()
        iterador = _scandir(carpeta, estadisticas)
        if iterador is None:
            continue
        hijos = []
        with iterador:
            try:
                for entry in iterador:
                    if tope is not None and time.monotonic() > tope:
                        return
                    nombre = entry.name
                    st = _stat_entrada(entry, estadisticas)
                    if st is None:
                        continue
                    es_carpeta = stat_mod.S_ISDIR(st.st_mode)
                    if es_carpeta and (nombre in excluir or nombre.startswith(".")):
                        continue
                    if _es_enlace(entry, st):
                        estadisticas.registrar_enlace(os.path.join(carpeta, nombre))
                        continue
                    ruta = os.path.join(carpeta, nombre)
                    hijos.append(Entrada(ruta, nombre, es_carpeta, st.st_size,
                                         st.st_mtime, st.st_mtime_ns))
                    if es_carpeta:
                        pila.append(ruta)
            except OSError as error:
                # Un fallo a mitad del listado deja el grupo incompleto: se
                # registra y no se reconcilia esa carpeta para no borrar filas.
                estadisticas.registrar_error(error, carpeta)
                continue
        yield carpeta, hijos


def _firma_grupo(grupo):
    partes = [
        f"{e.nombre}|{int(e.es_carpeta)}|{e.tamano}|{e.mtime_ns}\n"
        for e in sorted(grupo, key=lambda x: x.nombre.casefold())
    ]

    return hashlib.blake2b(
        "".join(partes).encode("utf-8", "surrogatepass"),
        digest_size=20
    ).hexdigest()


def _firma(entrada):
    """Como queda la fila en DB: las carpetas guardan ceros como siempre."""
    if entrada.es_carpeta:
        return (0, 0.0)
    return (entrada.tamano, entrada.mtime)


def _fila(entrada, padre):
    if entrada.es_carpeta:
        return (entrada.ruta, entrada.nombre.lower(), "", 0, 0.0,
                normalizar(entrada.nombre), padre)
    return (entrada.ruta, entrada.nombre.lower(),
            os.path.splitext(entrada.nombre)[1].lower(),
            entrada.tamano, entrada.mtime, normalizar(entrada.nombre), padre)


def _borrar_subarbol(con, rutas):
    """Elimina las filas que cuelgan de rutas desaparecidas, nivel por nivel."""
    nivel = list(rutas)
    while nivel:
        siguientes = []
        for padre in nivel:
            siguientes += [f[0] for f in con.execute(
                "SELECT ruta FROM archivos WHERE padre = ?", (padre,))]
        con.executemany("DELETE FROM archivos WHERE ruta = ?", [(r,) for r in nivel])
        con.executemany("DELETE FROM carpetas WHERE ruta = ?", [(r,) for r in nivel])
        nivel = siguientes


def _reciente(con):
    if database.version_indice(con) != database.VERSION_INDICE:
        return False
    if database.leer_meta(con, "escaneo_truncado") == "1":
        return False
    ultimo = database.leer_meta(con, "ultimo_escaneo")
    try:
        return bool(ultimo) and time.time() - float(ultimo) < SEG_ENTRE_ESCANEOS
    except ValueError:
        return False


def _accesible(ruta):
    return os.path.isdir(_ruta_extendida(str(ruta)))


def _sincronizar_unidades(con, raices):
    """Marca activas/desconectadas y devuelve las que hay que volver a escanear.

    Las filas de archivos de una unidad desconectada se conservan: la busqueda
    las filtra por estado. Al reconectar, se fuerza el escaneo de esa unidad
    aunque el escaneo global sea reciente.
    """
    actuales = list(dict.fromkeys(str(r) for r in raices))
    conocidas = {
        f[0]: (f[1], f[2]) for f in con.execute(
            "SELECT ruta, estado, ultima_revision FROM unidades")
    }
    reconectadas = set()
    for ruta in actuales:
        disponible = _accesible(ruta)
        estado = "activa" if disponible else "desconectada"
        anterior, revision = conocidas.get(ruta, (None, None))
        if disponible and (anterior != "activa" or revision is None):
            reconectadas.add(ruta)
        if anterior != estado:
            con.execute(
                "INSERT OR IGNORE INTO unidades (ruta, ultima_revision, estado) "
                "VALUES (?, NULL, ?)", (ruta, estado))
            con.execute(
                "UPDATE unidades SET estado = ? WHERE ruta = ?", (estado, ruta))
    for ruta, (estado, _revision) in conocidas.items():
        if ruta in actuales or _accesible(ruta):
            continue
        if estado != "desconectada":
            con.execute(
                "UPDATE unidades SET estado = 'desconectada' WHERE ruta = ?",
                (ruta,))
    con.commit()
    return reconectadas


def refrescar_unidades(con):
    """Comprueba si las unidades siguen accesibles, sin recorrer su contenido.

    Se usa antes de buscar para que una unidad desconectada desaparezca de los
    resultados de inmediato, y para reactivarla si vuelve a conectarse.
    """
    cambiado = False
    for ruta, estado in database.leer_unidades(con):
        nuevo = "activa" if _accesible(ruta) else "desconectada"
        if nuevo != estado:
            if nuevo == "activa":
                # Al reconectar hay que forzar un nuevo escaneo de la unidad:
                # sin ultima_revision la sincronizacion no puede darla por vista.
                con.execute(
                    "UPDATE unidades SET estado = 'activa', ultima_revision = NULL "
                    "WHERE ruta = ?", (ruta,))
            else:
                con.execute(
                    "UPDATE unidades SET estado = ? WHERE ruta = ?", (nuevo, ruta))
            cambiado = True
    if cambiado:
        con.commit()
    return cambiado


def _marcar_revisadas(con, raices):
    ahora = time.time()
    for raiz in raices:
        ruta = str(raiz)
        if _accesible(ruta):
            con.execute(
                "UPDATE unidades SET ultima_revision = ?, estado = 'activa' "
                "WHERE ruta = ?", (ahora, ruta))


def _indexar_raices(raices, con, max_archivos):
    estadisticas = Estadisticas()
    lote = []
    truncado = False

    def volcar():
        if lote:
            con.executemany(
                "INSERT OR REPLACE INTO archivos VALUES (?,?,?,?,?,?,?)", lote)
            lote.clear()

    def subir(fila):
        lote.append(fila)
        if len(lote) >= database.LOTE:
            volcar()

    def cerrar_grupo(carpeta, hijos):
        """Compara los hijos de una carpeta con la firma guardada y reconcilia.

        Si la firma coincide no se toca la base. Si difiere, se suben los hijos
        nuevos o modificados y se borra lo que ya no esta en el disco dentro de
        esa carpeta (nunca se borra por carpetas que no se recorrieron).
        """
        firma = _firma_grupo(hijos)
        fila = con.execute("SELECT firma FROM carpetas WHERE ruta = ?", (carpeta,)).fetchone()
        if fila is not None and fila[0] == firma:
            estadisticas.carpetas_sin_cambios += 1
            return
        actuales = {ruta: (tamano, modificado) for ruta, tamano, modificado in con.execute(
            "SELECT ruta, tamano, modificado FROM archivos WHERE padre = ?", (carpeta,))}
        vistos = set()
        for entrada in hijos:
            vistos.add(entrada.ruta)
            if actuales.get(entrada.ruta) == _firma(entrada):
                continue
            subir(_fila(entrada, carpeta))
        desaparecidos = [ruta for ruta in actuales if ruta not in vistos]
        if desaparecidos:
            _borrar_subarbol(con, desaparecidos)
        con.execute("INSERT OR REPLACE INTO carpetas VALUES (?, ?)", (carpeta, firma))

    for raiz in raices:
        if truncado:
            break
        raiz = str(raiz)
        if not os.path.isdir(raiz):
            continue
        for carpeta, hijos in recorrer(raiz, estadisticas):
            for entrada in hijos:
                if entrada.es_carpeta:
                    estadisticas.carpetas += 1
                else:
                    estadisticas.archivos += 1
            cerrar_grupo(carpeta, hijos)
            if estadisticas.archivos + estadisticas.carpetas >= max_archivos:
                truncado = True
                break
    volcar()
    return estadisticas, truncado


def indexar(raices=None, max_archivos=1000000, forzar=False):
    """Actualiza el indice de archivos del computador.

    Enumera el arbol y escribe solo las diferencias contra la base:
    altas, bajas, renombres y archivos modificados sin cambiar de nombre.
    El escaneo es completo (reconstruccion desde cero) cuando la base es
    nueva o cambio la version del indice.
    """
    raices = [str(r) for r in (raices or discos())]
    con = database.conectar()
    try:
        reconectadas = _sincronizar_unidades(con, raices)
        if not forzar and not reconectadas and _reciente(con):
            return database.contar(con, "archivos")
        completo = (database.version_indice(con) != database.VERSION_INDICE
                    or database.contar(con, "carpetas") == 0)
        if completo:
            con.execute("DELETE FROM archivos")
            con.execute("DELETE FROM carpetas")
            con.commit()
        estadisticas, truncado = _indexar_raices(raices, con, max_archivos)
        _marcar_revisadas(con, raices)
        database.escribir_meta(con, "version_indice", database.VERSION_INDICE)
        for clave, valor in estadisticas.a_meta(
                "completo" if completo else "incremental").items():
            database.escribir_meta(con, clave, valor)
        database.escribir_meta(con, "escaneo_truncado", "1" if truncado else "0")
        con.commit()
        return database.contar(con, "archivos")
    finally:
        con.close()


def buscar_en_vivo(tokens_consulta, consulta_norm, limite, raiz=None):
    """Rastrea las carpetas del usuario por si el archivo es nuevo y no esta en la base."""
    estadisticas = Estadisticas()
    encontrados = []
    con = database.conectar()
    try:
        for _carpeta, hijos in recorrer(raiz or Path.home(), estadisticas,
                                        presupuesto_seg=SEG_BUSQUEDA_VIVA):
            for entrada in hijos:
                nn = normalizar(entrada.nombre)
                if not all(" " + t in nn for t in tokens_consulta):
                    continue
                if entrada.es_carpeta:
                    tamano, mtime, ext = 0, 0.0, ""
                else:
                    tamano, mtime = entrada.tamano, entrada.mtime
                    ext = os.path.splitext(entrada.nombre)[1].lower()
                con.execute(
                    "INSERT OR REPLACE INTO archivos VALUES (?,?,?,?,?,?,?)",
                    (entrada.ruta, entrada.nombre.lower(), ext, tamano, mtime, nn,
                     os.path.dirname(entrada.ruta)))
                encontrados.append({"ruta": entrada.ruta, "nombre": entrada.nombre.lower(),
                                    "tamano": tamano, "modificado": mtime})
            if len(encontrados) >= limite:
                break
        con.commit()
    except Exception as e:
        # Antes se ignoraba en silencio y la busqueda parecia "no encontrado".
        print(f"(busqueda en vivo incompleta: {e})")
    finally:
        con.close()
    encontrados.sort(key=lambda f: (-puntuar(normalizar(f["nombre"]), consulta_norm),
                                    -(f["modificado"] or 0)))
    return encontrados[:limite]


def resumen_escaneo():
    """Estadisticas del ultimo escaneo en texto, para el cerebro de Jarvis."""
    con = database.conectar()
    try:
        if not database.leer_meta(con, "total_archivos"):
            return "Todavia no he escaneado el computador."
        tipo = database.leer_meta(con, "tipo_escaneo", "?")
        duracion = database.leer_meta(con, "duracion_escaneo", "0")
        partes = [
            f"Ultimo escaneo {tipo}: {database.leer_meta(con, 'total_archivos')} "
            f"archivos y {database.leer_meta(con, 'total_carpetas')} carpetas en "
            f"{duracion} segundos, {database.leer_meta(con, 'carpetas_sin_cambios', '0')} "
            f"carpetas sin cambios.",
        ]
        errores = json.loads(database.leer_meta(con, "errores", "{}"))
        if errores:
            partes.append("Errores: " + ", ".join(f"{k}={v}" for k, v in errores.items()))
        inaccesibles = json.loads(database.leer_meta(con, "carpetas_inaccesibles", "[]"))
        if inaccesibles:
            partes.append("Carpetas sin permiso: " + ", ".join(inaccesibles[:10]))
        desconectadas = [f[0] for f in con.execute(
            "SELECT ruta FROM unidades WHERE estado = 'desconectada'")]
        if desconectadas:
            partes.append("Unidades desconectadas: " + ", ".join(desconectadas))
        return " ".join(partes)
    finally:
        con.close()
