"""Ver y controlar el escritorio: capturas de pantalla / de la ventana activa, y ratón + teclado (pynput). El chat lo usa a través de
`python -m fruquis ctl …` (Bash). Todo está protegido por los ajustes: «Ver ventana» permite capturas y «Controlar» permite actuar."""
import json
import re
import shlex
import sys
import time
from pathlib import Path

from . import store, winctx

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


def prefix() -> str:
    """Prefijo para invocar este mismo programa desde Bash (ejecutable empaquetado o `python -m fruquis`)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" ctl'
    return f'"{sys.executable}" -m fruquis ctl'


HELP = """Uso: ctl screenshot [--screen] | windows | focus "<título>" | click X Y [--right|--double] | move X Y | type "<texto>" | key ctrl+l | scroll down|up [N]"""


def main(argv: list) -> int:
    if not argv:
        print(HELP)
        return 2
    cmd, args = argv[0], argv[1:]
    inputs = cmd in ("click", "move", "type", "key", "scroll", "focus")
    if not allowed("control" if inputs else "see"):
        print("Desactivado: el usuario no ha permitido " + ("controlar el escritorio" if inputs else "ver la ventana") + " (Ajustes o casillas del chat).")
        return 3
    if inputs and not _rate_ok():
        print(f"Demasiadas acciones por minuto (máximo {MAX_ACTIONS_PER_MIN}). Espera un momento.")
        return 4
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"{time.strftime('%F %T')} {shlex.join(argv)}\n")
    if cmd == "screenshot":
        rect = None if "--screen" in args else (winctx.active() or None)
        path, (x, y, w, h) = capture(rect, "screen" if rect is None else "window")
        print(f"Captura: {path}\nOrigen en pantalla: ({x}, {y}) · tamaño {w}x{h}. Léela con la herramienta Read; los clics usan coordenadas de esta imagen.")
    elif cmd == "windows":
        for w in winctx.list_windows():
            print(f"{w['title'][:70]}  ({w['x']},{w['y']} {w['w']}x{w['h']})")
    elif cmd == "focus":
        t = winctx.focus(" ".join(args))
        print(f"Enfocada: {t}" if t else "No encontré esa ventana.")
        time.sleep(0.4)
    else:
        print(act(cmd, args))
    return 0
