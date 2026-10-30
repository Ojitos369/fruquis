"""Vistas de la ventana única: cuidar, personajes, catálogo de animaciones, prompt, revisión de hoja y nuevo personaje."""
import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget)

from . import binaries, provider, sprites, store
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
                                       ("Imagen general y hoja neutral", self.refs), ("Prompt / generar animación", self.prompt),
                                       ("Exportar (.zip)", self.export), ("Editar nombre y detalles", self.edit))):
            grid.addWidget(button(lab, fn), i // 2, i % 2)
        right.addLayout(grid)
        self.del_btn = button("Eliminar personaje", self.remove, "danger")
        right.addWidget(self.del_btn)
        right.addWidget(QLabel("ANIMACIONES", objectName="section"))
        self.rep = QPlainTextEdit(readOnly=True)
        right.addWidget(self.rep, 1)
        self.status = QLabel(objectName="hint")
        right.addWidget(self.status)
        self.stop_btn = button("Cancelar análisis", self.stop_analysis, "danger")
        self.stop_btn.hide()
        right.addWidget(self.stop_btn)
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
        self.del_btn.setEnabled(not (sprites.BUNDLED / c.id).is_dir())  # los incluidos con la app no se borran
        self.del_btn.setText("Eliminar personaje")
        self.rep.setPlainText("\n".join(sprites.report(c)))

    def use(self):
        if c := self.cur():
            self.pet.load_character(c, remember=True)
            self.pet.say(f"¡Ahora soy {c.name}!")
            self.reload(c.id)
            self.shell.toast(f"Ahora es {c.name}")

    def remove(self):
        c = self.cur()
        if not c:
            return
        if self.del_btn.text() == "Eliminar personaje":  # confirmación en dos pasos, como en el catálogo
            self.del_btn.setText("¿Seguro? Pulsa otra vez")
            return
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
        self.sel = None
        self.reload()

    def catalog(self):
        if c := self.cur():
            self.shell.push("catalog", cid=c.id)

    def prompt(self):
        if c := self.cur():
            self.shell.push("prompt", cid=c.id)

    def refs(self):
        if c := self.cur():
            self.shell.push("refs", cid=c.id)

    def edit(self):
        if c := self.cur():
            self.shell.push("profile", cid=c.id)

    def add(self):
        """Hoja de cualquier tamaño: se detectan los cuadros y la IA propone qué animaciones son; luego la revisas."""
        c = self.cur()
        path, _ = QFileDialog.getOpenFileName(self, "Hoja de sprites", "", "Imágenes (*.png *.webp *.jpg *.jpeg)")
        if not c or not path:
            return
        self.status.setText("Analizando la hoja con la IA…")
        self.stop_btn.show()
        self.bg.run(lambda: sprites.plan(c.id, path, ai=True), lambda plan, err: self.planned(c, plan, err))

    def stop_analysis(self):
        self.bg.cancel()
        self.planned(None, None, "Análisis cancelado.")

    def planned(self, c, plan, err):
        self.status.setText("")
        self.stop_btn.hide()
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
        self.shell.toast(f"Importado: {c.name} · pulsa «Usar este personaje» para activarlo", 4500)
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
        gen = QHBoxLayout()
        self.btns["gen"] = button("✨  Generar con ChatGPT", self.generate, "primary")
        self.btns["cancel"] = button("Cancelar", self.cancel_gen, "danger")
        self.btns["cancel"].hide()
        gen.addWidget(self.btns["gen"])
        gen.addWidget(self.btns["cancel"])
        self.btns["many"] = button("Generar varias…", self.many, None)
        gen.addWidget(self.btns["many"])
        self.btns["improve"] = button("Mejorar con chat", self.improve, None)
        gen.addWidget(self.btns["improve"])
        self.btns["all"] = button("Prompt general de las faltantes", self.all_prompt, "ghost")
        gen.addWidget(self.btns["all"])
        right.addLayout(gen)
        self.status = QLabel(objectName="hint")
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        self.job = Bg()
        self.job.msg.connect(self.status.setText)
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
            it = QListWidgetItem(f"{sprites.label(n)}    {a['frames']}" if a else f"{sprites.label(n)}    —")
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
        self.btns["gen"].setText("✨  Regenerar con ChatGPT" if a else "✨  Generar con ChatGPT")
        self.btns["improve"].setEnabled(bool(a))
        missing = [x for x in sprites.WANTED if x not in c.anims]
        self.btns["all"].setText(f"Prompt general de las {len(missing)} faltantes" if missing else "Prompt general (no falta ninguna)")
        self.btns["all"].setEnabled(bool(missing))
        for wd in (self.fps, self.mode):
            wd.setEnabled(bool(a))
        w = sprites.WANTED.get(n)
        self.name.setText(sprites.label(n) if n else "")
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
            self.btns["delete"].setText("¿Seguro? Pulsa otra vez")
            self.arm_t.start(3000)
            return
        sprites.remove(self.cid, n)
        self.shell.toast(f"«{n}» eliminada")
        self.changed(n)

    def prompt(self):
        self.shell.push("prompt", cid=self.cid, anim=self.cur())

    def all_prompt(self):
        self.shell.push("allprompt", cid=self.cid)

    def many(self):
        self.shell.push("genbatch", cid=self.cid)

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
        self.gen_btn = button("✨  Generar con ChatGPT", self.generate, "primary")
        self.cancel_btn = button("Cancelar", self.cancel_gen, "danger")
        self.cancel_btn.hide()
        row.addWidget(self.gen_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(button("⧉  Copiar prompt", self.copy))
        row.addWidget(button("Guardar imagen de referencia", self.ref, "ghost"))
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
        row.addWidget(button("Aplicar", self.apply, "primary"))
        self.improve_btn = button("Mejorar con chat", self.improve)
        row.addWidget(self.improve_btn)
        row.addWidget(button("Cancelar", lambda: self.shell.back()))
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
        self.head.setText(f"{n} fila(s) de cuadros detectadas ({[len(r) for r in plan['rows']]})" + (" · propuesta de la IA" if plan["ai"] else "")
                          + ".\nUna por línea: nombre | fps | modo (loop, pingpong, once) | filas (desde 0). Borra una línea para omitirla." + warn)
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
        self.desc.setPlaceholderText("Descripción visual: la usan los prompts para mantener la identidad")
        self.desc.setFixedHeight(120)
        form.addRow(QLabel("Nombre", objectName="dim"), self.name)
        form.addRow(QLabel("Descripción", objectName="dim"), self.desc)
        form.addRow(QLabel("Celda (ancho×alto)", objectName="dim"), self.size)
        self.src_path = ""
        self.src_btn = button("Elegir imagen general (opcional)…", self.pick_src)
        form.addRow(QLabel("Imagen general", objectName="dim"), self.src_btn)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(button("Crear personaje", self.create, "primary"))
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
        self.src_btn.setText("Elegir imagen general (opcional)…")
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
        self.shell.toast(f"Creado: {c.name} · pulsa «Usar este personaje» para activarlo", 4500)


class RefsView(View):
    """Referencias del personaje: la imagen general (la cargas tú) y la hoja neutral de 4 vistas (se genera o se carga). Son solo de
    referencia: sirven para generar cualquier animación con todos los detalles y no aparecen en el catálogo de animaciones."""
    title = "Imagen general y hoja neutral"

    def __init__(self, shell):
        super().__init__(shell)
        self.cid, self.job = "", Bg()
        lay = self.page(spacing=12)
        hint = QLabel("La hoja neutral (frontal, trasera y dos laterales) es la base que se adjunta al generar cualquier animación para mantener "
                      "todos los detalles. Si generas una animación y no existe, se crea primero a partir de la imagen general.", objectName="dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.src_pic, self.src_info = QLabel(alignment=Qt.AlignCenter), QLabel(objectName="dim")
        self.neu_pic, self.neu_info = QLabel(alignment=Qt.AlignCenter), QLabel(objectName="dim")
        cards.addLayout(self.card("IMAGEN GENERAL", self.src_pic, self.src_info,
                                  (("Cargar imagen…", self.load_src, None), ("Identidad y anatomía", self.profile, None),
                                   ("Guardar…", lambda: self.save_ref("source"), "ghost"), ("Quitar", self.clear_src, "danger"))), 1)
        self.gen_btn = button("✨  Generar con ChatGPT", self.gen_neutral, "primary")
        self.improve_btn = button("Mejorar con chat", self.improve_neutral)
        self.neu_btns = (self.gen_btn, self.improve_btn, button("Prompt", self.neutral_prompt, "ghost"), button("Cargar propia…", self.load_neutral, "ghost"),
                         button("Guardar…", lambda: self.save_ref("neutral"), "ghost"), button("Quitar", self.clear_neutral, "danger"))
        cards.addLayout(self.card("HOJA NEUTRAL · 4 VISTAS", self.neu_pic, self.neu_info, None, self.neu_btns), 2)
        lay.addLayout(cards, 1)
        self.cancel_btn = button("Cancelar generación", self.cancel, "danger")
        self.cancel_btn.hide()
        lay.addWidget(self.cancel_btn)
        self.status = QLabel(objectName="hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.codex = QLabel(objectName="hint")
        lay.addWidget(self.codex)
        self.job.msg.connect(self.status.setText)

    def card(self, title, pic, info, specs, buttons=None):
        box = QFrame(objectName="card")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 12, 14, 12)
        v.addWidget(QLabel(title, objectName="section"))
        pic.setMinimumHeight(170)
        v.addWidget(pic, 1)
        info.setWordWrap(True)
        info.setMinimumHeight(40)
        v.addWidget(info)
        row = QGridLayout()  # en cuadrícula: con 5 botones en una fila los textos se cortaban
        for i, b in enumerate(buttons or [button(lab, fn, nm) for lab, fn, nm in specs]):
            row.addWidget(b, i // 3, i % 3)
        v.addLayout(row)
        wrap = QVBoxLayout()
        wrap.addWidget(box)
        return wrap

    def enter(self, cid="", **kw):
        self.cid = cid or self.cid
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
        for pic, f, w, h, empty in ((self.src_pic, c.source, 200, 170, "Sin imagen general"), (self.neu_pic, c.neutral, 430, 170, "Aún no hay hoja neutral")):
            pm = QPixmap(str(f)) if f else QPixmap()
            if f and not pm.isNull():
                pic.setPixmap(pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                pic.setText("")
            else:
                pic.setPixmap(QPixmap())
                pic.setText(empty)
        self.src_info.setText("Referencia de identidad: de aquí salen las 4 vistas." if c.source else "Cárgala para poder generar la hoja neutral.")
        self.neu_info.setText("Orden: frontal · trasera · lateral izquierda · lateral derecha." if c.neutral else
                              ("Lista para generarla con ChatGPT." if (c.source or sprites.reference(c)) else "Carga primero la imagen general."))
        self.gen_btn.setText("✨  Regenerar" if c.neutral else "✨  Generar")
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

    def profile(self):
        self.shell.push("profile", cid=self.cid)

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


class AllPromptView(View):
    """Un solo prompt para pedir varias animaciones: cada una como imagen separada, con sus propias variables."""
    title = "Prompt general de animaciones"

    def __init__(self, shell):
        super().__init__(shell)
        self.c = None
        lay = self.page(spacing=10)
        hint = QLabel("Elige las animaciones. El prompt pide una imagen independiente por cada una y respeta las variables de cada una "
                      "(cuadros, distribución, movimiento…). Edítalo si quieres antes de copiarlo.", objectName="dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        top = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumHeight(190)
        self.list.setStyleSheet("QListWidget::item{padding:4px 10px;margin:1px 4px}")
        top.addWidget(self.list, 2)
        side = QVBoxLayout()
        self.bg = QComboBox()
        self.bg.setEditable(True)
        self.bg.addItems(["#FF00FF", "", "#00FF00", "blanco sólido", "negro sólido"])
        self.bg.setCurrentText(store.get("prompt_bg", "#FF00FF"))
        side.addWidget(QLabel("Fondo", objectName="dim"))
        side.addWidget(self.bg)
        side.addWidget(button("Marcar todas", lambda: self.mark(True), "ghost"))
        side.addWidget(button("Quitar todas", lambda: self.mark(False), "ghost"))
        side.addStretch(1)
        top.addLayout(side, 1)
        lay.addLayout(top)
        self.count = QLabel(objectName="hint")
        lay.addWidget(self.count)
        self.text = QPlainTextEdit()
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addWidget(button("⧉  Copiar prompt general", self.copy, "primary"))
        row.addStretch(1)
        lay.addLayout(row)
        self.list.itemChanged.connect(self.build)
        self.bg.currentTextChanged.connect(self.build)

    def enter(self, cid="", **kw):
        self.c = sprites.get(cid)
        self.list.blockSignals(True)
        self.list.clear()
        for n in (x for x in sprites.WANTED if x not in self.c.anims):
            it = QListWidgetItem(f"{sprites.label(n)}  ·  {sprites.WANTED[n][1]}")
            it.setData(Qt.UserRole, n)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self.build()

    def names(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.Checked]

    def mark(self, on: bool):
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.list.blockSignals(False)
        self.build()

    def build(self, *_):
        names = self.names()
        self.count.setText(f"{len(names)} animación(es) seleccionada(s)")
        self.text.setPlainText(sprites.general_prompt(self.c, names, self.bg.currentText().strip()) if names and self.c else "")

    def copy(self):
        n = len(self.names())
        if not n:
            return self.shell.toast("Marca al menos una animación")
        copy_text(self.text.toPlainText())
        self.pet.say("¡Prompt general copiado! ✓", 3000)
        self.shell.back()
        self.shell.toast(f"Prompt general copiado ✓ ({n} animaciones)")


class NeutralPromptView(View):
    """Prompt para generar la hoja neutral (4 vistas) en cualquier generador de imágenes; se adjunta la imagen general como referencia."""
    title = "Prompt de la hoja neutral"

    def __init__(self, shell):
        super().__init__(shell)
        self.c = None
        lay = self.page(spacing=10)
        hint = QLabel("Adjunta al generador la imagen general del personaje. El resultado tiene que traer las 4 vistas (frontal, trasera, lateral "
                      "izquierda y lateral derecha); luego cárgalo con «Cargar propia…».", objectName="dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        form = QFormLayout()
        form.setVerticalSpacing(8)
        self.bg = QComboBox()
        self.bg.setEditable(True)
        self.bg.addItems(["#FF00FF", "", "#00FF00", "blanco sólido", "negro sólido"])
        self.bg.setCurrentText(store.get("prompt_bg", "#FF00FF"))
        self.extra = QLineEdit()
        self.extra.setPlaceholderText("detalles adicionales (opcional)")
        form.addRow(QLabel("Fondo", objectName="dim"), self.bg)
        form.addRow(QLabel("Detalles", objectName="dim"), self.extra)
        lay.addLayout(form)
        self.text = QPlainTextEdit()
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addWidget(button("⧉  Copiar prompt", self.copy, "primary"))
        row.addWidget(button("Ver imagen general", self.show_src, "ghost"))
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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="body")
        scroll.setWidget(body)
        outer.addWidget(scroll)
        wrap = QHBoxLayout(body)
        inner = QWidget()
        inner.setMaximumWidth(760)
        wrap.addStretch(1)
        wrap.addWidget(inner, 100)
        wrap.addStretch(1)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(10)
        # binarios
        lay.addWidget(QLabel("BINARIOS", objectName="section"))
        self.bins = {}
        for tool, label, hint in (("claude", "Chat (Claude Code CLI)", "Responde en el chat, las ideas y analiza las hojas de sprites."),
                                  ("codex", "Generador de imágenes (Codex CLI · ChatGPT)", "Genera las animaciones y la hoja neutral.")):
            lay.addWidget(self.binary_row(tool, label, hint))
        # IA por API (alternativa a los binarios)
        lay.addSpacing(10)
        lay.addWidget(QLabel("IA POR API", objectName="section"))
        self.apis = {}
        for what, label in (("chat", "Chat, ideas y análisis de hojas"), ("image", "Generador de imágenes")):
            lay.addWidget(self.api_row(what, label))
        # general
        lay.addSpacing(10)
        lay.addWidget(QLabel("MASCOTA", objectName="section"))
        row = QHBoxLayout()
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(30, 120)
        self.size.setValue(int(store.get("scale", 0.6) * 100))
        self.size_lb = QLabel(objectName="dim")
        self.size_lb.setFixedWidth(50)
        row.addWidget(QLabel("Tamaño"))
        row.addWidget(self.size, 1)
        row.addWidget(self.size_lb)
        lay.addLayout(row)
        self.size.valueChanged.connect(lambda v: self.size_lb.setText(f"{v}%"))
        self.size.sliderReleased.connect(self.apply_size)
        self.size_lb.setText(f"{self.size.value()}%")
        lay.addSpacing(10)
        lay.addWidget(QLabel("GENERACIÓN", objectName="section"))
        row = QHBoxLayout()
        self.par = QSpinBox()
        self.par.setRange(1, 6)
        self.par.setValue(int(store.get("parallel", 3)))
        self.par.valueChanged.connect(lambda v: store.put("parallel", v))
        hint = QLabel("generaciones a la vez al elegir varias (más es más rápido pero gasta más cuota)", objectName="dim")
        hint.setWordWrap(True)
        row.addWidget(QLabel("En paralelo"))
        row.addWidget(self.par)
        row.addWidget(hint, 1)
        lay.addLayout(row)
        lay.addSpacing(10)
        lay.addWidget(QLabel("PROMPTS", objectName="section"))
        row = QHBoxLayout()
        self.bg = QComboBox()
        self.bg.setEditable(True)
        self.bg.addItems(["#FF00FF", "", "#00FF00", "blanco sólido", "negro sólido"])
        self.bg.setCurrentText(store.get("prompt_bg", "#FF00FF"))
        self.bg.currentTextChanged.connect(lambda t: store.put("prompt_bg", t.strip()))
        row.addWidget(QLabel("Fondo por defecto"))
        row.addWidget(self.bg, 1)
        lay.addLayout(row)
        lay.addSpacing(10)
        lay.addWidget(QLabel("CHAT", objectName="section"))
        row = QHBoxLayout()
        self.model, self.effort = QComboBox(), QComboBox()
        for cb, items in ((self.model, ("haiku", "sonnet", "opus")), (self.effort, ("low", "medium", "high"))):
            cb.addItems(items)
        self.term = QCheckBox("Permitir que ejecute comandos (Terminal)")
        for lab, w in (("Modelo", self.model), ("Esfuerzo", self.effort)):
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        lay.addLayout(row)
        lay.addWidget(self.term)
        lay.addSpacing(10)
        lay.addWidget(QLabel("VOZ", objectName="section"))
        self.voice = QCheckBox("Escuchar su nombre: al oírlo, dicta tu pedido por voz y trabaja como asistente (reconocimiento local; baja el modelo la primera vez)")
        self.voice.setChecked(bool(store.get("voice", False)))
        self.voice.toggled.connect(self.set_voice)
        lay.addWidget(self.voice)
        self.vstate, self.vbar = QLabel(objectName="dim"), QProgressBar(textVisible=False)
        self.vbar.setRange(0, 100)
        self.vbar.setFixedHeight(6)
        self.vbar.hide()
        self.voice_state()
        v = self.pet.voice
        v.progress.connect(self.voice_progress)
        v.ready.connect(self.voice_state)
        v.problem.connect(lambda _: (self.voice_state(), self.voice.setChecked(False)))
        lay.addWidget(self.vstate)
        lay.addWidget(self.vbar)
        self.vlevel, self.vheard = QProgressBar(textVisible=False), QLabel("Oí: —", objectName="dim")  # prueba en vivo del micrófono
        self.vlevel.setRange(0, 100)
        self.vlevel.setFixedHeight(6)
        self.vlevel.setToolTip("Volumen del micrófono: debe moverse cuando hablas")
        self.vheard.setWordWrap(True)
        v.level.connect(self.vlevel.setValue)
        v.raw.connect(lambda t: self.vheard.setText(f"Oí: {t}"))
        lay.addWidget(self.vlevel)
        lay.addWidget(self.vheard)
        row = QHBoxLayout()
        self.vq = QComboBox()
        for label, key in (("Precisa · small (~480 MB, recomendada)", "small"), ("Rápida · base (~145 MB)", "base")):
            self.vq.addItem(label, key)
        self.vq.setCurrentIndex(max(0, self.vq.findData(v.size)))
        self.vq.currentIndexChanged.connect(lambda _: (v.set_size(self.vq.currentData()), self.voice_state()))
        row.addWidget(QLabel("Calidad"))
        row.addWidget(self.vq, 1)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.mic = QComboBox()
        self.mic.addItem("Predeterminado del sistema", "")
        for val, label in self.pet.voice.mics():
            self.mic.addItem(label, val)
        self.mic.setCurrentIndex(max(0, self.mic.findData(store.get("voice_mic", ""))))
        self.mic.currentIndexChanged.connect(lambda _: self.pet.voice.set_mic(self.mic.currentData()))
        row.addWidget(QLabel("Micrófono"))
        row.addWidget(self.mic, 1)
        lay.addLayout(row)
        lay.addSpacing(10)
        lay.addWidget(QLabel("ESCRITORIO", objectName="section"))
        self.see = QCheckBox("Ver la ventana activa en el chat (toma una captura antes de responder)")
        self.ctl = QCheckBox("Permitir controlar el escritorio: ratón, teclado y ventanas (acciones reales en tu equipo)")
        lay.addWidget(self.see)
        lay.addWidget(self.ctl)
        lay.addSpacing(10)
        lay.addWidget(QLabel("CALIDAD DE LAS IMÁGENES", objectName="section"))
        self.verify = QCheckBox("Verificar con IA que lo generado sea el mismo personaje (reintenta una vez si no se parece)")
        self.verify.setChecked(bool(store.get("verify_identity", True)))
        self.verify.toggled.connect(lambda v: store.put("verify_identity", bool(v)))
        self.clean = QCheckBox("Revisar con IA las piezas sueltas de cada cuadro al importar hojas")
        self.clean.setChecked(bool(store.get("ai_clean", True)))
        self.clean.toggled.connect(lambda v: store.put("ai_clean", bool(v)))
        lay.addWidget(self.verify)
        lay.addWidget(self.clean)
        warn = QLabel("macOS pide permisos de Accesibilidad y de Grabación de pantalla; en Wayland puede no funcionar (usa X11). "
                      "Cada acción queda en ~/.fruquis/ctl.log.", objectName="dim")
        warn.setWordWrap(True)
        lay.addWidget(warn)
        for w in (self.model, self.effort):
            w.currentTextChanged.connect(self.save_chat)
        for w in (self.term, self.see, self.ctl):
            w.toggled.connect(self.save_chat)
        lay.addSpacing(14)
        lay.addWidget(button("Restablecer ajustes", self.reset, "danger"), 0, Qt.AlignLeft)
        lay.addStretch(1)

    def binary_row(self, tool: str, label: str, hint: str) -> QFrame:
        box = QFrame(objectName="card")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        v.addWidget(QLabel(label))
        d = QLabel(hint, objectName="dim")
        d.setWordWrap(True)
        v.addWidget(d)
        row = QHBoxLayout()
        edit = QLineEdit(store.get(binaries.SETTING[tool], ""))
        edit.editingFinished.connect(lambda: self.save_bin(tool))
        row.addWidget(edit, 1)
        row.addWidget(button("Examinar…", lambda: self.browse(tool)))
        row.addWidget(button("Detectar", lambda: self.detect(tool), "ghost"))
        row.addWidget(button("Probar", lambda: self.test(tool), "primary"))
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
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        v.addWidget(QLabel(label))
        mode = QComboBox()
        mode.addItem("Binario local (CLI)", "binary")
        mode.addItem("API", "api")
        kind = QComboBox()
        kind.addItem("Formato OpenAI (OpenAI o servidor propio)", "openai")
        if what == "chat":
            kind.addItem("Formato Anthropic (Claude o servidor propio)", "anthropic")
        kind.addItem("Servidor aipi (claude/codex de tu servidor)", "server")
        url, key, model = QLineEdit(), QLineEdit(), QLineEdit()
        key.setEchoMode(QLineEdit.Password)
        url.setPlaceholderText("URL base; vacío = servidor oficial (servidor aipi: tu enlace personal con ?key=…)")
        key.setPlaceholderText("clave de la API (vacío = variable de entorno)")
        model.setPlaceholderText("modelo; vacío = el predeterminado")
        for w in (mode, kind, url, key, model):
            v.addWidget(w)
        d = QLabel("Con API el chat solo conversa y ve imágenes (sin terminal ni control del escritorio). La clave se guarda en ~/.fruquis/config.json.", objectName="dim")
        d.setWordWrap(True)
        v.addWidget(d)
        row = QHBoxLayout()
        st = QLabel(objectName="hint")
        st.setWordWrap(True)
        row.addWidget(button("Probar", lambda: self.test_api(what), "primary"))
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
        for cb, key, default in ((self.term, "tools", True), (self.see, "see", False), (self.ctl, "control", False)):
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
                                "see": self.see.isChecked(), "control": self.ctl.isChecked()})

    def reset(self):
        for key in ("bin_claude", "bin_codex", "ai", "scale", "prompt_bg", "chat_opts", "parallel", "verify_identity", "ai_clean"):
            store.put(key, None)
        self.pet.set_scale(0.6)
        self.enter()
        self.size.setValue(60)
        self.par.setValue(3)
        self.verify.setChecked(True)
        self.clean.setChecked(True)
        self.bg.setCurrentText("#FF00FF")
        self.shell.toast("Ajustes restablecidos")


class GenBatchView(View):
    """Elegir varias animaciones (faltantes o para reemplazar) y generarlas en paralelo, en segundo plano. Se puede salir de la pantalla:
    el trabajo sigue y la mascota avisa."""
    title = "Generar animaciones"
    COLOR = {"en cola": "#8d8da0", "generando": "#8a6ae0", "lista": "#7bd88f", "error": "#f07178", "cancelada": "#6a6a7c", "aplicada": "#7bd88f"}

    def __init__(self, shell):
        super().__init__(shell)
        self.cid = ""
        lay = self.page(spacing=10)
        hint = QLabel("Marca las animaciones que quieres generar: las faltantes nuevas y/o las existentes para reemplazarlas. Se generan a la vez "
                      "en segundo plano; puedes salir de esta pantalla mientras trabajan.", objectName="dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        top = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumHeight(190)
        self.list.setStyleSheet("QListWidget::item{padding:4px 10px;margin:1px 4px}")
        top.addWidget(self.list, 3)
        side = QVBoxLayout()
        side.addWidget(button("Marcar todas", lambda: self.mark("all"), "ghost"))
        side.addWidget(button("Marcar faltantes", lambda: self.mark("missing"), "ghost"))
        side.addWidget(button("Marcar existentes", lambda: self.mark("existing"), "ghost"))
        side.addWidget(button("Quitar todas", lambda: self.mark(None), "ghost"))
        side.addStretch(1)
        self.go = button("✨  Generar seleccionadas", self.start, "primary")
        side.addWidget(self.go)
        top.addLayout(side, 1)
        lay.addLayout(top)
        self.par_lb = QLabel(objectName="hint")
        lay.addWidget(self.par_lb)
        lay.addWidget(QLabel("COLA", objectName="section"))
        self.queue = QListWidget()
        lay.addWidget(self.queue, 1)
        row = QHBoxLayout()
        self.btns = {k: button(lab, fn, nm) for k, lab, fn, nm in (("review", "Revisar", self.review, None), ("apply", "Aplicar", self.apply_one, None),
                     ("cancel", "Cancelar", self.cancel_one, "danger"), ("cancel_all", "Cancelar todas", self.cancel_all, "danger"), ("apply_all", "Aplicar todas las listas", self.apply_all, "primary"),
                     ("clear", "Limpiar terminadas", lambda: shell.gen.clear_finished(), "ghost"))}
        for b in self.btns.values():
            row.addWidget(b)
        lay.addLayout(row)
        self.err = QLabel(objectName="hint")
        self.err.setWordWrap(True)
        lay.addWidget(self.err)
        shell.gen.changed.connect(self.redraw)
        self.queue.currentRowChanged.connect(self.sel_changed)

    def enter(self, cid="", **kw):
        self.cid = cid or self.cid
        c = sprites.get(self.cid)
        self.list.clear()
        for n in sprites.WANTED:
            have = n in c.anims
            it = QListWidgetItem(f"{sprites.label(n)}  ·  {'reemplazar (ya existe)' if have else 'falta'}")
            it.setData(Qt.UserRole, n)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked if have else Qt.Checked)
            if have:
                it.setForeground(QColor("#8d8da0"))
            self.list.addItem(it)
        self.par_lb.setText(f"En paralelo: {int(store.get('parallel', 3))} a la vez (cámbialo en Ajustes).")
        self.redraw()

    def mark(self, only):
        """only: None = quitar todas, "all" = todas, "missing" = faltantes, "existing" = existentes."""
        c = sprites.get(self.cid)
        for i in range(self.list.count()):
            have = self.list.item(i).data(Qt.UserRole) in c.anims
            on = only == "all" or (only == "missing" and not have) or (only == "existing" and have)
            self.list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def start(self):
        from . import imagegen
        names = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.Checked]
        if not names:
            return self.shell.toast("Marca al menos una animación")
        if not imagegen.provider.image_ready():
            self.shell.toast("No hay generador de imágenes. Elige el binario de Codex o configura una API en Ajustes.", 5000)
            return self.shell.open("settings")
        c = sprites.get(self.cid)
        if not (c.neutral or c.source or sprites.reference(c)):
            return self.shell.toast("Carga primero la imagen general del personaje (Imagen general y hoja neutral).", 5000)
        started = self.shell.gen.start(self.cid, names)
        self.shell.toast(f"Generando {len(started)} en segundo plano" if started else "Esas ya están en curso")

    # ---- cola ----
    def mine(self):
        return [j for j in self.shell.gen.jobs if j.cid == self.cid]

    def redraw(self):
        sel = self.queue.currentRow()
        self.queue.blockSignals(True)
        self.queue.clear()
        for j in self.mine():
            it = QListWidgetItem(f"●  {j.anim}  —  {j.status}" + (f"  ·  {j.msg}" if j.msg and j.status in ("generando", "en cola") else ""))
            it.setForeground(QColor(self.COLOR.get(j.status, "#ececf1")))
            self.queue.addItem(it)
        self.queue.blockSignals(False)
        self.queue.setCurrentRow(min(sel, self.queue.count() - 1) if self.queue.count() else -1)
        self.sel_changed()

    def cur(self):
        i = self.queue.currentRow()
        jobs = self.mine()
        return jobs[i] if 0 <= i < len(jobs) else None

    def sel_changed(self, *_):
        j = self.cur()
        self.btns["review"].setEnabled(bool(j and j.status == "lista"))
        self.btns["apply"].setEnabled(bool(j and j.status == "lista"))
        self.btns["cancel"].setEnabled(bool(j and j.status in ("en cola", "generando")))
        self.btns["cancel_all"].setEnabled(any(x.status in ("en cola", "generando") for x in self.mine()))
        n = sum(x.status == "lista" for x in self.mine())
        self.btns["apply_all"].setEnabled(n > 0)
        self.btns["apply_all"].setText(f"Aplicar todas las listas ({n})" if n else "Aplicar todas las listas")
        self.err.setText(f"✗ {j.error}" if j and j.status == "error" else "")

    def review(self):
        if (j := self.cur()) and j.plan:
            self.shell.push("review", cid=j.cid, plan=j.plan, job=j)

    def apply_one(self):
        if (j := self.cur()) and j.plan:
            self.shell.gen.apply(j, self.pet)
            self.shell.toast(f"«{j.anim}» aplicada")

    def apply_all(self):
        ready = [j for j in self.mine() if j.status == "lista"]
        for j in ready:
            self.shell.gen.apply(j, self.pet)
        self.shell.toast(f"{len(ready)} animaciones aplicadas")

    def cancel_one(self):
        if j := self.cur():
            self.shell.gen.cancel(j)

    def cancel_all(self):
        for j in self.mine():
            self.shell.gen.cancel(j)


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
        self.use_btn = button("Usar esta versión", self.use, "primary")
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
        self.clip_btn = button("📎", self.attach, "ghost")
        self.clip_btn.setToolTip("Adjuntar imágenes de referencia (clic otra vez para quitarlas)")
        self.send_btn = button("✨  Enviar", self.send, "primary")
        self.cancel_btn = button("Cancelar", self.cancel, "danger")
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
        self.clip_btn.setText(f"📎 {len(self.refs)}" if self.refs else "📎")

    def send(self):
        from . import imagegen
        text = self.input.text().strip()
        if not text or self.busy or not self.versions:
            return
        base = self.versions[self.combo.currentIndex()]["path"]
        extra, self.refs = self.refs, []
        self.clip_btn.setText("📎")
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

    def __init__(self, shell):
        super().__init__(shell)
        self.cid, self.job, self.loading = "", Bg(), False
        lay = self.page(spacing=8)
        hint = QLabel("La IA mira las imágenes del personaje y escribe cómo es y qué cuerpo tiene; con eso se adaptan los prompts de cada animación. "
                      "Puedes corregir los textos a mano.", objectName="dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.cname, self.cdesc = QLineEdit(), QPlainTextEdit()
        self.cname.setPlaceholderText("Nombre del personaje")
        self.cdesc.setPlaceholderText("Descripción breve")
        self.cdesc.setFixedHeight(60)
        for lab, w in (("NOMBRE", self.cname), ("DESCRIPCIÓN", self.cdesc)):
            lay.addWidget(QLabel(lab, objectName="section"))
            lay.addWidget(w)
        # personalidad: la usa el chat para contestar como el personaje; se escribe, se busca en la red o se saca de su historia
        self.persona, self.story = QPlainTextEdit(), QPlainTextEdit()
        self.persona.setPlaceholderText("Cómo es y cómo habla: temperamento, muletillas, cómo trata al usuario… (vacío = tierna y breve)")
        self.story.setPlaceholderText("Opcional: pega aquí la historia del personaje y pulsa «Sacar de la historia»")
        for lab, w, h in (("PERSONALIDAD (CHAT)", self.persona, 70), ("HISTORIA", self.story, 60)):
            lay.addWidget(QLabel(lab, objectName="section"))
            w.setFixedHeight(h)
            lay.addWidget(w)
        prow = QHBoxLayout()
        self.web_btn = button("🌐  Buscar personalidad en la red", lambda: self.gen_persona(False))
        self.story_btn = button("📖  Sacar de la historia", lambda: self.gen_persona(True))
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
        self.ai_btn = button("✨  Analizar con IA", self.analyze, "primary")
        row.addWidget(self.ai_btn)
        self.stop_btn = button("Cancelar análisis", self.stop_analysis, "danger")
        self.stop_btn.hide()
        row.addWidget(self.stop_btn)
        row.addWidget(button("Guardar", self.save))
        row.addStretch(1)
        lay.addLayout(row)
        self.status = QLabel(objectName="hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.save_t = QTimer(self, singleShot=True, interval=900, timeout=self.save)
        for w in (self.identity, self.anatomy, self.actions, self.cdesc, self.persona, self.story):
            w.textChanged.connect(lambda: None if self.loading else self.save_t.start())
        self.cname.textChanged.connect(lambda: None if self.loading else self.save_t.start())

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
        self.loading = False
        self.ai_btn.setText("✨  Volver a analizar con IA" if c.identity else "✨  Analizar con IA")

    def save(self):
        actions = {}
        for ln in self.actions.toPlainText().splitlines():
            k, _, v = ln.partition(":")
            if k.strip() in sprites.WANTED and v.strip():
                actions[k.strip()] = v.strip()
        sprites.set_profile(self.cid, self.identity.toPlainText().strip(), self.anatomy.toPlainText().strip(), actions,
                            self.cname.text().strip(), self.cdesc.toPlainText().strip(), self.persona.toPlainText().strip(), self.story.toPlainText().strip())
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
