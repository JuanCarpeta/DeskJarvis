import os
import socket
import sys
import traceback

# Si se ejecuta sin terminal (pythonw), guarda la salida en un archivo.
BASE = os.path.dirname(os.path.abspath(__file__))
if sys.stdout is None or sys.stderr is None or "pythonw" in os.path.basename(sys.executable).lower():
    _log = open(os.path.join(BASE, "jarvis.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = _log
    sys.stderr = _log

from config import MODO_TEXTO, PALABRAS_APAGAR, PUERTO_UNICO, SEG_ESCUCHA_ESPERA, VENTANA_SEG

_candado = None


def adquirir_instancia():
    """Evita que se ejecuten dos instancias de Jarvis al mismo tiempo."""
    global _candado
    _candado = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _candado.bind(("127.0.0.1", PUERTO_UNICO))
    except OSError:
        print("Jarvis ya está en ejecución.")
        _candado.close()
        _candado = None
        return False
    return True


def actualizar_inventario():
    """Actualiza la información del equipo una vez al iniciar Jarvis."""
    try:
        from core.inventario import construir

        construir()
        # El cerebro utiliza el inventario para construir su contexto inicial.
        from core.cerebro import refrescar

        refrescar()
        print("Inventario actualizado.")
    except Exception:
        traceback.print_exc()


def main_texto():
    from core.activacion import coincide
    from core.archivos import indexar
    from core.cerebro import preguntar

    print("Jarvis listo (modo texto). Escribe 'salir' para terminar.")
    indexar()
    while True:
        try:
            texto = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nJarvis apagado.")
            break

        if not texto:
            continue
        if coincide(texto, PALABRAS_APAGAR):
            print("Jarvis: Hasta luego.")
            break

        respuesta = preguntar(texto)
        print("Jarvis:", respuesta)


def main_voz():
    from core.activacion import buscar_wake, coincide
    from core.archivos import indexar
    from core.cerebro import preguntar
    from core.oido import escuchar
    from core.voz import hablar

    hablar("Jarvis listo.")
    indexar()
    en_espera = True
    print("En espera. Di 'oye Jarvis' para activarme.")

    while True:
        if en_espera:
            oido = escuchar(espera=None, max_seg=SEG_ESCUCHA_ESPERA)
            if not oido:
                continue
            print("(oído en espera):", oido)
            detectado, resto = buscar_wake(oido)
            if not detectado:
                continue

            en_espera = False
            if not resto.strip(" .,!¡¿?"):
                hablar("Dime.")
                continue
            texto = resto
        else:
            texto = escuchar(espera=VENTANA_SEG)
            if not texto:
                en_espera = True
                print("😴 En espera. Di 'oye Jarvis' para activarme.")
                continue

        print("Tú:", texto)
        if coincide(texto, PALABRAS_APAGAR):
            hablar("Hasta luego.")
            break

        respuesta = preguntar(texto)
        print("Jarvis:", respuesta)
        hablar(respuesta)


def main():
    if not adquirir_instancia():
        return

    actualizar_inventario()
    if MODO_TEXTO:
        main_texto()
    else:
        main_voz()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nJarvis apagado.")
    except Exception:
        traceback.print_exc()
