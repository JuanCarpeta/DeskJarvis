import os
import tempfile
import unittest

import core.cerebro as cerebro


class TestIntenciones(unittest.TestCase):
    """El detector de ordenes no debe secuestrar conversacion normal."""

    def test_pregunta_normal_no_responde_no_encontrado(self):
        original = cerebro.buscar
        cerebro.buscar = lambda *a, **k: []
        try:
            self.assertIsNone(cerebro._responder_directo(
                "¿dónde está la capital de Francia?", "buscar"))
        finally:
            cerebro.buscar = original

    def test_haz_una_pregunta_no_crea_archivos(self):
        self.assertIsNone(cerebro._intencion("haz una pregunta"))

    def test_genera_un_resumen_no_crea_archivos(self):
        self.assertIsNone(cerebro._intencion("genera un resumen de la reunión"))

    def test_abreme_la_puerta_no_abre_archivos(self):
        original = cerebro.buscar
        cerebro.buscar = lambda *a, **k: []
        try:
            self.assertIsNone(cerebro._responder_directo("abreme la puerta", "abrir"))
        finally:
            cerebro.buscar = original

    def test_crear_documento_word_si_es_orden(self):
        self.assertEqual(cerebro._intencion("hazme un documento de word sobre el reciclaje"), "crear")

    def test_crear_carpeta_si_es_orden(self):
        self.assertEqual(cerebro._intencion("crea una carpeta llamada proyectos"), "crear")

    def test_buscar_archivo_si_es_orden(self):
        self.assertEqual(cerebro._intencion("busca el archivo de quimica"), "buscar")


class TestContenido(unittest.TestCase):
    def test_extrae_texto_dictado(self):
        texto = "crea un archivo llamado notas con el texto comprar pan y leche"
        self.assertEqual(cerebro._contenido_solicitado(texto), "comprar pan y leche")

    def test_sin_contenido_devuelve_none(self):
        self.assertIsNone(cerebro._contenido_solicitado("crea un archivo llamado notas"))

    def test_el_contenido_llega_a_crear_archivo(self):
        capturado = {}

        def falso_crear(ruta, titulo=None, contenido=None):
            capturado.update(ruta=ruta, titulo=titulo, contenido=contenido)
            return "ok"

        original = cerebro.crear_archivo
        cerebro.crear_archivo = falso_crear
        try:
            cerebro._responder_crear(
                "crea un archivo llamado notas con el texto comprar pan")
        finally:
            cerebro.crear_archivo = original

        self.assertTrue(capturado["ruta"].endswith("notas.txt"))
        self.assertEqual(capturado["contenido"], "comprar pan")


class TestSinResultados(unittest.TestCase):
    def test_busqueda_vacia_deja_decidir_al_modelo(self):
        original = cerebro.buscar
        cerebro.buscar = lambda *a, **k: []
        try:
            self.assertIsNone(cerebro._responder_directo(
                "¿dónde está la capital de Francia?", "buscar"))
            self.assertIsNone(cerebro._responder_directo("abreme la puerta", "abrir"))
        finally:
            cerebro.buscar = original


class TestHistorial(unittest.TestCase):
    def test_recorte_no_deja_tool_huerfano(self):
        original = cerebro.historial
        cerebro.historial = [{"role": "system", "content": "prompt"}]
        for i in range(10):
            cerebro.historial += [
                {"role": "user", "content": f"p{i}"},
                {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "x"}}]},
                {"role": "tool", "content": "r", "tool_name": "x"},
                {"role": "assistant", "content": "respuesta"},
            ]
        try:
            cerebro._recortar_historial(maximo=10, conservar=6)
            self.assertEqual(cerebro.historial[0]["role"], "system")
            self.assertNotEqual(cerebro.historial[1]["role"], "tool")
            self.assertNotEqual(cerebro.historial[1]["role"], "assistant")
            self.assertLessEqual(len(cerebro.historial), 7)
        finally:
            cerebro.historial = original


class TestSinOllama(unittest.TestCase):
    def test_las_ordenes_directas_funcionan_sin_ollama(self):
        original_ollama = cerebro.ollama
        original_carpeta = cerebro.crear_carpeta
        cerebro.ollama = None
        cerebro.crear_carpeta = lambda ruta: f"Carpeta creada: {ruta}"
        try:
            respuesta = cerebro.preguntar("crea una carpeta llamada prueba")
        finally:
            cerebro.ollama = original_ollama
            cerebro.crear_carpeta = original_carpeta
        self.assertIn("Carpeta creada", respuesta)


class TestFunctionCalling(unittest.TestCase):
    def setUp(self):
        self._ollama = cerebro.ollama
        self._historial = cerebro.historial
        cerebro.historial = [{"role": "system", "content": "prompt"}]

    def tearDown(self):
        cerebro.ollama = self._ollama
        cerebro.historial = self._historial

    def test_preguntar_ejecuta_la_herramienta_que_elige_el_modelo(self):
        consultas = []
        respuestas = [
            {"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "buscar_archivos",
                              "arguments": {"consulta": "informe"}}}]}},
            {"message": {"role": "assistant", "content": "Encontre el informe."}},
        ]

        class FalsoOllama:
            @staticmethod
            def chat(**kwargs):
                return respuestas.pop(0)

        original_buscar = cerebro.buscar
        cerebro.ollama = FalsoOllama
        cerebro.buscar = lambda consulta: consultas.append(consulta) or []
        try:
            respuesta = cerebro.preguntar("busca el informe")
        finally:
            cerebro.buscar = original_buscar

        self.assertEqual(consultas[-1], "informe")
        self.assertIn("informe", respuesta.lower())

    def test_accion_directa_no_pide_otra_respuesta_al_modelo(self):
        llamadas = []

        class FalsoOllama:
            @staticmethod
            def chat(**kwargs):
                llamadas.append(kwargs)
                return {"message": {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "crear_carpeta",
                                  "arguments": {"ruta": "prueba"}}}]}}

        original_crear = cerebro.crear_carpeta
        cerebro.ollama = FalsoOllama
        cerebro.crear_carpeta = lambda ruta: f"Carpeta creada: {ruta}"
        try:
            respuesta = cerebro.preguntar("necesito una carpeta nueva para el proyecto")
        finally:
            cerebro.crear_carpeta = original_crear

        self.assertEqual(len(llamadas), 1)
        self.assertIn("Carpeta creada", respuesta)

    def test_ruta_inexistente_no_se_abre(self):
        original_abrir = cerebro.abrir
        cerebro.abrir = lambda ruta: self.fail("no debio abrir una ruta inexistente")
        try:
            resultado = cerebro._ejecutar(
                "abrir_archivo", {"ruta": r"C:\ruta\que\no\existe\archivo.txt"})
        finally:
            cerebro.abrir = original_abrir
        self.assertIn("No existe", resultado)


class TestListarYNavegar(unittest.TestCase):
    def test_detecta_peticiones_de_listado(self):
        frases = (
            "dame un listado de lo que hay en C:\\",
            "dime que hay en C:\\",
            "que hay en proyectos",
            "muestrame que hay en descargas",
            "lista los archivos de documentos",
        )
        for frase in frases:
            self.assertEqual(cerebro._intencion(frase), "listar", frase)

    def test_muestrame_un_archivo_no_es_un_listado(self):
        self.assertIsNone(cerebro._intencion("muestrame el archivo informe"))
        self.assertEqual(
            cerebro._intencion("muestrame el contenido de informe"), "leer")

    def test_listado_no_navega(self):
        original_listar = cerebro.listar
        original_navegar = cerebro.navegar
        capturado = {}

        def falso_listar(ruta):
            capturado["ruta"] = ruta
            return "listado"

        cerebro.listar = falso_listar
        cerebro.navegar = lambda ruta: self.fail("no debio navegar")
        try:
            respuesta = cerebro._responder_directo(
                "dime que hay en C:\\", "listar")
        finally:
            cerebro.listar = original_listar
            cerebro.navegar = original_navegar

        self.assertEqual(respuesta, "listado")
        self.assertTrue(capturado["ruta"].startswith("C:"))

    def test_disco_local_va_a_la_raiz(self):
        original_navegar = cerebro.navegar
        capturado = {}
        cerebro.navegar = lambda ruta: capturado.setdefault("ruta", ruta) or "ok"
        try:
            cerebro._responder_directo("ve a mi disco local", "navegar")
        finally:
            cerebro.navegar = original_navegar

        unidad, resto = os.path.splitdrive(capturado["ruta"])
        self.assertTrue(unidad)
        self.assertEqual(resto, "\\")

    def test_navega_carpeta_relativa_a_la_actual(self):
        with tempfile.TemporaryDirectory() as temporal:
            sub = os.path.join(temporal, "proyectos")
            os.mkdir(sub)
            original_dir = cerebro.directorio_actual
            original_navegar = cerebro.navegar
            capturado = {}
            cerebro.directorio_actual = lambda: temporal
            cerebro.navegar = lambda ruta: capturado.setdefault("ruta", ruta) or "ok"
            try:
                cerebro._responder_directo("ve a proyectos", "navegar")
            finally:
                cerebro.directorio_actual = original_dir
                cerebro.navegar = original_navegar

        self.assertEqual(os.path.normcase(capturado["ruta"]),
                         os.path.normcase(sub))

    def test_lista_la_carpeta_actual_por_su_nombre(self):
        with tempfile.TemporaryDirectory() as temporal:
            base = os.path.join(temporal, "proyectos")
            os.mkdir(base)
            original_dir = cerebro.directorio_actual
            original_listar = cerebro.listar
            capturado = {}
            cerebro.directorio_actual = lambda: base
            cerebro.listar = lambda ruta: capturado.setdefault("ruta", ruta) or "ok"
            try:
                cerebro._responder_directo("que hay en proyectos", "listar")
            finally:
                cerebro.directorio_actual = original_dir
                cerebro.listar = original_listar

        self.assertEqual(os.path.normcase(capturado["ruta"]),
                         os.path.normcase(base))

    def test_si_suelto_pide_aclaracion_sin_modelo(self):
        original_ollama = cerebro.ollama
        original_historial = cerebro.historial
        llamadas = []

        class FalsoOllama:
            @staticmethod
            def chat(**kwargs):
                llamadas.append(kwargs)
                return {"message": {"role": "assistant", "content": "inventado"}}

        cerebro.ollama = FalsoOllama
        cerebro.historial = [{"role": "system", "content": "prompt"}]
        try:
            respuesta = cerebro.preguntar("si")
        finally:
            cerebro.ollama = original_ollama
            cerebro.historial = original_historial

        self.assertEqual(llamadas, [])
        self.assertIn("qué quieres", respuesta.lower())


if __name__ == "__main__":
    unittest.main()
