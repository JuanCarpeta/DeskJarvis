import os
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

try:
    import psutil
except ModuleNotFoundError:
    psutil = None

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "archivos.db")

# Horas que se acepta la base sin volver a recorrer el disco
HORAS_INDICE = 12
# Subir esto obliga a reconstruir la base (por ejemplo al cambiar que se guarda)
VERSION_INDICE = "2"
# Segundos maximos de rastreo en vivo si la base no encuentra nada
SEG_BUSQUEDA_VIVA = 15


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


CARPETAS = discos()

EXCLUIR = {
    "AppData", "node_modules", ".git", "__pycache__", "venv", ".venv",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "System32", "$Recycle.Bin", "Recovery", "PerfLogs",
    "System Volume Information", "$WinREAgent",
}

EXT_TEXTO = {
    ".txt", ".md", ".csv", ".log", ".json", ".xml", ".html", ".htm",
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".rb", ".php",
    ".ini", ".cfg", ".yml", ".yaml", ".sql", ".bat", ".ps1", ".sh",
}

MAX_BYTES = 2_000_000

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


# Carpeta en la que Jarvis esta "ubicado" sin abrir ninguna ventana
_directorio_actual = str(Path.home())


def normalizar(texto):
    """Minusculas, sin acentos y con espacios alrededor (comparar por palabras)."""
    texto = unicodedata.normalize("NFKD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return " " + texto.strip() + " "


def _tokens(consulta):
    return [t for t in normalizar(consulta).split() if len(t) > 1 and t not in PARADAS]


RUTA_RE = re.compile(r'([A-Za-z]:[\\/][^"\'<>|?*\r\n]*)')


def extraer_ruta(texto):
    """Devuelve la primera ruta de Windows que exista dentro del texto."""
    for m in RUTA_RE.finditer(texto or ""):
        bruto = m.group(1).strip().strip('"\'')
        partes = [p for p in bruto.split() if p]
        for i in range(len(partes), 0, -1):
            cand = " ".join(partes[:i]).rstrip(".,;:!¡¿? ")
            try:
                if Path(cand).exists():
                    return str(Path(cand))
            except OSError:
                continue
    return None


def _primera_existente(nombres):
    bases = [Path.home()]
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        valor = os.environ.get(var)
        if valor:
            bases.append(Path(valor))
    for base in bases:
        for nombre in nombres:
            p = base / nombre
            if p.exists():
                return p
    return None


def ruta_conocida(texto):
    """Traduce frases como 'mi disco local' o 'descargas' a una ruta real."""
    t = normalizar(texto)
    claves_disco = ("disco local", "disco duro", "unidad c", "disco c",
                    "mi pc", "este equipo", "mi computadora", "mi computador")
    if any(f" {k} " in t for k in claves_disco):
        return str(Path(os.environ.get("SystemDrive", "C:") + "\\"))
    mapa = {
        "escritorio": ("Desktop", "Escritorio"),
        "desktop": ("Desktop", "Escritorio"),
        "descargas": ("Downloads", "Descargas"),
        "downloads": ("Downloads", "Descargas"),
        "documentos": ("Documents", "Documentos"),
        "documents": ("Documents", "Documentos"),
        "imagenes": ("Pictures", "Imagenes", "Imágenes"),
        "pictures": ("Pictures", "Imagenes", "Imágenes"),
        "musica": ("Music", "Musica", "Música"),
        "videos": ("Videos", "Vídeos"),
    }
    for clave, nombres in mapa.items():
        if f" {clave} " in t:
            p = _primera_existente(nombres)
            if p:
                return str(p)
    return None


def resolver_objetivo(texto):
    """Ruta explicita (C:\\...) o carpeta conocida mencionada en el texto."""
    return extraer_ruta(texto) or ruta_conocida(texto)


def _conectar():
    con = sqlite3.connect(DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS archivos (
               ruta TEXT PRIMARY KEY,
               nombre TEXT,
               ext TEXT,
               tamano INTEGER,
               modificado REAL,
               nombre_norm TEXT
           )"""
    )
    columnas = {c[1] for c in con.execute("PRAGMA table_info(archivos)")}
    if "nombre_norm" not in columnas:
        con.execute("ALTER TABLE archivos ADD COLUMN nombre_norm TEXT")
        filas = con.execute("SELECT ruta, nombre FROM archivos").fetchall()
        con.executemany(
            "UPDATE archivos SET nombre_norm = ? WHERE ruta = ?",
            [(normalizar(n or ""), r) for r, n in filas],
        )
    con.execute("CREATE INDEX IF NOT EXISTS idx_nombre ON archivos(nombre)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_norm ON archivos(nombre_norm)")
    con.execute("CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT)")
    con.commit()
    return con


def _ultima_indexacion(con):
    try:
        fila = con.execute("SELECT valor FROM meta WHERE clave='ultima_indexacion'").fetchone()
        return float(fila[0]) if fila else 0.0
    except Exception:
        return 0.0


def _version_indice(con):
    try:
        fila = con.execute("SELECT valor FROM meta WHERE clave='version_indice'").fetchone()
        return fila[0] if fila else ""
    except Exception:
        return ""


def indexar(raices=None, max_archivos=1000000, forzar=False):
    """Recorre las unidades y guarda nombre/ruta/tamano en archivos.db."""
    raices = raices or CARPETAS
    con = _conectar()
    total_db = con.execute("SELECT COUNT(*) FROM archivos").fetchone()[0]
    if (not forzar and total_db and _version_indice(con) == VERSION_INDICE
            and (time.time() - _ultima_indexacion(con)) < HORAS_INDICE * 3600):
        con.close()
        return total_db

    con.execute("DELETE FROM archivos")
    total = 0
    lote = []

    def volcar():
        nonlocal lote
        if lote:
            con.executemany("INSERT OR REPLACE INTO archivos VALUES (?,?,?,?,?,?)", lote)
            lote = []

    def agregar(ruta, nombre, ext, tamano, modificado):
        nonlocal total
        lote.append((ruta, nombre.lower(), ext, tamano, modificado, normalizar(nombre)))
        total += 1
        if len(lote) >= 1000:
            volcar()

    lleno = False
    for raiz in raices:
        raiz = Path(raiz)
        if not raiz.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(raiz, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if d not in EXCLUIR and not d.startswith(".")]
            for nombre in dirnames:
                agregar(os.path.join(dirpath, nombre), nombre, "", 0, 0.0)
                if total >= max_archivos:
                    lleno = True
                    break
            if lleno:
                break
            for nombre in filenames:
                ruta = os.path.join(dirpath, nombre)
                try:
                    st = os.stat(ruta)
                except OSError:
                    continue
                agregar(ruta, nombre, os.path.splitext(nombre)[1].lower(),
                        st.st_size, st.st_mtime)
                if total >= max_archivos:
                    lleno = True
                    break
            if lleno:
                break
        if lleno:
            break
    volcar()
    con.execute("INSERT OR REPLACE INTO meta VALUES ('ultima_indexacion', ?)", (str(time.time()),))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('version_indice', ?)", (VERSION_INDICE,))
    con.commit()
    con.close()
    return total


def _puntuar(nombre_norm, consulta_norm):
    """Mas puntos si el nombre coincide completo o empieza igual."""
    n = nombre_norm.strip()
    c = consulta_norm.strip()
    if n == c:
        return 100
    if n.startswith(c):
        return 60
    return 0


def _buscar_en_db(con, tokens, consulta_norm, limite):
    # Cada palabra debe aparecer como palabra completa dentro del nombre,
    # asi "taller" ya no confunde con "installer".
    sql = "SELECT ruta, nombre, nombre_norm, tamano, modificado FROM archivos WHERE 1=1"
    params = []
    for t in tokens[:6]:
        sql += " AND nombre_norm LIKE ?"
        params.append(f"% {t}%")
    sql += " LIMIT 3000"
    filas = con.execute(sql, params).fetchall()
    if not filas:
        return []
    filas.sort(key=lambda f: (-_puntuar(f[2] or "", consulta_norm), -(f[4] or 0)))
    return [{"ruta": f[0], "nombre": f[1], "tamano": f[3], "modificado": f[4]}
            for f in filas[:limite]]


def _buscar_en_vivo(tokens, consulta_norm, limite):
    """Rastrea la carpeta del usuario por si el archivo es nuevo y no esta en la base."""
    inicio = time.time()
    encontrados = []
    con = _conectar()
    try:
        for dirpath, dirnames, filenames in os.walk(Path.home(), onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if d not in EXCLUIR and not d.startswith(".")]
            for nombre in dirnames:
                nn = normalizar(nombre)
                if all((" " + t) in nn for t in tokens):
                    ruta = os.path.join(dirpath, nombre)
                    con.execute("INSERT OR REPLACE INTO archivos VALUES (?,?,?,?,?,?)",
                                (ruta, nombre.lower(), "", 0, 0.0, nn))
                    encontrados.append({"ruta": ruta, "nombre": nombre.lower(),
                                        "tamano": 0, "modificado": 0.0})
                    if len(encontrados) >= limite:
                        raise StopIteration
            for nombre in filenames:
                nn = normalizar(nombre)
                if all((" " + t) in nn for t in tokens):
                    ruta = os.path.join(dirpath, nombre)
                    try:
                        st = os.stat(ruta)
                    except OSError:
                        continue
                    con.execute("INSERT OR REPLACE INTO archivos VALUES (?,?,?,?,?,?)",
                                (ruta, nombre.lower(), os.path.splitext(nombre)[1].lower(),
                                 st.st_size, st.st_mtime, nn))
                    encontrados.append({"ruta": ruta, "nombre": nombre.lower(),
                                        "tamano": st.st_size, "modificado": st.st_mtime})
                    if len(encontrados) >= limite:
                        raise StopIteration
            if time.time() - inicio > SEG_BUSQUEDA_VIVA:
                break
        con.commit()
    except StopIteration:
        con.commit()
    except Exception as e:
        # Antes se ignoraba en silencio y la busqueda parecia "no encontrado".
        print(f"(busqueda en vivo incompleta: {e})")
    finally:
        con.close()
    encontrados.sort(key=lambda f: (-_puntuar(normalizar(f["nombre"]), consulta_norm),
                                    -(f["modificado"] or 0)))
    return encontrados[:limite]


def buscar(consulta, limite=10):
    """Busca archivos por nombre. Acepta frases completas y no distingue acentos."""
    consulta = (consulta or "").strip()
    if not consulta:
        return []
    tokens = _tokens(consulta)
    if not tokens:
        tokens = [t for t in normalizar(consulta).split() if t] or [consulta.lower()]
    consulta_norm = normalizar(" ".join(tokens))
    con = _conectar()
    try:
        resultados = _buscar_en_db(con, tokens, consulta_norm, limite)
    finally:
        con.close()
    if resultados:
        return resultados
    return _buscar_en_vivo(tokens, consulta_norm, limite)


def directorio_actual():
    """Carpeta en la que Jarvis esta ubicado actualmente."""
    return _directorio_actual


def navegar(ruta):
    """Ubica a Jarvis en una carpeta SIN abrir ninguna ventana."""
    global _directorio_actual
    p = Path(ruta)
    if not p.exists():
        return f"No existe: {ruta}"
    if not p.is_dir():
        return f"{p} es un archivo, no una carpeta."
    _directorio_actual = str(p)
    return f"Ahora estoy en: {p}"


def abrir(ruta):
    """Abre un archivo o carpeta con el programa predeterminado de Windows."""
    p = Path(ruta)
    if not p.exists():
        return f"No existe: {ruta}"
    try:
        os.startfile(str(p))  # type: ignore[attr-defined]
    except Exception as e:
        return f"No pude abrirlo: {e}"
    return f"Abierto: {p.name}"

def crear_carpeta(ruta):
    """Crea una carpeta, incluyendo las carpetas padre si faltan."""
    p = Path(ruta)
    try:
        p.mkdir(parents=True, exist_ok=True)
        return f"Carpeta creada: {p}"
    except Exception as e:
        return f"No pude crear la carpeta: {e}"


def crear_archivo(ruta, titulo=None, contenido=None):
    """Crea un archivo de cualquier extension.

    Word, Excel, PowerPoint y PDF se generan como documentos reales.
    El resto se crea con contenido de texto o vacio.
    """
    p = Path(ruta)
    ext = p.suffix.lower()
    if not ext:
        return "El nombre necesita una extension, por ejemplo .txt o .docx."
    if p.exists():
        return f"Ya existe un archivo con ese nombre: {p}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if ext in EXT_TEXTO:
            p.write_text(contenido if contenido is not None else (titulo or ""),
                         encoding="utf-8")
        elif ext == ".xlsx":
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = (titulo or "Hoja1")[:31]
            if contenido:
                for linea in str(contenido).splitlines():
                    ws.append([c.strip() for c in linea.split(",")])
            wb.save(str(p))
        elif ext == ".docx":
            import docx
            doc = docx.Document()
            if titulo:
                doc.add_heading(titulo, 0)
            if contenido:
                doc.add_paragraph(str(contenido))
            doc.save(str(p))
        elif ext == ".pptx":
            from pptx import Presentation
            prs = Presentation()
            diapo = prs.slides.add_slide(prs.slide_layouts[0])
            if titulo:
                diapo.shapes.title.text = titulo
            if contenido:
                diapo.placeholders[1].text = str(contenido)
            prs.save(str(p))
        elif ext == ".pdf":
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen.canvas import Canvas
            c = Canvas(str(p), pagesize=A4)
            y = 800
            if titulo:
                c.setFont("Helvetica-Bold", 16)
                c.drawString(50, y, titulo)
                y -= 40
            c.setFont("Helvetica", 11)
            if contenido:
                for linea in str(contenido).splitlines():
                    c.drawString(50, y, linea)
                    y -= 15
            c.save()
        elif contenido is not None:
            p.write_text(str(contenido), encoding="utf-8")
        else:
            p.touch()
    except ModuleNotFoundError as e:
        paquete = {"docx": "python-docx", "openpyxl": "openpyxl", "pptx": "python-pptx",
                   "reportlab": "reportlab", "pypdf": "pypdf"}.get(e.name, e.name)
        return (f"Falta la dependencia '{paquete}' para crear {ext}. "
                f"Instalala con: pip install {paquete}")
    except PermissionError:
        return ("Windows bloqueo la escritura en esa carpeta. "
                "Activa Python en Acceso controlado a carpetas o elige otra carpeta. "
                f"Ruta: {p}")
    except FileNotFoundError:
        return ("No pude escribir en esa carpeta. Puede estar protegida por Windows "
                f"(Acceso controlado a carpetas) o no existir: {p.parent}")
    except Exception as e:
        return f"No pude crear el archivo: {e}"
    return f"Archivo creado: {p}"


def leer(ruta, max_chars=4000):
    """Extrae texto de txt, pdf, docx y xlsx."""
    p = Path(ruta)
    if not p.exists():
        return "El archivo no existe."
    if p.is_dir():
        return f"{p.name} es una carpeta, no un archivo."
    ext = p.suffix.lower()
    try:
        if ext in EXT_TEXTO:
            texto = p.read_text(encoding="utf-8", errors="ignore")
        elif ext == ".pdf":
            from pypdf import PdfReader
            texto = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
        elif ext == ".docx":
            import docx
            texto = "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
        elif ext in (".xlsx", ".xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
            partes = []
            for hoja in wb.worksheets:
                for fila in hoja.iter_rows(values_only=True):
                    partes.append(" | ".join("" if c is None else str(c) for c in fila))
            texto = "\n".join(partes)
        else:
            return f"No se leer archivos {ext}."
    except Exception as e:
        return f"Error al leer: {e}"
    return " ".join(texto.split())[:max_chars]
