"""Mascota estilo shimeji: ventana transparente siempre encima. Camina, trepa y se cuelga por los bordes de la pantalla y de la
ventana activa, se deja arrastrar, cuidar (tamagotchi) y conversar."""
import math
import random
import threading
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMenu, QMessageBox, QPushButton, QWidget

from . import chat, sprites, store, theme, winctx
from .care import ACTIONS, Care

SPEED = 100  # px/s sobre un borde
GRAVITY = 1800
KIND_SAY = {"browser": "¡Veo tu navegador!", "terminal": "La terminal… ¿qué ejecutamos?", "editor": "Ahí se escribe código."}
DO_ANIM = {"comer": "eating", "limpiar": "cleaning", "jugar": "playing", "dormir": "sleeping", "mimar": "pampered"}


class Bridge(QObject):
    reply = Signal(str, str)  # (destino, texto)


class Seg:
    """Un borde por el que camina: de a a b; `rot` gira el sprite para que sus pies miren al borde; `n` sale hacia el aire."""

    def __init__(self, a, b, rot, n, kind):
        self.a, self.b, self.rot, self.n, self.kind = QPointF(*a), QPointF(*b), rot, n, kind
        self.len = math.hypot(b[0] - a[0], b[1] - a[1])
        self.d = ((b[0] - a[0]) / self.len, (b[1] - a[1]) / self.len)
        r = math.radians(rot)
        self.local = 1 if self.d[0] * math.cos(r) + self.d[1] * math.sin(r) > 0 else -1  # +1: ir de a a b es "hacia la derecha" del sprite


class Track:
    def __init__(self, segs, closed, win_id=None):
        self.segs, self.closed, self.win_id = segs, closed, win_id

    def top(self):
        return next((i for i, s in enumerate(self.segs) if s.kind == "win-top"), None)


def screen_track(r: QRect) -> Track:
    l, t, rr, b = r.left(), r.top(), r.right() + 1, r.bottom() + 1
    return Track([Seg((l, b), (rr, b), 0, (0, -1), "floor"), Seg((rr, b), (rr, t), -90, (-1, 0), "wall"),
                  Seg((rr, t), (l, t), 180, (0, 1), "ceil"), Seg((l, t), (l, b), 90, (1, 0), "wall")], True)


def window_track(w: dict, scr: QRect, d: float) -> Track | None:
    """Circuito por fuera de la ventana: sube por su borde izquierdo, camina por arriba y baja por el derecho. None si no cabe arriba."""
    x, y, ww, hh = w["x"], w["y"], w["w"], w["h"]
    if ww < d or y - d * 0.9 < scr.top() or x + ww < scr.left() + d or x > scr.right() - d:
        return None
    segs = []
    if x - d * 0.6 >= scr.left():
        segs.append(Seg((x, y + hh), (x, y), -90, (-1, 0), "win-side"))
    segs.append(Seg((x, y), (x + ww, y), 0, (0, -1), "win-top"))
    if x + ww + d * 0.6 <= scr.right():
        segs.append(Seg((x + ww, y), (x + ww, y + hh), 90, (1, 0), "win-side"))
    return Track(segs, False, w["id"])


class Bubble(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(260)
        self.label.setStyleSheet("background:#fffbe9;color:#2b2140;border:2px solid #8a7bd6;border-radius:10px;padding:6px 9px;font-size:13px")
        self.timer = QTimer(self, singleShot=True, timeout=self.hide)

    def say(self, text: str, anchor: QRect, ms: int = 6000):
        self.label.setText(text)
        self.label.adjustSize()
        self.resize(self.label.size())
        scr = (QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()).availableGeometry()
        x = min(max(anchor.center().x() - self.width() // 2, scr.left()), scr.right() - self.width())
        y = anchor.top() - self.height() - 4
        self.move(x, y if y >= scr.top() else anchor.bottom() + 4)
        self.show()
        self.timer.start(ms)


class Pet(QWidget):
    def __init__(self, char: sprites.Character, scale: float, bridge: Bridge):
        # Sin foco: pulsar a la mascota no debe activar ni traer al frente la ventana de la interfaz
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.bridge, self.scale, self.bubble = bridge, scale, Bubble()
        self.ui: dict = {}  # callbacks de la interfaz: chat, care, chars
        self.state, self.until, self.vy = "idle", 0.0, 0.0
        self.anim, self.fi, self.acc, self.last = "", 0, 0.0, time.monotonic()
        self.press, self.dragging, self.hold = None, False, QPoint()
        self.ctx, self.ctx_kind, self.win, self.say_at = None, "otro", None, {}
        self.active_at, self.hop_at, self.low_at, self.save_at = time.monotonic(), 0.0, 0.0, time.monotonic()
        self.dir, self.mirror, self.hop, self.last_id = 1, False, None, None
        self.vx, self.samples, self.pamper_until = 0.0, [], 0.0
        self.load_character(char)
        self.wave()
        QTimer(self, interval=33, timeout=self.tick).start()
        QTimer(self, interval=1500, timeout=self.poll).start()

    # ---- personaje ----
    def load_character(self, c: sprites.Character):
        self.char, self.have = c, c.anims
        self.w, self.h = int(c.cell[0] * self.scale), int(c.cell[1] * self.scale)
        self.D = max(self.w, self.h)
        self.resize(self.D, self.D)
        self.frames = {n: self._cut(n) for n in self.have}
        self.care = Care(store.HOME / "care" / f"{c.id}.json")
        self.scr = (QApplication.screenAt(self.pos()) or QApplication.primaryScreen()).availableGeometry()
        self.screen_t, self.win = screen_track(self.scr), None
        self.attach("screen", 0, min(self.scr.width() * 0.7, self.scr.width() - self.D), 1)
        self.anim = ""
        store.put("active", c.id)

    def refresh_character(self, c: sprites.Character):
        """Recarga animaciones tras agregar, reemplazar o borrar, sin mover a la mascota."""
        self.char, self.have = c, c.anims
        self.frames = {n: self._cut(n) for n in self.have}
        if self.anim not in self.have:
            self.anim = ""
            self.play("idle")

    def _cut(self, name: str) -> list:
        a, (cw, ch) = self.have[name], self.char.cell
        pm = QPixmap(str(a["sheet"]))
        cols = max(1, pm.width() // cw)
        return [pm.copy((i % cols) * cw, (a["row"] + i // cols) * ch, cw, ch).scaled(self.w, self.h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                for i in range(a["frames"])]

    def play(self, name: str):
        name = sprites.fallback(self.have, name) or next(iter(self.have), "")
        if name != self.anim:
            self.anim, self.fi, self.acc = name, 0, 0.0

    def paintEvent(self, _):
        fr = self.frames.get(self.anim)
        if not fr:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.translate(self.D / 2, self.D / 2)
        p.rotate(self.seg.rot if self.attached else 0)
        if self.mirror:
            p.scale(-1, 1)
        if time.monotonic() < self.pamper_until:  # mimos: se aprieta y estira como si la acariciaran
            k = math.sin(time.monotonic() * 9) * 0.035
            p.scale(1 + k, 1 - k)
        a = self.have[self.anim]
        i = self.fi
        if a.get("pingpong") and a["frames"] > 1 and i >= a["frames"]:
            i = 2 * a["frames"] - 2 - i
        p.drawPixmap(-self.w // 2, -self.h // 2, fr[max(0, min(i, len(fr) - 1))])

    # ---- sobre los bordes ----
    @property
    def attached(self) -> bool:
        return self.state not in ("drag", "fall", "hop")

    def track(self) -> Track:
        return self.screen_t if self.at[0] == "screen" else self.win

    @property
    def seg(self) -> Seg:
        return self.track().segs[self.at[1]]

    def attach(self, which: str, i: int, s: float, direction: int):
        self.at, self.s, self.dir = (which, i), s, direction
        self.state = "idle"

    def center(self) -> QPointF:
        sg = self.seg
        p = sg.a + QPointF(sg.d[0], sg.d[1]) * self.s
        return p + QPointF(*sg.n) * (self.h / 2)

    def place(self):
        c = self.center() if self.attached else self.c
        self.c = c
        self.move(int(c.x() - self.D / 2), int(c.y() - self.D / 2))

    def advance_along(self, dt: float):
        tr, i = self.track(), self.at[1]
        self.s += self.dir * SPEED * dt
        sg = tr.segs[i]
        if 0 <= self.s <= sg.len:
            return
        forward = self.s > sg.len
        j = i + (1 if forward else -1)
        if tr.closed:
            j %= len(tr.segs)
        elif not 0 <= j < len(tr.segs):
            self.fall_from()  # el borde se acabó
            return
        over = self.s - sg.len if forward else -self.s
        nxt = tr.segs[j]
        if random.random() < (0.45 if tr.closed else 0.3):  # a veces da media vuelta en vez de doblar la esquina
            self.s, self.dir = (sg.len - 1 if forward else 1), -self.dir
            return
        self.at, self.s = (self.at[0], j), (min(over, nxt.len) if forward else max(0.0, nxt.len - over))
        self.dir = 1 if forward else -1

    def fall_from(self):
        c = self.center()
        self.c, self.vy, self.state, self.mirror = c, 0.0, "fall", False

    # ---- bucle ----
    def tick(self):
        now = time.monotonic()
        dt, self.last = min(now - self.last, 0.1), now
        a = self.have.get(self.anim)
        if a:
            self.acc += dt * a["fps"]
            if self.acc >= 1:
                step, self.acc = int(self.acc), self.acc % 1
                n = a["frames"]
                if a.get("pingpong") and n > 1:
                    self.fi = (self.fi + step) % (2 * n - 2)
                else:
                    self.fi = (self.fi + step) % n if a["loop"] else min(self.fi + step, n - 1)
        self.care.advance(dt)
        if now - self.save_at > 60:
            self.save_at = now
            self.care.save()
            if (w := self.care.worst()) and now - self.low_at > 300:
                self.low_at = now
                self.say({"hambre": "Tengo hambre… 🍙", "limpieza": "Necesito un baño 🫧", "diversion": "Estoy aburrida 🎾", "energia": "Tengo sueño 💤"}[w[0]])
        st = self.state
        if st == "drag":
            self.play("dragged")
        elif st == "fall":
            self.mirror = False
            self.play("falling")
            self.vy += GRAVITY * dt
            self.vx *= max(0.0, 1 - 0.5 * dt)  # rozamiento con el aire
            prev = self.c.y() + self.h / 2
            self.c = QPointF(self.c.x() + self.vx * dt, self.c.y() + self.vy * dt)
            if not self.grab_edge(now):
                self.land(prev, self.c.y() + self.h / 2)
        elif st == "hop":
            self.hop_step(now)
        elif st == "walk":
            self.advance_along(dt)
            if self.state == "walk":
                self.face()
                if now >= self.until:
                    self.state, self.until = "idle", now + random.uniform(2, 6)
        elif st in ("once", "sleep"):
            if now >= self.until:
                self.state, self.until = "idle", now + random.uniform(2, 6)
        elif st == "idle":
            self.think(now)
        self.place()
        self.update()

    def face(self):
        """Animación de caminar según el sentido local; en paredes y techo usa 'climbing' (espejada) o el correr rotado."""
        sg = self.seg
        local = self.dir * sg.local
        if sg.rot != 0 and "climbing" in self.have:
            self.play("climbing")
            self.mirror = local < 0
        else:
            self.play("running-right" if local > 0 else "running-left")
            self.mirror = False

    def think(self, now: float):
        sg = self.seg
        pos = QCursor.pos()
        c = self.c
        if "look" in self.have and math.hypot(pos.x() - c.x(), pos.y() - c.y()) < 500 and sg.rot == 0:
            ang = (math.degrees(math.atan2(pos.x() - c.x(), -(pos.y() - c.y()))) % 360 + _look_offset()) % 360
            self.anim, self.fi, self.mirror = "look", round(ang / 22.5) % 16, False
        else:
            self.play("sitting" if sg.kind == "win-top" else "idle")
            self.mirror = False
        if now < self.until:
            return
        self.until = now + random.uniform(2, 6)
        if sg.rot != 0 and random.random() < 0.12:  # se suelta de la pared o del techo
            self.fall_from()
        elif self.care.s["energia"] < 25 or now - self.active_at > 180:
            self.rest(25)
        else:
            r = random.random()
            if r < 0.6:
                self.dir = random.choice((-1, 1))
                self.state, self.until = "walk", now + random.uniform(2, 7)
            elif r < 0.75:
                self.state, self.until = "once", now + 3
                self.play("playing")
            else:
                self.play("waiting")

    def rest(self, secs: float):
        self.state, self.until, self.mirror = "sleep", time.monotonic() + secs, False
        self.play("sleeping")
        self.care.s["energia"] = min(100, self.care.s["energia"] + secs)

    def land(self, prev: float, foot: float):
        x = self.c.x()
        d = 1 if self.vx >= 0 else -1
        if self.win and (i := self.win.top()) is not None:
            sg = self.win.segs[i]
            if prev <= sg.a.y() <= foot and sg.a.x() <= x <= sg.b.x():
                self.attach("win", i, x - sg.a.x(), d)
                return self.slide()
        sc = (QApplication.screenAt(QPoint(int(x), int(self.c.y()))) or QApplication.primaryScreen()).availableGeometry()
        if foot >= sc.bottom() + 1:
            self.scr, self.screen_t = sc, screen_track(sc)
            self.attach("screen", 0, max(0.0, min(x - self.scr.left(), self.scr.width())), d)
            self.slide()

    def grab_edge(self, now: float) -> bool:
        """Lanzada contra una pared o el techo de la pantalla: se agarra y sigue trepando en la dirección del tiro."""
        c = self.c
        sc = (QApplication.screenAt(QPoint(int(c.x()), int(c.y()))) or QApplication.primaryScreen()).availableGeometry()
        l, t, r, b = sc.left(), sc.top(), sc.right() + 1, sc.bottom() + 1
        if c.y() - self.h / 2 <= t and self.vy < 0:
            i, s, d = 2, r - c.x(), 1 if self.vx <= 0 else -1  # el techo avanza hacia la izquierda: d=+1
        elif c.x() + self.w / 2 >= r and self.vx > 0:
            i, s, d = 1, b - c.y(), 1 if self.vy <= 0 else -1  # pared derecha: +1 sube
        elif c.x() - self.w / 2 <= l and self.vx < 0:
            i, s, d = 3, c.y() - t, -1 if self.vy <= 0 else 1  # pared izquierda: -1 sube
        else:
            return False
        self.scr, self.screen_t = sc, screen_track(sc)
        n = self.screen_t.segs[i].len
        self.attach("screen", i, max(0.0, min(s, n)), d)
        self.state, self.until = "walk", now + 1.5
        self.vx = self.vy = 0.0
        return True

    def touch(self):
        self.state, self.until = "once", time.monotonic() + 0.8
        self.play("jumping")

    def slide(self):
        """Al aterrizar con velocidad horizontal sigue corriendo un poco en esa dirección."""
        if abs(self.vx) > 120:
            self.state, self.until = "walk", time.monotonic() + min(2.0, abs(self.vx) / 700)
        else:
            self.touch()
        self.vx = 0.0

    def hop_step(self, now: float):
        if self.win is None:  # la ventana dejó de ser la activa en pleno salto
            return self.fall_from()
        t0, t1, a, b = self.hop
        t = min(1.0, (now - t0) / (t1 - t0))
        self.c = QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t - 90 * 4 * t * (1 - t))
        self.mirror = False
        self.play("jumping")
        if t >= 1.0:
            sg = self.win.segs[self.win.top()]
            self.attach("win", self.win.top(), max(0.0, min(b.x() - sg.a.x(), sg.len)), self.dir)
            self.state, self.until = "once", now + 2.5
            self.play("typing" if self.ctx_kind == "terminal" else "poking")

    # ---- ventana activa ----
    def poll(self):
        c = winctx.active()
        if c and ("fruquis" in c["cls"].lower() or c["title"].startswith("Fruquis") or "python" in c["cls"].lower()):
            return
        self.ctx, kind = c, winctx.kind(c)
        now = time.monotonic()
        if self.win:  # lo que pisa ya no es la ventana activa: se refresca o se cae
            if c and c["id"] == self.win.win_id:
                self.refresh_win(c)
            elif self.at[0] == "win" and self.attached:
                self.fall_from()
                self.win = None
            else:
                self.win = None
        if c and (self.win is None) and self.attached and self.at[0] == "screen" and self.state in ("idle", "walk", "once") \
                and now - self.hop_at > 8 and (c["id"] != getattr(self, "last_id", None) or kind != self.ctx_kind):
            self.last_id, self.hop_at = c["id"], now
            sc = (QApplication.screenAt(QPoint(c["x"] + c["w"] // 2, c["y"] + 40)) or QApplication.primaryScreen()).availableGeometry()
            tr = window_track(c, sc, self.D)
            if tr is not None and tr.top() is not None:
                self.win, self.scr, self.ctx_kind = tr, sc, kind
                top = tr.segs[tr.top()]
                tx = top.a.x() + random.uniform(0.15, 0.85) * top.len
                self.hop_at = now
                self.hop = (now, now + 0.9, QPointF(self.c), QPointF(tx, top.a.y() - self.h / 2))
                self.state = "hop"
                if kind in KIND_SAY and now - self.say_at.get(kind, 0) > 40:
                    self.say_at[kind] = now
                    self.say(KIND_SAY[kind])
        self.ctx_kind = kind

    def refresh_win(self, c: dict):
        tr = window_track(c, self.scr, self.D)
        if tr is None or tr.top() is None:
            if self.at[0] == "win" and self.attached:
                self.fall_from()
            self.win = None
            return
        same = self.win is not None and len(tr.segs) == len(self.win.segs)
        j = self.at[1] if same else tr.top()  # si cambió la forma (ya no cabe un lado), vuelve a la cima
        self.win = tr
        if self.at[0] == "win":
            self.at, self.s = ("win", j), min(self.s, tr.segs[j].len)

    # ---- ratón ----
    def mousePressEvent(self, e):
        self.press, self.dragging, self.hold = e.globalPosition().toPoint(), False, e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self.press is None:
            return
        g = e.globalPosition().toPoint()
        if not self.dragging and (g - self.press).manhattanLength() > 5:
            self.dragging, self.state = True, "drag"
        if self.dragging:
            self.c = QPointF(g.x() - self.hold.x() + self.D / 2, g.y() - self.hold.y() + self.D / 2)
            self.samples = (self.samples + [(time.monotonic(), g.x(), g.y())])[-8:]

    def mouseReleaseEvent(self, e):
        self.active_at = time.monotonic()
        if self.dragging:
            self.state, self.vx, self.vy = "fall", *self.throw_velocity()
        else:
            self.menu(e.globalPosition().toPoint())
        self.press = None

    def throw_velocity(self):
        """Velocidad (px/s) del puntero en los últimos 120 ms antes de soltar; 0 si la mano ya estaba quieta."""
        now = time.monotonic()
        pts = [q for q in self.samples if now - q[0] < 0.12]
        self.samples = []
        if len(pts) < 2 or now - pts[-1][0] > 0.08:
            return 0.0, 0.0
        dt = max(pts[-1][0] - pts[0][0], 0.016)
        cap = lambda v: max(-3200.0, min(3200.0, v))
        return cap((pts[-1][1] - pts[0][1]) / dt), cap((pts[-1][2] - pts[0][2]) / dt)

    def menu(self, at: QPoint):
        m = QMenu(self)
        for label, fn in (("Estado", self.status), ("Ideas", self.ideas), ("Mimar", lambda: self.do("mimar"))):
            m.addAction(QAction(label, m, triggered=fn))
        sub = m.addMenu("Animación")
        for name in sorted(self.have):
            if name != sprites.LOOK:
                sub.addAction(QAction(name, sub, triggered=lambda _=False, n=name: self.preview(n)))
        for label, fn in (("Chat", self.ui.get("chat")), ("Cuidar", self.ui.get("care")), ("Personajes…", self.ui.get("chars")),
                          ("Saludar", self.wave), ("Salir", QApplication.quit)):
            m.addAction(QAction(label, m, triggered=fn or (lambda: None)))
        m.exec(at)

    def preview(self, name: str, secs: float | None = None):
        """Reproduce una animación del personaje un rato (menú Animación y catálogo)."""
        a = self.have.get(name)
        if not a:
            return
        if self.attached and self.seg.rot != 0:  # prueba de pie: se suelta
            self.fall_from()
        self.state, self.mirror = "once", False
        self.until = time.monotonic() + (secs or max(2.5, 2 * a["frames"] / a["fps"]))
        self.anim, self.fi, self.acc = name, 0, 0.0

    def say(self, text: str, ms: int = 6000):
        self.bubble.say(text, self.geometry(), ms)

    def wave(self):
        self.state, self.until = "once", time.monotonic() + 2
        self.play("waving")
        self.say("¡Hola! Soy " + self.char.name + ".")

    def talk(self, secs: float = 1.5):
        self.state, self.until = "once", time.monotonic() + secs
        self.play("talking")

    def do(self, action: str):
        """Acción del tamagotchi: aplica el efecto, anima y habla."""
        text = self.care.act(action)
        self.active_at = time.monotonic()
        if action == "dormir":
            self.rest(15)
        elif action == "mimar":
            self.pamper_until = time.monotonic() + 5
            self.state, self.until, self.mirror = "once", self.pamper_until, False
            self.play("pampered")
        else:
            self.state, self.until, self.mirror = "once", time.monotonic() + 3.5, False
            self.play(DO_ANIM[action])
        self.say(text)

    def status(self):
        c = self.ctx
        win = f"{c['title'][:50]} ({self.ctx_kind})" if c else "ninguna"
        self.talk()
        self.say(f"Ventana: {win}\nCPU {psutil.cpu_percent()}% · RAM {psutil.virtual_memory().percent}%\n"
                 f"Animaciones: {len(self.have)} · claude: {'sí' if chat.claude_bin() else 'no'}", 9000)

    def ideas(self):
        c = self.ctx
        self.say("Pensando…", 30000)
        self.talk(3)
        prompt = (f"El usuario tiene abierta la ventana '{c['title'][:80]}' ({c['cls']}, tipo {self.ctx_kind}). "
                  if c else "No sé qué ventana tiene abierta el usuario. ") + "Dame 3 ideas muy cortas y útiles de qué hacer ahora."
        self.ask_async(prompt, "bubble")

    def ask_async(self, prompt: str, dest: str, **opts):
        """Pregunta en un hilo; el resultado vuelve por bridge.reply. Solo el chat (dest='chat') puede ejecutar comandos, si el usuario lo permite."""
        opts.setdefault("tools", False)
        opts.setdefault("persona", (self.char.name, self.char.description))
        threading.Thread(target=lambda: self.bridge.reply.emit(dest, chat.ask(prompt, track=dest == "chat", **opts)), daemon=True).start()


def _look_offset() -> float:
    import os
    return float(os.environ.get("FRUQUIS_LOOK_OFFSET", "0"))


class FloatButton(QPushButton):
    """Botón 💬 que se arrastra a cualquier parte; recuerda dónde lo dejaste."""

    def __init__(self, on_click):
        super().__init__("💬")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(46, 46)
        self.setCursor(Qt.OpenHandCursor)
        self.setStyleSheet("QPushButton{background:#6b4fbb;color:white;border-radius:23px;font-size:20px}QPushButton:hover{background:#8a6ae0}")
        self.on_click, self.press, self.off = on_click, None, QPoint()
        saved = store.get("button")
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(*(saved if saved else (scr.right() - 62, scr.bottom() - 62)))
        self.clamp()

    def clamp(self):
        scr = (QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()).availableGeometry()
        self.move(max(scr.left(), min(self.x(), scr.right() - self.width())), max(scr.top(), min(self.y(), scr.bottom() - self.height())))

    def mousePressEvent(self, e):
        self.press, self.off, self.moved = e.globalPosition().toPoint(), e.position().toPoint(), False

    def mouseMoveEvent(self, e):
        if self.press is None:
            return
        g = e.globalPosition().toPoint()
        if (g - self.press).manhattanLength() > 5:
            self.moved = True
        if self.moved:
            self.move(g - self.off)

    def mouseReleaseEvent(self, e):
        if self.moved:
            self.clamp()
            store.put("button", [self.x(), self.y()])
        else:
            self.on_click()
        self.press = None


def run(scale: float = 0.6):
    from .chatui import ChatView
    from .shell import MainWindow
    from .ui import CareView, CatalogView, CharactersView, NewCharView, PromptView, ReviewView

    app = QApplication([])
    theme.apply(app)
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge()
    if not sprites.list_all():  # instalación nueva: los personajes no vienen en el repositorio
        path, _ = QFileDialog.getOpenFileName(None, "Fruquis: importa un personaje (.zip)", "", "Personaje (*.zip)")
        try:
            if not path:
                raise SystemExit("Fruquis necesita al menos un personaje. Impórtalo con ./run.sh import personaje.zip")
            sprites.import_character(path)
        except SystemExit as e:
            QMessageBox.warning(None, "Fruquis", str(e))
            return
    pet = Pet(sprites.get(store.get("active", "")), scale, bridge)
    shell = MainWindow(pet)
    for name, view in (("chat", ChatView(shell, bridge)), ("care", CareView(shell)), ("chars", CharactersView(shell)), ("catalog", CatalogView(shell)),
                       ("prompt", PromptView(shell)), ("review", ReviewView(shell)), ("newchar", NewCharView(shell))):
        shell.add_view(name, view)

    def toggle_chat():
        if shell.current() == "chat":
            shell.hide()
        else:
            shell.open("chat", near=btn)
    btn = FloatButton(toggle_chat)
    pet.ui = {"chat": lambda: shell.open("chat"), "care": lambda: shell.open("care"), "chars": lambda: shell.open("chars")}
    app.aboutToQuit.connect(pet.care.save)
    btn.show()
    pet.show()
    app.exec()
