import time
from collections import deque

try:
    import numpy as np
    import sounddevice as sd
    from faster_whisper import WhisperModel
except ModuleNotFoundError:
    np = None
    sd = None
    WhisperModel = None

from config import SAMPLE_RATE, UMBRAL, SILENCIO_SEG, MAX_SEG, PROMPT_INICIAL

whisper = None


def _obtener_whisper():
    global whisper
    if whisper is not None:
        return whisper
    if np is None or sd is None or WhisperModel is None:
        raise RuntimeError(
            "Faltan dependencias de audio: instala faster-whisper, numpy y sounddevice."
        )
    print("Cargando modelo de voz (la primera vez descarga unos 500 MB)...")
    whisper = WhisperModel("small", device="cpu", compute_type="int8")
    return whisper


def escuchar(espera=None, max_seg=MAX_SEG):
    """Graba hasta que dejes de hablar. Si 'espera' es None, espera sin límite a que hables."""
    modelo = _obtener_whisper()
    bloque = int(SAMPLE_RATE * 0.1)
    previo = deque(maxlen=3)
    audio = []
    hablando = False
    silencio = 0.0
    inicio = time.time()
    inicio_habla = 0.0

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                        dtype="float32", blocksize=bloque) as stream:
        while True:
            datos, _ = stream.read(bloque)
            volumen = float(np.sqrt(np.mean(datos ** 2)))

            if volumen > UMBRAL:
                if not hablando:
                    hablando = True
                    inicio_habla = time.time()
                    audio.extend(previo)
                silencio = 0.0
            elif hablando:
                silencio += 0.1

            if hablando:
                audio.append(datos.copy())
                if silencio >= SILENCIO_SEG or time.time() - inicio_habla > max_seg:
                    break
            else:
                previo.append(datos.copy())
                if espera is not None and time.time() - inicio > espera:
                    return ""

    senal = np.concatenate(audio).flatten()
    if len(senal) < SAMPLE_RATE * 0.4:   # ruidos muy cortos se ignoran
        return ""
    segmentos, _ = modelo.transcribe(senal, language="es", vad_filter=True,
                                      initial_prompt=PROMPT_INICIAL)
    return " ".join(s.text for s in segmentos).strip()