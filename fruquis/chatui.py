"""Chat de Fruquis con patrones actuales de interfaces de IA (Claude, ChatGPT, Gemini): respuesta que se escribe en vivo con cursor y botón de
detener, texto del asistente sin burbuja y mensaje tuyo en píldora, compositor con modelo / esfuerzo / terminal visibles, acciones copiar y
regenerar, errores con reintento, micro-textos de "pensando" y atajos (Enter envía, Shift+Enter salto, Ctrl+N nuevo chat)."""
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from . import chat, sprites, store
from .app import clip

BG, PANEL, USER, TEXT, DIM, ACCENT, LINE = "#16161c", "#1f1f27", "#34304a", "#ececf1", "#8d8da0", "#8a6ae0", "#2d2d3a"
CSS = f"""
#root {{ background:{BG}; font-family:'Inter','Segoe UI','Noto Sans',sans-serif; }}
#head {{ background:{PANEL}; border-bottom:1px solid {LINE}; }}
#name {{ color:{TEXT}; font-size:15px; font-weight:600; }}
#state {{ color:{DIM}; font-size:11px; }}
QScrollArea {{ border:none; background:{BG}; }}
#feed {{ background:{BG}; }}
QScrollBar:vertical {{ background:{BG}; width:8px; margin:0; }}
QScrollBar::handle:vertical {{ background:#34343f; border-radius:4px; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:#45455a; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
#bar {{ background:{PANEL}; border:1px solid #38384a; border-radius:18px; }}
QPlainTextEdit {{ background:transparent; color:{TEXT}; border:none; font-size:14px; selection-background-color:{ACCENT}; }}
#send {{ background:{ACCENT}; color:white; border:none; border-radius:15px; font-size:14px; }}
#send:hover {{ background:#9b80ee; }}
#send:disabled {{ background:#34343f; color:#6e6e82; }}
#ghost {{ background:transparent; color:{DIM}; border:none; font-size:12px; padding:4px 8px; border-radius:8px; }}
#ghost:hover {{ background:#2a2a36; color:{TEXT}; }}
#act {{ background:transparent; color:#6e6e82; border:none; font-size:11px; padding:2px 6px; border-radius:6px; }}
#act:hover {{ background:#2a2a36; color:{TEXT}; }}
#chip {{ background:{PANEL}; color:{TEXT}; border:1px solid #38384a; border-radius:14px; padding:8px 14px; font-size:12px; text-align:left; }}
#chip:hover {{ border:1px solid {ACCENT}; background:#252532; }}
QComboBox#opt {{ background:transparent; color:{DIM}; border:none; font-size:11px; padding:2px 6px; border-radius:8px; }}
QComboBox#opt:hover {{ background:#2a2a36; color:{TEXT}; }}
QComboBox#opt::drop-down {{ width:0; border:none; }}
QComboBox QAbstractItemView {{ background:{PANEL}; color:{TEXT}; selection-background-color:{ACCENT}; border:1px solid #38384a; outline:none; }}
QCheckBox#opt {{ color:{DIM}; font-size:11px; spacing:5px; padding:2px 4px; }}
QCheckBox#opt:hover {{ color:{TEXT}; }}
QCheckBox#opt::indicator {{ width:12px; height:12px; border-radius:6px; border:1px solid #55556a; background:transparent; }}
QCheckBox#opt::indicator:checked {{ background:{ACCENT}; border:1px solid {ACCENT}; }}
"""
SUGGEST = (("💡", "¿Qué me recomiendas hacer ahora?"), ("🪟", "Revisa en qué ventana estoy"), ("✨", "Cuéntame algo curioso"))
THINK = ("Pensando", "Dándole vueltas", "Casi lo tengo", "Revisando")
MODELS = (("Haiku", "haiku"), ("Sonnet", "sonnet"), ("Opus", "opus"))
EFFORTS = (("esfuerzo bajo", "low"), ("esfuerzo medio", "medium"), ("esfuerzo alto", "high"))


def avatar(path, size) -> QPixmap:
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, size, size))
    p.setClipPath(clip)
    p.fillRect(0, 0, size, size, QColor("#2b2447"))
    if path:
        p.drawPixmap(0, int(size * 0.02), QPixmap(str(path)).scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
    p.end()
    return out


def text_label(text: str, mine: bool, error: bool = False) -> QLabel:
    lb = QLabel()
    lb.setTextFormat(Qt.MarkdownText)
    lb.setText(text)
    lb.setWordWrap(True)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
    lb.setOpenExternalLinks(True)
    if mine:  # píldora suave a la derecha
        lb.setStyleSheet(f"background:{USER};color:{TEXT};border-radius:18px;padding:9px 15px;font-size:14px")
    else:  # el asistente va sin burbuja, como texto sobre el fondo
        lb.setStyleSheet(f"background:transparent;color:{'#f0a0a0' if error else TEXT};padding:2px 2px;font-size:14px")
    return lb


class Composer(QPlainTextEdit):
    """Enter envía, Shift+Enter hace salto de línea; crece hasta 6 líneas."""

    def __init__(self, on_send, on_change):
        super().__init__()
        self.on_send = on_send
        self.setFixedHeight(34)
        self.document().documentLayout().documentSizeChanged.connect(lambda s: self.setFixedHeight(int(min(max(34, s.height() + 12), 140))))
        self.textChanged.connect(on_change)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ShiftModifier:
            self.on_send()
        else:
            super().keyPressEvent(e)


class ChatView(QWidget):
    """Vista de chat de la ventana única; la navegación (Esc, atrás) la maneja la ventana."""
    title = "Chat"

    def __init__(self, shell, bridge):
        super().__init__()
        self.setObjectName("root")
        self.setStyleSheet(CSS)
        self.shell, self.pet, self.hist, self.last_user = shell, shell.pet, [], ""
        self.cid, self.log = "", []
        self.waiting, self.cancelled, self.typing, self.n, self.welcome = False, False, None, 0, None
        self.reveal_t, self.reveal_full, self.reveal_lb, self.last_actions = None, "", None, None
        outer = QHBoxLayout(self)  # contenido centrado con ancho máximo, como ChatGPT o Claude
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner.setMaximumWidth(780)
        outer.addStretch(1)
        outer.addWidget(inner, 100)
        outer.addStretch(1)
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # cabecera
        head = QFrame(objectName="head")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 10, 10, 10)
        self.pic = QLabel()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.who, self.state = QLabel(objectName="name"), QLabel("en línea", objectName="state")
        titles.addWidget(self.who)
        titles.addWidget(self.state)
        new = QPushButton("＋ Nuevo chat", objectName="ghost", cursor=Qt.PointingHandCursor, toolTip="Ctrl+N")
        new.clicked.connect(self.reset)
        hl.addWidget(self.pic)
        hl.addLayout(titles, 1)
        hl.addWidget(new)
        root.addWidget(head)
        # mensajes
        self.scroll = QScrollArea(widgetResizable=True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.feed = QWidget(objectName="feed")
        self.col = QVBoxLayout(self.feed)
        self.col.setContentsMargins(16, 16, 16, 12)
        self.col.setSpacing(14)
        self.col.addStretch(1)
        self.scroll.setWidget(self.feed)
        root.addWidget(self.scroll, 1)
        # compositor: texto arriba, controles visibles abajo (modelo, esfuerzo, terminal) y enviar / detener
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 4, 12, 12)
        bar = QFrame(objectName="bar")
        bv = QVBoxLayout(bar)
        bv.setContentsMargins(14, 6, 8, 6)
        bv.setSpacing(2)
        self.box = Composer(self.send, self.sync)
        bv.addWidget(self.box)
        row = QHBoxLayout()
        row.setSpacing(2)
        opts = store.get("chat_opts", {})
        self.model, self.effort = QComboBox(objectName="opt"), QComboBox(objectName="opt")
        for cb, items, key, default in ((self.model, MODELS, "model", "haiku"), (self.effort, EFFORTS, "effort", "medium")):
            for lab, val in items:
                cb.addItem(lab, val)
            cb.setCurrentIndex(max(0, cb.findData(opts.get(key, default))))
            cb.setCursor(Qt.PointingHandCursor)
            cb.currentIndexChanged.connect(self.save_opts)
        self.term = QCheckBox("Terminal", objectName="opt", cursor=Qt.PointingHandCursor,
                              toolTip="Si está activa, el personaje puede ejecutar comandos Bash para cumplir lo que pidas")
        self.term.setChecked(opts.get("tools", True))
        self.term.toggled.connect(self.save_opts)
        self.see = QCheckBox("Ver ventana", objectName="opt", cursor=Qt.PointingHandCursor,
                             toolTip="Antes de responder toma una captura de la ventana activa para que el personaje vea su contenido")
        self.see.setChecked(opts.get("see", False))
        self.ctl = QCheckBox("Controlar", objectName="opt", cursor=Qt.PointingHandCursor,
                             toolTip="El personaje puede ver y controlar tu escritorio: mover el ratón, hacer clic y escribir. Desmárcalo para impedirlo.")
        self.ctl.setChecked(opts.get("control", False))
        self.see.toggled.connect(self.save_opts)
        self.ctl.toggled.connect(self.save_opts)
        self.ctl.toggled.connect(self.control_notice)
        self.go = QPushButton("➤", objectName="send", cursor=Qt.PointingHandCursor)
        self.go.setFixedSize(30, 30)
        self.go.clicked.connect(self.on_go)
        for w in (self.model, self.effort, self.term, self.see, self.ctl):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.go)
        bv.addLayout(row)
        wl.addWidget(bar)
        root.addWidget(wrap)
        self.dot_t = QTimer(self, interval=400, timeout=self.pulse)
        self.rev_t = QTimer(self, interval=16, timeout=self.step_reveal)
        QShortcut(QKeySequence("Ctrl+N"), self, self.reset)
        bridge.reply.connect(self.got)
        self.refresh_char()  # carga la conversación guardada del personaje
        self.sync()

    def save_opts(self, *_):
        store.put("chat_opts", {"model": self.model.currentData(), "effort": self.effort.currentData(), "tools": self.term.isChecked(),
                                "see": self.see.isChecked(), "control": self.ctl.isChecked()})

    def control_notice(self, on: bool):
        self.state.setText("⚠ controla tu escritorio" if on else "en línea")
        if on:
            self.pet.say("Ojo: con «Controlar» activo puedo mover el ratón y teclear. Pulsa ■ para detenerme.", 6000)

    # ---- presentación ----
    def refresh_char(self):
        c = self.pet.char
        if c.id != self.cid and not self.busy():  # otro personaje: su propia conversación
            self.cid = c.id
            self.restore()
        self.who.setText(c.name)
        self.pic.setPixmap(avatar(sprites.reference(c), 38))
        self.box.setPlaceholderText(f"Escríbele a {c.name}…")

    def empty(self):
        self.welcome = QWidget()
        v = QVBoxLayout(self.welcome)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(8)
        big = QLabel()
        big.setPixmap(avatar(sprites.reference(self.pet.char), 88))
        hi = QLabel(f"¿En qué te ayudo?")
        hi.setStyleSheet(f"color:{TEXT};font-size:20px;font-weight:600")
        sub = QLabel("Pregunta, pide ideas o dime que ejecute algo.")
        sub.setStyleSheet(f"color:{DIM};font-size:12px")
        for w in (big, hi, sub):
            v.addWidget(w, 0, Qt.AlignHCenter)
        v.addSpacing(8)
        for icon, t in SUGGEST:
            b = QPushButton(f"{icon}  {t}", objectName="chip", cursor=Qt.PointingHandCursor)
            b.setMinimumWidth(300)
            b.clicked.connect(lambda _=False, t=t: self.send(t))
            v.addWidget(b, 0, Qt.AlignHCenter)
        self.col.insertWidget(0, self.welcome, 1)

    def scroll_end(self):
        QTimer.singleShot(40, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    def width_limit(self, mine: bool) -> int:
        return int(min(self.width(), 780) * (0.78 if mine else 0.9)) - (0 if mine else 40)

    def add(self, text: str, mine: bool, error: bool = False):
        """Agrega un mensaje; devuelve (fila, etiqueta de texto)."""
        if self.welcome is not None:
            self.welcome.deleteLater()
            self.welcome = None
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        lb = text_label(text, mine, error)
        lb.setMaximumWidth(self.width_limit(mine))
        lb.setProperty("mine", mine)
        if mine:
            h.addStretch(1)
            h.addWidget(lb)
        else:
            av = QLabel()
            av.setPixmap(avatar(sprites.reference(self.pet.char), 26))
            h.addWidget(av, 0, Qt.AlignTop)
            h.addWidget(lb, 1)
        self.col.insertWidget(self.col.count() - 1, row)
        self.scroll_end()
        return row, lb

    def add_actions(self, row: QWidget, error: bool):
        """Copiar y regenerar (o reintentar) bajo el último mensaje del asistente; el hueco bajo el anterior se quita."""
        if self.last_actions:
            self.last_actions.deleteLater()
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(34, 0, 0, 0)
        h.setSpacing(0)
        for lab, fn in (("↻ Reintentar" if error else "↻ Regenerar", self.regenerate), ("⧉ Copiar", self.copy_last)):
            if error and "Copiar" in lab:
                continue
            b = QPushButton(lab, objectName="act", cursor=Qt.PointingHandCursor)
            b.clicked.connect(fn)
            h.addWidget(b)
        stamp = QLabel(time.strftime("%H:%M"))
        stamp.setStyleSheet("color:#55556a;font-size:10px;padding-left:6px")
        h.addWidget(stamp)
        h.addStretch(1)
        self.col.insertWidget(self.col.count() - 1, bar)
        self.last_actions = bar
        self.scroll_end()

    # ---- estados ----
    def pulse(self):
        self.n += 1
        if self.typing:
            self.typing.setText(f"<span style='color:{DIM}'>{THINK[(self.n // 5) % len(THINK)]}{'.' * (self.n % 4)}</span>")

    def set_waiting(self, on: bool):
        self.waiting = on
        self.state.setText("pensando…" if on else "en línea")
        if on:
            row, lb = self.add("", False)
            lb.setTextFormat(Qt.RichText)
            self.typing, self.typing_row, self.n = lb, row, 0
            self.pulse()
            self.dot_t.start()
        else:
            self.dot_t.stop()
            if self.typing:
                self.typing_row.deleteLater()
                self.typing = None
        self.sync()

    def busy(self) -> bool:
        return self.waiting or self.reveal_lb is not None

    def sync(self):
        busy = self.busy()
        self.go.setText("■" if busy else "➤")
        self.go.setToolTip("Detener" if busy else "Enviar")
        self.go.setEnabled(busy or bool(self.box.toPlainText().strip()))

    def on_go(self):
        if self.busy():
            self.stop()
        else:
            self.send()

    def stop(self):
        if self.reveal_lb is not None:  # ya está escribiendo: muestra todo de golpe
            self.finish_reveal()
        elif self.waiting:
            self.cancelled = True
            chat.cancel()
            self.pet.clear_busy()
            self.set_waiting(False)
            row, _ = self.add("*Detenido.*", False)

    def reset(self):
        if self.busy():
            return
        while self.col.count() > 1:
            w = self.col.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.hist, self.last_actions, self.log = [], None, []
        self.save_log()
        self.empty()

    # ---- persistencia: la conversación de cada personaje se guarda en ~/.fruquis/chats ----
    def record(self, mine: bool, text: str):
        self.log = (self.log + [{"mine": mine, "text": text}])[-200:]
        self.save_log()

    def save_log(self):
        store.write(store.chat_path(self.cid), self.log)

    def restore(self):
        """Vuelve a dibujar la conversación guardada del personaje actual (o la pantalla de bienvenida si no hay)."""
        while self.col.count() > 1:
            w = self.col.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.welcome, self.last_actions, self.hist = None, None, []
        self.log = store.read(store.chat_path(self.cid), []) or []
        if not self.log:
            return self.empty()
        name = self.pet.char.name
        row = None
        for m in self.log:
            row, _ = self.add(m["text"], m["mine"])
            self.hist.append(f"{'Tú' if m['mine'] else name}: {m['text']}")
        if not self.log[-1]["mine"]:
            self.add_actions(row, chat.is_error(self.log[-1]["text"]))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        for lb in self.feed.findChildren(QLabel):
            if lb.property("mine") is not None:
                lb.setMaximumWidth(self.width_limit(bool(lb.property("mine"))))

    # ---- conversación ----
    def enter(self, **kw):
        self.refresh_char()
        o = store.get("chat_opts", {})  # los valores por defecto se cambian también desde Ajustes
        for cb, key, default in ((self.model, "model", "haiku"), (self.effort, "effort", "medium")):
            cb.blockSignals(True)
            cb.setCurrentIndex(max(0, cb.findData(o.get(key, default))))
            cb.blockSignals(False)
        for cb, key, default in ((self.term, "tools", True), (self.see, "see", False), (self.ctl, "control", False)):
            cb.blockSignals(True)
            cb.setChecked(o.get(key, default))
            cb.blockSignals(False)
        self.state.setText("⚠ controla tu escritorio" if self.ctl.isChecked() else "en línea")
        self.box.setFocus()

    def send(self, text=None):
        text = (text if isinstance(text, str) else self.box.toPlainText()).strip()
        if not text or self.busy():
            return
        self.box.clear()
        self.add(text, True)
        self.hist.append(f"Tú: {text}")
        self.record(True, text)
        self.last_user = text
        self.ask()

    def ask(self):
        c = self.pet.ctx
        ctx = f"(Ventana activa del usuario: {c['title'][:80]})\n" if c else ""
        if self.last_actions:
            self.last_actions.deleteLater()
            self.last_actions = None
        self.cancelled = False
        image = self.snapshot() if (self.see.isChecked() or self.ctl.isChecked()) else None
        self.set_waiting(True)
        self.pet.set_busy("reading" if image else "thinking")
        self.pet.ask_async(ctx + "\n".join(self.hist[-10:]) + f"\n{self.pet.char.name}:", "chat", model=self.model.currentData(),
                           effort=self.effort.currentData(), tools=self.term.isChecked(), image=image, desktop=self.ctl.isChecked())

    def snapshot(self):
        """Captura de la última ventana externa. Oculta un instante las ventanas de Fruquis para que no tapen el contenido."""
        from . import control
        from PySide6.QtCore import QThread
        shell, fl = self.shell, self.shell.float
        shown = (shell.isVisible(), bool(fl and fl.isVisible()))
        for w in (shell, fl, self.pet, self.pet.bubble):
            if w is not None:
                w.hide()
        QApplication.processEvents()
        QThread.msleep(260)
        try:
            path, _ = control.capture(self.pet.ctx)
        except Exception:  # noqa: BLE001 - sin captura se responde igual, solo con el título de la ventana
            path = None
        self.pet.show()
        if shown[0]:
            shell.show()
        if shown[1]:
            fl.show()
        self.box.setFocus()
        return str(path) if path else None

    def regenerate(self):
        if self.busy() or not self.last_user:
            return
        for i in range(self.col.count() - 2, -1, -1):  # quita la última respuesta (fila y acciones)
            w = self.col.itemAt(i).widget()
            if w:
                w.deleteLater()
                if w is not self.last_actions:
                    break
        if self.hist and not self.hist[-1].startswith("Tú:"):
            self.hist.pop()
        if self.log and not self.log[-1]["mine"]:
            self.log.pop()
            self.save_log()
        self.last_actions = None
        self.ask()

    def copy_last(self):
        for line in reversed(self.hist):
            if not line.startswith("Tú:"):
                QApplication.clipboard().setText(line.split(": ", 1)[1])
                self.state.setText("copiado ✓")
                QTimer.singleShot(1500, lambda: self.state.setText("en línea"))
                return

    def got(self, dest: str, text: str):
        self.pet.until = time.monotonic() + 0.5
        if dest == "bubble":
            self.pet.say(text, 12000)
            if self.isVisible():
                self.add(text, False)
        elif dest == "chat":
            if self.cancelled:
                self.cancelled = False
                self.pet.clear_busy()
                return
            self.set_waiting(False)
            self.pet.set_busy("writing")
            err = chat.is_error(text)
            row, lb = self.add("", False, err)
            self.reveal_row, self.reveal_lb, self.reveal_full, self.reveal_err, self.reveal_pos = row, lb, text, err, 0
            self.hist.append(f"{self.pet.char.name}: {text}")
            if not err:
                self.record(False, text)
            self.pet.say(clip(text), 8000)
            self.rev_t.start()
            self.sync()

    # escritura en vivo: el CLI devuelve la respuesta completa, así que se revela por trozos con un cursor parpadeante
    def step_reveal(self):
        n = len(self.reveal_full)
        self.reveal_pos = min(n, self.reveal_pos + max(2, n // 90))
        cursor = "▍" if (self.reveal_pos // 6) % 2 == 0 or self.reveal_pos < n else ""
        self.reveal_lb.setText(self.reveal_full[: self.reveal_pos] + (cursor if self.reveal_pos < n else ""))
        self.scroll_end()
        if self.reveal_pos >= n:
            self.finish_reveal()

    def finish_reveal(self):
        self.rev_t.stop()
        self.reveal_lb.setText(self.reveal_full)
        self.add_actions(self.reveal_row, self.reveal_err)
        self.reveal_lb = None
        self.pet.clear_busy()
        self.sync()
