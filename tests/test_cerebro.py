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


if __name__ == "__main__":
    unittest.main()
