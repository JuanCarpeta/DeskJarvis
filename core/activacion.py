import difflib
import re
import unicodedata


def normalizar(texto):
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", texto)


def buscar_wake(texto):
    """Detecta 'jarvis' aunque Whisper lo transcriba de forma parecida."""
    originales = re.split(r"\s+", str(texto).strip())
    for i, palabra in enumerate(originales):
        p = normalizar(palabra).strip()
        if p and difflib.get_close_matches(p, ["jarvis"], n=1, cutoff=0.75):
            return True, " ".join(originales[i + 1:]).strip()
    return False, ""


def coincide(texto, conjunto):
    """Reconoce comandos completos y evita apagar por mencionar una palabra."""
    frase = normalizar(texto).strip()
    comandos = {normalizar(comando).strip() for comando in conjunto}
    return bool(frase) and frase in comandos
