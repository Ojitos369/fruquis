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


def _run(*cmd, timeout=1) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
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
    if sys.platform == "darwin":
        return _mac()
    if os.environ.get("DISPLAY"):
        return _x11()
    return None


def _ext(props: str, name: str):
    m = re.search(name + r".*?= (\d+), (\d+), (\d+), (\d+)", props)
    return tuple(int(v) for v in m.groups()) if m else (0, 0, 0, 0)  # izquierda, derecha, arriba, abajo


def _x11(wid: str | None = None) -> dict | None:
    """La ventana `wid` (o la activa) con su rectángulo visible; None si está minimizada."""
    if wid is None:
        m = re.search(r"0x[0-9a-f]+", _run("xprop", "-root", "_NET_ACTIVE_WINDOW"))
        if not m or int(m.group(), 16) == 0:
            return None
        wid = m.group()
    props = _run("xprop", "-id", wid, "WM_CLASS", "_NET_WM_NAME", "_NET_FRAME_EXTENTS", "_GTK_FRAME_EXTENTS", "_NET_WM_STATE", "_NET_WM_WINDOW_TYPE")
    if re.search(r"_NET_WM_STATE_HIDDEN|_NET_WM_WINDOW_TYPE_(DESKTOP|DOCK)", props):  # minimizada, el fondo del escritorio o un panel
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


def _win(hwnd=None) -> dict | None:
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    hwnd = hwnd or u.GetForegroundWindow()
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


MAC_FRONT = """tell application "System Events"
  set p to first application process whose frontmost is true
  set n to name of p
  try
    set w to first window of p
    set {x, y} to position of w
    set {ww, hh} to size of w
    return n & "|" & (name of w) & "|" & x & "|" & y & "|" & ww & "|" & hh
  on error
    return n & "|||||"
  end try
end tell"""
MAC_LIST = """tell application "System Events"
  set out to ""
  repeat with p in (every application process whose visible is true)
    try
      repeat with w in windows of p
        set {x, y} to position of w
        set {ww, hh} to size of w
        set out to out & (name of p) & "|" & (name of w) & "|" & x & "|" & y & "|" & ww & "|" & hh & linefeed
      end repeat
    end try
  end repeat
  return out
end tell"""


def _mac_row(line: str) -> dict | None:
    """Fila «app|título|x|y|ancho|alto» de osascript → ventana (requiere el permiso de Accesibilidad / Automatización de macOS)."""
    p = line.strip().split("|")
    if len(p) < 6 or not p[0]:
        return None
    try:
        x, y, w, h = (int(float(v)) for v in p[2:6])
    except ValueError:
        return {"id": p[0], "title": p[1] or p[0], "cls": p[0], "x": 0, "y": 0, "w": 0, "h": 0}
    return {"id": p[0], "title": p[1] or p[0], "cls": p[0], "x": x, "y": y, "w": w, "h": h}


def _mac() -> dict | None:
    r = _run("osascript", "-e", MAC_FRONT, timeout=6)
    w = _mac_row(r) if r else None
    return w if w and w["w"] > 0 else None


def list_windows() -> list:
    """Ventanas abiertas: [{id, title, x, y, w, h}]. X11 (wmctrl) y Windows."""
    if sys.platform == "darwin":
        rows = (_mac_row(l) for l in _run("osascript", "-e", MAC_LIST, timeout=8).splitlines())
        return [w for w in rows if w and w["w"] > 0]
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        u, out = ctypes.windll.user32, []

        def cb(hwnd, _):
            if u.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(256)
                u.GetWindowTextW(hwnd, buf, 256)
                if buf.value.strip():
                    r = wintypes.RECT()
                    u.GetWindowRect(hwnd, ctypes.byref(r))
                    out.append({"id": str(hwnd), "title": buf.value, "x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top})
            return True
        u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb), 0)
        return out
    out = []
    for line in _run("wmctrl", "-lG").splitlines():
        p = line.split(None, 7)
        if len(p) >= 8 and p[1] != "-1":
            out.append({"id": p[0], "title": p[7], "x": int(p[2]), "y": int(p[3]), "w": int(p[4]), "h": int(p[5])})
    return out


def _hwnds() -> list:
    """Ventanas de Windows a la vista, de la de enfrente a la de atrás: sin minimizadas ni ocultas (cloaked: apps UWP o de otro escritorio)."""
    import ctypes
    from ctypes import wintypes

    u, out = ctypes.windll.user32, []

    def cb(hwnd, _):
        cloaked = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(cloaked), 4)  # 14 = DWMWA_CLOAKED
        if u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd) and not cloaked.value and u.GetWindowTextLengthW(hwnd):
            out.append(hwnd)
        return True
    u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    return out


def visible() -> list:
    """Ventanas a la vista (no minimizadas, del escritorio virtual actual) con el formato de active(). Lento: llamar fuera del hilo de la interfaz."""
    if sys.platform == "darwin":
        return list_windows()
    if sys.platform == "win32":
        return [w for h in _hwnds() if (w := _win(h))]
    if not os.environ.get("DISPLAY"):
        return []
    m = re.search(r"= (\d+)", _run("xprop", "-root", "_NET_CURRENT_DESKTOP"))
    desk = m.group(1) if m else "0"
    return [w for line in _run("wmctrl", "-l").splitlines() if len(p := line.split(None, 2)) >= 2 and p[1] == desk and (w := _x11(hex(int(p[0], 16))))]  # mismo id que active()


def grab(fragment: str):
    """(título, imagen PIL) de la primera ventana cuyo título contenga `fragment`, SIN enfocarla (aunque esté tapada por otras). None si no existe o no se pudo.
    Windows: PrintWindow; X11: `import` de ImageMagick. macOS no está soportado (screencapture -l necesita el id de ventana de Quartz)."""
    from PIL import Image
    hit = next((w for w in list_windows() if fragment.lower() in w["title"].lower()), None)
    if not hit or hit["w"] <= 0 or hit["h"] <= 0:
        return None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        w, h, hwnd = hit["w"], hit["h"], int(hit["id"])
        if u.IsIconic(hwnd):  # minimizada: no tiene contenido que pintar
            return None

        class BIH(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("w", wintypes.LONG), ("h", wintypes.LONG), ("planes", wintypes.WORD), ("bpp", wintypes.WORD),
                        ("comp", wintypes.DWORD), ("sz", wintypes.DWORD), ("xp", wintypes.LONG), ("yp", wintypes.LONG), ("a", wintypes.DWORD), ("b", wintypes.DWORD)]
        g.CreateCompatibleDC.restype = g.CreateCompatibleBitmap.restype = g.SelectObject.restype = ctypes.c_void_p
        u.GetWindowDC.restype = ctypes.c_void_p
        hdc = u.GetWindowDC(hwnd)
        mdc = g.CreateCompatibleDC(ctypes.c_void_p(hdc))
        bmp = g.CreateCompatibleBitmap(ctypes.c_void_p(hdc), w, h)
        g.SelectObject(ctypes.c_void_p(mdc), ctypes.c_void_p(bmp))
        ok = u.PrintWindow(hwnd, ctypes.c_void_p(mdc), 2)  # 2 = PW_RENDERFULLCONTENT: también navegadores y apps aceleradas
        buf = ctypes.create_string_buffer(w * h * 4)
        bi = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)  # alto negativo: filas de arriba abajo
        g.GetDIBits(ctypes.c_void_p(mdc), ctypes.c_void_p(bmp), 0, h, buf, ctypes.byref(bi), 0)
        g.DeleteObject(ctypes.c_void_p(bmp))
        g.DeleteDC(ctypes.c_void_p(mdc))
        u.ReleaseDC(hwnd, ctypes.c_void_p(hdc))
        return (hit["title"], Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")) if ok else None
    if sys.platform == "darwin":
        return None
    import io
    png = subprocess.run(["import", "-window", hit["id"], "png:-"], capture_output=True, timeout=10).stdout
    return (hit["title"], Image.open(io.BytesIO(png))) if png else None


def focus(fragment: str) -> str | None:
    """Enfoca la primera ventana cuyo título contenga `fragment`; devuelve su título o None."""
    hit = next((w for w in list_windows() if fragment.lower() in w["title"].lower()), None)
    if not hit:
        return None
    if sys.platform == "darwin":
        _run("osascript", "-e", f'tell application "{hit.get("cls") or hit["id"]}" to activate', timeout=6)
    elif sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.ShowWindow(int(hit["id"]), 9)
        ctypes.windll.user32.SetForegroundWindow(int(hit["id"]))
    else:
        _run("wmctrl", "-i", "-a", hit["id"])
    return hit["title"]
