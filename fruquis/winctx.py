"""Ventana activa del sistema: título, clase y rectángulo. X11 (xprop/wmctrl) y Windows (ctypes)."""
import os
import re
import subprocess
import sys

KINDS = {
    "browser": r"chrom|firefox|brave|edge|vivaldi|opera|zen|librewolf",
    "terminal": r"terminal|konsole|alacritty|kitty|wezterm|xterm|tilix|ghostty|foot|powershell|cmd\.exe|windowsterminal|conhost",
    "editor": r"code|cursor|jetbrains|pycharm|idea|sublime|vim|zed|obsidian",
}


def _run(*cmd) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return ""


def kind(info: dict | None) -> str:
    if not info:
        return "otro"
    text = f"{info['cls']} {info['title']}".lower()
    return next((k for k, rx in KINDS.items() if re.search(rx, text)), "otro")


def active() -> dict | None:
    """{title, cls, x, y, w, h} de la ventana en primer plano, o None."""
    if sys.platform == "win32":
        return _win()
    if os.environ.get("DISPLAY"):
        return _x11()
    return None


def _ext(props: str, name: str):
    m = re.search(name + r".*?= (\d+), (\d+), (\d+), (\d+)", props)
    return tuple(int(v) for v in m.groups()) if m else (0, 0, 0, 0)  # izquierda, derecha, arriba, abajo


def _x11() -> dict | None:
    m = re.search(r"0x[0-9a-f]+", _run("xprop", "-root", "_NET_ACTIVE_WINDOW"))
    if not m or int(m.group(), 16) == 0:
        return None
    wid = m.group()
    props = _run("xprop", "-id", wid, "WM_CLASS", "_NET_WM_NAME", "_NET_FRAME_EXTENTS", "_GTK_FRAME_EXTENTS", "_NET_WM_STATE")
    if "_NET_WM_STATE_HIDDEN" in props:
        return None
    cls = re.search(r'WM_CLASS.*?= (.*)', props)
    title = re.search(r'_NET_WM_NAME.*?= "(.*)"', props)
    geo = {}
    for line in _run("xwininfo", "-id", wid).splitlines():
        k, _, v = line.partition(":")
        if k.strip() in ("Absolute upper-left X", "Absolute upper-left Y", "Width", "Height"):
            geo[k.strip()] = int(v)
    if len(geo) < 4:
        return None
    x, y, w, h = geo["Absolute upper-left X"], geo["Absolute upper-left Y"], geo["Width"], geo["Height"]
    fl, fr, ft, fb = _ext(props, "_NET_FRAME_EXTENTS")  # decoración del gestor: la ventana visible es más grande
    gl, gr, gt, gb = _ext(props, "_GTK_FRAME_EXTENTS")  # sombra invisible de las ventanas CSD: la visible es más chica
    return {"id": wid, "title": title.group(1) if title else "", "cls": cls.group(1).replace('"', "") if cls else "",
            "x": x - fl + gl, "y": y - ft + gt, "w": w + fl + fr - gl - gr, "h": h + ft + fb - gt - gb}


def _win() -> dict | None:
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return None
    buf = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(hwnd, buf, 256)
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil
        cls = psutil.Process(pid.value).name()
    except Exception:
        cls = ""
    return {"id": str(hwnd), "title": buf.value, "cls": cls, "x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top}
