"""Ver y controlar el escritorio: capturas de pantalla / de la ventana activa, y ratón + teclado (pynput). El chat lo usa a través de
`python -m fruquis ctl …` (Bash). Todo está protegido por los ajustes: «Ver ventana» permite capturas y «Controlar» permite actuar."""
import json
import re
import shlex
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

from . import deps, store, winctx

SHOTS = store.HOME / "shots"
STATE = store.HOME / "ctl_state.json"
LOG = store.HOME / "ctl.log"
MAX_ACTIONS_PER_MIN = 60


def allowed(level: str) -> bool:
    o = store.get("chat_opts", {})
    return bool(o.get("control")) if level == "control" else bool(o.get("see") or o.get("control"))


def capture(rect=None, name="shot") -> tuple:
    """Captura (la ventana `rect` = {x,y,w,h} o toda la pantalla). Guarda el PNG y recuerda el origen para que los clics usen coordenadas de la imagen."""
    from PIL import ImageGrab
    full = ImageGrab.grab(all_screens=True)
    ox, oy = (rect["x"], rect["y"]) if rect else (0, 0)
    box = (max(0, ox), max(0, oy), min(full.width, ox + rect["w"]) if rect else full.width, min(full.height, oy + rect["h"]) if rect else full.height)
    img = full.crop(box)
    SHOTS.mkdir(parents=True, exist_ok=True)
    for old in sorted(SHOTS.glob("*.png"))[:-11]:  # solo se conservan las últimas capturas
        old.unlink()
    path = SHOTS / f"{name}-{int(time.time() * 1000)}.png"
    img.save(path)
    STATE.write_text(json.dumps({"origin": [box[0], box[1]], "size": [img.width, img.height], "at": time.time()}))
    return path, (box[0], box[1], img.width, img.height)


def _origin() -> tuple:
    try:
        o = json.loads(STATE.read_text())["origin"]
        return o[0], o[1]
    except Exception:
        return 0, 0


def _rate_ok() -> bool:
    now = time.time()
    try:
        recent = [t for t in json.loads(STATE.read_text()).get("acts", []) if now - t < 60]
    except Exception:
        recent = []
    if len(recent) >= MAX_ACTIONS_PER_MIN:
        return False
    try:
        d = json.loads(STATE.read_text())
    except Exception:
        d = {}
    d["acts"] = recent + [now]
    STATE.write_text(json.dumps(d))
    return True


def _keys(combo: str):
    from pynput.keyboard import Key
    names = {"ctrl": Key.ctrl, "control": Key.ctrl, "alt": Key.alt, "shift": Key.shift, "super": Key.cmd, "cmd": Key.cmd, "win": Key.cmd,
             "enter": Key.enter, "return": Key.enter, "tab": Key.tab, "esc": Key.esc, "escape": Key.esc, "backspace": Key.backspace,
             "delete": Key.delete, "space": Key.space, "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
             "home": Key.home, "end": Key.end, "pageup": Key.page_up, "pagedown": Key.page_down, **{f"f{i}": getattr(Key, f"f{i}") for i in range(1, 13)}}
    return [names.get(p.lower(), p) for p in re.split(r"\+", combo) if p]


def act(cmd: str, args: list) -> str:
    """Una acción de entrada. Las coordenadas son de la última captura (píxeles de la imagen)."""
    from pynput.keyboard import Controller as Kb
    from pynput.mouse import Button, Controller as Ms
    ms, kb = Ms(), Kb()
    ox, oy = _origin()
    if cmd in ("click", "move"):
        x, y = int(args[0]) + ox, int(args[1]) + oy
        ms.position = (x, y)
        time.sleep(0.05)
        if cmd == "click":
            btn = Button.right if "--right" in args else Button.left
            ms.click(btn, 2 if "--double" in args else 1)
        return f"{cmd} en ({args[0]}, {args[1]})"
    if cmd == "type":
        text = " ".join(args)
        kb.type(text)
        return f"escrito: {text[:60]}"
    if cmd == "key":
        keys = _keys(args[0])
        for k in keys:
            kb.press(k)
        for k in reversed(keys):
            kb.release(k)
        return f"tecla {args[0]}"
    if cmd == "scroll":
        n = int(args[1]) if len(args) > 1 else 3
        ms.scroll(0, -n if args[0] == "down" else n)
        return f"scroll {args[0]} {n}"
    raise SystemExit(f"Acción desconocida: {cmd}")


def volume(level: int | None = None, delta: int = 0) -> int:
    """Volumen del sistema (0-100). Lo fija en `level` (o lo mueve `delta`) y devuelve el valor REAL leído después: así se verifica lo hecho en vez
    de fiarse de que un comando saliera bien."""
    cur = None
    if sys.platform == "win32":
        deps.ensure({"pycaw": "pycaw"})
        from pycaw.pycaw import AudioUtilities
        ev = AudioUtilities.GetSpeakers().EndpointVolume
        if level is not None or delta:
            cur = round(ev.GetMasterVolumeLevelScalar() * 100)
            ev.SetMasterVolumeLevelScalar(max(0, min(100, level if level is not None else cur + delta)) / 100, None)
            ev.SetMute(0, None)
        return round(ev.GetMasterVolumeLevelScalar() * 100)
    mac = sys.platform == "darwin"

    def run(*a):
        return subprocess.run(a, capture_output=True, text=True).stdout

    def read() -> int:
        if mac:
            return int(run("osascript", "-e", "output volume of (get volume settings)").strip())
        m = re.search(r"(\d+)%", run("pactl", "get-sink-volume", "@DEFAULT_SINK@")) or re.search(r"\[(\d+)%\]", run("amixer", "get", "Master"))
        return int(m.group(1))
    if level is not None or delta:
        n = max(0, min(100, level if level is not None else read() + delta))
        if mac:
            run("osascript", "-e", f"set volume output volume {n}")
        elif run("pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{n}%") == "" and not run("pactl", "info"):
            run("amixer", "set", "Master", f"{n}%")
    return read()


_NUMS = {"cero": 0, "diez": 10, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100,
         "ciento": 100}


def parse_volume(text: str):
    """«volumen al 20%», «sube el volumen», «pon el volumen en cincuenta», «volumen al máximo»…: (nivel, cambio) o None si no es solo eso.
    Frases largas o con varias órdenes («… y abre el navegador») no se tocan: siguen al asistente."""
    t = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
    w = re.findall(r"[a-z]+|\d+", t)
    if "volumen" not in w or len(w) > 9 or "y" in w:
        return None
    n = next((int(x) for x in w if x.isdigit()), next((_NUMS[x] for x in w if x in _NUMS), None))
    if any(x in w for x in ("maximo", "tope")):
        return 100, 0
    if "minimo" in w:
        return 0, 0
    if "mitad" in w:
        return 50, 0
    up, down = bool({"sube", "subir", "aumenta", "aumentar", "mas"} & set(w)), bool({"baja", "bajar", "disminuye", "reduce", "menos"} & set(w))
    if n is not None and not (up or down) or (n is not None and {"a", "al", "en", "hasta"} & set(w)):
        return min(n, 100), 0
    if up or down:
        return None, (n if n is not None else 10) * (1 if up else -1)
    return None


def audio_apps() -> list:
    """Apps que están emitiendo sonido ahora (nombre del proceso). Solo Windows (pycaw, medidor de pico); en otros sistemas, lista vacía."""
    if sys.platform != "win32":
        return []
    try:
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
        names = set()
        for s in AudioUtilities.GetAllSessions():
            if s.Process and s.State == 1 and s._ctl.QueryInterface(IAudioMeterInformation).GetPeakValue() > 0.001:
                names.add(s.Process.name())
        return sorted(names)
    except Exception:  # noqa: BLE001 - sin pycaw o sin dispositivo de audio
        return []


def overview() -> str:
    """Resumen del escritorio para el prompt: ventanas abiertas y apps que suenan (lo que el usuario llama «revisar todo»)."""
    titles = "\n".join(f"- {w['title'][:90]}" for w in winctx.list_windows())
    snd = ", ".join(audio_apps()) or "ninguna detectada"
    return f"[Ventanas abiertas ahora:\n{titles}\nApps con sonido ahora: {snd}]"


def prefix() -> str:
    """Prefijo para invocar este mismo programa desde la terminal (ejecutable empaquetado o `python -m fruquis`); en PowerShell hace falta `&`."""
    call = "& " if sys.platform == "win32" else ""
    if getattr(sys, "frozen", False):
        return f'{call}"{sys.executable}" ctl'
    return f'{call}"{sys.executable}" -m fruquis ctl'


HELP = """Uso: ctl screenshot [--screen|--window "<título>"] | windows | audio | focus "<título>" | click X Y [--right|--double] | move X Y | type "<texto>" | key ctrl+l | scroll down|up [N] (cada una admite --window "<título>") | volume [0-100|+N|-N]"""


def main(argv: list) -> int:
    if not argv:
        print(HELP)
        return 2
    cmd, args = argv[0], argv[1:]
    inputs = cmd in ("click", "move", "type", "key", "scroll", "focus", "volume")
    if not allowed("control" if inputs else "see"):
        print("Desactivado: el usuario no ha permitido " + ("controlar el escritorio" if inputs else "ver la ventana") + " (Ajustes o casillas del chat).")
        return 3
    if inputs and not _rate_ok():
        print(f"Demasiadas acciones por minuto (máximo {MAX_ACTIONS_PER_MIN}). Espera un momento.")
        return 4
    if inputs and cmd != "focus" and "--window" in args:  # actuar sobre otra ventana: se enfoca y X Y pasan a ser de la imagen de `screenshot --window`
        i = args.index("--window")
        frag = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
        title = winctx.focus(frag)
        if not title:
            print("No encontré esa ventana. Mira `windows`.")
            return 1
        time.sleep(0.4)
        w = next((w for w in winctx.list_windows() if w["title"] == title), None)
        if w:
            try:
                d = json.loads(STATE.read_text())
            except Exception:
                d = {}
            STATE.write_text(json.dumps({**d, "origin": [w["x"], w["y"]]}))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:  # lo que se teclea puede llevar acentos o emojis
        f.write(f"{time.strftime('%F %T')} {shlex.join(argv)}\n")
    if cmd == "screenshot" and "--window" in args:  # de una ventana concreta, enfocada o no; no cambia el origen de los clics
        frag = " ".join(a for a in args if a != "--window")
        got = winctx.grab(frag)
        if not got:
            print("No pude capturar esa ventana (no existe, está minimizada o este sistema no lo permite). Mira `windows` y prueba otra parte del título.")
            return 1
        SHOTS.mkdir(parents=True, exist_ok=True)
        path = SHOTS / f"ventana-{int(time.time() * 1000)}.png"
        got[1].save(path)
        print(f"Captura de «{got[0]}»: {path}\nLéela con Read. Para actuar en ella usa --window \"<título>\" en click/type/key/scroll: X Y serán de esta imagen.")
    elif cmd == "screenshot":
        rect = None if "--screen" in args else (winctx.active() or None)
        path, (x, y, w, h) = capture(rect, "screen" if rect is None else "window")
        print(f"Captura: {path}\nOrigen en pantalla: ({x}, {y}) · tamaño {w}x{h}. Léela con la herramienta Read; los clics usan coordenadas de esta imagen.")
    elif cmd == "windows":
        for w in winctx.list_windows():
            print(f"{w['title'][:70]}  ({w['x']},{w['y']} {w['w']}x{w['h']})")
    elif cmd == "audio":
        print(overview())
    elif cmd == "volume":  # volume [0-100 | +N | -N]: sin argumento solo lo lee
        a = args[0] if args else ""
        v = volume(int(a) if a.isdigit() else None, int(a) if a[:1] in "+-" and a[1:].isdigit() else 0)
        print(f"Volumen actual: {v}% (valor leído del sistema tras el cambio)")
    elif cmd == "focus":
        t = winctx.focus(" ".join(args))
        print(f"Enfocada: {t}" if t else "No encontré esa ventana.")
        time.sleep(0.4)
    else:
        print(act(cmd, args))
    return 0
