import unittest

from core.activacion import buscar_wake, coincide
from config import PALABRAS_APAGAR


class TestActivacion(unittest.TestCase):
    def test_comando_salir_completo(self):
        self.assertTrue(coincide("salir", PALABRAS_APAGAR))

    def test_comando_apagar_con_tilde(self):
        self.assertTrue(coincide("apágate", PALABRAS_APAGAR))

    def test_frase_normal_no_apaga_jarvis(self):
        self.assertFalse(coincide("quiero salir a jugar", PALABRAS_APAGAR))

    def test_mencionar_apagar_no_apaga_jarvis(self):
        self.assertFalse(coincide("quiero apagar la computadora", PALABRAS_APAGAR))

    def test_frase_explicita_apagar_jarvis(self):
        self.assertTrue(coincide("apagar Jarvis", PALABRAS_APAGAR))

    def test_detecta_palabra_de_activacion(self):
        detectado, resto = buscar_wake("oye Jarvis abre el bloc de notas")
        self.assertTrue(detectado)
        self.assertEqual(resto, "abre el bloc de notas")

    def test_detecta_wake_con_puntuacion(self):
        detectado, resto = buscar_wake("oye, Jarvis! abre el bloc de notas")
        self.assertTrue(detectado)
        self.assertEqual(resto, "abre el bloc de notas")


if __name__ == "__main__":
    unittest.main()
