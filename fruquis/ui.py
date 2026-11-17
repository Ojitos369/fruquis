"""Vistas de la ventana única: cuidar, personajes, catálogo de animaciones, prompt, revisión de hoja y nuevo personaje."""
import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QLayout, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from . import binaries, icons, provider, speech, sprites, store
from .voice import MODELS
from .care import ACTIONS
from .chatui import avatar, copy_text, pick_images

LABELS = {"hambre": "Hambre", "limpieza": "Limpieza", "diversion": "Diversión", "energia": "Energía"}


class Bg(QObject):
    """Corre una función lenta (IA, generación de imágenes) fuera del hilo de la interfaz y entrega el resultado; `msg` lleva el progreso."""
    done = Signal(int, object, str)
    msg = Signal(str)

    def __init__(self):
        super().__init__()
        self.cbs, self.n = {}, 0
        self.done.connect(self._fin)

    def _fin(self, i, r, e):
        if cb := self.cbs.pop(i, None):
            cb(r, e)

    def run(self, fn, cb):
        self.n += 1
        i = self.n
        self.cbs[i] = cb

        def go():
            try:
                self.done.emit(i, fn(), "")
            except SystemExit as e:
                self.done.emit(i, None, str(e))
            except Exception as e:  # noqa: BLE001 - se muestra al usuario
                self.done.emit(i, None, f"{type(e).__name__}: {e}")
        threading.Thread(target=go, daemon=True).start()

    def cancel(self):
        """Descarta los resultados pendientes y aborta los análisis con IA en curso."""
        self.cbs.clear()
        provider.cancel()


class View(QWidget):
    """Una vista de la ventana única. `enter` se llama cada vez que se muestra (al abrirla y al volver a ella)."""
    title = ""

    def __init__(self, shell):
        super().__init__()
        self.shell, self.pet = shell, shell.pet

    def enter(self, **kw):
        pass

    def page(self, margins=(32, 24, 32, 20), spacing=14, scroll=False, width=760) -> QVBoxLayout:
        """Contenido centrado con ancho máximo, como las apps modernas. `scroll`: para páginas más altas que la ventana."""
        host = self
        if scroll:
            area = QScrollArea(widgetResizable=True)
            area.setFrameShape(QFrame.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            host = QWidget(objectName="body")
            area.setWidget(host)
            box = QVBoxLayout(self)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(area)
        outer = QHBoxLayout(host)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner.setMaximumWidth(width)
        col = QVBoxLayout(inner)
        col.setContentsMargins(*margins)
        col.setSpacing(spacing)
        outer.addStretch(1)
        outer.addWidget(inner, 100)
        outer.addStretch(1)
        return col

    def reflow(self, grid: QGridLayout, widgets: list, cw: int, cols=0) -> int:
        """Reparte las cards en tantas columnas como quepan; devuelve cuántas son."""
        n = max(1, (min(self.width(), 1100) - 56 + 14) // (cw + 14))
        if n != cols or grid.count() != len(widgets):
            while grid.count():
                grid.takeAt(0)
            for i, w in enumerate(widgets):
                grid.addWidget(w, i // n, i % n, Qt.AlignTop | Qt.AlignLeft)
            grid.setColumnStretch(n, 1)
        return n


def button(text, fn, name=None):
    b = QPushButton(text, cursor=Qt.PointingHandCursor)
    if name:
        b.setObjectName(name)
    b.clicked.connect(lambda _=False: fn())
    return b


def seticon(b: QPushButton, name: str, tip: str | None = None):
    """Cambia el icono (y la acción que dice el tooltip) de un botón creado con `ibtn`."""
    b.setIcon(icons.icon(name, {"ibp": icons.ON, "ibd": "#f07178"}.get(b.objectName(), icons.IDLE)))
    if tip:
        b.setToolTip(tip)


def ibtn(name: str, tip: str, fn, kind="ib", size=34) -> QPushButton:
    """Botón de solo icono: la acción sale al pasar el cursor. `kind`: ib = discreto, ibp = principal, ibd = peligroso."""
    b = QPushButton(cursor=Qt.PointingHandCursor, toolTip=tip, objectName=kind)
    b.setFixedSize(size, size)
    b.setIconSize(QSize(18, 18))
    seticon(b, name)
    b.clicked.connect(lambda _=False: fn())
    return b


class Tap(QLabel):
    """Etiqueta (imagen o texto) en la que se puede pulsar."""
    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


def frame_index(k: int, n: int, mode: str) -> int:
    """Cuadro que toca en el paso k de una animación de n cuadros (loop, pingpong o once)."""
    if mode == "pingpong" and n > 1:
        m = k % (2 * n - 2)
        return m if m < n else 2 * n - 2 - m
    return min(k, n - 1) if mode == "once" else k % n


def anim_mode(a: dict) -> str:
    return "pingpong" if a.get("pingpong") else ("loop" if a.get("loop", True) else "once")


def anim_frames(c, a: dict, h: int) -> list:
    pm = QPixmap(str(a["sheet"]))
    cw, ch = c.cell
    cols = max(1, pm.width() // cw)
    return [pm.copy((i % cols) * cw, (a["row"] + i // cols) * ch, cw, ch).scaledToHeight(h, Qt.SmoothTransformation) for i in range(a["frames"])]


class CareView(View):
    """Tamagotchi minimalista: cuatro barras finas y acciones como iconos (el nombre sale al pasar el cursor)."""
    title = "Cuidar"
    ICON = {"hambre": "🍙", "limpieza": "🫧", "diversion": "🎾", "energia": "💤"}

    def __init__(self, shell):
        super().__init__(shell)
        lay = self.page(spacing=14)
        self.head = QLabel(objectName="h1")
        lay.addWidget(self.head)
        self.bars = {}
        for k, lab in LABELS.items():
            row = QHBoxLayout()
            row.setSpacing(10)
            ic = QLabel(self.ICON[k], toolTip=lab)
            ic.setFixedWidth(24)
            b = QProgressBar(textVisible=False, toolTip=lab)
            b.setRange(0, 100)
            for w in (ic, b):
                row.addWidget(w)
            lay.addLayout(row)
            self.bars[k] = b
        lay.addSpacing(8)
        grid = QHBoxLayout()
        grid.setSpacing(8)
        for act in ACTIONS:
            btn = QPushButton(ACTIONS[act][1].split()[0], objectName="pill", cursor=Qt.PointingHandCursor, toolTip=act.capitalize())
            btn.setStyleSheet("font-size:20px")
            btn.clicked.connect(lambda _=False, a=act: self.pet.do(a))
            grid.addWidget(btn)
        lay.addLayout(grid)
        lay.addStretch(1)
        QTimer(self, interval=1000, timeout=self.refresh).start()

    def enter(self, **kw):
        self.refresh()

    def refresh(self):
        self.head.setText(self.pet.char.name)
        for k, b in self.bars.items():
            v = round(self.pet.care.s[k])
            b.setValue(v)
            b.setStyleSheet("QProgressBar::chunk{background:%s}" % ("#f07178" if v < 25 else "#8a6ae0"))


class CharactersView(View):
    """Catálogo de personajes en cards: tocar el personaje lo activa; sus acciones son iconos bajo el nombre."""
    title = "Personajes"
    CW = 168

    def __init__(self, shell):
        super().__init__(shell)
        self.chars, self.sel, self.arm, self.cols = {}, None, None, 0
        lay = self.page(margins=(28, 18, 28, 18), spacing=14, scroll=True, width=1100)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        bar.addStretch(1)
        self.jobs_btn = ibtn("activity", "Generaciones", lambda: shell.push("jobs"))
        for b in (ibtn("upload", "Importar (.zip)", self.imp), self.jobs_btn, ibtn("plus", "Nuevo personaje", lambda: shell.push("newchar"), "ibp")):
            bar.addWidget(b)
        lay.addLayout(bar)
        host = QWidget()
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        lay.addWidget(host)
        lay.addStretch(1)
        self.cards = []
        self.arm_t = QTimer(self, singleShot=True, interval=3000, timeout=self.disarm)
        shell.gen.changed.connect(self.badge)

    def enter(self, **kw):
        self.reload(self.sel)
        self.badge()

    def badge(self):
        n = self.shell.gen.pending()
        self.jobs_btn.setText(f" {n}" if n else "")
        self.jobs_btn.setFixedWidth(52 if n else 34)

    def reload(self, select=None):
        self.chars = sprites.list_all()
        for c in self.cards:
            c.deleteLater()
        self.cards = [self.card(c) for c in self.chars.values()]
        self.cols = 0
        self.flow()

    def card(self, c) -> QFrame:
        active = c.id == self.pet.char.id
        box = QFrame(objectName="card")
        box.setProperty("active", active)
        box.setFixedWidth(self.CW)
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 14, 10, 8)
        v.setSpacing(6)
        pic = Tap(alignment=Qt.AlignCenter, cursor=Qt.PointingHandCursor, toolTip="Usar este personaje")
        pic.setPixmap(avatar(sprites.reference(c), 96))
        pic.clicked.connect(lambda c=c: self.use(c))
        name = QLabel(c.name, objectName="h2", alignment=Qt.AlignCenter)
        name.setStyleSheet("padding:0")
        name.setToolTip(c.description)
        v.addWidget(pic)
        v.addWidget(name)
        row = QHBoxLayout()
        row.setSpacing(0)
        trash = ibtn("trash", "Eliminar", lambda c=c: self.remove(c, trash), "ibd", 30)
        trash.setEnabled(not (sprites.BUNDLED / c.id).is_dir())  # los incluidos con la app no se borran
        for b in (ibtn("film", "Animaciones", lambda c=c: self.shell.push("anims", cid=c.id), size=30), ibtn("edit", "Editar", lambda c=c: self.shell.push("refs", cid=c.id), size=30),
                  ibtn("download", "Exportar (.zip)", lambda c=c: self.export(c), size=30), trash):
            row.addWidget(b)
        v.addLayout(row)
        return box

    def flow(self):
        self.cols = self.reflow(self.grid, self.cards, self.CW, self.cols)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.flow()

    def use(self, c):
        if c.id == self.pet.char.id:
            return
        self.sel = c.id
        self.pet.load_character(c, remember=True)
        self.pet.say(f"¡Ahora soy {c.name}!")
        self.reload()
        self.shell.toast(f"Ahora es {c.name}")

    def disarm(self):
        if self.arm:
            self.arm = None
            self.reload()

    def remove(self, c, btn):
        if self.arm != c.id:  # confirmación en dos pasos: el icono pasa a ✓ y vuelve solo a los 3 s
            self.arm = c.id
            seticon(btn, "check", "¿Seguro? Pulsa otra vez")
            self.arm_t.start()
            return
        self.arm = None
        if len(self.chars) < 2:
            return self.shell.toast("Debe quedar al menos un personaje.", 4000)
        if c.id == self.pet.char.id:  # la mascota pasa a otro personaje antes de borrar el activo
            other = next(o for o in self.chars.values() if o.id != c.id)
            self.pet.load_character(other, remember=True)
        try:
            sprites.delete(c.id)
        except (SystemExit, OSError) as e:
            return self.shell.toast(str(e), 5000)
        self.shell.toast(f"Eliminado: {c.name}")
        self.reload()

    def export(self, c):
        path, _ = QFileDialog.getSaveFileName(self, "Exportar personaje", str(Path.home() / f"{c.id}.zip"), "Zip (*.zip)")
        if path:
            try:
                out = sprites.export_character(c.id, path)
            except (SystemExit, OSError) as e:
                return self.shell.toast(str(e), 5000)
            self.shell.toast(f"Exportado: {out.name}")

    def imp(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importar personaje", "", "Personaje (*.zip)")
        if not path:
            return
        try:
            c = sprites.import_character(path)
        except SystemExit as e:
            return self.shell.toast(str(e), 6000)
        self.shell.toast(f"Importado: {c.name}", 3000)
        self.sel = c.id
        self.reload()


class AnimCard(QFrame):
    """Card de una animación: miniatura en movimiento y nombre. Clic abre su detalle; mantener pulsado marca (y en modo selección, el clic marca)."""
    tapped, held = Signal(str), Signal(str)

    def __init__(self, name: str, c, a: dict | None):
        super().__init__(objectName="card")
        self.name, self.frames, self.k, self.acc, self.long = name, [], 0, 0, False
        self.mode, self.ms = (anim_mode(a), 1000 / a["fps"]) if a else ("loop", 0)
        self.setFixedWidth(AnimsView.CW)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(sprites.label(name))
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 10, 8, 8)
        v.setSpacing(6)
        self.pic = QLabel(alignment=Qt.AlignCenter, objectName="dim")
        self.pic.setFixedHeight(84)
        if a:
            self.frames = anim_frames(c, a, 80)
            self.pic.setPixmap(self.frames[0])
        else:
            self.pic.setText("—")
        lb = QLabel(sprites.label(name), alignment=Qt.AlignCenter, objectName="" if a else "dim")
        v.addWidget(self.pic)
        v.addWidget(lb)
        self.hold = QTimer(self, singleShot=True, interval=500, timeout=self.on_hold)

    def on_hold(self):
        self.long = True
        self.held.emit(self.name)

    def advance(self, dt: int):
        if len(self.frames) < 2:
            return
        self.acc += dt
        steps = int(self.acc // self.ms)
        if steps:
            self.acc -= steps * self.ms
            self.k += steps
            self.pic.setPixmap(self.frames[frame_index(self.k, len(self.frames), self.mode)])

    def mark(self, on: bool):
        self.setProperty("active", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.long = False
            self.hold.start()

    def mouseReleaseEvent(self, e):
        self.hold.stop()
        if e.button() == Qt.LeftButton and not self.long and self.rect().contains(e.position().toPoint()):
            self.tapped.emit(self.name)


class AnimsView(View):
    """Animaciones de un personaje como cards con miniatura en movimiento. Tocar una abre su detalle; con el icono de selección (o manteniendo
    pulsada una card) se marcan varias para generarlas a la vez o eliminarlas."""
    CW = 136

    def __init__(self, shell):
        super().__init__(shell)
        self.cid, self.cards, self.picked, self.selecting, self.cols, self.arm = "", {}, set(), False, 0, False
        lay = self.page(margins=(28, 18, 28, 18), spacing=14, scroll=True, width=1100)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.count = QLabel(objectName="dim")
        bar.addWidget(self.count)
        bar.addStretch(1)
        self.tools = {k: ibtn(ic, tip, fn, nm) for k, ic, tip, fn, nm in (
            ("all", "checks", "Seleccionar todo", lambda: self.set_picked(set(self.cards)), "ib"),
            ("none", "x", "Deseleccionar todo", lambda: self.set_picked(set()), "ib"),
            ("inv", "reset", "Invertir selección", lambda: self.set_picked(set(self.cards) - self.picked), "ib"),
            ("del", "trash", "Eliminar seleccionadas", self.delete, "ibd"),
            ("gen", "sparkles", "Generar seleccionadas", self.generate, "ibp"))}
        for b in self.tools.values():
            bar.addWidget(b)
        self.sel_btn = ibtn("check", "Seleccionar", self.toggle_select)
        bar.addWidget(self.sel_btn)
        lay.addLayout(bar)
        host = QWidget()
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        lay.addWidget(host)
        lay.addStretch(1)
        self.arm_t = QTimer(self, singleShot=True, interval=3000, timeout=self.disarm)
        self.timer = QTimer(self, interval=50, timeout=lambda: [c.advance(50) for c in self.cards.values()])

    @property
    def title(self):
        return f"Animaciones · {sprites.get(self.cid).name}" if self.cid else "Animaciones"

    def enter(self, cid="", **kw):
        self.cid = cid or self.cid
        self.picked, self.selecting = set(), False
        self.build()
        self.timer.start()

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def build(self):
        c = sprites.get(self.cid)
        for w in self.cards.values():
            w.deleteLater()
        self.cards = {}
        for n in sorted(c.anims) + [n for n in sprites.WANTED if n not in c.anims]:
            card = AnimCard(n, c, c.anims.get(n))
            card.tapped.connect(self.tap)
            card.held.connect(self.hold)
            self.cards[n] = card
        self.cols = 0
        self.flow()
        self.sync()

    def flow(self):
        self.cols = self.reflow(self.grid, list(self.cards.values()), self.CW, self.cols)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.flow()

    # ---- selección ----
    def tap(self, n):
        if self.selecting:
            self.set_picked(self.picked ^ {n})
        else:
            self.shell.push("catalog", cid=self.cid, select=n)

    def hold(self, n):
        self.selecting = True
        self.set_picked(self.picked | {n})

    def toggle_select(self):
        self.selecting = not self.selecting
        self.set_picked(set() if not self.selecting else self.picked)

    def set_picked(self, s):
        self.picked = s
        self.disarm()

    def disarm(self):
        self.arm = False
        seticon(self.tools["del"], "trash", "Eliminar seleccionadas")
        self.sync()

    def sync(self):
        c = sprites.get(self.cid)
        for n, card in self.cards.items():
            card.mark(n in self.picked)
        sel = self.selecting
        for k in ("all", "none", "inv"):
            self.tools[k].setVisible(sel)
        self.tools["gen"].setVisible(bool(self.picked))
        self.tools["del"].setVisible(any(n in c.anims for n in self.picked))
        self.count.setText(str(len(self.picked)) if sel else "")
        seticon(self.sel_btn, "x" if sel else "check", "Salir de la selección" if sel else "Seleccionar")

    # ---- acciones sobre lo seleccionado ----
    def generate(self):
        from . import imagegen
        if not imagegen.provider.image_ready():
            self.shell.toast("No hay generador de imágenes. Elige el binario de Codex o configura una API en Ajustes.", 5000)
            return self.shell.open("settings")
        c = sprites.get(self.cid)
        if not (c.neutral or c.source or sprites.reference(c)):
            return self.shell.toast("Carga primero la imagen general del personaje (Editar personaje).", 5000)
        self.shell.gen.start(self.cid, [n for n in self.cards if n in self.picked])
        self.shell.push("jobs")

    def delete(self):
        if not self.arm:  # confirmación en dos pasos: el icono pasa a ✓ y vuelve solo a los 3 s
            self.arm = True
            seticon(self.tools["del"], "check", "¿Seguro? Pulsa otra vez")
            self.arm_t.start()
            return
        c = sprites.get(self.cid)
        gone = [n for n in self.picked if n in c.anims]
        for n in gone:
            sprites.remove(self.cid, n)
        self.pet.refresh_character(sprites.get(self.cid))
        self.shell.toast(f"{len(gone)} eliminada(s)")
        self.picked, self.arm = set(), False
        self.build()


class CatalogView(View):
    """Animaciones de un personaje: lista a un lado y, al otro, vista previa con las acciones como iconos (el nombre sale al pasar el cursor)."""

    def __init__(self, shell):
        super().__init__(shell)
        self.cid, self.frames, self.k, self.sel, self.arm = "", [], 0, None, None
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        right = QVBoxLayout()
        right.setContentsMargins(24, 18, 24, 18)
        right.setSpacing(12)
        card = QFrame(objectName="card")
        cv = QVBoxLayout(card)
        self.view = QLabel(alignment=Qt.AlignCenter, objectName="dim")
        self.view.setMinimumHeight(250)
        cv.addWidget(self.view)
        right.addWidget(card, 1)
        head = QHBoxLayout()
        self.name = QLabel(objectName="h1")
        self.info = QLabel(objectName="dim")
        self.fps, self.mode = QSpinBox(), QComboBox()
        self.fps.setRange(1, 30)
        self.fps.setSuffix(" fps")
        self.fps.setFixedWidth(76)
        self.mode.addItems(["loop", "pingpong", "once"])
        self.mode.setFixedWidth(100)
        head.addWidget(self.name)
        head.addWidget(self.info, 1)
        head.addWidget(self.fps)
        head.addWidget(self.mode)
        right.addLayout(head)
        acts = QHBoxLayout()
        acts.setSpacing(4)
        self.btns = {k: ibtn(ic, tip, fn, nm) for k, ic, tip, fn, nm in (
            ("test", "play", "Probar en la mascota", self.test, "ibp"), ("replace", "upload", "Reemplazar", self.replace, "ib"),
            ("prompt", "file", "Prompt", self.prompt, "ib"), ("delete", "trash", "Eliminar", self.delete, "ibd"),
            ("gen", "sparkles", "Generar con ChatGPT", self.generate, "ibp"), ("cancel", "x", "Cancelar generación", self.cancel_gen, "ibd"),
            ("improve", "wand", "Mejorar con chat", self.improve, "ib"))}
        self.btns["cancel"].hide()
        for k in ("test", "replace", "prompt", "delete"):
            acts.addWidget(self.btns[k])
        acts.addStretch(1)
        for k in ("cancel", "improve", "gen"):
            acts.addWidget(self.btns[k])
        right.addLayout(acts)
        self.status = QLabel(objectName="hint")
        right.addWidget(self.status)
        self.job = Bg()
        self.job.msg.connect(self.status.setText)
        main.addLayout(right, 1)
        self.timer = QTimer(self, timeout=self.tick)
        self.arm_t = QTimer(self, singleShot=True, timeout=self.disarm)
        self.fps.valueChanged.connect(self.autosave)
        self.mode.currentIndexChanged.connect(self.autosave)

    @property
    def title(self):
        return f"Animaciones · {sprites.get(self.cid).name}" if self.cid else "Animaciones"

    def enter(self, cid="", select=None, **kw):
        if cid != self.cid:
            self.sel = None
        self.cid = cid
        self.refresh(select or self.sel)

    def char(self):
        return sprites.get(self.cid)

    def names(self):
        c = self.char()
        return sorted(c.anims) + [n for n in sprites.WANTED if n not in c.anims]

    def refresh(self, select=None):
        names = self.names()
        self.sel = select if select in names else (names[0] if names else None)
        self.pick()

    def cur(self):
        return self.sel

    def disarm(self):
        self.arm = None
        seticon(self.btns["delete"], "trash", "Eliminar")

    def pick(self, _=0):
        n, c = self.cur(), self.char()
        self.sel = n
        self.disarm()
        a = c.anims.get(n) if n else None
        self.timer.stop()
        for k in ("test", "delete"):
            self.btns[k].setEnabled(bool(a))
        self.btns["replace"].setToolTip("Reemplazar" if a else "Agregar…")
        self.btns["gen"].setToolTip("Regenerar con ChatGPT" if a else "Generar con ChatGPT")
        self.btns["improve"].setEnabled(bool(a))
        for wd in (self.fps, self.mode):
            wd.setEnabled(bool(a))
        w = sprites.WANTED.get(n)
        self.name.setText(sprites.label(n) if n else "")
        if not a:
            self.frames = []
            self.view.setPixmap(QPixmap())
            self.view.setText("—")
            self.info.setText(w[1].capitalize() if w else "")
            return
        self.frames = anim_frames(c, a, 240)
        for wd in (self.fps, self.mode):
            wd.blockSignals(True)
        self.fps.setValue(a["fps"])
        self.mode.setCurrentText(anim_mode(a))
        for wd in (self.fps, self.mode):
            wd.blockSignals(False)
        self.info.setText((f"{w[1].capitalize()} · " if w else "") + f"{a['frames']} cuadros")
        self.k = 0
        self.view.setText("")
        self.timer.start(int(1000 / a["fps"]))

    def tick(self):
        if not self.frames:
            return
        self.k += 1
        self.view.setPixmap(self.frames[frame_index(self.k, len(self.frames), self.mode.currentText())])

    def changed(self, select=None):
        self.pet.refresh_character(self.char())
        self.refresh(select)

    def autosave(self, *_):
        n = self.cur()
        if n in self.char().anims:
            sprites.set_meta(self.cid, n, self.fps.value(), self.mode.currentText())
            self.pet.refresh_character(self.char())
            self.timer.start(int(1000 / self.fps.value()))

    def test(self):
        self.pet.preview(self.cur())

    def replace(self):
        n = self.cur()
        path, _ = QFileDialog.getOpenFileName(self, f"Hoja con la animación '{n}'", "", "Imágenes (*.png *.webp *.jpg *.jpeg)")
        if not path:
            return
        try:
            from . import importer
            sprites.replace(self.cid, n, path)  # todas las filas de la hoja forman la animación
        except SystemExit as e:
            return self.shell.toast(str(e), 5000)
        self.shell.toast(f"«{n}» actualizada ({self.char().anims[n]['frames']} cuadros)")
        self.changed(n)

    def delete(self):
        n = self.cur()
        if self.arm != n:  # confirmación en dos pasos, sin ventanas emergentes
            self.arm = n
            seticon(self.btns["delete"], "check", "¿Seguro? Pulsa otra vez")
            self.arm_t.start(3000)
            return
        sprites.remove(self.cid, n)
        self.shell.toast(f"«{n}» eliminada")
        self.changed(n)

    def prompt(self):
        self.shell.push("prompt", cid=self.cid, anim=self.cur())

    def improve(self):
        self.shell.push("refine", cid=self.cid, target=self.cur())

    def generate(self):
        """Genera esta animación con el binario local de Codex (ChatGPT): usa la hoja neutral como referencia y, si falta, la crea primero."""
        from . import imagegen
        n, c = self.cur(), self.char()
        if not imagegen.provider.image_ready():
            self.shell.toast("No hay generador de imágenes. Elige el binario de Codex o configura una API en Ajustes.", 5000)
            return self.shell.open("settings")
        text = sprites.prompt(c, n, background=store.get("prompt_bg", "#FF00FF"))
        self.btns["gen"].setEnabled(False)
        self.btns["cancel"].show()
        self.status.setText("Preparando…")
        self.job.run(lambda: imagegen.make_animation(c.id, n, text, self.job.msg.emit), lambda plan, err: self.generated(c.id, plan, err))

    def cancel_gen(self):
        from . import imagegen
        imagegen.cancel()

    def generated(self, cid, plan, err):
        self.btns["gen"].setEnabled(True)
        self.btns["cancel"].hide()
        self.status.setText("")
        if err:
            return self.shell.toast(err, 7000)
        self.pet.say("¡Ya salió la imagen! Revisa y aplica ✨", 5000)
        self.shell.push("review", cid=cid, plan=plan)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)


class PromptView(View):
    """Prompt (plantilla con variables) para pedir en un generador de imágenes una animación que falta. Al copiarlo, vuelve atrás y avisa."""
    title = "Prompt de animación"

    def __init__(self, shell):
        super().__init__(shell)
        self.c = None
        lay = self.page(spacing=10)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.anim, self.frames = QComboBox(), QSpinBox()
        self.anim.setEditable(True)
        self.frames.setRange(2, 24)
        self.bg = QComboBox()
        self.bg.setEditable(True)
        self.bg.addItems(["#FF00FF", "", "#00FF00", "blanco sólido", "negro sólido"])  # el generador no da transparencia real: se usa croma y se recorta
        self.bg.setCurrentText(store.get("prompt_bg", "#FF00FF"))
        self.bg.lineEdit().setPlaceholderText("transparente")
        self.dist, self.dir, self.action, self.extra = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.dist.setPlaceholderText("automática")
        self.dir.setPlaceholderText("la de la referencia")
        self.extra.setPlaceholderText("opcional")
        for lab, w in (("Animación", self.anim), ("Cuadros", self.frames), ("Fondo", self.bg), ("Distribución", self.dist), ("Dirección", self.dir),
                       ("Movimiento", self.action), ("Detalles", self.extra)):
            form.addRow(QLabel(lab, objectName="dim"), w)
        lay.addLayout(form)
        self.text = QPlainTextEdit()
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        self.gen_btn = ibtn("sparkles", "Generar con ChatGPT", self.generate, "ibp")
        self.cancel_btn = ibtn("x", "Cancelar", self.cancel_gen, "ibd")
        self.cancel_btn.hide()
        row.addWidget(self.gen_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(ibtn("copy", "Copiar prompt", self.copy))
        row.addWidget(ibtn("image", "Guardar imagen de referencia", self.ref))
        row.addStretch(1)
        lay.addLayout(row)
        self.status = QLabel(objectName="hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.job = Bg()
        self.job.msg.connect(self.status.setText)
        self.anim.currentTextChanged.connect(self.reset)
        self.frames.valueChanged.connect(self.build)
        for w in (self.dist, self.dir, self.action, self.extra):
            w.textEdited.connect(self.build)
        self.bg.currentTextChanged.connect(self.build)

    def enter(self, cid="", anim=None, **kw):
        self.c = sprites.get(cid)
        self.anim.blockSignals(True)
        self.anim.clear()
        self.anim.addItems([n for n in sprites.WANTED if n not in self.c.anims] + [n for n in sprites.WANTED if n in self.c.anims])
        self.anim.blockSignals(False)
        self.anim.setCurrentText(anim or self.anim.itemText(0))
        self.reset(self.anim.currentText())

    def reset(self, name):
        w = sprites.WANTED.get(name.strip())
        self.frames.blockSignals(True)
        self.frames.setValue(w[2] if w else 8)
        self.frames.blockSignals(False)
        self.action.setText(w[4] if w else "")
        self.build()

    def build(self, *_):
        if self.c:
            self.text.setPlainText(sprites.prompt(self.c, self.anim.currentText().strip() or "nueva", self.frames.value(), self.action.text() or None,
                                                  self.bg.currentText().strip(), self.dist.text().strip(), self.dir.text().strip(), "", self.extra.text().strip()))

    def generate(self):
        """Pasa el prompt a ChatGPT (Codex) con la hoja neutral como referencia (la crea primero si falta) y manda el resultado a revisión."""
        from . import imagegen
        cid, anim, text = self.c.id, self.anim.currentText().strip() or "nueva", self.text.toPlainText()
        self.gen_btn.setEnabled(False)
        self.cancel_btn.show()
        self.status.setText("Preparando…")
        self.job.run(lambda: imagegen.make_animation(cid, anim, text, self.job.msg.emit), lambda plan, err: self.generated(cid, plan, err))

    def cancel_gen(self):
        from . import imagegen
        imagegen.cancel()

    def generated(self, cid, plan, err):
        self.gen_btn.setEnabled(True)
        self.cancel_btn.hide()
        self.status.setText("")
        if err:
            return self.shell.toast(err, 7000)
        self.c = sprites.get(cid)  # por si se generó la hoja neutral por el camino: el prompt ya la menciona
        self.pet.say("¡Ya salió la imagen! Revisa y aplica ✨", 5000)
        self.shell.push("review", cid=cid, plan=plan)

    def copy(self):
        copy_text(self.text.toPlainText())
        self.pet.say("¡Prompt copiado! ✓", 3000)
        self.shell.back()
        self.shell.toast("Prompt copiado ✓")

    def ref(self):
        p = sprites.reference(self.c)
        self.shell.toast(f"Referencia guardada: {p}" if p else "Este personaje aún no tiene imagen", 5000)


class ReviewView(View):
    """Revisión de lo que detectó la IA en una hoja: una animación por línea, editable."""
    title = "Revisar animaciones detectadas"

    def __init__(self, shell):
        super().__init__(shell)
        self.cid, self.plan, self.job = "", None, None
        lay = self.page(spacing=12)
        self.head = QLabel(objectName="dim")
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.shot = QLabel(alignment=Qt.AlignCenter)
        lay.addWidget(self.shot)
        self.text = QPlainTextEdit()
        self.text.setStyleSheet("font-family:monospace;")
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addWidget(ibtn("check", "Aplicar", self.apply, "ibp"))
        self.improve_btn = ibtn("wand", "Mejorar con chat", self.improve)
        row.addWidget(self.improve_btn)
        row.addWidget(ibtn("x", "Cancelar", lambda: self.shell.back()))
        row.addStretch(1)
        lay.addLayout(row)

    def enter(self, cid="", plan=None, job=None, **kw):
        if plan is None:
            return
        self.cid, self.plan, self.job = cid, plan, job
        n = len(plan["rows"])
        total = sum(len(r) for r in plan["rows"])
        wr = f"\n⚠ {plan['warning']}" if plan.get("warning") else ""
        warn = wr + f"\n⚠ Se esperaban {plan['expected']} cuadros y detecté {total}." if plan.get("expected") and plan["expected"] != total else ""
        self.head.setText(f"{n} fila(s) {[len(r) for r in plan['rows']]}" + (" · IA" if plan["ai"] else "") + "\nnombre | fps | modo | filas" + warn)
        self.text.setToolTip("Una por línea: nombre | fps | modo (loop, pingpong, once) | filas (desde 0). Borra una línea para omitirla.")
        pm = QPixmap(plan["raw"]).scaled(720, 170, Qt.KeepAspectRatio, Qt.SmoothTransformation) if plan.get("raw") else QPixmap()
        self.shot.setPixmap(pm)
        self.shot.setVisible(bool(plan.get("raw")))
        self.improve_btn.setVisible(bool(plan.get("raw")))
        self.text.setPlainText("\n".join(f"{o['name']} | {o['fps']} | {o['mode']} | {','.join(str(r) for r in o['rows'])}" for o in plan["anims"]))

    def improve(self):
        if self.plan and self.plan.get("raw") and self.plan["anims"]:
            self.shell.push("refine", cid=self.cid, target=self.plan["anims"][0]["name"], image=self.plan["raw"])

    def apply(self):
        n = len(self.plan["rows"])
        anims = []
        try:
            for ln in self.text.toPlainText().splitlines():
                if ln.strip():
                    nm, fps, mode, rows = (x.strip() for x in ln.split("|"))
                    anims.append({"name": nm, "fps": int(fps), "mode": mode if mode in ("loop", "pingpong", "once") else "loop",
                                  "rows": [int(r) for r in rows.split(",") if 0 <= int(r) < n]})
            sprites.apply(self.cid, self.plan["rows"], anims)
        except (ValueError, SystemExit) as e:
            return self.shell.toast(f"No pude leer las líneas: {e}", 5000)
        if self.cid == self.pet.char.id:
            self.pet.refresh_character(sprites.get(self.cid))
        if getattr(self, "job", None):  # vino de la cola de generación
            self.shell.gen.set(self.job, status="aplicada", msg="aplicada")
        self.shell.back()
        self.shell.toast(f"Agregadas: {', '.join(o['name'] for o in anims)}")


class NewCharView(View):
    title = "Nuevo personaje"

    def __init__(self, shell):
        super().__init__(shell)
        lay = self.page(spacing=12)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.name, self.size = QLineEdit(), QLineEdit("192x208")
        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText("Descripción visual")
        self.desc.setFixedHeight(120)
        form.addRow(QLabel("Nombre", objectName="dim"), self.name)
        form.addRow(QLabel("Descripción", objectName="dim"), self.desc)
        form.addRow(QLabel("Celda (ancho×alto)", objectName="dim"), self.size)
        self.src_path = ""
        self.src_btn = button("Elegir…", self.pick_src)
        form.addRow(QLabel("Imagen general", objectName="dim"), self.src_btn)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(ibtn("check", "Crear personaje", self.create, "ibp"))
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)

    def pick_src(self):
        path, _ = QFileDialog.getOpenFileName(self, "Imagen general del personaje", "", "Imágenes (*.png *.webp *.jpg *.jpeg)")
        if path:
            self.src_path = path
            self.src_btn.setText(Path(path).name)

    def enter(self, **kw):
        self.name.clear()
        self.desc.clear()
        self.src_path = ""
        self.src_btn.setText("Elegir…")
        self.name.setFocus()

    def create(self):
        if not self.name.text().strip():
            return self.shell.toast("Ponle un nombre")
        try:
            w, h = (int(v) for v in self.size.text().lower().split("x"))
        except ValueError:
            return self.shell.toast("El tamaño debe verse así: 192x208")
        c = sprites.create(self.name.text().strip(), self.desc.toPlainText(), (w, h))
        if self.src_path:
            try:
                sprites.set_source(c.id, self.src_path)
            except SystemExit as e:
                self.shell.toast(str(e), 5000)
        self.shell.views["chars"].sel = c.id
        self.shell.back()
        self.shell.toast(f"Creado: {c.name}", 3000)


class RefsView(View):
    """Referencias del personaje: la imagen general (la cargas tú) y la hoja neutral de 4 vistas (se genera o se carga). Son solo de
    referencia: sirven para generar cualquier animación con todos los detalles y no aparecen en el catálogo de animaciones."""
    title = "Editar personaje"

    def __init__(self, shell):
        super().__init__(shell)
        self.cid, self.job = "", Bg()
        lay = self.page(spacing=12, scroll=True)
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.src_pic, self.neu_pic = QLabel(alignment=Qt.AlignCenter, objectName="dim"), QLabel(alignment=Qt.AlignCenter, objectName="dim")
        cards.addLayout(self.card("IMAGEN GENERAL", self.src_pic, (ibtn("upload", "Cargar imagen…", self.load_src), ibtn("download", "Guardar…", lambda: self.save_ref("source")),
                                                                 ibtn("trash", "Quitar", self.clear_src, "ibd"))), 1)
        self.gen_btn = ibtn("sparkles", "Generar con ChatGPT", self.gen_neutral, "ibp")
        self.improve_btn = ibtn("wand", "Mejorar con chat", self.improve_neutral)
        self.neu_btns = (self.gen_btn, self.improve_btn, ibtn("file", "Prompt", self.neutral_prompt), ibtn("upload", "Cargar propia…", self.load_neutral),
                         ibtn("download", "Guardar…", lambda: self.save_ref("neutral")), ibtn("trash", "Quitar", self.clear_neutral, "ibd"))
        cards.addLayout(self.card("HOJA NEUTRAL · 4 VISTAS", self.neu_pic, self.neu_btns), 2)
        lay.addLayout(cards, 1)
        self.cancel_btn = ibtn("x", "Cancelar generación", self.cancel, "ibd")
        self.cancel_btn.hide()
        lay.addWidget(self.cancel_btn, 0, Qt.AlignLeft)
        self.status = QLabel(objectName="hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.codex = QLabel(objectName="hint")
        lay.addWidget(self.codex)
        self.job.msg.connect(self.status.setText)
        self.prof = ProfileView(shell, lay)  # sus campos van en esta misma página

    def card(self, title, pic, buttons):
        box = QFrame(objectName="card")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 12, 14, 12)
        v.addWidget(QLabel(title, objectName="section"))
        pic.setMinimumHeight(170)
        v.addWidget(pic, 1)
        row = QHBoxLayout()
        row.setSpacing(2)
        for b in buttons:
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        wrap = QVBoxLayout()
        wrap.addWidget(box)
        return wrap

    def enter(self, cid="", **kw):
        self.cid = cid or self.cid
        self.prof.enter(cid=self.cid)
        self.refresh()
        self.codex.setText("Comprobando Codex…")
        Bg_ = getattr(self, "_chk", None) or Bg()
        self._chk = Bg_
        from . import imagegen
        Bg_.run(imagegen.status, lambda r, e: self.codex.setText(("✓ " if r and r[0] else "✗ ") + (r[1] if r else e)))

    def char(self):
        return sprites.get(self.cid)

    def refresh(self):
        c = self.char()
        for pic, f, w, h, empty in ((self.src_pic, c.source, 200, 170, "—"), (self.neu_pic, c.neutral, 430, 170, "—")):
            pm = QPixmap(str(f)) if f else QPixmap()
            if f and not pm.isNull():
                pic.setPixmap(pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                pic.setText("")
            else:
                pic.setPixmap(QPixmap())
                pic.setText(empty)
        self.gen_btn.setToolTip("Regenerar con ChatGPT" if c.neutral else "Generar con ChatGPT (4 vistas: frontal, trasera y laterales)")
        self.improve_btn.setEnabled(bool(c.neutral))
        self.gen_btn.setEnabled(bool(c.source or sprites.reference(c)) and not self.cancel_btn.isVisible())

    def load_src(self):
        path, _ = QFileDialog.getOpenFileName(self, "Imagen general del personaje", "", "Imágenes (*.png *.webp *.jpg *.jpeg)")
        if not path:
            return
        try:
            sprites.set_source(self.cid, path)
        except SystemExit as e:
            return self.shell.toast(str(e), 5000)
        self.refresh()
        self.shell.toast("Imagen general guardada")

    def save_ref(self, which):
        """Copia la imagen general o la hoja neutral (cargada o generada) a donde elija el usuario."""
        f = getattr(self.char(), which)
        if not f:
            return self.shell.toast("Aún no hay imagen que guardar")
        f = Path(f)
        path, _ = QFileDialog.getSaveFileName(self, "Guardar imagen", str(Path.home() / f"{self.cid}-{which}{f.suffix}"), "Imágenes (*.png *.webp *.jpg *.jpeg)")
        if path:
            shutil.copyfile(f, path)
            self.shell.toast("Imagen guardada")

    def clear_src(self):
        sprites.clear_ref(self.cid, "source")
        self.refresh()

    def load_neutral(self):
        path, _ = QFileDialog.getOpenFileName(self, "Hoja neutral (4 vistas)", "", "Imágenes (*.png *.webp *.jpg *.jpeg)")
        if not path:
            return
        try:
            sprites.set_neutral(self.cid, path)
        except SystemExit as e:
            return self.shell.toast(str(e), 6000)
        self.refresh()
        self.shell.toast("Hoja neutral guardada")

    def neutral_prompt(self):
        self.shell.push("neutralprompt", cid=self.cid)

    def improve_neutral(self):
        self.shell.push("refine", cid=self.cid, target="neutral")

    def clear_neutral(self):
        sprites.clear_ref(self.cid, "neutral")
        self.refresh()

    def gen_neutral(self):
        from . import imagegen
        cid = self.cid
        self.cancel_btn.show()
        self.gen_btn.setEnabled(False)
        self.status.setText("Preparando…")
        self.job.run(lambda: imagegen.make_neutral(cid, self.job.msg.emit), self.generated)

    def cancel(self):
        from . import imagegen
        imagegen.cancel()

    def generated(self, log, err):
        self.cancel_btn.hide()
        self.status.setText("")
        self.refresh()
        if err:
            return self.shell.toast(err, 7000)
        self.pet.say("¡Ya tengo mis 4 vistas! ✨", 4000)
        self.shell.toast("Hoja neutral generada")


class NeutralPromptView(View):
    """Prompt para generar la hoja neutral (4 vistas) en cualquier generador de imágenes; se adjunta la imagen general como referencia."""
    title = "Prompt de la hoja neutral"

    def __init__(self, shell):
        super().__init__(shell)
        self.c = None
        lay = self.page(spacing=10)
        form = QFormLayout()
        form.setVerticalSpacing(8)
        self.bg = QComboBox()
        self.bg.setEditable(True)
        self.bg.addItems(["#FF00FF", "", "#00FF00", "blanco sólido", "negro sólido"])
        self.bg.setCurrentText(store.get("prompt_bg", "#FF00FF"))
        self.extra = QLineEdit()
        self.extra.setPlaceholderText("opcional")
        form.addRow(QLabel("Fondo", objectName="dim"), self.bg)
        form.addRow(QLabel("Detalles", objectName="dim"), self.extra)
        lay.addLayout(form)
        self.text = QPlainTextEdit()
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addWidget(ibtn("copy", "Copiar prompt", self.copy, "ibp"))
        row.addWidget(ibtn("image", "Ver imagen general", self.show_src))
        row.addStretch(1)
        lay.addLayout(row)
        self.bg.currentTextChanged.connect(self.build)
        self.extra.textEdited.connect(self.build)

    def enter(self, cid="", **kw):
        self.c = sprites.get(cid)
        self.build()

    def build(self, *_):
        if self.c:
            self.text.setPlainText(sprites.neutral_prompt(self.c, self.bg.currentText().strip(), self.extra.text().strip()))

    def show_src(self):
        p = self.c.source or sprites.reference(self.c)
        self.shell.toast(f"Imagen de referencia: {p}" if p else "Aún no hay imagen general: cárgala en la vista anterior", 5000)

    def copy(self):
        copy_text(self.text.toPlainText())
        self.pet.say("¡Prompt de la hoja neutral copiado! ✓", 3000)
        self.shell.back()
        self.shell.toast("Prompt de la hoja neutral copiado ✓")


class SettingsView(View):
    """Ajustes del aplicativo: binarios del chat y del generador de imágenes, tamaño de la mascota, fondo de los prompts y valores del chat."""
    title = "Ajustes"

    def __init__(self, shell):
        super().__init__(shell)
        self.job = Bg()
        self.bins, self.apis = {}, {}
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        rail = QFrame(objectName="side")  # categorías como iconos: cada una es una página corta
        rail.setFixedWidth(64)
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(10, 12, 10, 12)
        rv.setSpacing(6)
        self.pages, cats = QStackedWidget(), QButtonGroup(self)
        main.addWidget(rail)
        main.addWidget(self.pages, 1)
        for i, (ic, tip, build) in enumerate((("chat", "Chat", self.page_chat), ("sparkles", "IA", self.page_ai), ("user", "Mascota", self.page_pet),
                                              ("mic", "Voz", self.page_voice), ("image", "Imágenes", self.page_images), ("link", "Otro equipo", self.page_link))):
            b = QPushButton(objectName="tab", cursor=Qt.PointingHandCursor, checkable=True, toolTip=tip, icon=icons.icon(ic))
            b.setFixedSize(44, 44)
            b.setIconSize(QSize(20, 20))
            cats.addButton(b, i)
            rv.addWidget(b)
            self.pages.addWidget(self.scroller(tip, build))
        cats.idClicked.connect(self.pages.setCurrentIndex)
        cats.button(0).setChecked(True)
        rv.addStretch(1)
        rv.addWidget(ibtn("reset", "Restablecer ajustes", self.reset, "ibd"), 0, Qt.AlignHCenter)
        for w in (self.model, self.effort):
            w.currentTextChanged.connect(self.save_chat)
        for w in (self.term, self.see, self.ctl, self.web):
            w.toggled.connect(self.save_chat)

    # ---- armado: páginas cortas, cada una con grupos (cards) de filas «nombre … control» ----
    def scroller(self, title: str, build) -> QScrollArea:
        area = QScrollArea(widgetResizable=True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="body")
        area.setWidget(body)
        wrap = QHBoxLayout(body)
        inner = QWidget()
        inner.setMaximumWidth(620)
        wrap.addStretch(1)
        wrap.addWidget(inner, 100)
        wrap.addStretch(1)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(28, 24, 28, 28)
        lay.setSpacing(16)
        lay.addWidget(QLabel(title, objectName="h1"))
        build(lay)
        lay.addStretch(1)
        return area

    @staticmethod
    def group(*items) -> QFrame:
        box = QFrame(objectName="card")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(14)
        for it in items:
            v.addLayout(it) if isinstance(it, QLayout) else v.addWidget(it)
        return box

    @staticmethod
    def row(label: str, w: QWidget, grow=False) -> QHBoxLayout:
        r = QHBoxLayout()
        r.addWidget(QLabel(label, toolTip=w.toolTip()), 1)
        r.addWidget(w, 2 if grow else 0)
        return r

    def page_chat(self, lay):
        self.model, self.effort = QComboBox(), QComboBox()
        for cb, items in ((self.model, ("haiku", "sonnet", "opus")), (self.effort, ("low", "medium", "high"))):
            cb.addItems(items)
            cb.setFixedWidth(130)
        self.term = QCheckBox(toolTip="Permitir que el chat ejecute comandos")
        self.see = QCheckBox(toolTip="Toma una captura de la ventana activa antes de responder")
        self.ctl = QCheckBox(toolTip="Ratón, teclado y ventanas: acciones reales en tu equipo. macOS pide permisos de Accesibilidad y de Grabación de pantalla; "
                             "en Wayland puede no funcionar (usa X11). Cada acción queda en ~/.fruquis/ctl.log")
        self.web = QCheckBox(toolTip="Controlar tu navegador (pestañas, páginas, formularios) con la extensión Claude in Chrome. Más lento al arrancar")
        lay.addWidget(self.group(self.row("Modelo", self.model), self.row("Esfuerzo", self.effort)))
        lay.addWidget(self.group(self.row("Terminal", self.term), self.row("Ver ventana", self.see), self.row("Controlar escritorio", self.ctl),
                                 self.row("Navegador", self.web)))

    def page_ai(self, lay):
        for tool, label, hint in (("claude", "Chat (Claude Code CLI)", "Responde en el chat, las ideas y analiza las hojas de sprites."),
                                  ("codex", "Imágenes (Codex CLI · ChatGPT)", "Genera las animaciones y la hoja neutral.")):
            lay.addWidget(self.binary_row(tool, label, hint))
        for what, label in (("chat", "Chat por API"), ("image", "Imágenes por API")):
            lay.addWidget(self.api_row(what, label))

    def page_pet(self, lay):
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(30, 120)
        self.size.setValue(int(store.get("scale", 0.6) * 100))
        self.size_lb = QLabel(f"{self.size.value()}%", objectName="dim")
        self.size_lb.setFixedWidth(44)
        self.size.valueChanged.connect(lambda v: self.size_lb.setText(f"{v}%"))
        self.size.sliderReleased.connect(self.apply_size)
        size = QHBoxLayout()
        size.addWidget(QLabel("Tamaño"))
        size.addWidget(self.size, 1)
        size.addWidget(self.size_lb)
        lay.addWidget(self.group(size))
        head = QHBoxLayout()
        head.addWidget(QLabel("Monitores donde anda"), 1)
        head.addWidget(ibtn("monitor", "Identificar: muestra el número de cada monitor en su pantalla", self.identify))
        self.mon_box = QVBoxLayout()
        self.mon_box.setSpacing(10)
        lay.addWidget(self.group(head, self.mon_box))
        self.fill_monitors()
        QApplication.instance().screenAdded.connect(self.fill_monitors)
        QApplication.instance().screenRemoved.connect(self.fill_monitors)

    def page_voice(self, lay):
        v = self.pet.voice
        self.voice = QCheckBox(toolTip="Al oírlo, dicta tu pedido por voz y trabaja como asistente (reconocimiento local; baja el modelo la primera vez)")
        self.voice.setChecked(bool(store.get("voice", False)))
        self.voice.toggled.connect(self.set_voice)
        self.vstate, self.vbar = QLabel(objectName="dim"), QProgressBar(textVisible=False)
        self.vbar.setRange(0, 100)
        self.vbar.setFixedHeight(6)
        self.vbar.hide()
        self.voice_state()
        v.progress.connect(self.voice_progress)
        v.ready.connect(self.voice_state)
        v.problem.connect(lambda _: (self.voice_state(), self.voice.setChecked(False)))
        self.vlevel, self.vheard = QProgressBar(textVisible=False), QLabel("Oí: —", objectName="dim")  # prueba en vivo del micrófono
        self.vlevel.setRange(0, 100)
        self.vlevel.setFixedHeight(6)
        self.vlevel.setToolTip("Volumen del micrófono: debe moverse cuando hablas")
        self.vheard.setWordWrap(True)
        v.level.connect(self.vlevel.setValue)
        v.raw.connect(lambda t: self.vheard.setText(f"Oí: {t}"))
        lay.addWidget(self.group(self.row("Escuchar su nombre", self.voice), self.vstate, self.vbar, self.vlevel, self.vheard))
        self.speak = QCheckBox(toolTip="Masculina o femenina según el género del personaje")
        self.speak.setChecked(bool(store.get("speak", True)))
        self.speak.toggled.connect(lambda on: (store.put("speak", bool(on)), on or speech.stop()))
        self.vq = QComboBox()
        for label, key in (("Precisa · small (~480 MB)", "small"), ("Rápida · base (~145 MB)", "base")):
            self.vq.addItem(label, key)
        self.vq.setCurrentIndex(max(0, self.vq.findData(v.size)))
        self.vq.currentIndexChanged.connect(lambda _: (v.set_size(self.vq.currentData()), self.voice_state()))
        self.mic = QComboBox()
        self.mic.addItem("Predeterminado del sistema", "")
        for val, label in v.mics():
            self.mic.addItem(label, val)
        self.mic.setCurrentIndex(max(0, self.mic.findData(store.get("voice_mic", ""))))
        self.mic.currentIndexChanged.connect(lambda _: v.set_mic(self.mic.currentData()))
        lay.addWidget(self.group(self.row("Responder con voz", self.speak), self.row("Calidad", self.vq, True), self.row("Micrófono", self.mic, True)))

    def page_images(self, lay):
        self.par = QSpinBox(toolTip="Generaciones a la vez al elegir varias (más es más rápido pero gasta más cuota)")
        self.par.setRange(1, 6)
        self.par.setValue(int(store.get("parallel", 3)))
        self.par.setFixedWidth(70)
        self.par.valueChanged.connect(lambda v: store.put("parallel", v))
        self.bg = QComboBox(toolTip="Color de fondo que piden los prompts (se recorta al importar)")
        self.bg.setEditable(True)
        self.bg.addItems(["#FF00FF", "", "#00FF00", "blanco sólido", "negro sólido"])
        self.bg.setCurrentText(store.get("prompt_bg", "#FF00FF"))
        self.bg.setFixedWidth(130)
        self.bg.currentTextChanged.connect(lambda t: store.put("prompt_bg", t.strip()))
        self.verify = QCheckBox(toolTip="Comprueba que lo generado sea el mismo personaje (reintenta una vez si no se parece)")
        self.verify.setChecked(bool(store.get("verify_identity", True)))
        self.verify.toggled.connect(lambda v: store.put("verify_identity", bool(v)))
        self.clean = QCheckBox(toolTip="Revisa las piezas sueltas de cada cuadro al importar hojas")
        self.clean.setChecked(bool(store.get("ai_clean", True)))
        self.clean.toggled.connect(lambda v: store.put("ai_clean", bool(v)))
        lay.addWidget(self.group(self.row("En paralelo", self.par), self.row("Fondo", self.bg)))
        lay.addWidget(self.group(self.row("Verificar identidad", self.verify), self.row("Limpiar piezas sueltas", self.clean)))

    def page_link(self, lay):
        lay.addWidget(self.link_box())

    def link_box(self) -> QFrame:
        """Vínculo con otro equipo (celular u otra PC): un código compartido, ruta local (LAN) y/o relay en tu servidor aipi."""
        box = QFrame(objectName="card")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(12)
        box.setToolTip("Vincula este equipo con otro (celular u otra PC) para darle órdenes («dile al celular que abra Maps») y pasarle archivos. Un equipo crea el "
                       "código y el otro lo escribe. En la misma red se conectan solos; entre redes distintas hace falta el enlace de tu servidor aipi. "
                       "Los mensajes van firmados pero no cifrados.")
        self.l_name, self.l_relay, self.l_accept = QLineEdit(), QLineEdit(), QComboBox()
        self.l_name.setPlaceholderText("nombre de este equipo")
        self.l_relay.setPlaceholderText("enlace del servidor aipi (?key=…) · vacío = misma red")
        for label, val in (("Preguntar antes de ejecutar sus órdenes", "ask"), ("Ejecutar sin preguntar", "auto"), ("No aceptar órdenes", "off")):
            self.l_accept.addItem(label, val)
        for w in (self.l_name, self.l_relay, self.l_accept):
            v.addWidget(w)
        self.l_code = QLabel()
        self.l_code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.l_state = QLabel(objectName="hint")
        self.l_state.setWordWrap(True)
        v.addWidget(self.l_code)
        row = QHBoxLayout()
        for ic, tip, fn, kind in (("plus", "Crear vínculo", self.link_new, "ibp"), ("link", "Unirme con un código…", self.link_join, "ib"), ("x", "Desvincular", self.link_off, "ibd"),
                                  ("upload", "Enviar archivo…", self.link_file, "ib")):
            row.addWidget(ibtn(ic, tip, fn, kind))
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(self.l_state)
        self.l_name.editingFinished.connect(self.link_save)
        self.l_relay.editingFinished.connect(self.link_save)
        self.l_accept.currentIndexChanged.connect(self.link_save)
        t = QTimer(self)
        t.timeout.connect(self.link_refresh)
        t.start(2000)
        self.link_load()
        return box

    def link_load(self):
        from . import link
        c = link.conf()
        ai = (store.get("ai", {}) or {}).get("chat", {})
        for w, val in ((self.l_name, c["name"]), (self.l_relay, c["relay"] or (ai.get("url", "") if ai.get("kind") == "server" else ""))):
            w.blockSignals(True)
            w.setText(val)
            w.blockSignals(False)
        self.l_accept.blockSignals(True)
        self.l_accept.setCurrentIndex(max(0, self.l_accept.findData(c["accept"])))
        self.l_accept.blockSignals(False)
        self.link_refresh()

    def link_refresh(self):
        from . import link
        code = link.conf()["code"]
        self.l_code.setText(f"Código: {link.show_code(code)}" if code else "Sin vincular")
        self.l_state.setText(self.pet.hub.link.status())

    def link_save(self, *_):
        from . import link
        link.save(name=self.l_name.text().strip() or link.conf()["name"], relay=self.l_relay.text().strip(), accept=self.l_accept.currentData())
        self.pet.hub.link.start()  # el nombre y el relay cambian lo que anuncia y a dónde se conecta

    def link_new(self):
        from . import link
        link.save(code=link.new_code())
        self.link_save()
        self.pet.say("Escribe ese código en el otro equipo («Unirme con un código»).", 8000)

    def link_join(self):
        from PySide6.QtWidgets import QInputDialog
        from . import link
        text, ok = QInputDialog.getText(self, "Unirme", "Código del otro equipo:")
        code = link.clean_code(text) if ok else ""
        if len(code) == 12:
            link.save(code=code)
            self.link_save()
        elif ok:
            self.l_state.setText("✗ El código tiene 12 letras o números (ABCD-EFGH-JKMN).")

    def link_off(self):
        from . import link
        link.save(code="")
        store.put("link_peers", {})
        self.pet.hub.link.stop()
        self.link_refresh()

    def link_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Enviar al otro equipo", str(Path.home()))
        if path:
            self.pet.hub.send_file(path)

    def binary_row(self, tool: str, label: str, hint: str) -> QFrame:
        box = QFrame(objectName="card")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(12)
        v.addWidget(QLabel(label, toolTip=hint))
        row = QHBoxLayout()
        edit = QLineEdit(store.get(binaries.SETTING[tool], ""))
        edit.editingFinished.connect(lambda: self.save_bin(tool))
        row.addWidget(edit, 1)
        row.addWidget(ibtn("folder", "Examinar…", lambda: self.browse(tool)))
        row.addWidget(ibtn("search", "Detectar automáticamente", lambda: self.detect(tool)))
        row.addWidget(ibtn("check", "Probar", lambda: self.test(tool), "ibp"))
        v.addLayout(row)
        st = QLabel(objectName="hint")
        st.setWordWrap(True)
        v.addWidget(st)
        self.bins[tool] = (edit, st)
        return box

    def api_row(self, what: str, label: str) -> QFrame:
        """Usar un binario o una API (oficial o propia, con la misma forma que la de OpenAI / Anthropic) para chat o imágenes."""
        box = QFrame(objectName="card")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(12)
        v.addWidget(QLabel(label))
        mode = QComboBox()
        mode.addItem("Binario (CLI)", "binary")
        mode.addItem("API", "api")
        kind = QComboBox()
        kind.addItem("OpenAI (o propio)", "openai")
        if what == "chat":
            kind.addItem("Anthropic (o propio)", "anthropic")
        kind.addItem("Servidor aipi", "server")
        url, key, model = QLineEdit(), QLineEdit(), QLineEdit()
        key.setEchoMode(QLineEdit.Password)
        url.setPlaceholderText("URL base · vacío = oficial (aipi: tu enlace con ?key=…)")
        key.setPlaceholderText("clave · vacío = variable de entorno")
        model.setPlaceholderText("modelo · vacío = predeterminado")
        for w in (mode, kind, url, key, model):
            v.addWidget(w)
        box.setToolTip("Con API el chat solo conversa y ve imágenes (sin terminal ni control del escritorio). La clave se guarda en ~/.fruquis/config.json.")
        row = QHBoxLayout()
        st = QLabel(objectName="hint")
        st.setWordWrap(True)
        row.addWidget(ibtn("check", "Probar", lambda: self.test_api(what), "ibp"))
        row.addWidget(st, 1)
        v.addLayout(row)
        self.apis[what] = (mode, kind, url, key, model, st)
        for w in (mode, kind):
            w.currentIndexChanged.connect(lambda *_: self.save_api(what))
        for w in (url, key, model):
            w.editingFinished.connect(lambda: self.save_api(what))
        return box

    def save_api(self, what: str):
        mode, kind, url, key, model, _ = self.apis[what]
        ai = dict(store.get("ai", {}) or {})
        ai[what] = {"mode": mode.currentData(), "kind": kind.currentData(), "url": url.text().strip(), "key": key.text().strip(), "model": model.text().strip()}
        store.put("ai", ai)

    def test_api(self, what: str):
        from . import provider
        self.save_api(what)
        st = self.apis[what][5]
        st.setText("Probando…")
        self.job.run(lambda: provider.test(what), lambda r, e: st.setText(f"✗ {e}" if e else ("✓ " if r[0] else "✗ ") + r[1].lstrip("✓ ")))

    def enter(self, **kw):
        for what, (mode, kind, url, key, model, st) in self.apis.items():
            c = (store.get("ai", {}) or {}).get(what) or {}
            for w in (mode, kind, url, key, model):
                w.blockSignals(True)
            mode.setCurrentIndex(max(0, mode.findData(c.get("mode", "binary"))))
            kind.setCurrentIndex(max(0, kind.findData(c.get("kind", "openai"))))
            url.setText(c.get("url", ""))
            key.setText(c.get("key", ""))
            model.setText(c.get("model", ""))
            for w in (mode, kind, url, key, model):
                w.blockSignals(False)
            st.setText("")
        for tool, (edit, st) in self.bins.items():
            edit.setPlaceholderText(f"automático: {binaries.detect(tool) or 'no encontrado'}")
            edit.setText(store.get(binaries.SETTING[tool], ""))
            st.setText("")
        o = store.get("chat_opts", {})
        for w, val in ((self.model, o.get("model", "haiku")), (self.effort, o.get("effort", "medium"))):
            w.blockSignals(True)
            w.setCurrentText(val)
            w.blockSignals(False)
        for cb, key, default in ((self.term, "tools", True), (self.see, "see", False), (self.ctl, "control", False), (self.web, "browser", False)):
            cb.blockSignals(True)
            cb.setChecked(o.get(key, default))
            cb.blockSignals(False)

    def save_bin(self, tool: str):
        edit, _ = self.bins[tool]
        store.put(binaries.SETTING[tool], edit.text().strip())

    def browse(self, tool: str):
        path, _ = QFileDialog.getOpenFileName(self, f"Binario de {tool}", str(Path.home()))
        if path:
            self.bins[tool][0].setText(path)
            self.save_bin(tool)
            self.test(tool)

    def detect(self, tool: str):
        edit, st = self.bins[tool]
        found = binaries.detect(tool)
        edit.setText("")
        self.save_bin(tool)  # vacío = automático
        st.setText(f"Automático: {found}" if found else f"No encontré «{tool}» en tu sistema. Instálalo o elige la ruta con Examinar.")

    def test(self, tool: str):
        edit, st = self.bins[tool]
        path = edit.text().strip() or binaries.detect(tool) or ""
        st.setText("Probando…")

        def work():
            ok, txt = binaries.check(path)
            if ok and tool == "codex":
                from . import imagegen
                ok2, txt2 = imagegen.status()
                txt += f" · {'sesión de ChatGPT activa' if ok2 else 'sin sesión: ejecuta `codex login`'}"
            return ok, txt, path
        self.job.run(work, lambda r, e: st.setText(f"✗ {e}" if e else f"{'✓' if r[0] else '✗'} {r[1]}  ·  {r[2]}"))

    def fill_monitors(self, *_):
        """Una casilla por monitor (mismo número que «Identificar» y que las órdenes de voz); se guardan los apagados por nombre."""
        while self.mon_box.count():
            self.mon_box.takeAt(0).widget().deleteLater()
        off = store.get("screens_off", [])
        for i, s in enumerate(QApplication.screens()):
            g = s.geometry()
            cb = QCheckBox(f"Monitor {i + 1} · {s.name()} · {g.width()}×{g.height()}")
            cb.setChecked(s.name() not in off)
            cb.toggled.connect(lambda on, n=s.name(), cb=cb: self.set_monitor(n, on, cb))
            self.mon_box.addWidget(cb)

    def set_monitor(self, name: str, on: bool, cb: QCheckBox):
        off = [n for n in store.get("screens_off", []) if n != name] + ([] if on else [name])
        if all(s.name() in off for s in QApplication.screens()):  # al menos uno encendido
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
            return
        store.put("screens_off", off)
        self.pet.load_screens()  # si estaba en uno apagado, se va a otro en su siguiente revisión

    def identify(self):
        """Número grande en el centro de cada monitor durante 3 s."""
        self.marks = []
        for i, s in enumerate(QApplication.screens()):
            lb = QLabel(f"{i + 1}")
            lb.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
            lb.setAttribute(Qt.WA_ShowWithoutActivating)
            lb.setAlignment(Qt.AlignCenter)
            lb.setStyleSheet("background:#6b4fbb;color:white;font-size:140px;font-weight:bold")
            lb.setGeometry(s.geometry().center().x() - 120, s.geometry().center().y() - 120, 240, 240)
            lb.show()
            self.marks.append(lb)
        QTimer.singleShot(3000, lambda: [m.close() for m in self.marks])

    def apply_size(self):
        scale = round(self.size.value() / 100, 2)
        store.put("scale", scale)
        self.pet.set_scale(scale)

    def voice_state(self):
        self.vbar.hide()
        v = self.pet.voice
        self.vstate.setText("✓ Modelo de voz disponible" if v.have() else f"⬇ Falta descargar el modelo de voz (~{MODELS[v.size] // 1_000_000} MB): se baja al activarlo")

    def voice_progress(self, p: int):
        self.vbar.setVisible(p < 100)
        self.vbar.setValue(p)
        self.vstate.setText(f"Descargando el modelo de voz… {p}%" if p < 100 else "Instalando el modelo…")

    def set_voice(self, on: bool):
        store.put("voice", on)
        self.pet.voice.enable(on)
        if on:
            self.pet.say("Descargando el modelo de voz la primera vez… luego di mi nombre", 7000)

    def save_chat(self, *_):
        store.put("chat_opts", {**store.get("chat_opts", {}), "model": self.model.currentText(), "effort": self.effort.currentText(), "tools": self.term.isChecked(),
                                "see": self.see.isChecked(), "control": self.ctl.isChecked(), "browser": self.web.isChecked()})
        if self.sender() is self.ctl and self.ctl.isChecked():
            self.pet.say("Ojo: con «Controlar» activo puedo mover el ratón y teclear. Pulsa ■ en el chat para detenerme.", 6000)

    def reset(self):
        for key in ("bin_claude", "bin_codex", "ai", "scale", "prompt_bg", "chat_opts", "parallel", "verify_identity", "ai_clean", "speak"):
            store.put(key, None)
        self.pet.set_scale(0.6)
        self.enter()
        self.size.setValue(60)
        self.par.setValue(3)
        self.verify.setChecked(True)
        self.clean.setChecked(True)
        self.bg.setCurrentText("#FF00FF")
        self.shell.toast("Ajustes restablecidos")


class JobsView(View):
    """Todo lo que se genera con ChatGPT, de todos los personajes: una card por animación con su estado y las acciones como iconos."""
    title = "Generaciones"
    COLOR = {"en cola": (141, 141, 160), "generando": (138, 106, 224), "lista": (123, 216, 143), "error": (240, 113, 120), "cancelada": (106, 106, 124), "aplicada": (123, 216, 143)}

    def __init__(self, shell):
        super().__init__(shell)
        lay = self.page(margins=(28, 18, 28, 18), spacing=10, scroll=True, width=900)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        bar.addStretch(1)
        self.btns = {k: ibtn(ic, tip, fn, nm) for k, ic, tip, fn, nm in (
            ("clear", "broom", "Limpiar terminadas", lambda: shell.gen.clear_finished(), "ib"), ("cancel_all", "x", "Cancelar todas", shell.gen.cancel_all, "ibd"),
            ("apply_all", "checks", "Aplicar todas las listas", self.apply_all, "ibp"))}
        for b in self.btns.values():
            bar.addWidget(b)
        lay.addLayout(bar)
        self.box = QVBoxLayout()
        self.box.setSpacing(10)
        lay.addLayout(self.box)
        self.empty = QLabel("Nada en curso", objectName="dim", alignment=Qt.AlignCenter)
        lay.addWidget(self.empty)
        lay.addStretch(1)
        shell.gen.changed.connect(self.redraw)

    def enter(self, **kw):
        self.redraw()

    def redraw(self):
        if not self.isVisible() and self.box.count():
            return  # se redibuja al volver a la pantalla
        while self.box.count():
            self.box.takeAt(0).widget().deleteLater()
        jobs = self.shell.gen.jobs
        for j in reversed(jobs):
            if card := self.card(j):
                self.box.addWidget(card)
        self.empty.setVisible(not self.box.count())
        self.btns["apply_all"].setEnabled(any(j.status == "lista" for j in jobs))
        self.btns["cancel_all"].setEnabled(any(j.status in ("en cola", "generando") for j in jobs))
        self.btns["clear"].setEnabled(any(j.status not in ("en cola", "generando", "lista") for j in jobs))

    def card(self, j) -> QFrame | None:
        try:
            c = sprites.get(j.cid)
        except Exception:  # noqa: BLE001 - el personaje se eliminó: su trabajo ya no se muestra
            return None
        box = QFrame(objectName="card")
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(10)
        pic = QLabel(toolTip=c.name)
        pic.setPixmap(avatar(sprites.reference(c), 40))
        row.addWidget(pic)
        mid = QVBoxLayout()
        mid.setSpacing(0)
        mid.addWidget(QLabel(sprites.label(j.anim)))
        mid.addWidget(QLabel(c.name, objectName="dim"))
        row.addLayout(mid, 1)
        r, g, b = self.COLOR.get(j.status, (236, 236, 241))
        chip = QLabel(j.status, objectName="chip")
        chip.setStyleSheet(f"background:rgba({r},{g},{b},45);color:rgb({r},{g},{b})")
        chip.setFixedHeight(22)
        row.addWidget(chip, 0, Qt.AlignVCenter)
        if j.status == "lista":
            row.addWidget(ibtn("eye", "Revisar", lambda j=j: j.plan and self.shell.push("review", cid=j.cid, plan=j.plan, job=j)))
            row.addWidget(ibtn("check", "Aplicar", lambda j=j: self.apply(j), "ibp"))
        elif j.status in ("en cola", "generando"):
            row.addWidget(ibtn("x", "Cancelar", lambda j=j: self.shell.gen.cancel(j), "ibd"))
        v.addLayout(row)
        if j.status == "generando":
            bar = QProgressBar(textVisible=False)
            bar.setRange(0, 0)  # avance indeterminado
            bar.setFixedHeight(4)
            v.addWidget(bar)
        note = j.error if j.status == "error" else j.msg
        if note:
            lb = QLabel(note, objectName="hint", toolTip=note)
            lb.setWordWrap(True)
            v.addWidget(lb)
        return box

    def apply(self, j):
        self.shell.gen.apply(j, self.pet)
        self.shell.toast(f"«{j.anim}» aplicada")

    def apply_all(self):
        ready = [j for j in self.shell.gen.jobs if j.status == "lista"]
        for j in ready:
            self.shell.gen.apply(j, self.pet)
        self.shell.toast(f"{len(ready)} animaciones aplicadas")


class RefineView(View):
    """Mejorar una imagen generada conversando: describes qué está mal («el reverso está mal, no se distingue») y se genera una nueva versión a
    partir de la actual; se puede iterar las veces necesarias, volver a una versión anterior y quedarse con la mejor."""
    title = "Mejorar con chat"
    CHIPS = ("El reverso está mal: debe verse la espalda, no la cara", "Que las vistas se distingan mejor entre sí", "Más nitidez y menos ruido",
             "Conserva más los detalles de la imagen general")

    def __init__(self, shell):
        super().__init__(shell)
        self.cid, self.target, self.versions, self.job, self.busy = "", "neutral", [], Bg(), False
        lay = self.page(spacing=8)
        self.shot = QLabel(alignment=Qt.AlignCenter)
        self.shot.setMinimumHeight(210)
        self.shot.setStyleSheet("background:#0f0f14;border:1px solid #2d2d3a;border-radius:14px")
        lay.addWidget(self.shot, 3)
        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self.show_version)
        row.addWidget(self.combo, 1)
        self.use_btn = ibtn("check", "Usar esta versión", self.use, "ibp")
        row.addWidget(self.use_btn)
        lay.addLayout(row)
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumHeight(110)
        lay.addWidget(self.log, 1)
        chips = QGridLayout()
        chips.setSpacing(6)
        for i, t in enumerate(self.CHIPS):
            b = button(t, lambda t=t: self.input.setText(t), "ghost")
            b.setStyleSheet("font-size:11px;padding:5px 10px;text-align:left")
            chips.addWidget(b, i // 2, i % 2)
        lay.addLayout(chips)
        send = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("¿Qué hay que corregir? Se aplica sobre la versión seleccionada")
        self.input.returnPressed.connect(self.send)
        self.refs = []
        self.clip_btn = ibtn("clip", "Adjuntar imágenes de referencia", self.attach)
        self.send_btn = ibtn("send", "Enviar", self.send, "ibp")
        self.cancel_btn = ibtn("x", "Cancelar", self.cancel, "ibd")
        self.cancel_btn.hide()
        for w in (self.input, self.clip_btn, self.send_btn, self.cancel_btn):
            send.addWidget(w)
        lay.addLayout(send)
        self.status = QLabel(objectName="hint")
        lay.addWidget(self.status)
        self.job.msg.connect(self.status.setText)

    def enter(self, cid="", target="neutral", image=None, **kw):
        from . import imagegen
        if self.busy:
            return
        if cid != self.cid or target != self.target or image:
            c = sprites.get(cid)
            self.cid, self.target, self.versions = cid, target, []
            try:
                if image:
                    first = image
                elif target == "neutral":
                    first = str(imagegen.neutral_ref(c))
                else:
                    first = str(imagegen.animation_ref(c, target))
            except (KeyError, OSError, AttributeError):
                self.shell.toast("No hay imagen que mejorar todavía: genérala o cárgala primero.", 5000)
                return self.shell.back()
            self.versions = [{"path": first, "note": "original"}]
            self.log.setPlainText("")
            self.refresh_combo(0)
        self.title = "Mejorar · " + ("hoja neutral" if target == "neutral" else target)
        self.shell.title.setText(self.title)
        self.input.setFocus()

    def refresh_combo(self, select):
        self.combo.blockSignals(True)
        self.combo.clear()
        for i, v in enumerate(self.versions):
            self.combo.addItem(f"v{i + 1} · {v['note'][:60]}")
        self.combo.blockSignals(False)
        self.combo.setCurrentIndex(select)
        self.show_version()

    def show_version(self, *_):
        i = self.combo.currentIndex()
        if 0 <= i < len(self.versions):
            pm = QPixmap(self.versions[i]["path"])
            self.shot.setPixmap(pm.scaled(740, 230, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not pm.isNull() else QPixmap())

    def attach(self):
        """Si ya hay imágenes adjuntas, el clic las quita; si no, abre el selector."""
        self.refs = [] if self.refs else pick_images(self)
        seticon(self.clip_btn, "check" if self.refs else "clip", f"{len(self.refs)} imagen(es): clic para quitarlas" if self.refs else "Adjuntar imágenes de referencia")

    def send(self):
        from . import imagegen
        text = self.input.text().strip()
        if not text or self.busy or not self.versions:
            return
        base = self.versions[self.combo.currentIndex()]["path"]
        extra, self.refs = self.refs, []
        seticon(self.clip_btn, "clip", "Adjuntar imágenes de referencia")
        if extra:
            text += f"  (+{len(extra)} imagen(es) de referencia)"
        self.busy = True
        self.input.clear()
        self.send_btn.setEnabled(False)
        self.cancel_btn.show()
        self.log.appendPlainText(f"Tú (sobre v{self.combo.currentIndex() + 1}): {text}")
        self.status.setText("Preparando…")
        self.pet.set_busy("working")
        cid, target, bg = self.cid, self.target, store.get("prompt_bg", "#FF00FF")
        self.job.run(lambda: imagegen.refine(cid, base, text, target, self.job.msg.emit, key=("refine", id(self)), background=bg, extra=extra),
                     lambda path, err: self.done(path, err, text))

    def done(self, path, err, text):
        self.busy = False
        self.pet.clear_busy()
        self.send_btn.setEnabled(True)
        self.cancel_btn.hide()
        self.status.setText("")
        if err:
            self.log.appendPlainText(f"✗ {err}")
            return self.shell.toast(err, 6000)
        self.versions.append({"path": path, "note": text})
        self.log.appendPlainText(f"✨ v{len(self.versions)} lista")
        self.refresh_combo(len(self.versions) - 1)
        self.pet.say("¡Nueva versión lista! Míra si quedó mejor ✨", 4000)

    def cancel(self):
        from . import imagegen
        imagegen.cancel(("refine", id(self)))

    def use(self):
        """Se queda con la versión seleccionada: la hoja neutral se guarda; una animación pasa por la pantalla de revisión."""
        from . import imagegen
        path = self.versions[self.combo.currentIndex()]["path"]
        try:
            if self.target == "neutral":
                sprites.set_neutral(self.cid, path)
                self.shell.back()
                self.shell.toast("Hoja neutral actualizada")
            else:
                self.shell.push("review", cid=self.cid, plan=imagegen.plan_from_image(self.cid, self.target, path))
        except SystemExit as e:
            self.shell.toast(str(e), 6000)


class ProfileView(View):
    """Identidad visual y anatomía del personaje (las analiza la IA mirando sus imágenes; son editables). Se incluyen en TODOS los prompts: así lo
    generado se parece al personaje y cada animación se adapta a su cuerpo (una serpiente repta, un pulpo usa tentáculos…)."""
    title = "Identidad y anatomía"

    def __init__(self, shell, lay=None):
        super().__init__(shell)
        self.cid, self.job, self.loading = "", Bg(), False
        lay = lay or self.page(spacing=8)  # con `lay` se incrusta en otra vista (RefsView)
        self.cname, self.cdesc = QLineEdit(), QPlainTextEdit()
        self.cname.setPlaceholderText("Nombre del personaje")
        self.cdesc.setPlaceholderText("Descripción breve")
        self.cdesc.setFixedHeight(60)
        self.gender = QComboBox()  # voz con la que responde (speech.py)
        for label, key in (("Sin definir (voz del sistema)", ""), ("Masculino", "masculino"), ("Femenino", "femenino")):
            self.gender.addItem(label, key)
        for lab, w in (("NOMBRE", self.cname), ("DESCRIPCIÓN", self.cdesc), ("GÉNERO (VOZ)", self.gender)):
            lay.addWidget(QLabel(lab, objectName="section"))
            lay.addWidget(w)
        # personalidad: la usa el chat para contestar como el personaje; se escribe, se busca en la red o se saca de su historia
        self.persona, self.story = QPlainTextEdit(), QPlainTextEdit()
        self.persona.setPlaceholderText("Cómo es y cómo habla: temperamento, muletillas, cómo trata al usuario… (vacío = tierna y breve)")
        self.story.setPlaceholderText("Opcional: la historia del personaje")
        for lab, w, h in (("PERSONALIDAD (CHAT)", self.persona, 70), ("HISTORIA", self.story, 60)):
            lay.addWidget(QLabel(lab, objectName="section"))
            w.setFixedHeight(h)
            lay.addWidget(w)
        prow = QHBoxLayout()
        self.web_btn = ibtn("globe", "Buscar la personalidad en la red", lambda: self.gen_persona(False))
        self.story_btn = ibtn("book", "Sacar la personalidad de la historia", lambda: self.gen_persona(True))
        prow.addWidget(self.web_btn)
        prow.addWidget(self.story_btn)
        prow.addStretch(1)
        lay.addLayout(prow)
        self.identity, self.anatomy, self.actions = QPlainTextEdit(), QPlainTextEdit(), QPlainTextEdit()
        self.identity.setPlaceholderText("Descripción visual precisa: tipo de criatura, colores, rasgos, accesorios, proporciones…")
        self.anatomy.setPlaceholderText("Partes del cuerpo que sí tiene y las que no; cómo se mueve de forma natural…")
        self.actions.setPlaceholderText("Una por línea:  animación: cómo se mueve ESTE personaje en esa animación")
        for lab, w, h in (("IDENTIDAD VISUAL", self.identity, 90), ("ANATOMÍA Y MOVIMIENTO", self.anatomy, 80), ("ACCIONES ADAPTADAS", self.actions, 160)):
            lay.addWidget(QLabel(lab, objectName="section"))
            w.setMinimumHeight(h)
            lay.addWidget(w, 1 if w is self.actions else 0)
        row = QHBoxLayout()
        self.ai_btn = ibtn("sparkles", "Analizar con IA", self.analyze, "ibp")
        row.addWidget(self.ai_btn)
        self.stop_btn = ibtn("x", "Cancelar análisis", self.stop_analysis, "ibd")
        self.stop_btn.hide()
        row.addWidget(self.stop_btn)
        row.addWidget(ibtn("save", "Guardar", self.save))
        row.addStretch(1)
        lay.addLayout(row)
        self.status = QLabel(objectName="hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.save_t = QTimer(self, singleShot=True, interval=900, timeout=self.save)
        for w in (self.identity, self.anatomy, self.actions, self.cdesc, self.persona, self.story):
            w.textChanged.connect(lambda: None if self.loading else self.save_t.start())
        self.cname.textChanged.connect(lambda: None if self.loading else self.save_t.start())
        self.gender.currentIndexChanged.connect(lambda _: None if self.loading else self.save_t.start())

    def enter(self, cid="", **kw):
        self.cid = cid or self.cid
        self.load()
        self.status.setText("")

    def load(self):
        c = sprites.get(self.cid)
        self.loading = True
        self.cname.setText(c.name)
        self.cdesc.setPlainText(c.description)
        self.identity.setPlainText(c.identity)
        self.anatomy.setPlainText(c.anatomy)
        self.actions.setPlainText("\n".join(f"{k}: {v}" for k, v in c.actions.items()))
        self.persona.setPlainText(c.personality)
        self.story.setPlainText(c.story)
        self.gender.setCurrentIndex(max(0, self.gender.findData(c.gender)))
        self.loading = False
        self.ai_btn.setToolTip("Volver a analizar con IA" if c.identity else "Analizar con IA")

    def save(self):
        actions = {}
        for ln in self.actions.toPlainText().splitlines():
            k, _, v = ln.partition(":")
            if k.strip() in sprites.WANTED and v.strip():
                actions[k.strip()] = v.strip()
        sprites.set_profile(self.cid, self.identity.toPlainText().strip(), self.anatomy.toPlainText().strip(), actions,
                            self.cname.text().strip(), self.cdesc.toPlainText().strip(), self.persona.toPlainText().strip(), self.story.toPlainText().strip(),
                            self.gender.currentData())
        if self.cid == self.pet.char.id:
            self.pet.char = sprites.get(self.cid)  # la mascota activa usa el nombre/descripción nuevos
        self.status.setText("Guardado ✓")

    def analyze(self):
        from . import anatomy
        cid = self.cid
        self.ai_btn.setEnabled(False)
        self.stop_btn.show()
        self.status.setText("Analizando las imágenes del personaje con la IA…")
        self.pet.set_busy("reading")
        self.job.run(lambda: anatomy.analyze(cid), self.analyzed)

    def stop_analysis(self):
        self.job.cancel()
        self.analyzed(None, "Análisis cancelado.")

    def gen_persona(self, from_story: bool):
        """Personalidad buscada en internet (personajes conocidos) o deducida de la historia que escribiste."""
        from . import personality
        story = self.story.toPlainText().strip()
        if from_story and not story:
            return self.shell.toast("Escribe primero la historia del personaje.", 4000)
        self.save()
        cid = self.cid
        for b in (self.web_btn, self.story_btn):
            b.setEnabled(False)
        self.stop_btn.show()
        self.status.setText("Leyendo la historia…" if from_story else "Buscando al personaje en internet…")
        self.pet.set_busy("reading" if from_story else "searching")
        self.job.run(lambda: personality.generate(cid, story if from_story else ""), self.analyzed)

    def analyzed(self, r, err):
        self.ai_btn.setEnabled(True)
        for b in (self.web_btn, self.story_btn):
            b.setEnabled(True)
        self.stop_btn.hide()
        self.pet.clear_busy()
        if err:
            self.status.setText("")
            return self.shell.toast(err, 6000)
        self.load()
        if isinstance(r, str):  # personalidad
            if self.cid == self.pet.char.id:
                self.pet.char = sprites.get(self.cid)
            return self.status.setText("Personalidad guardada ✓ — el chat ya contesta así. Puedes corregirla a mano.")
        self.status.setText("Análisis guardado ✓ — se usará en todos los prompts.")
        self.pet.say("¡Ya sé cómo soy! 🐍 Revísalo y corrígelo si hace falta.", 5000)
