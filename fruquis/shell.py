"""Ventana única de Fruquis: una sola ventana que cambia de vista (chat, cuidar, personajes, catálogo, prompt…) con historial como un
navegador. Esc, Alt+←, el botón ← y el botón atrás del ratón regresan a la vista anterior; en la primera vista, Esc oculta la ventana."""
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

ROOTS = (("chat", "💬  Chat"), ("care", "🍙  Cuidar"), ("chars", "🧸  Personajes"))
OWNER = {"catalog": "chars", "prompt": "chars", "review": "chars", "newchar": "chars"}  # a qué pestaña pertenece cada vista


class MainWindow(QWidget):
    def __init__(self, pet):
        super().__init__(None, Qt.Window)
        self.pet, self.stack, self.views = pet, [], {}
        self.setObjectName("win")
        self.setWindowTitle("Fruquis")
        self.resize(900, 640)
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

    def render(self):
        name, kw = self.stack[-1]
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
