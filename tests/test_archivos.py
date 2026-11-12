import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import archivos, database, scanner
from core.scanner_errors import (
    ACCESO_DENEGADO, DESAPARECIDO, DESCONOCIDO, EN_USO, RUTA_LARGA,
    UNIDAD_CAIDA, clasificar,
)


class BaseConDBTemporal(unittest.TestCase):
    """Cada prueba usa su propia base de datos y su propia carpeta falsa."""

    def setUp(self):
        self._temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporal.cleanup)
        self._db_real = database.DB
        database.DB = os.path.join(self._temporal.name, "prueba.db")
        database.inicializar()
        self._seg_real = scanner.SEG_ENTRE_ESCANEOS
        scanner.SEG_ENTRE_ESCANEOS = 0
        self.raiz = Path(self._temporal.name) / "equipo"
        self.docs = self.raiz / "docs"
        self.docs.mkdir(parents=True)
        self.archivo = self.docs / "informe.txt"
        self.archivo.write_text("hola", encoding="utf-8")

    def tearDown(self):
        database.DB = self._db_real
        scanner.SEG_ENTRE_ESCANEOS = self._seg_real

    def rutas_en_db(self):
        con = database.conectar()
        try:
            return {f[0]: (f[1], f[2]) for f in con.execute(
                "SELECT ruta, tamano, modificado FROM archivos")}
        finally:
            con.close()

    def meta(self, clave, defecto=None):
        con = database.conectar()
        try:
            return database.leer_meta(con, clave, defecto)
        finally:
            con.close()


class TestIndexacion(BaseConDBTemporal):
    def test_primer_escaneo_llena_la_base(self):
        total = scanner.indexar([self.raiz])
        self.assertEqual(total, len(self.rutas_en_db()))
        self.assertIn(str(self.archivo), self.rutas_en_db())
        self.assertIn(str(self.docs), self.rutas_en_db())

    def test_incremental_agrega_archivos_nuevos(self):
        scanner.indexar([self.raiz])
        nuevo = self.docs / "notas.txt"
        nuevo.write_text("nuevo", encoding="utf-8")
        scanner.indexar([self.raiz])
        self.assertIn(str(nuevo), self.rutas_en_db())

    def test_incremental_detecta_borrado_de_archivo(self):
        scanner.indexar([self.raiz])
        self.archivo.unlink()
        scanner.indexar([self.raiz])
        self.assertNotIn(str(self.archivo), self.rutas_en_db())

    def test_incremental_detecta_renombres(self):
        scanner.indexar([self.raiz])
        renombrado = self.docs / "final.txt"
        self.archivo.rename(renombrado)
        scanner.indexar([self.raiz])
        rutas = self.rutas_en_db()
        self.assertNotIn(str(self.archivo), rutas)
        self.assertIn(str(renombrado), rutas)

    def test_borrar_carpeta_elimina_su_contenido(self):
        sub = self.docs / "sub"
        sub.mkdir()
        (sub / "interno.txt").write_text("x", encoding="utf-8")
        scanner.indexar([self.raiz])
        shutil.rmtree(sub)
        scanner.indexar([self.raiz])
        rutas = self.rutas_en_db()
        self.assertNotIn(str(sub), rutas)
        self.assertNotIn(str(sub / "interno.txt"), rutas)

    def test_incremental_omite_carpetas_sin_cambios(self):
        scanner.indexar([self.raiz])
        antes = len(self.rutas_en_db())
        scanner.indexar([self.raiz])
        self.assertEqual(antes, len(self.rutas_en_db()))
        self.assertEqual(self.meta("tipo_escaneo"), "incremental")
        self.assertGreater(int(self.meta("carpetas_sin_cambios")), 0)
        self.assertEqual(self.meta("escaneo_truncado"), "0")

    def test_modificar_archivo_sin_renombrar_se_detecta(self):
        """El caso limite: modificar contenido no toca el mtime de la carpeta.

        NTFS ni siquiera actualiza el mtime de una carpeta al crear o borrar
        archivos dentro de ella, asi que la deteccion incremental no puede
        depender de el: usa la firma de los hijos de cada carpeta.
        """
        scanner.indexar([self.raiz])
        self.archivo.write_text("contenido mas largo", encoding="utf-8")
        os.utime(self.archivo, (1000, 2000))
        scanner.indexar([self.raiz])
        self.assertEqual(self.rutas_en_db()[str(self.archivo)], (19, 2000.0))

    def test_carpeta_con_cambios_actualiza_archivos_modificados(self):
        scanner.indexar([self.raiz])
        self.archivo.write_text("otro contenido", encoding="utf-8")
        os.utime(self.archivo, (1000, 3000))
        (self.docs / "extra.txt").write_text("x", encoding="utf-8")
        scanner.indexar([self.raiz])
        self.assertEqual(self.rutas_en_db()[str(self.archivo)][1], 3000.0)

    def test_excluye_carpetas_conocidas_y_ocultas(self):
        for nombre in ("node_modules", ".git", "AppData"):
            carpeta = self.raiz / nombre
            carpeta.mkdir()
            (carpeta / "dentro.txt").write_text("x", encoding="utf-8")
        (self.raiz / ".gitignore").write_text("x", encoding="utf-8")
        scanner.indexar([self.raiz])
        rutas = self.rutas_en_db()
        self.assertNotIn(str(self.raiz / "node_modules"), rutas)
        self.assertNotIn(str(self.raiz / ".git"), rutas)
        self.assertNotIn(str(self.raiz / "AppData"), rutas)
        self.assertIn(str(self.raiz / ".gitignore"), rutas)

    def test_cambiar_version_reconstruye(self):
        scanner.indexar([self.raiz])
        con = database.conectar()
        database.escribir_meta(con, "version_indice", "vieja")
        con.commit()
        con.close()
        nuevo = self.docs / "versionado.txt"
        nuevo.write_text("x", encoding="utf-8")
        scanner.indexar([self.raiz])
        self.assertIn(str(nuevo), self.rutas_en_db())


class TestBuscar(BaseConDBTemporal):
    def test_buscar_encuentra_archivo_indexado(self):
        scanner.indexar([self.raiz])
        resultados = archivos.buscar("informe")
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["ruta"], str(self.archivo))

    def test_buscar_ignora_mayusculas_y_acentos(self):
        scanner.indexar([self.raiz])
        self.assertEqual(len(archivos.buscar("INFORMÉ")), 1)

    def test_buscar_en_vivo_rastrea_ruta_concreta(self):
        resultados = scanner.buscar_en_vivo(
            scanner.tokens("informe"), scanner.normalizar("informe"), 5, raiz=self.raiz)
        self.assertEqual([r["ruta"] for r in resultados], [str(self.archivo)])


class TestUnidades(BaseConDBTemporal):
    def estado_unidad(self, ruta):
        con = database.conectar()
        try:
            return con.execute(
                "SELECT estado, ultima_revision FROM unidades WHERE ruta = ?",
                (str(ruta),)).fetchone()
        finally:
            con.close()

    def buscar_en_db(self, consulta):
        con = database.conectar()
        try:
            return archivos.buscar_en_db(
                con, scanner.tokens(consulta), scanner.normalizar(consulta), 10)
        finally:
            con.close()

    def test_unidad_se_registra_al_indexar(self):
        scanner.indexar([self.raiz])
        estado, revision = self.estado_unidad(self.raiz)
        self.assertEqual(estado, "activa")
        self.assertIsNotNone(revision)

    def test_unidad_desconectada_conserva_filas_pero_no_aparece(self):
        scanner.indexar([self.raiz])
        self.assertEqual(len(self.buscar_en_db("informe")), 1)
        shutil.rmtree(self.raiz)
        scanner.indexar([self.raiz])
        self.assertEqual(self.estado_unidad(self.raiz)[0], "desconectada")
        self.assertIn(str(self.archivo), self.rutas_en_db())
        self.assertEqual(self.buscar_en_db("informe"), [])

    def test_busqueda_ignora_unidad_desconectada_y_conserva_la_activa(self):
        otra = Path(self._temporal.name) / "otra"
        otra.mkdir()
        otro_archivo = otra / "informe-otro.txt"
        otro_archivo.write_text("otro", encoding="utf-8")
        scanner.indexar([self.raiz, otra])
        shutil.rmtree(self.raiz)
        resultados = self.buscar_en_db("informe")
        self.assertEqual([r["ruta"] for r in resultados], [str(otro_archivo)])

    def test_desconexion_se_refleja_en_la_siguiente_busqueda(self):
        scanner.indexar([self.raiz])
        self.assertEqual(len(self.buscar_en_db("informe")), 1)
        shutil.rmtree(self.raiz)
        self.assertEqual(self.buscar_en_db("informe"), [])
        self.assertEqual(self.estado_unidad(self.raiz)[0], "desconectada")

    def test_reconexion_se_refleja_en_la_siguiente_busqueda(self):
        scanner.indexar([self.raiz])
        shutil.rmtree(self.raiz)
        self.buscar_en_db("informe")
        self.docs.mkdir(parents=True)
        self.archivo.write_text("hola", encoding="utf-8")
        self.assertEqual(len(self.buscar_en_db("informe")), 1)
        self.assertEqual(self.estado_unidad(self.raiz)[0], "activa")

    def test_desconexion_se_detecta_aunque_el_escaneo_sea_reciente(self):
        scanner.indexar([self.raiz])
        shutil.rmtree(self.raiz)
        scanner.SEG_ENTRE_ESCANEOS = 3600
        scanner.indexar([self.raiz])
        self.assertEqual(self.estado_unidad(self.raiz)[0], "desconectada")

    def test_unidad_ausente_de_discos_se_marca_desconectada(self):
        scanner.indexar([self.raiz])
        shutil.rmtree(self.raiz)
        with mock.patch("core.scanner.discos", return_value=[]):
            scanner.indexar()
        self.assertEqual(self.estado_unidad(self.raiz)[0], "desconectada")
        self.assertIn("Unidades desconectadas", scanner.resumen_escaneo())

    def test_reconexion_fuerza_escaneo_y_vuelve_a_buscar(self):
        scanner.indexar([self.raiz])
        shutil.rmtree(self.raiz)
        scanner.indexar([self.raiz])
        self.docs.mkdir(parents=True)
        self.archivo.write_text("hola de nuevo", encoding="utf-8")
        scanner.SEG_ENTRE_ESCANEOS = 3600
        scanner.indexar([self.raiz])
        self.assertEqual(self.estado_unidad(self.raiz)[0], "activa")
        self.assertEqual(len(self.buscar_en_db("informe")), 1)

    def test_reconexion_detectada_por_busqueda_fuerza_nuevo_escaneo(self):
        scanner.indexar([self.raiz])
        self.assertEqual(len(self.buscar_en_db("informe")), 1)

        shutil.rmtree(self.raiz)
        self.assertEqual(self.buscar_en_db("informe"), [])
        self.assertEqual(self.estado_unidad(self.raiz)[0], "desconectada")

        self.docs.mkdir(parents=True)
        self.archivo.write_text("hola de nuevo", encoding="utf-8")
        nuevo = self.docs / "creado-offline.txt"
        nuevo.write_text("nuevo", encoding="utf-8")

        self.assertEqual(len(self.buscar_en_db("informe")), 1)
        estado, revision = self.estado_unidad(self.raiz)
        self.assertEqual(estado, "activa")
        self.assertIsNone(revision)

        scanner.SEG_ENTRE_ESCANEOS = 3600
        scanner.indexar([self.raiz])

        self.assertIsNotNone(self.estado_unidad(self.raiz)[1])
        self.assertIn(str(nuevo), self.rutas_en_db())
        self.assertEqual(len(self.buscar_en_db("creado")), 1)


class TestEstadisticas(BaseConDBTemporal):
    def test_guarda_estadisticas_del_ultimo_escaneo(self):
        scanner.indexar([self.raiz])
        self.assertEqual(self.meta("total_archivos"), "1")
        self.assertEqual(self.meta("total_carpetas"), "1")
        self.assertEqual(self.meta("total_errores"), "0")
        self.assertEqual(self.meta("tipo_escaneo"), "completo")
        self.assertEqual(json.loads(self.meta("errores")), {})
        self.assertIn("1 archivos", scanner.resumen_escaneo())

    def test_errores_se_cuentan_por_categoria(self):
        error = OSError("sin permiso")
        error.winerror = 5
        estadisticas = scanner.Estadisticas()
        estadisticas.registrar_error(error, str(self.docs / "secreta"))
        meta = estadisticas.a_meta("completo")
        self.assertEqual(meta["total_errores"], "1")
        self.assertIn("secreta", meta["carpetas_inaccesibles"])


class TestErroresDeIteracion(unittest.TestCase):
    def test_error_al_iterar_se_registra_y_no_aborta(self):
        estadisticas = scanner.Estadisticas()

        class IteradorRoto:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def __iter__(self):
                return self

            def __next__(self):
                raise OSError("fallo a mitad del listado")

        with mock.patch("core.scanner._scandir", return_value=IteradorRoto()):
            grupos = list(scanner.recorrer("C:\\carpeta", estadisticas))

        self.assertEqual(grupos, [])
        self.assertEqual(estadisticas.total_errores, 1)
        self.assertEqual(estadisticas.errores[DESCONOCIDO], 1)


class TestClasificacionErrores(unittest.TestCase):
    def _con_winerror(self, numero):
        error = OSError("prueba")
        error.winerror = numero
        return error

    def test_permiso(self):
        self.assertEqual(clasificar(PermissionError("x")), ACCESO_DENEGADO)
        self.assertEqual(clasificar(self._con_winerror(5)), ACCESO_DENEGADO)

    def test_en_uso(self):
        self.assertEqual(clasificar(self._con_winerror(32)), EN_USO)
        self.assertEqual(clasificar(self._con_winerror(33)), EN_USO)

    def test_unidad_caida(self):
        self.assertEqual(clasificar(self._con_winerror(21)), UNIDAD_CAIDA)

    def test_ruta_larga(self):
        self.assertEqual(clasificar(self._con_winerror(206)), RUTA_LARGA)

    def test_desaparecido(self):
        self.assertEqual(clasificar(FileNotFoundError("x")), DESAPARECIDO)

    def test_desconocido(self):
        self.assertEqual(clasificar(ValueError("x")), DESCONOCIDO)


class TestEnlacesYRutas(BaseConDBTemporal):
    def test_junction_no_se_recorre(self):
        objetivo = self.raiz / "real"
        objetivo.mkdir()
        (objetivo / "dentro.txt").write_text("x", encoding="utf-8")
        enlace = self.raiz / "atajo"
        try:
            import _winapi
            _winapi.CreateJunction(str(objetivo), str(enlace))
        except (ImportError, OSError):
            self.skipTest("este equipo no permite crear junctions de prueba")
        if not (enlace / "dentro.txt").exists():
            self.skipTest("el junction de prueba no apunto donde se esperaba")
        scanner.indexar([self.raiz])
        rutas = self.rutas_en_db()
        self.assertNotIn(str(enlace), rutas)
        self.assertNotIn(str(enlace / "dentro.txt"), rutas)
        self.assertIn(str(objetivo / "dentro.txt"), rutas)
        self.assertGreater(int(self.meta("enlaces_omitidos")), 0)

    def test_ruta_extendida(self):
        if os.name != "nt":
            self.skipTest("solo aplica en Windows")
        corta = "C:\\carpeta"
        self.assertEqual(scanner._ruta_extendida(corta), corta)
        larga = "C:\\" + "x" * 300
        self.assertEqual(scanner._ruta_extendida(larga), "\\\\?\\" + larga)

    def test_encuentra_archivos_en_rutas_profundas(self):
        carpeta = self.raiz
        try:
            for _ in range(30):
                carpeta = carpeta / ("nivel_" + "x" * 10)
                carpeta.mkdir()
            profundo = carpeta / "hondo.txt"
            profundo.write_text("x", encoding="utf-8")
        except OSError:
            self.skipTest("este equipo no permite crear rutas largas")
        if len(str(profundo)) <= scanner.LIMITE_RUTA:
            self.skipTest("la ruta generada no supera el limite clasico")
        scanner.indexar([self.raiz])
        self.assertIn(str(profundo), self.rutas_en_db())


class TestListarEInfo(BaseConDBTemporal):
    def test_listar_muestra_contenido_real(self):
        texto = archivos.listar(str(self.docs))
        self.assertIn("informe.txt", texto)
        self.assertIn("[archivo]", texto)

    def test_listar_carpeta_vacia(self):
        vacia = self.raiz / "vacia"
        vacia.mkdir()
        self.assertIn("vacia", archivos.listar(str(vacia)).lower())

    def test_listar_ruta_inexistente(self):
        self.assertIn("No existe", archivos.listar(str(self.raiz / "nada")))

    def test_info_devuelve_datos_reales(self):
        texto = archivos.info(str(self.archivo))
        self.assertIn("4 bytes", texto)
        self.assertIn("archivo", texto)

    def test_info_carpeta(self):
        self.assertIn("carpeta", archivos.info(str(self.docs)))


if __name__ == "__main__":
    unittest.main()
