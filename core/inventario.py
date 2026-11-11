import json, os, platform, subprocess

try:
    import psutil
except ModuleNotFoundError:
    psutil = None

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(BASE, "inventario.json")

def _ps(cmd):
    """Ejecuta PowerShell forzando salida UTF-8 (si no, Windows entrega cp850)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + cmd],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return out.stdout.strip()
    except Exception as e:
        print(f"(no pude consultar PowerShell: {e})")
        return ""

def recolectar():
    discos = []
    if psutil is not None:
        for p in psutil.disk_partitions():
            try:
                u = psutil.disk_usage(p.mountpoint)
                discos.append({"unidad": p.device, "total_gb": round(u.total/1e9),
                               "libre_gb": round(u.free/1e9)})
            except Exception:
                pass
    programas = _ps(
        "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,"
        "HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* "
        "| Where-Object DisplayName | Select-Object -ExpandProperty DisplayName")
    gpu = _ps("(Get-CimInstance Win32_VideoController).Name")
    nucleos = psutil.cpu_count(logical=True) if psutil is not None else 1
    ram_gb = round(psutil.virtual_memory().total/1e9) if psutil is not None else 0
    return {
        "so": {"sistema": platform.system(), "version": platform.version(),
               "equipo": platform.node()},
        "cpu": {"modelo": platform.processor(),
                "nucleos": nucleos},
        "ram_gb": ram_gb,
        "discos": discos,
        "gpu": [g for g in gpu.splitlines() if g.strip()],
        "programas": sorted({p.strip() for p in programas.splitlines() if p.strip()}),
    }

def construir():
    inv = recolectar()
    with open(RUTA, "w", encoding="utf-8") as f:
        json.dump(inv, f, indent=2, ensure_ascii=False)
    return inv

def cargar():
    if os.path.exists(RUTA):
        with open(RUTA, encoding="utf-8") as f:
            return json.load(f)
    return construir()

def resumen(max_prog=30):
    inv = cargar()
    so = inv.get("so") or {}
    cpu = inv.get("cpu") or {}
    prog = ", ".join((inv.get("programas") or [])[:max_prog])
    gpu = ", ".join(inv.get("gpu") or []) or "no detectada"
    discos = ", ".join(
        f"{d.get('unidad', '?')} {d.get('libre_gb', '?')}/{d.get('total_gb', '?')} GB"
        for d in (inv.get("discos") or [])
    ) or "no detectados"
    return (f"SO {so.get('sistema', '?')} ({so.get('equipo', '?')}). "
            f"CPU {cpu.get('modelo', '?')} ({cpu.get('nucleos', '?')} núcleos), "
            f"RAM {inv.get('ram_gb', 0)} GB, GPU {gpu}. "
            f"Discos: {discos}. Programas: {prog}.")