"""Instala con pip, la primera vez que hacen falta, las dependencias opcionales (voz, volumen). En la versión empaquetada no se puede: ahí van incluidas."""
import importlib
import subprocess
import sys


def ensure(mods: dict, on_start=None):
    """`mods`: {módulo: paquete de pip}. Si falta alguno, instala todo lo que falta (con ensurepip si el entorno se creó sin pip, p. ej. con uv)."""
    missing = []
    for mod, pkg in mods.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return
    if getattr(sys, "frozen", False):
        raise ImportError("faltan " + ", ".join(missing))
    if on_start:
        on_start(missing)

    def py(*a):
        return subprocess.run([sys.executable, "-m", *a], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    r = py("pip", "install", *missing)
    if r.returncode and "No module named pip" in r.stderr:
        py("ensurepip")
        r = py("pip", "install", *missing)
    if r.returncode:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "pip falló")
    importlib.invalidate_caches()
