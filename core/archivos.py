"""Herramientas publicas de archivos para el cerebro: buscar, abrir, leer y crear.

El recorrido del disco vive en core/scanner.py y el acceso a la base en
core/database.py; este modulo es solo la cara visible que usa el cerebro.
"""

import os
import re
from datetime import datetime
from pathlib import Path

from core import database
from core.scanner import (
    buscar_en_vivo, indexar, normalizar, puntuar, refrescar_unidades, tokens,
)

EXT_TEXTO = {
    ".txt", ".md", ".csv", ".log", ".json", ".xml", ".html", ".htm",
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".rb", ".php",
    ".ini", ".cfg", ".yml", ".yaml", ".sql", ".bat", ".ps1", ".sh",
}

MAX_BYTES = 2_000_000

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
        unidad = os.environ.get("SystemDrive")
        return os.path.abspath(unidad + os.sep) if unidad else os.path.abspath(os.sep)
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


def _base_unidad(ruta):
    base = os.path.normcase(os.path.abspath(ruta))
    if not base.endswith(os.sep):
        base += os.sep
    return base


def _patron_unidad(base):
    escapado = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escapado + "%"


def buscar_en_db(con, tokens_consulta, consulta_norm, limite):
    refrescar_unidades(con)
    unidades = database.leer_unidades(con)
    offline = [_base_unidad(ruta) for ruta, estado in unidades
               if estado != "activa"]
    # Cada palabra debe aparecer como palabra completa dentro del nombre,
    # asi "taller" ya no confunde con "installer".
    sql = "SELECT ruta, nombre, nombre_norm, tamano, modificado FROM archivos WHERE 1=1"
    params = []
    for t in tokens_consulta[:6]:
        sql += " AND nombre_norm LIKE ?"
        params.append(f"% {t}%")
    if offline:
        sql += " AND NOT (" + " OR ".join(
            "ruta LIKE ? ESCAPE '\\'" for _ in offline) + ")"
        params.extend(_patron_unidad(base) for base in offline)
    sql += " LIMIT 3000"
    filas = con.execute(sql, params).fetchall()
    if not filas:
        return []
    filas.sort(key=lambda f: (-puntuar(f[2] or "", consulta_norm), -(f[4] or 0)))
    return [{"ruta": f[0], "nombre": f[1], "tamano": f[3], "modificado": f[4]}
            for f in filas[:limite]]


def buscar(consulta, limite=10):
    """Busca archivos por nombre. Acepta frases completas y no distingue acentos."""
    consulta = (consulta or "").strip()
    if not consulta:
        return []
    toks = tokens(consulta)
    if not toks:
        toks = [t for t in normalizar(consulta).split() if t] or [consulta.lower()]
    consulta_norm = normalizar(" ".join(toks))
    con = database.conectar()
    try:
        resultados = buscar_en_db(con, toks, consulta_norm, limite)
    finally:
        con.close()
    if resultados:
        return resultados
    return buscar_en_vivo(toks, consulta_norm, limite)


# Carpeta en la que Jarvis esta "ubicado" sin abrir ninguna ventana
_directorio_actual = str(Path.home())


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


def listar(ruta):
    """Lista el contenido real de una carpeta."""
    p = Path(ruta)
    if not p.exists():
        return f"No existe: {ruta}"
    if not p.is_dir():
        return f"{p} es un archivo, no una carpeta."
    try:
        elementos = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except OSError as e:
        return f"No pude listar {p}: {e}"
    if not elementos:
        return f"La carpeta {p} esta vacia."
    lineas = [
        f"{'[carpeta]' if x.is_dir() else '[archivo]'} {x.name}"
        for x in elementos[:100]
    ]
    resto = len(elementos) - 100
    if resto > 0:
        lineas.append(f"... y {resto} mas.")
    return f"Contenido de {p}:\n" + "\n".join(lineas)


def info(ruta):
    """Tamano, fecha de modificacion y tipo real de un archivo o carpeta."""
    p = Path(ruta)
    if not p.exists():
        return f"No existe: {ruta}"
    try:
        datos = p.stat()
    except OSError as e:
        return f"No pude leer {p}: {e}"
    fecha = datetime.fromtimestamp(datos.st_mtime).strftime("%Y-%m-%d %H:%M")
    if p.is_dir():
        return f"{p} es una carpeta, modificada el {fecha}."
    tam = f"{datos.st_size} bytes"
    if datos.st_size >= 1024 * 1024:
        tam += f" ({datos.st_size / (1024 * 1024):.1f} MB)"
    elif datos.st_size >= 1024:
        tam += f" ({datos.st_size / 1024:.1f} KB)"
    return f"{p} es un archivo de {tam}, modificado el {fecha}."
