MODELO = "llama3.1:8b"

# Modo de uso: True = solo texto (teclado), False = voz (microfono y altavoz)
MODO_TEXTO = True

#Microfono

SAMPLE_RATE = 16000
UMBRAL = 0.015
SILENCIO_SEG = 1.2
MAX_SEG = 15
VENTANA_SEG = 10
SEG_ESCUCHA_ESPERA = 6
PROMPT_INICIAL = "Conversacion en español con Jarvis"

#Palabras claves

PALABRAS_APAGAR = {"apagar", "salir", "apagate", "apagar jarvis", "cerrar jarvis", "salir de jarvis"}

#Evitar abrir dos jarvis
PUERTO_UNICO = 48653

MAX_PASOS = 4
TEMPERATURA = 0