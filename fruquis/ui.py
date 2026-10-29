"""Vistas de la ventana única: cuidar, personajes, catálogo de animaciones, prompt, revisión de hoja y nuevo personaje."""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import sprites
from .care import ACTIONS
from .chatui import avatar

LABELS = {"hambre": "Hambre", "limpieza": "Limpieza", "diversion": "Diversión", "energia": "Energía"}


class Bg(QObject):
    """Corre una función lenta (IA, análisis de imagen) fuera del hilo de la interfaz y entrega el resultado."""
    done = Signal(object, str)

    def run(self, fn, cb):
        self.done.connect(lambda r, e: cb(r, e))

        def go():
            try:
                self.done.emit(fn(), "")
            except SystemExit as e:
                self.done.emit(None, str(e))
            except Exception as e:  # noqa: BLE001 - se muestra al usuario
                self.done.emit(None, f"{type(e).__name__}: {e}")
        threading.Thread(target=go, daemon=True).start()


class View(QWidget):
    """Una vista de la ventana única. `enter` se llama cada vez que se muestra (al abrirla y al volver a ella)."""
    title = ""

    def __init__(self, shell):
        super().__init__()
        self.shell, self.pet = shell, shell.pet

    def enter(self, **kw):
        pass

    def page(self, margins=(32, 24, 32, 20), spacing=14) -> QVBoxLayout:
        """Contenido centrado con ancho máximo, como las apps modernas."""
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner.setMaximumWidth(760)
        col = QVBoxLayout(inner)
        col.setContentsMargins(*margins)
        col.setSpacing(spacing)
        outer.addStretch(1)
        outer.addWidget(inner, 100)
        outer.addStretch(1)
        return col


def button(text, fn, name=None):
    b = QPushButton(text, cursor=Qt.PointingHandCursor)
    if name:
        b.setObjectName(name)
    b.clicked.connect(lambda _=False: fn())
    return b


class CareView(View):
    """Tamagotchi minimalista: cuatro barras finas y acciones en píldoras."""
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
            ic = QLabel(self.ICON[k])
            ic.setFixedWidth(24)
            name = QLabel(lab, objectName="dim")
            name.setFixedWidth(80)
            b = QProgressBar(textVisible=False)
            b.setRange(0, 100)
            for w in (ic, name, b):
                row.addWidget(w)
            lay.addLayout(row)
            self.bars[k] = b
        lay.addSpacing(8)
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, act in enumerate(ACTIONS):
            btn = QPushButton(f"{ACTIONS[act][1].split()[0]}  {act.capitalize()}", objectName="pill", cursor=Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, a=act: self.pet.do(a))
            grid.addWidget(btn, i // 3, i % 3)
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
    """Lista de personajes a la izquierda; detalle y acciones a la derecha."""
    title = "Personajes"

    def __init__(self, shell):
        super().__init__(shell)
        self.bg, self.chars, self.sel = Bg(), {}, None
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        side = QFrame(objectName="side")
        side.setFixedWidth(250)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 12, 0, 12)
        self.list = QListWidget()
        self.list.setIconSize(QSize(34, 34))
        sv.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.setContentsMargins(10, 0, 10, 0)
        for lab, fn in (("＋ Nuevo", lambda: shell.push("newchar")), ("Importar", self.imp)):
            row.addWidget(button(lab, fn, "ghost"))
        sv.addLayout(row)
        main.addWidget(side)
        right = QVBoxLayout()
        right.setContentsMargins(28, 24, 28, 20)
        right.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(16)
        self.pic = QLabel()
        titles = QVBoxLayout()
        self.name, self.desc = QLabel(objectName="h1"), QLabel(objectName="dim")
        self.desc.setWordWrap(True)
        titles.addWidget(self.name)
        titles.addWidget(self.desc)
        head.addWidget(self.pic)
        head.addLayout(titles, 1)
        right.addLayout(head)
        self.use_btn = button("Usar este personaje", self.use, "primary")
        right.addWidget(self.use_btn)
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (lab, fn) in enumerate((("Catálogo de animaciones", self.catalog), ("Agregar hoja de sprites", self.add),
                                       ("Prompt para una animación", self.prompt), ("Exportar (.zip)", self.export))):
            grid.addWidget(button(lab, fn), i // 2, i % 2)
        right.addLayout(grid)
        right.addWidget(QLabel("ANIMACIONES", objectName="section"))
        self.rep = QPlainTextEdit(readOnly=True)
        right.addWidget(self.rep, 1)
        self.status = QLabel(objectName="hint")
        right.addWidget(self.status)
        main.addLayout(right, 1)
        self.list.currentRowChanged.connect(self.show_one)

    def enter(self, **kw):
        self.reload(self.sel)

    def reload(self, select=None):
        self.chars = sprites.list_all()
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.chars.values():
            self.list.addItem(QListWidgetItem(QIcon(avatar(sprites.reference(c), 34)), c.name + ("   ●" if c.id == self.pet.char.id else "")))
        self.list.blockSignals(False)
        ids = list(self.chars)
        want = select or self.pet.char.id
        self.list.setCurrentRow(ids.index(want) if want in ids else 0)
        self.show_one()

    def cur(self):
        i = self.list.currentRow()
        return list(self.chars.values())[i] if 0 <= i < len(self.chars) else None

    def show_one(self, _=0):
        c = self.cur()
        if not c:
            return
        self.sel = c.id
        self.pic.setPixmap(avatar(sprites.reference(c), 72))
        self.name.setText(c.name)
        self.desc.setText(f"{c.description}\nCeldas {c.cell[0]}×{c.cell[1]} · {len(c.anims)} animaciones")
        active = c.id == self.pet.char.id
        self.use_btn.setText("Personaje activo ✓" if active else "Usar este personaje")
        self.use_btn.setEnabled(not active)
        self.rep.setPlainText("\n".join(sprites.report(c)))

    def use(self):
        if c := self.cur():
            self.pet.load_character(c)
            self.pet.say(f"¡Ahora soy {c.name}!")
            self.reload(c.id)
            self.shell.toast(f"Ahora es {c.name}")

    def catalog(self):
        if c := self.cur():
            self.shell.push("catalog", cid=c.id)

    def prompt(self):
        if c := self.cur():
            self.shell.push("prompt", cid=c.id)

    def add(self):
        """Hoja de cualquier tamaño: se detectan los cuadros y la IA propone qué animaciones son; luego la revisas."""
        c = self.cur()
        path, _ = QFileDialog.getOpenFileName(self, "Hoja de sprites", "", "Imágenes (*.png *.webp *.jpg)")
        if not c or not path:
            return
        self.status.setText("Analizando la hoja con la IA…")
        self.bg.run(lambda: sprites.plan(c.id, path, ai=True), lambda plan, err: self.planned(c, plan, err))

    def planned(self, c, plan, err):
        self.status.setText("")
        if err:
            return self.shell.toast(err, 5000)
        self.shell.push("review", cid=c.id, plan=plan)

    def export(self):
        c = self.cur()
        if not c:
            return
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
        self.shell.toast(f"Importado: {c.name}")
        self.sel = c.id
        self.reload(c.id)


class CatalogView(View):
    """Catálogo de animaciones de un personaje: vista previa, ajustes al vuelo, probar, reemplazar, eliminar y agregar las que faltan."""

    def __init__(self, shell):
        super().__init__(shell)
        self.cid, self.frames, self.k, self.sel, self.arm = "", [], 0, None, None
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        side = QFrame(objectName="side")
        side.setFixedWidth(240)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 14, 0, 14)
        sv.addWidget(QLabel("  ANIMACIONES", objectName="section"))
        self.list = QListWidget()
        sv.addWidget(self.list, 1)
        main.addWidget(side)
        right = QVBoxLayout()
        right.setContentsMargins(24, 20, 24, 20)
        right.setSpacing(12)
        card = QFrame(objectName="card")
        cv = QVBoxLayout(card)
        self.view = QLabel(alignment=Qt.AlignCenter)
        self.view.setMinimumHeight(250)
        cv.addWidget(self.view)
        right.addWidget(card, 1)
        self.name = QLabel(objectName="h1")
        self.info = QLabel(objectName="dim")
        self.info.setWordWrap(True)
        right.addWidget(self.name)
        right.addWidget(self.info)
        row = QHBoxLayout()
        self.fps, self.mode = QSpinBox(), QComboBox()
        self.fps.setRange(1, 30)
        self.fps.setSuffix(" fps")
        self.mode.addItems(["loop", "pingpong", "once"])
        row.addWidget(self.fps)
        row.addWidget(self.mode)
        row.addStretch(1)
        right.addLayout(row)
        acts = QHBoxLayout()
        self.btns = {k: button(lab, fn, nm) for k, lab, fn, nm in (("test", "▶  Probar en la mascota", self.test, "primary"),
                     ("replace", "Reemplazar", self.replace, None), ("prompt", "Prompt", self.prompt, "ghost"), ("delete", "Eliminar", self.delete, "danger"))}
        for b in self.btns.values():
            acts.addWidget(b)
        right.addLayout(acts)
        main.addLayout(right, 1)
        self.timer = QTimer(self, timeout=self.tick)
        self.arm_t = QTimer(self, singleShot=True, timeout=self.disarm)
        self.list.currentRowChanged.connect(self.pick)
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
        c = self.char()
        self.list.blockSignals(True)
        self.list.clear()
        for n in self.names():
            a = c.anims.get(n)
            it = QListWidgetItem(f"{n}    {a['frames']}" if a else f"{n}    —")
            if not a:
                it.setForeground(QColor("#6a6a7c"))
            self.list.addItem(it)
        self.list.blockSignals(False)
        names = self.names()
        self.list.setCurrentRow(names.index(select) if select in names else 0)
        self.pick(self.list.currentRow())

    def cur(self):
        i = self.list.currentRow()
        return self.names()[i] if i >= 0 else None

    def disarm(self):
        self.arm = None
        self.btns["delete"].setText("Eliminar")

    def pick(self, _=0):
        n, c = self.cur(), self.char()
        self.sel = n
        self.disarm()
        a = c.anims.get(n) if n else None
        self.timer.stop()
        for k in ("test", "delete"):
            self.btns[k].setEnabled(bool(a))
        self.btns["replace"].setText("Reemplazar" if a else "Agregar…")
        for wd in (self.fps, self.mode):
            wd.setEnabled(bool(a))
        w = sprites.WANTED.get(n)
        self.name.setText(n or "")
        if not a:
            self.frames = []
            self.view.setPixmap(QPixmap())
            self.view.setText("Aún no tiene esta animación")
            self.info.setText(f"{w[1].capitalize()}. Mientras tanto usa «{w[3]}»." if w and w[3] else (w[1].capitalize() if w else ""))
            return
        pm = QPixmap(str(a["sheet"]))
        cw, ch = c.cell
        cols = max(1, pm.width() // cw)
        self.frames = [pm.copy((i % cols) * cw, (a["row"] + i // cols) * ch, cw, ch).scaledToHeight(240, Qt.SmoothTransformation) for i in range(a["frames"])]
        for wd in (self.fps, self.mode):
            wd.blockSignals(True)
        self.fps.setValue(a["fps"])
        self.mode.setCurrentText("pingpong" if a.get("pingpong") else ("loop" if a.get("loop", True) else "once"))
        for wd in (self.fps, self.mode):
            wd.blockSignals(False)
        self.info.setText(f"{a['frames']} cuadro{'s' if a['frames'] != 1 else ''}" + (f" · {w[1]}" if w else ""))
        self.k = 0
        self.view.setText("")
        self.timer.start(int(1000 / a["fps"]))

    def tick(self):
        if not self.frames:
            return
        n, mode = len(self.frames), self.mode.currentText()
        self.k += 1
        i = self.k % n
        if mode == "pingpong" and n > 1:
            m = self.k % (2 * n - 2)
            i = m if m < n else 2 * n - 2 - m
        elif mode == "once":
            i = min(self.k, n - 1)
        self.view.setPixmap(self.frames[i])

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
        path, _ = QFileDialog.getOpenFileName(self, f"Hoja con la animación '{n}'", "", "Imágenes (*.png *.webp *.jpg)")
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
            self.btns["delete"].setText("¿Seguro? Pulsa otra vez")
            self.arm_t.start(3000)
            return
        sprites.remove(self.cid, n)
        self.shell.toast(f"«{n}» eliminada")
        self.changed(n)

    def prompt(self):
        self.shell.push("prompt", cid=self.cid, anim=self.cur())

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
        self.bg.addItems(["", "#FF00FF", "#00FF00", "blanco sólido", "negro sólido"])
        self.bg.lineEdit().setPlaceholderText("vacío = transparente")
        self.dist, self.dir, self.action, self.extra = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.dist.setPlaceholderText("vacío = automática (p. ej. 4 columnas × 2 filas)")
        self.dir.setPlaceholderText("vacío = la orientación de la referencia")
        self.extra.setPlaceholderText("opcional")
        for lab, w in (("Animación", self.anim), ("Cuadros", self.frames), ("Fondo", self.bg), ("Distribución", self.dist), ("Dirección", self.dir),
                       ("Movimiento", self.action), ("Detalles", self.extra)):
            form.addRow(QLabel(lab, objectName="dim"), w)
        lay.addLayout(form)
        self.text = QPlainTextEdit()
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addWidget(button("⧉  Copiar prompt", self.copy, "primary"))
        row.addWidget(button("Guardar imagen de referencia", self.ref))
        row.addStretch(1)
        lay.addLayout(row)
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

    def copy(self):
        QApplication.clipboard().setText(self.text.toPlainText())
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
        self.cid, self.plan = "", None
        lay = self.page(spacing=12)
        self.head = QLabel(objectName="dim")
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.text = QPlainTextEdit()
        self.text.setStyleSheet("font-family:monospace;")
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addWidget(button("Aplicar", self.apply, "primary"))
        row.addWidget(button("Cancelar", lambda: self.shell.back()))
        row.addStretch(1)
        lay.addLayout(row)

    def enter(self, cid="", plan=None, **kw):
        if plan is None:
            return
        self.cid, self.plan = cid, plan
        n = len(plan["rows"])
        self.head.setText(f"{n} fila(s) de cuadros detectadas ({[len(r) for r in plan['rows']]})" + (" · propuesta de la IA" if plan["ai"] else "")
                          + ".\nUna por línea: nombre | fps | modo (loop, pingpong, once) | filas (desde 0). Borra una línea para omitirla.")
        self.text.setPlainText("\n".join(f"{o['name']} | {o['fps']} | {o['mode']} | {','.join(str(r) for r in o['rows'])}" for o in plan["anims"]))

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
        self.desc.setPlaceholderText("Descripción visual: la usan los prompts para mantener la identidad")
        self.desc.setFixedHeight(120)
        form.addRow(QLabel("Nombre", objectName="dim"), self.name)
        form.addRow(QLabel("Descripción", objectName="dim"), self.desc)
        form.addRow(QLabel("Celda (ancho×alto)", objectName="dim"), self.size)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(button("Crear personaje", self.create, "primary"))
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)

    def enter(self, **kw):
        self.name.clear()
        self.desc.clear()
        self.name.setFocus()

    def create(self):
        if not self.name.text().strip():
            return self.shell.toast("Ponle un nombre")
        try:
            w, h = (int(v) for v in self.size.text().lower().split("x"))
        except ValueError:
            return self.shell.toast("El tamaño debe verse así: 192x208")
        c = sprites.create(self.name.text().strip(), self.desc.toPlainText(), (w, h))
        self.shell.views["chars"].sel = c.id
        self.shell.back()
        self.shell.toast(f"Creado: {c.name}")
