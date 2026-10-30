"""Ventana única de Fruquis: una sola ventana que cambia de vista (chat, cuidar, personajes, catálogo, prompt…) con historial como un
navegador. Esc, Alt+←, el botón ← y el botón atrás del ratón regresan a la vista anterior; en la primera vista, Esc oculta la ventana."""
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSizeGrip, QStackedWidget, QVBoxLayout, QWidget

from . import store
from .gen import GenManager

ROOTS = (("chat", "💬  Chat"), ("care", "🍙  Cuidar"), ("chars", "🧸  Personajes"), ("settings", "⚙  Ajustes"))
OWNER = {"catalog": "chars", "prompt": "chars", "review": "chars", "newchar": "chars", "refs": "chars", "allprompt": "chars", "neutralprompt": "chars", "genbatch": "chars", "refine": "chars", "profile": "chars"}  # a qué pestaña pertenece cada vista


class FloatChat(QWidget):
    """Chat flotante: una ventanita sin marco, siempre encima, que se abre junto a la mascota y la sigue. Aloja la MISMA vista de chat que la
    ventana principal (misma conversación): al abrir el chat en la ventana, la vista vuelve allí."""
    W, H = 400, 560

    def __init__(self, shell):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.shell, self.user_moved, self.view, self.last = shell, False, None, None
        self.resize(self.W, self.H)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        frame = QFrame(objectName="float")
        outer.addWidget(frame)
        v = QVBoxLayout(frame)
        v.setContentsMargins(0, 0, 0, 6)
        v.setSpacing(0)
        bar = QFrame(objectName="floatbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 6, 6, 6)
        self.title = QLabel("💬", objectName="dim")
        bl.addWidget(self.title, 1)
        for text, tip, fn in (("↗", "Abrir en la ventana", self.to_window), ("✕", "Cerrar", self.shell.close_float)):
            b = QPushButton(text, objectName="ghost", cursor=Qt.PointingHandCursor, toolTip=tip)
            b.setFixedWidth(30)
            b.clicked.connect(fn)
            bl.addWidget(b)
        self.bar = bar
        v.addWidget(bar)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        v.addLayout(self.body, 1)
        grip = QHBoxLayout()
        grip.addStretch(1)
        grip.addWidget(QSizeGrip(self))
        v.addLayout(grip)

    def adopt(self, view: QWidget):
        self.shell.pages.removeWidget(view)
        self.body.addWidget(view)
        view.show()
        self.view = view
        self.title.setText(f"💬  {self.shell.pet.char.name}")

    def release(self):
        if self.view is not None:
            self.body.removeWidget(self.view)
            self.shell.pages.addWidget(self.view)
            self.view = None

    def to_window(self):
        self.shell.open("chat")

    def place(self):
        g = self.shell.pet.geometry()
        scr = (QApplication.screenAt(g.center()) or QApplication.primaryScreen()).availableGeometry()
        x = g.right() + 8 if g.right() + 8 + self.width() <= scr.right() else g.left() - self.width() - 8
        y = g.center().y() - int(self.height() * 0.7)
        self.move(max(scr.left(), min(x, scr.right() - self.width())), max(scr.top(), min(y, scr.bottom() - self.height())))
        self.last = (g.x(), g.y())

    def follow(self):
        """Va con la mascota mientras no la hayas movido tú."""
        g = self.shell.pet.geometry()
        if self.isVisible() and not self.user_moved and (g.x(), g.y()) != self.last:
            self.place()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 52 and (h := self.windowHandle()) is not None:  # arrastrar desde la barra
            self.user_moved = True
            h.startSystemMove()
        else:
            super().mousePressEvent(e)


class MainWindow(QWidget):
    def __init__(self, pet):
        super().__init__(None, Qt.Window)
        self.pet, self.stack, self.views = pet, [], {}
        self.gen = GenManager()  # generaciones en segundo plano: viven con la ventana, no con una vista
        self.float = None
        self.setObjectName("win")
        self.setWindowTitle("Fruquis")
        self.resize(*(store.get("win") or (900, 640)))
        self.size_t = QTimer(self, singleShot=True, interval=600, timeout=lambda: store.put("win", [self.width(), self.height()]))
        self.setMinimumSize(620, 480)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        bar = QFrame(objectName="topbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(6)
        self.back_btn = QPushButton("←", objectName="ghost", cursor=Qt.PointingHandCursor, toolTip="Atrás (Esc)")
        self.back_btn.setFixedWidth(36)
        self.back_btn.clicked.connect(self.back)
        self.title = QLabel(objectName="h2")
        bl.addWidget(self.back_btn)
        bl.addWidget(self.title, 1)
        self.tabs = {}
        for name, lab in ROOTS:
            b = QPushButton(lab, objectName="tab", cursor=Qt.PointingHandCursor, checkable=True)
            b.clicked.connect(lambda _=False, n=name: self.open(n))
            bl.addWidget(b)
            self.tabs[name] = b
        root.addWidget(bar)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self.toast_lb = QLabel(self, objectName="toast")
        self.toast_lb.hide()
        self.toast_t = QTimer(self, singleShot=True, timeout=self.toast_lb.hide)
        QShortcut(QKeySequence("Alt+Left"), self, self.back)

    def add_view(self, name: str, view: QWidget):
        self.views[name] = view
        self.pages.addWidget(view)

    # ---- navegación ----
    def open(self, name: str, near: QWidget | None = None, **kw):
        """Abre una vista como inicio de un historial nuevo (las pestañas)."""
        was_hidden = not self.isVisible()
        self.stack = []
        self.push(name, **kw)
        if was_hidden:
            self.place(near)
        self.show()
        self.raise_()
        self.activateWindow()

    def push(self, name: str, **kw):
        self.stack.append((name, kw))
        self.render()

    def back(self):
        if len(self.stack) > 1:
            self.stack.pop()
            self.render()
        else:
            self.hide()

    # ---- chat flotante ----
    def float_open(self) -> bool:
        return self.float is not None and self.float.isVisible()

    def open_float(self):
        """Abre el chat junto a la mascota (la vista de chat se muda de la ventana principal a la flotante)."""
        if self.float is None:
            self.float = FloatChat(self)
        if not self.float_open():
            if self.isVisible() and self.current() == "chat":
                self.hide()
            self.float.adopt(self.views["chat"])
            self.views["chat"].enter()
            self.float.user_moved = False
            self.float.place()
            self.float.show()
        self.float.raise_()
        self.float.activateWindow()
        self.views["chat"].box.setFocus()

    def close_float(self):
        if self.float is not None:
            self.float.release()
            self.float.hide()

    def toggle_float(self):
        self.close_float() if self.float_open() else self.open_float()

    def follow_float(self):
        if self.float_open():
            self.float.follow()

    def render(self):
        name, kw = self.stack[-1]
        if name == "chat" and self.float is not None and self.float.view is not None:  # el chat vuelve a la ventana principal
            self.close_float()
        v = self.views[name]
        self.pages.setCurrentWidget(v)
        v.enter(**kw)
        self.title.setText(v.title)
        self.back_btn.setVisible(len(self.stack) > 1)
        owner = OWNER.get(name, name)
        for n, b in self.tabs.items():
            b.setChecked(n == owner)

    def current(self) -> str | None:
        return self.stack[-1][0] if self.stack and self.isVisible() else None

    def place(self, near: QWidget | None):
        """Al abrirse de cero: junto al botón 💬 si vino de él; si no, centrada en la pantalla de la mascota."""
        scr = (QApplication.screenAt((near.geometry().center() if near else self.pet.geometry().center())) or QApplication.primaryScreen()).availableGeometry()
        if near:
            b = near.geometry()
            x = min(max(b.right() - self.width(), scr.left()), scr.right() - self.width())
            y = b.top() - self.height() - 8
            self.move(x, y if y >= scr.top() else min(b.bottom() + 8, scr.bottom() - self.height()))
        else:
            self.move(scr.center() - QPoint(self.width() // 2, self.height() // 2))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.size_t.start()  # recuerda el tamaño elegido (con un pequeño retardo para no escribir en cada píxel)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:  # llega aquí si ningún control (p. ej. una lista desplegable abierta) la consumió
            self.back()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.BackButton:  # botón atrás del ratón, como en los navegadores
            self.back()
        else:
            super().mousePressEvent(e)

    # ---- avisos ----
    def toast(self, text: str, ms: int = 2600):
        self.toast_lb.setText(text)
        self.toast_lb.adjustSize()
        self.toast_lb.move((self.width() - self.toast_lb.width()) // 2, 64)
        self.toast_lb.show()
        self.toast_lb.raise_()
        self.toast_t.start(ms)
