import pyttsx3

# Un solo motor para todo el proceso: crear pyttsx3.init() en cada frase es
# lento y en Windows termina colgandose despues de varias llamadas.
_motor = None


def _obtener_motor():
    global _motor
    if _motor is not None:
        return _motor
    motor = pyttsx3.init()
    motor.setProperty("rate", 175)
    for voz in motor.getProperty("voices"):
        nombre = (getattr(voz, "name", "") or "").lower()
        ident = (getattr(voz, "id", "") or "").lower()
        if "spanish" in nombre or "es-" in ident or "es_" in ident:
            motor.setProperty("voice", voz.id)
            break
    _motor = motor
    return _motor


def hablar(texto):
    """Lee el texto en voz alta. Si el audio falla, no tumba a Jarvis."""
    texto = (texto or "").replace("*", "").replace("#", "").strip()
    if not texto:
        return
    try:
        motor = _obtener_motor()
        motor.say(texto)
        motor.runAndWait()
    except Exception as e:
        print(f"(no pude hablar: {e})")
