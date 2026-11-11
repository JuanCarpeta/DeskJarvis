"""Clasificacion de errores del escaneo y estadisticas para Jarvis."""

import json
import time
from collections import Counter

ACCESO_DENEGADO = "acceso_denegado"
EN_USO = "en_uso"
RUTA_LARGA = "ruta_larga"
UNIDAD_CAIDA = "unidad_caida"
ENLACE = "enlace"
DESAPARECIDO = "desaparecido"
DESCONOCIDO = "desconocido"

ETIQUETAS = {
    ACCESO_DENEGADO: "carpetas sin permiso",
    EN_USO: "archivos en uso por otro programa",
    RUTA_LARGA: "rutas demasiado largas",
    UNIDAD_CAIDA: "unidades caidas o desconectadas",
    ENLACE: "enlaces y junctions omitidos",
    DESAPARECIDO: "rutas que desaparecieron durante el escaneo",
    DESCONOCIDO: "errores desconocidos",
}

MAX_RUTAS_REGISTRADAS = 50


def clasificar(error):
    """Traduce una excepcion de Windows a una categoria estable."""
    winerror = getattr(error, "winerror", None)
    if isinstance(error, PermissionError) or winerror == 5:
        return ACCESO_DENEGADO
    if winerror in (32, 33):
        return EN_USO
    if winerror == 21:
        return UNIDAD_CAIDA
    if winerror == 206:
        return RUTA_LARGA
    if isinstance(error, FileNotFoundError):
        return DESAPARECIDO
    return DESCONOCIDO


class Estadisticas:
    """Acumula lo que ocurre durante un escaneo para dejarlo en la tabla meta."""

    def __init__(self):
        self.inicio = time.monotonic()
        self.archivos = 0
        self.carpetas = 0
        self.carpetas_sin_cambios = 0
        self.enlaces = 0
        self.errores = Counter()
        self.rutas_error = {}
        self.rutas_enlaces = []

    @property
    def duracion(self):
        return time.monotonic() - self.inicio

    @property
    def total_errores(self):
        return sum(self.errores.values())

    def registrar_error(self, error, ruta):
        categoria = clasificar(error)
        self.errores[categoria] += 1
        rutas = self.rutas_error.setdefault(categoria, [])
        if len(rutas) < MAX_RUTAS_REGISTRADAS:
            rutas.append(ruta)

    def registrar_enlace(self, ruta):
        self.enlaces += 1
        if len(self.rutas_enlaces) < MAX_RUTAS_REGISTRADAS:
            self.rutas_enlaces.append(ruta)

    def a_meta(self, tipo_escaneo):
        """Diccionario listo para guardar en la tabla meta."""
        return {
            "tipo_escaneo": tipo_escaneo,
            "total_archivos": str(self.archivos),
            "total_carpetas": str(self.carpetas),
            "carpetas_sin_cambios": str(self.carpetas_sin_cambios),
            "enlaces_omitidos": str(self.enlaces),
            "total_errores": str(self.total_errores),
            "errores": json.dumps(dict(self.errores), ensure_ascii=False),
            "carpetas_inaccesibles": json.dumps(
                self.rutas_error.get(ACCESO_DENEGADO, []), ensure_ascii=False),
            "ultimo_escaneo": str(time.time()),
            "duracion_escaneo": f"{self.duracion:.2f}",
        }

    def resumen(self):
        partes = [f"{self.archivos} archivos y {self.carpetas} carpetas"]
        if self.carpetas_sin_cambios:
            partes.append(f"{self.carpetas_sin_cambios} carpetas sin cambios")
        if self.enlaces:
            partes.append(f"{self.enlaces} enlaces omitidos")
        if self.errores:
            partes.append(f"{self.total_errores} errores:")
            for categoria, cantidad in self.errores.most_common():
                partes.append(f"  {ETIQUETAS.get(categoria, categoria)}: {cantidad}")
                for ruta in self.rutas_error.get(categoria, [])[:5]:
                    partes.append(f"    {ruta}")
        return "\n".join(partes)
