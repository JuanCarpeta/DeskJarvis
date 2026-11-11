# Jarvis IA

Asistente personal de escritorio desarrollado en Python. La versión actual incluye un modo de texto, un modo de voz, integración con Ollama, reconocimiento de voz con Faster-Whisper y herramientas básicas para buscar, abrir y leer archivos.

## Requisitos

- Windows 10 u 11.
- Python 3.13 (es la versión usada en el entorno original del proyecto).
- Ollama instalado y ejecutándose.
- Un modelo descargado en Ollama. El proyecto usa `llama3.1:8b` por defecto.
- Micrófono para utilizar el modo de voz.

## Instalación

Abre PowerShell en la carpeta del proyecto y ejecuta:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si PowerShell bloquea la activación del entorno, puedes ejecutar los comandos usando directamente `\.venv\Scripts\python.exe`.

## Preparar Ollama

Comprueba que Ollama esté instalado y que el modelo configurado esté disponible:

```powershell
ollama pull llama3.1:8b
ollama list
```

El modelo se configura en `config.py`, en la variable `MODELO`.

## Ejecutar

```powershell
python main.py
```

En `config.py`:

- `MODO_TEXTO = True`: utiliza el teclado.
- `MODO_TEXTO = False`: utiliza el micrófono y la voz.

## Pruebas

Ejecuta las pruebas automatizadas con:

```powershell
python -m unittest discover -s tests -v
```

## Datos locales

`archivos.db` e `inventario.json` se generan en el computador al ejecutar Jarvis. No se incluyen en el repositorio porque contienen rutas, nombres de equipo y otra información local.

## Estado del proyecto

El proyecto está en desarrollo. Las funciones de búsqueda web, memoria persistente avanzada y la interfaz gráfica todavía están pendientes.
