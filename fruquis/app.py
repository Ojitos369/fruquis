"""Mascota estilo shimeji: ventana transparente siempre encima. Camina, trepa y se cuelga por los bordes de la pantalla y de la
ventana activa, se deja arrastrar, cuidar (tamagotchi) y conversar."""
import math
import os
import random
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMenu, QMessageBox, QPushButton, QWidget

from . import chat, machine, sprites, store, theme, winctx
from .care import ACTIONS, Care
from .voice import log

SPEED = 100  # px/s sobre un borde
GRAVITY = 1800
KIND_SAY = {"browser": "¡Veo tu navegador!", "terminal": "La terminal… ¿qué ejecutamos?", "editor": "Ahí se escribe código."}
DO_ANIM = {"comer": "eating", "limpiar": "cleaning", "jugar": "playing", "dormir": "sleeping", "mimar": "pampered"}


def clip(text: str, n: int = 220) -> str:
    """Recorta un texto markdown para la burbuja sin dejar marcas abiertas (**, `) que se verían como asteriscos sueltos."""
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(" ,;:.\n")
    for mark in ("**", "`"):
        if cut.count(mark) % 2:
            cut += mark
    return cut + "…"


BUSY_TEXT = {"thinking": "💭 Pensando…", "searching": "🔎 Buscando en internet…","reading": "👀 Mirando…", "working": "⚙️ Trabajando…", "writing": "✍️ Escribiendo…"}
WALL_ANIMS = ("climbing", "clinging")  # se dibujan de pie con la pared a su izquierda (no como si estuvieran en el piso)
BUSY_ANIM = {"thinking": "review", "reading": "reading", "searching": "reading", "working": "typing", "writing": "typing"}  # fase de la IA → animación


class Bridge(QObject):
    reply = Signal(str, str)  # (destino, texto)
    phase = Signal(str)       # thinking / reading / working / writing mientras responde


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


TAIL = 11  # alto de la flechita del globo


class Bubble(QWidget):
    """Globo de diálogo con flechita que apunta a la mascota (abajo si el globo queda encima de ella, arriba si queda debajo)."""
    FILL, EDGE = QColor("#fffbe9"), QColor("#8a7bd6")

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.MarkdownText)  # las respuestas llegan en markdown: negritas, listas, código…
        self.label.setOpenExternalLinks(True)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(280)
        self.label.setStyleSheet("background:transparent;color:#2b2140;padding:8px 12px;font-size:13px")
        self.timer = QTimer(self, singleShot=True, timeout=self.hide)
        self.above, self.tail_x, self.thought = True, 20, False

    def say(self, text: str, anchor: QRect, ms: int = 6000, thought: bool = False):
        self.thought = thought  # globo de pensamiento: nube con burbujitas en vez de flechita
        self.label.setText(text)
        self.label.adjustSize()
        bw, bh = self.label.width(), self.label.height()
        self.resize(bw, bh + TAIL)
        scr = (QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()).availableGeometry()
        x = min(max(anchor.center().x() - bw // 2, scr.left()), scr.right() - bw)
        y = anchor.top() - self.height() - 2
        self.above = y >= scr.top()  # si no cabe encima, va debajo con la flecha hacia arriba
        if not self.above:
            y = anchor.bottom() + 2
        self.label.move(0, 0 if self.above else TAIL)
        self.tail_x = max(18, min(anchor.center().x() - x, bw - 18))  # la punta señala el centro de la mascota
        self.move(x, y)
        self.update()
        self.show()
        self.timer.start(ms)

    def paintEvent(self, _):
        bw, bh = self.label.width(), self.label.height()
        top = 0 if self.above else TAIL
        body = QRectF(1.5, top + 1.5, bw - 3, bh - 3)
        path = QPainterPath()
        tx = self.tail_x
        if self.thought:  # nube redondeada y dos burbujitas que bajan (o suben) hacia la mascota
            path.addRoundedRect(body, min(bh, 40) / 2, min(bh, 40) / 2)
            s = 1 if self.above else -1
            y0 = body.bottom() if self.above else body.top()
            for dy, r in ((4, 4.0), (9.5, 2.5)):
                path.addEllipse(QPointF(tx, y0 + s * dy), r, r)
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(self.FILL)
            p.setPen(QPen(self.EDGE, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
            return
        path.addRoundedRect(body, 12, 12)
        if self.above:
            tri = QPolygonF([QPointF(tx - 9, body.bottom() - 1), QPointF(tx + 9, body.bottom() - 1), QPointF(tx, body.bottom() + TAIL - 2)])
        else:
            tri = QPolygonF([QPointF(tx - 9, body.top() + 1), QPointF(tx + 9, body.top() + 1), QPointF(tx, body.top() - TAIL + 2)])
        tail = QPainterPath()
        tail.addPolygon(tri)
        tail.closeSubpath()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self.FILL)
        p.setPen(QPen(self.EDGE, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path.united(tail))  # el contorno de la unión no marca la base de la flecha: se ve un solo globo


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
        self.after_land = None  # acción pedida en pared o techo: se suelta y la hace al aterrizar
        self.hop_off = 0.0  # altura (px) del salto real mientras suena la animación «jumping»
        self.keep_free = store.get("keep_free")  # {"side": derecha|izquierda, "frac": 0.35}: espacio del piso que se le pidió dejar libre
        self.busy_phase, self.think_on, self.followers = None, False, []  # mientras la IA responde la mascota se queda quieta y muestra lo que hace
        bridge.phase.connect(self.on_phase)
        bridge.reply.connect(self.on_reply)
        self.load_character(char)
        self.wave()
        QTimer(self, interval=33, timeout=self.tick).start()
        QTimer(self, interval=1500, timeout=self.poll).start()

    # ---- personaje ----
    def load_character(self, c: sprites.Character, remember: bool = False):
        """Carga un personaje. `remember` lo guarda como el activo (solo cuando el usuario lo elige; al arrancar no se sobrescribe)."""
        self.char, self.have = c, c.anims
        self.w, self.h = int(c.cell[0] * self.scale), int(c.cell[1] * self.scale)
        self.D = max(self.w, self.h)
        self.resize(self.D, self.D)
        self.frames = {n: self._cut(n) for n in self.have}
        self.care = Care(store.HOME / "care" / f"{c.id}.json")
        self.scr = (QApplication.screenAt(self.pos()) or QApplication.primaryScreen()).availableGeometry()
        self.screen_t, self.win = screen_track(self.scr), None
        frac = self.c.x() / self.scr.width() if hasattr(self, "c") else store.get("pos", 0.7)  # al cambiar de personaje se queda donde estaba
        self.attach("screen", 0, max(0.0, min(frac * self.scr.width(), self.scr.width() - self.D)), 1)
        self.anim = ""
        if remember:
            store.put("active", c.id)

    def set_scale(self, scale: float):
        """Cambia el tamaño de la mascota al instante (se conserva el personaje y su posición)."""
        self.care.save()
        self.scale = scale
        self.load_character(self.char)

    def save_pos(self):
        if hasattr(self, "c") and self.scr.width():
            store.put("pos", round(max(0.0, min(1.0, (self.c.x() - self.scr.left()) / self.scr.width())), 4))

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
        # borra el cuadro anterior: sin esto los píxeles semitransparentes se iban acumulando y quedaba un rastro de cuadros viejos
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.translate(self.D / 2, self.D / 2)
        sg = self.seg
        if self.attached and sg.rot != 0 and self.anim in WALL_ANIMS:
            # −x local → hacia la pared (x local → al aire, n), cabeza (−y local) → hacia donde avanza: sube, baja o cruza el techo de frente
            w, t = sg.n, (self.dir * sg.d[0], self.dir * sg.d[1])
            if self.anim == "clinging" and abs(sg.rot) == 90:  # quieta en la pared: de pie, sin voltearse de cabeza
                t = (0, -1)
            p.setTransform(QTransform(w[0], w[1], -t[0], -t[1], 0, 0), True)
        else:
            p.rotate(sg.rot if self.attached else 0)
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
        return p + QPointF(*sg.n) * (self.h / 2 + self.hop_off)

    def place(self):
        c = self.center() if self.attached else self.c
        self.c = c
        # setGeometry y no move: al cruzar pantallas con distinta escala (DPI) Qt reescala la ventana y la dejaba recortada
        self.setGeometry(int(c.x() - self.D / 2), int(c.y() - self.D / 2), self.D, self.D)

    def free_range(self, width: float) -> tuple[float, float]:
        """Tramo del piso donde puede andar, sin el espacio que se le pidió dejar libre."""
        f = self.keep_free
        if not f:
            return 0.0, width
        return (0.0, width * (1 - f["frac"])) if f["side"] == "derecha" else (width * f["frac"], width)

    def move_to(self, side: str | None = None, mon=None) -> str:
        """Orden de voz: se coloca en el piso a la izquierda/derecha/centro (o arriba, en el techo) y/o en otro monitor ('next', 'prev' o número)."""
        screens = QApplication.screens()
        ctr = self.center() if self.attached else self.c
        cur = QApplication.screenAt(QPoint(int(ctr.x()), int(ctr.y()))) or QApplication.primaryScreen()
        if mon is not None:
            i = screens.index(cur) if cur in screens else 0
            j = (i + 1) % len(screens) if mon == "next" else (i - 1) % len(screens) if mon == "prev" else mon
            if len(screens) < 2 and mon in ("next", "prev"):
                return "Solo tengo un monitor 😅"
            if not 0 <= j < len(screens):
                return f"Solo veo {len(screens)} monitor(es)"
            cur = screens[j]
        sc = cur.availableGeometry()
        keep = (ctr.x() - self.scr.left()) / max(1, self.scr.width())  # sin lado: conserva su posición relativa en el monitor nuevo
        frac = {"izquierda": 0.06, "derecha": 0.94, "centro": 0.5, "arriba": keep}.get(side, keep)
        self.win, self.scr, self.screen_t = None, sc, screen_track(sc)
        if side == "arriba":  # el techo avanza de derecha a izquierda
            self.attach("screen", 2, sc.width() * (1 - frac), 1)
        else:
            lo, hi = self.free_range(sc.width())
            self.attach("screen", 0, min(max(frac * sc.width(), lo), hi), 1)
        self.state, self.until = "once", time.monotonic() + 2
        self.play("waving")
        n = f" (monitor {screens.index(cur) + 1})" if len(screens) > 1 else ""
        return {"izquierda": "Me fui a la izquierda ⬅️", "derecha": "Me fui a la derecha ➡️", "centro": "Aquí al centro 🎯", "arriba": "Me subí al techo ⬆️"}.get(side, "Me cambié de monitor 🖥️") + n

    def set_free(self, side: str | None, frac: float = 0.35) -> str:
        """Orden de voz: deja libre la derecha o la izquierda del piso (no anda ni salta a ventanas ahí). Sin lado, vuelve a andar por donde quiera."""
        self.keep_free = {"side": side, "frac": frac} if side else None
        store.put("keep_free", self.keep_free)
        if not side:
            return "¡Listo, ando por donde quiera otra vez! 🏃"
        if self.at == ("screen", 0):
            lo, hi = self.free_range(self.seg.len)
            self.s = min(max(self.s, lo), hi)
        elif self.at[0] != "screen" or self.attached:
            self.win = None
            self.fall_from()  # sale de paredes, techo o ventanas: al caer aterriza y el piso ya está acotado
        return f"Dejo libre la {side}{' (esquina)' if frac < 0.3 else ''} ✋"

    def advance_along(self, dt: float):
        if self.keep_free and self.at == ("screen", 0):
            lo, hi = self.free_range(self.seg.len)
            self.s += self.dir * SPEED * dt
            if not lo <= self.s <= hi:  # llegó al límite del espacio libre: da la vuelta
                self.s, self.dir = min(max(self.s, lo), hi), -self.dir
            return
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
        if now - self.save_at > 30:
            self.save_at = now
            self.care.save()
            self.save_pos()
            if (w := self.care.worst()) and now - self.low_at > 300:
                self.low_at = now
                self.say({"hambre": "Tengo hambre… 🍙", "limpieza": "Necesito un baño 🫧", "diversion": "Estoy aburrida 🎾", "energia": "Tengo sueño 💤"}[w[0]] + "  \nHaz clic en mí para cuidarme.")
        st = self.state
        if self.busy_phase and st in ("idle", "walk", "once", "sleep"):  # responde: no se mueve
            self.state = st = "busy"
            self.target = None
        if st == "drag":
            self.play("dragged")
        elif st == "fall":
            self.mirror = False
            self.play("falling")
            self.vy += GRAVITY * dt
            self.vx *= max(0.0, 1 - 0.5 * dt)  # rozamiento con el aire
            prev = self.c.y() + self.h / 2
            self.c = QPointF(self.c.x() + self.vx * dt, self.c.y() + self.vy * dt)
            if self.after_land or not self.grab_edge(now):  # con una acción pendiente no se agarra: va al piso
                self.land(prev, self.c.y() + self.h / 2)
        elif st == "hop":
            self.hop_step(now)
        elif st == "busy":
            self.mirror = False
            if self.attached and self.seg.rot != 0:  # responde de pie: primero baja al piso
                self.fall_from()
            elif self.busy_phase:
                self.play(BUSY_ANIM.get(self.busy_phase, "review"))
            else:
                self.state, self.until = "idle", now + 2
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
        self.hop_off = 0.0
        if self.attached and self.anim == "jumping" and self.state in ("once", "idle", "walk"):
            # la animación de brincar tiene que brincar: el cuerpo sube y baja con los cuadros (agacharse → impulso → aire → caer)
            n = self.have["jumping"]["frames"]
            self.hop_off = self.h * 0.55 * math.sin(math.pi * (((self.fi + self.acc) % n) / n))
        self.place()
        for f in self.followers:
            f()
        self.update()

    def face(self):
        """Animación de caminar según el sentido local; en paredes y techo usa 'climbing' (paintEvent la orienta) o el correr rotado."""
        sg = self.seg
        local = self.dir * sg.local
        if sg.rot != 0 and "climbing" in self.have:
            self.play("climbing")
            self.mirror = False
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
            self.play("sitting" if sg.kind == "win-top" else "clinging" if sg.rot != 0 else "idle")
            self.mirror = False
        if now < self.until:
            return
        self.until = now + random.uniform(2, 6)
        if sg.rot != 0:  # en pared o techo solo se agarra, trepa o se suelta (jugar, esperar o dormir ahí se vería girado)
            if random.random() < 0.12 or self.care.s["energia"] < 25 or now - self.active_at > 180:
                self.fall_from()
            elif random.random() < 0.6:
                self.dir = random.choice((-1, 1))
                self.state, self.until = "walk", now + random.uniform(2, 7)
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

    def on_floor(self, f) -> bool:
        """Las animaciones de pie en pared o techo se verían giradas: se suelta y hace `f` al aterrizar."""
        if self.attached and self.seg.rot != 0:
            self.after_land = f
            self.fall_from()
            return False
        return True

    def rest(self, secs: float):
        if not self.on_floor(lambda: self.rest(secs)):
            return
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
                return self.landed()
        sc = (QApplication.screenAt(QPoint(int(x), int(self.c.y()))) or QApplication.primaryScreen()).availableGeometry()
        if foot >= sc.bottom() + 1:
            self.scr, self.screen_t = sc, screen_track(sc)
            self.attach("screen", 0, max(0.0, min(x - self.scr.left(), self.scr.width())), d)
            self.landed()

    def landed(self):
        f, self.after_land = self.after_land, None
        if f:
            self.vx = 0.0
            f()
        else:
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
        if c and (self.win is None) and not self.keep_free and self.attached and self.at[0] == "screen" and self.state in ("idle", "walk", "once") \
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

    def mouseDoubleClickEvent(self, e):
        if f := self.ui.get("float"):
            self.press = None
            f()

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
        w = self.care.worst()
        for name, label in (("comer", "🍙 Comer"), ("limpiar", "🫧 Limpiar"), ("jugar", "🎾 Jugar"), ("mimar", "💜 Mimar"), ("dormir", "💤 Dormir")):
            need = "❗ " if w and ACTIONS[name][0].get(w[0], 0) > 0 else ""  # marca lo que sube la barra más baja
            m.addAction(QAction(need + label, m, triggered=lambda _=False, n=name: self.do(n)))
        sub = m.addMenu("Animación")
        for name in sorted(self.have, key=sprites.label):  # en español, como el menú de la mascota en Android
            if name != sprites.LOOK:
                sub.addAction(QAction(sprites.label(name), sub, triggered=lambda _=False, n=name: self.preview(n)))
        for label, fn in (("Chat flotante", self.ui.get("float")), ("Cuidar", self.ui.get("care")), ("Personajes…", self.ui.get("chars")), ("Ajustes…", self.ui.get("settings")),
                          ("Salir", QApplication.quit)):
            m.addAction(QAction(label, m, triggered=fn or (lambda: None)))
        m.exec(at)

    def set_busy(self, phase: str | None = "thinking"):
        self.busy_phase, self.think_on = phase, True
        self.show_thought()

    def clear_busy(self):
        self.busy_phase, self.think_on = None, False
        if self.bubble.thought:
            self.bubble.hide()

    def on_phase(self, phase: str):
        if self.busy_phase is not None:
            self.busy_phase = phase
            self.show_thought()

    def show_thought(self):
        """Globo de pensamiento con lo que hace la IA mientras trabaja (aunque el chat esté cerrado)."""
        text = BUSY_TEXT.get(self.busy_phase)
        if text and self.think_on and self.bubble.label.text() != text:
            self.bubble.say(text, self.geometry(), 300000, thought=True)

    def on_reply(self, dest: str, text: str):
        if dest != "chat":  # el chat suspende el estado ocupado cuando termina de escribir la respuesta
            self.clear_busy()
            self.act_pending()

    def act_pending(self):
        """Hace la animación que pidió la IA en su respuesta ([[anim:…]]), ya sin el estado ocupado (que la taparía). Si es de cuidado
        (limpiarse, comer…) también aplica su efecto en el tamagotchi, sin el globo de la acción para no tapar la respuesta."""
        name, self.pending_anim = getattr(self, "pending_anim", None), None
        if not name:
            return
        if action := next((a for a, n in DO_ANIM.items() if n == name), None):
            self.care.act(action)
        self.preview(name, 5)

    def preview(self, name: str, secs: float | None = None):
        """Reproduce una animación del personaje un rato (menú Animación y catálogo)."""
        a = self.have.get(name)
        if not a:
            return
        if not self.on_floor(lambda: self.preview(name, secs)):
            return
        self.state, self.mirror = "once", False
        self.until = time.monotonic() + (secs or max(2.5, 2 * a["frames"] / a["fps"]))
        self.anim, self.fi, self.acc = name, 0, 0.0

    def say(self, text: str, ms: int = 6000):
        self.bubble.say(text, self.geometry(), ms)

    def wave(self):
        if not self.on_floor(self.wave):
            return
        self.state, self.until = "once", time.monotonic() + 2
        self.play("waving")
        self.say("¡Hola! Soy " + self.char.name + ".")

    def talk(self, secs: float = 1.5):
        if not self.on_floor(lambda: self.talk(secs)):
            return
        self.state, self.until = "once", time.monotonic() + secs
        self.play("talking")

    def listen(self, secs: float):
        """Te está escuchando: «listening» si el personaje la tiene; si no, «talking»."""
        if not self.on_floor(lambda: self.listen(secs)):
            return
        self.state, self.until = "once", time.monotonic() + secs
        self.play("listening" if "listening" in self.have else "talking")

    def do(self, action: str):
        """Acción del tamagotchi: aplica el efecto, anima y habla."""
        if not self.on_floor(lambda: self.do(action)):
            return
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
        self.say(f"**Ventana:** {win}  \nCPU {psutil.cpu_percent()}% · RAM {psutil.virtual_memory().percent}%  \n"
                 f"Animaciones: {len(self.have)} · claude: {'sí' if chat.provider.chat_ready() else 'no'}", 9000)

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
        opts.setdefault("persona", (self.char.name, self.char.description, self.char.personality, list(self.have)))
        opts.setdefault("on_phase", self.bridge.phase.emit)
        self.set_busy("thinking")
        def run():
            try:
                out = chat.ask(prompt, track=dest == "chat", **opts)
            except Exception as e:  # noqa: BLE001 - antes se perdía en silencio (la app no tiene consola) y el chat se quedaba esperando
                log("error", donde="chat.ask", detalle=traceback.format_exc()[-1200:])
                out = f"No pude responder ({e})"
            out, self.pending_anim = chat.split_anim(out, self.have)
            self.bridge.reply.emit(dest, out)
        threading.Thread(target=run, daemon=True).start()


def _look_offset() -> float:
    import os
    return float(os.environ.get("FRUQUIS_LOOK_OFFSET", "0"))


class FloatButton(QPushButton):
    """Botón que se arrastra a cualquier parte; recuerda dónde lo dejaste. Clic principal: abre el chat (modo 💬) o dicta una orden (modo 🎙);
    clic secundario: cambia entre los dos modos."""

    def __init__(self, on_click, on_mic=None, on_mode=None):
        super().__init__("💬")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(46, 46)
        self.setCursor(Qt.OpenHandCursor)
        self.setStyleSheet("QPushButton{background:#6b4fbb;color:white;border-radius:23px;font-size:20px}QPushButton:hover{background:#8a6ae0}")
        self.on_click, self.on_mic, self.on_mode, self.press, self.off, self.moved = on_click, on_mic, on_mode, None, QPoint(), False
        self.mode = store.get("button_mode", "chat") if on_mic else "chat"
        self.listening = False
        self.refresh()
        saved = store.get("button")
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(*(saved if saved else (scr.right() - 62, scr.bottom() - 62)))
        self.clamp()

    def refresh(self):
        self.setText("🔴" if self.listening else "🎙" if self.mode == "mic" else "💬")
        self.setToolTip("Clic: dictar una orden · clic derecho: volver al chat" if self.mode == "mic" else "Clic: abrir el chat · clic derecho: cambiar a micrófono")

    def set_listening(self, on: bool):
        self.listening = on
        self.refresh()

    def clamp(self):
        scr = (QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()).availableGeometry()
        self.move(max(scr.left(), min(self.x(), scr.right() - self.width())), max(scr.top(), min(self.y(), scr.bottom() - self.height())))

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:  # clic secundario: chat ↔ micrófono
            self.press = None
            if self.on_mic:
                self.mode = "mic" if self.mode == "chat" else "chat"
                store.put("button_mode", self.mode)
                self.refresh()
                if self.on_mode:
                    self.on_mode(self.mode)
            return
        self.press, self.off, self.moved = e.globalPosition().toPoint(), e.position().toPoint(), False

    def mouseMoveEvent(self, e):
        if self.press is None:
            return
        g = e.globalPosition().toPoint()
        if (g - self.press).manhattanLength() > 5:
            self.moved = True
        if self.moved:
            self.move(g - self.off)

    def mouseDoubleClickEvent(self, e):
        if f := getattr(self, "ui", {}).get("float"):
            self.press = None
            f()

    def mouseReleaseEvent(self, e):
        if self.press is None:  # soltó el clic secundario
            return
        if self.moved:
            self.clamp()
            store.put("button", [self.x(), self.y()])
        elif self.mode == "mic":
            self.on_mic()
        else:
            self.on_click()
        self.press = None


def run(scale: float | None = None):
    from .chatui import ChatView
    from .shell import MainWindow
    from .voice import AWAKE_S, Voice
    from .ui import CareView, CatalogView, CharactersView, NewCharView, AllPromptView, GenBatchView, NeutralPromptView, ProfileView, RefineView, PromptView, SettingsView, RefsView, ReviewView

    app = QApplication([])
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.png"))))  # Ayax, igual que el ícono de Android
    # sin consola (pythonw) los errores desaparecían: se guardan en ~/.fruquis/voice.log
    sys.excepthook = lambda t, v, tb: (log("error", donde="excepción", detalle="".join(traceback.format_exception(t, v, tb))[-1200:]), sys.__excepthook__(t, v, tb))
    threading.excepthook = lambda a: log("error", donde=f"hilo {a.thread.name if a.thread else '?'}",
                                         detalle="".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback))[-1200:])
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
    pet = Pet(sprites.get(store.get("active", "")), scale or store.get("scale", 0.6), bridge)
    machine.start()  # índice local (apps, binarios, carpetas) en segundo plano, guardado solo en ~/.fruquis
    voice = pet.voice = Voice(lambda: pet.char.name, lambda: [c.name for c in sprites.list_all().values()], lambda: pet.busy_phase is not None)  # antes que las vistas: Ajustes lista los micrófonos
    shell = MainWindow(pet)
    for name, view in (("chat", ChatView(shell, bridge)), ("care", CareView(shell)), ("chars", CharactersView(shell)), ("catalog", CatalogView(shell)),
                       ("prompt", PromptView(shell)), ("review", ReviewView(shell)), ("newchar", NewCharView(shell)), ("refs", RefsView(shell)), ("allprompt", AllPromptView(shell)), ("neutralprompt", NeutralPromptView(shell)), ("settings", SettingsView(shell)), ("genbatch", GenBatchView(shell)), ("refine", RefineView(shell)), ("profile", ProfileView(shell))):
        shell.add_view(name, view)

    def toggle_chat():
        if shell.float_open():
            shell.close_float()
        elif shell.current() == "chat":
            shell.hide()
        else:
            shell.open("chat", near=btn)
    # avisos de la mascota cuando las generaciones en segundo plano terminan
    def on_job(j):
        if j.status == "lista":
            pet.say(f"«{j.anim}» lista ✨ Revísala en Generar animaciones", 5000)
        elif j.status == "error":
            pet.say(f"No pude generar «{j.anim}»", 5000)
    shell.gen.finished.connect(on_job)
    shell.gen.all_done.connect(lambda ok, bad: pet.say(f"¡Terminé! {ok} lista(s)" + (f", {bad} con error" if bad else "") + " ✨", 7000))
    voice.woke.connect(lambda: (pet.say("🎙 Escuchando…", AWAKE_S * 1000), pet.listen(AWAKE_S)))
    voice.status.connect(lambda m: pet.say(m, 6000))
    voice.progress.connect(lambda p: p % 10 == 0 and pet.say(f"Descargando el modelo de voz… {p}%", 4000))
    voice.problem.connect(lambda m: (pet.say(m, 9000), store.put("voice", False)))

    def on_heard(text):  # la orden dictada entra al chat como si la hubieras escrito, sin abrirlo: responde con globos
        shell.views["chat"].send(text, "voz")
    voice.heard.connect(on_heard)
    voice.unsure.connect(lambda t: pet.say(f"No te entendí bien: «{t}». ¿Lo repites?", 6000))

    def on_stop():  # «detener»: corta la petición en curso (la respuesta que se está escribiendo se muestra completa)
        chat_view = shell.views["chat"]
        if chat_view.busy():
            chat_view.stop()
            pet.say("Detenido ✋", 3000)
    voice.stop.connect(on_stop)
    voice.enable(bool(store.get("voice", False)))
    chat_view = shell.views["chat"]
    btn = FloatButton(toggle_chat, chat_view.toggle_mic,
                      lambda m: (voice.set_mic_mode(m == "mic"), pet.say("Ahora te escucho si dices mi nombre 🎙; un clic me dicta sin nombre (clic derecho: volver al chat)" if m == "mic" else "Ahora un clic abre el chat 💬 (ya no te escucho)", 4000)))
    voice.listening.connect(btn.set_listening)
    pet.ui = {"chat": lambda: shell.open("chat"), "float": shell.toggle_float, "care": lambda: shell.open("care"), "chars": lambda: shell.open("chars"), "settings": lambda: shell.open("settings")}
    pet.followers.append(shell.follow_float)
    app.aboutToQuit.connect(pet.care.save)
    app.aboutToQuit.connect(pet.save_pos)
    btn.show()
    pet.show()
    signal.signal(signal.SIGINT, lambda *_: app.quit())  # Ctrl+C en la terminal
    tick = QTimer()
    tick.start(300)
    tick.timeout.connect(lambda: None)  # deja correr Python para que llegue la señal
    code = app.exec()
    sys.stdout.flush()
    os._exit(code)  # los hilos de audio/Whisper bloqueados dejaban el proceso colgado al salir
