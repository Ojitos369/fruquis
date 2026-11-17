"""Une el vínculo entre equipos (link.py) con la mascota: recibe órdenes del otro equipo (con confirmación según Ajustes), las ejecuta con el chat
y devuelve el resultado; muestra lo que llega (respuestas, archivos). Paridad con la parte de servicio de Link.kt."""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from . import chat, link, store
from .voice import log

CONFIRM_S = 120  # si nadie contesta el aviso, se rechaza


class LinkHub(QObject):
    ask = Signal(str, object)  # (texto, [respuesta, evento]) → se pregunta en el hilo de la interfaz

    def __init__(self, pet):
        super().__init__()
        self.pet, self.link, self.lock = pet, link.Link(self.on_msg), threading.Lock()
        self.ask.connect(self.on_ask)
        self.link.start()

    def on_ask(self, text: str, box: list):
        box[0] = QMessageBox.question(None, "Fruquis · otro equipo", text) == QMessageBox.Yes
        box[1].set()

    def confirm(self, text: str) -> bool:
        box = [False, threading.Event()]
        self.ask.emit(text, box)
        box[1].wait(CONFIRM_S)
        return box[0]

    def tell(self, text: str):
        self.pet.bridge.reply.emit("bubble", text)

    def parse(self, text: str):
        """(destino, orden) si el pedido habla de otro equipo vinculado; None si no."""
        return link.parse(text, link.known()) if link.conf()["code"] else None

    def reply(self, to: str, mid: str, text: str):
        try:
            self.link.send("result", text, to=to, re=mid)
        except link.LinkError as e:
            log("error", donde="vinculo.respuesta", detalle=str(e))

    def send_task(self, to: str, text: str):
        """Manda la orden en un hilo y avisa a qué equipo y por qué ruta salió (o por qué no)."""
        def run():
            try:
                via = self.link.send("task", text, to=to)
                self.tell(f"📲 Se lo mandé a {to or 'tu otro equipo'} (por {via}). Te aviso cuando responda.")
            except link.LinkError as e:
                self.tell(f"📲 No pude mandarlo: {e}")
        threading.Thread(target=run, daemon=True).start()

    def send_file(self, path: str, to: str = ""):
        def run():
            try:
                via = self.link.send_file(path, to)
                self.tell(f"📤 «{Path(path).name}» enviado (por {via}).")
            except link.LinkError as e:
                self.tell(f"📤 No pude enviarlo: {e}")
        threading.Thread(target=run, daemon=True).start()

    def on_msg(self, m: dict):
        who, kind = m.get("n", "otro equipo"), m.get("type")
        log("vinculo", tipo=kind, de=who, texto=str(m.get("text", ""))[:300])
        if kind == "result":
            self.tell(f"📲 {who}: {m.get('text', '')}")
        elif kind == "file" and m.get("path"):
            self.tell(f"📥 {who} te envió «{Path(m['path']).name}» (en {link.DOWNLOADS})")
        elif kind == "task":
            self.run_task(who, m["id"], str(m.get("text", "")))

    def run_task(self, who: str, mid: str, text: str):
        mode = link.conf()["accept"]
        if mode == "off":
            return self.reply(who, mid, "Ese equipo no acepta órdenes del otro.")
        if mode == "ask" and not self.confirm(f"«{who}» pide:\n\n{text}\n\n¿Lo hago en este equipo?"):
            return self.reply(who, mid, "Lo rechazaron en el otro equipo.")
        if not self.lock.acquire(blocking=False):
            return self.reply(who, mid, "Ese equipo está ocupado con otra orden; reintenta en un momento.")
        try:
            self.tell(f"📲 {who} me pide: {text}")
            o, c = store.get("chat_opts", {}), self.pet.char
            out = chat.ask(f"(Orden enviada desde otro equipo del usuario, «{who}»; ejecútala aquí, en este equipo.)\n{text}", model=o.get("model", "haiku"),
                           effort=o.get("effort", "medium"), tools=bool(o.get("tools", True)), desktop=bool(o.get("control")),
                           persona=(c.name, c.description, c.personality, []), timeout=180)
            self.reply(who, mid, out)
            self.tell(f"📲 Listo lo de {who}: {out}")
        except Exception as e:  # noqa: BLE001 - el otro equipo espera una respuesta pase lo que pase
            log("error", donde="vinculo.orden", detalle=str(e))
            self.reply(who, mid, f"No pude hacerlo ({e})")
        finally:
            self.lock.release()
