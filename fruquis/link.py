"""Vínculo entre equipos (escritorio ↔ Android u otro escritorio): órdenes y archivos de uno al otro. Paridad con Link.kt.
Los equipos comparten un código; cada mensaje va firmado con HMAC-SHA256 con ese código (no se acepta nada sin firma válida, ni repetido, ni viejo).
Dos rutas, se prueba primero la local:
  · LAN: cada equipo avisa por UDP (broadcast) en la red y recibe por HTTP; sin servidor.
  · Relay: el servidor aipi (`/api/link/send` y `/api/link/poll`) reenvía los sobres; funciona entre redes distintas.
La firma autentica pero NO cifra: por LAN el contenido viaja visible para quien esté en la misma red; el relay lo ve el dueño del servidor (usa HTTPS)."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import socket
import sys
import threading
import time
import unicodedata
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from . import store

UDP = 8379          # puerto del aviso por LAN
BEACON_S = 4        # cada cuántos segundos avisa
FRESH_S = 15        # un equipo visto hace más que esto ya no cuenta como alcanzable por LAN
SKEW_S = 300        # tolerancia de reloj entre equipos
MAX_FILE = 15 * 1024 * 1024
CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
KIND = "pc"
KIND_NAMES = {"pc": ("pc", "computadora", "compu", "laptop", "escritorio", "ordenador"), "phone": ("celular", "telefono", "movil", "cel")}
DOWNLOADS = Path.home() / "Downloads" / "Fruquis"


class LinkError(Exception):
    pass


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()).strip()


def new_code() -> str:
    return "".join(secrets.choice(CODE_CHARS) for _ in range(12))


def clean_code(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def show_code(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def room(code: str) -> str:
    """Identificador público de la sala: no revela el código."""
    return hashlib.sha256(("fruquis-link:" + code).encode()).hexdigest()[:16]


def sign(code: str, body: str) -> str:
    return hmac.new(code.encode(), body.encode(), "sha256").hexdigest()


def relay_parts(link: str) -> tuple:
    """Enlace personal del servidor aipi (con ?key=…) → (base, clave)."""
    u = urlparse(link.strip())
    key = (parse_qs(u.query).get("key") or [""])[0]
    return (link.split("?")[0].split("/api/")[0].rstrip("/") if u.scheme else ""), key


def conf() -> dict:
    c = {"code": "", "name": socket.gethostname(), "relay": "", "accept": "ask", **(store.get("link", {}) or {})}
    if not c.get("id"):
        c["id"] = secrets.token_hex(4)
        store.put("link", c)
    return c


def save(**kw):
    store.put("link", {**conf(), **kw})


def known() -> dict:
    """Equipos vistos alguna vez en este vínculo: {id: {n: nombre, k: tipo}}."""
    return store.get("link_peers", {}) or {}


def parse(text: str, peers: dict) -> tuple | None:
    """«dile al celular que abra Maps» / «en el otro equipo, abre X» → (nombre del destino o "", orden); None si no habla de otro equipo."""
    names = {"otro equipo": "", "otro dispositivo": "", "el otro": ""}
    for p in peers.values():
        names[norm(p.get("n", ""))] = p.get("n", "")
        for alias in KIND_NAMES.get(p.get("k"), ()):
            names.setdefault(alias, p.get("n", ""))
    names.pop("", None)
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    folded = unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode()  # misma longitud que `text` en español: los índices valen para el original
    m = re.match(rf"\s*(?:(?:dile|dicele|pidele|mandale)\s+(?:a|al)\s+|(?:en|con)\s+|al\s+)(?:el\s+|la\s+|mi\s+|tu\s+)?({alt})\b[\s,:;.]*(?:que\s+)?(.+)", folded, re.S)
    if not m:
        return None
    to = names[m.group(1)] if m.group(1) in names else names[norm(m.group(1))]
    return to, (text[m.start(2):] if len(folded) == len(text) else m.group(2)).strip()


class Link:
    """Hilos de red del vínculo. `on_msg(m)` se llama (en un hilo) con cada mensaje verificado: task / result / file (con `path`) / ping."""

    def __init__(self, on_msg):
        self.on_msg, self.peers, self.seen, self.ev = on_msg, {}, {}, threading.Event()
        self.http, self.relay_ok, self.error, self.port = None, None, "", 0

    # ---- ciclo de vida ----
    def start(self):
        self.stop()
        c = conf()
        if not c["code"]:
            return
        self.ev, link = threading.Event(), self
        self.peers, self.error, self.relay_ok = {}, "", None

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    ok = link.receive(json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), MAX_FILE * 2))))
                except (ValueError, TypeError):
                    ok = False
                self.send_response(200 if ok else 403)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        self.http = ThreadingHTTPServer(("0.0.0.0", 0), H)
        self.port = self.http.server_address[1]
        for fn in (self.http.serve_forever, self._beacon, self._listen, self._poll):
            threading.Thread(target=fn, daemon=True, name="link").start()

    def stop(self):
        self.ev.set()
        if self.http:
            threading.Thread(target=self.http.shutdown, daemon=True).start()
            self.http = None

    # ---- recibir ----
    def receive(self, env: dict) -> bool:
        c = conf()
        try:
            body = env["b"]
            if not hmac.compare_digest(sign(c["code"], body), env["s"]):
                return False
            m = json.loads(body)
            mid, src, ts = str(m["id"]), m["from"], m["ts"] / 1000
        except (KeyError, ValueError, TypeError, AttributeError):
            return False
        now = time.time()
        if src == c["id"] or abs(now - ts) > SKEW_S:
            return False
        self.seen = {k: t for k, t in self.seen.items() if now - t < 2 * SKEW_S}
        if mid in self.seen:
            return True  # ya llegó por la otra ruta
        self.seen[mid] = now
        self._peer(src, m.get("n", "?"), m.get("k", ""))
        if m.get("to") and norm(m["to"]) != norm(c["name"]):
            return True  # firmado y válido, pero para otro equipo
        if m.get("type") == "file":
            try:
                m["path"] = str(self._save_file(m))
            except (OSError, ValueError) as e:
                m["type"], m["text"] = "result", f"No pude guardar el archivo ({e})"
        m.pop("data", None)
        threading.Thread(target=self.on_msg, args=(m,), daemon=True).start()
        return True

    def _save_file(self, m: dict) -> Path:
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(str(m["fname"])).name).strip(". ") or "archivo"
        DOWNLOADS.mkdir(parents=True, exist_ok=True)
        dest, i = DOWNLOADS / name, 1
        while dest.exists():
            dest = DOWNLOADS / f"{Path(name).stem} ({i}){Path(name).suffix}"
            i += 1
        dest.write_bytes(base64.b64decode(m["data"], validate=True))
        return dest

    def _peer(self, pid: str, name: str, kind: str, addr: tuple = None):
        p = self.peers.setdefault(pid, {})
        p.update(n=name, k=kind)
        if addr:
            p.update(ip=addr[0], port=addr[1], seen=time.time())
        k = known()
        if k.get(pid) != {"n": name, "k": kind}:
            store.put("link_peers", {**k, pid: {"n": name, "k": kind}})

    # ---- LAN ----
    def _beacon(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while not self.ev.is_set():
            c = conf()
            try:
                s.sendto(json.dumps({"r": room(c["code"]), "i": c["id"], "n": c["name"], "k": KIND, "p": self.port}).encode(), ("255.255.255.255", UDP))
            except OSError:
                pass  # sin red: se reintenta
            self.ev.wait(BEACON_S)

    def _listen(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(1)
        try:
            s.bind(("", UDP))
        except OSError as e:
            self.error = f"LAN: no pude abrir el puerto {UDP} ({e})"
            return
        while not self.ev.is_set():
            try:
                data, addr = s.recvfrom(2048)
                d, c = json.loads(data), conf()
                if d["r"] == room(c["code"]) and d["i"] != c["id"]:
                    self._peer(d["i"], str(d["n"]), str(d["k"]), (addr[0], int(d["p"])))
            except (socket.timeout, ValueError, KeyError, TypeError):
                continue
            except OSError:
                self.ev.wait(1)
        s.close()

    # ---- relay ----
    def _poll(self):
        after = None
        while not self.ev.is_set():
            c = conf()
            base, key = relay_parts(c["relay"])
            if not base:
                self.ev.wait(5)
                continue
            q = {"key": key, "room": room(c["code"]), "wait": 25, **({} if after is None else {"after": after})}
            try:
                with urllib.request.urlopen(f"{base}/api/link/poll/?{urlencode(q)}", timeout=40) as r:
                    d = json.load(r)
                after, self.relay_ok = d["seq"], True
                for it in d["items"]:
                    self.receive(it["e"])
            except Exception as e:  # noqa: BLE001 - red caída o servidor reiniciando: se reintenta
                self.relay_ok, self.error = False, f"Relay: {e}"
                self.ev.wait(5)

    # ---- enviar ----
    def send(self, type: str, text: str = "", to: str = "", **extra) -> str:
        """Envía a los otros equipos (o a `to`). Devuelve la ruta usada («LAN» o «relay»); LinkError si ninguna llegó."""
        c = conf()
        if not c["code"]:
            raise LinkError("Este equipo no está vinculado todavía.")
        body = json.dumps({"id": secrets.token_hex(8), "from": c["id"], "n": c["name"], "k": KIND, "to": to, "ts": int(time.time() * 1000),
                           "type": type, "text": text, **extra}, ensure_ascii=False)
        env = {"b": body, "s": sign(c["code"], body)}
        sent = False
        for p in list(self.peers.values()):
            if p.get("ip") and time.time() - p.get("seen", 0) < FRESH_S and (not to or norm(p["n"]) == norm(to)):
                try:
                    self._post(f"http://{p['ip']}:{p['port']}/", env)
                    sent = True
                except OSError:
                    pass
        if sent:
            return "LAN"
        base, key = relay_parts(c["relay"])
        if not base:
            raise LinkError("El otro equipo no está en tu red y falta el enlace del servidor (relay).")
        try:
            self._post(f"{base}/api/link/send/?{urlencode({'key': key, 'room': room(c['code'])})}", env)
        except OSError as e:
            raise LinkError(f"No pude llegar al relay ({e})")
        return "relay"

    @staticmethod
    def _post(url: str, env: dict):
        req = urllib.request.Request(url, json.dumps(env).encode(), {"Content-Type": "application/json", "User-Agent": "fruquis"})
        with urllib.request.urlopen(req, timeout=15):
            pass

    def send_file(self, path: str, to: str = "") -> str:
        p = Path(path)
        if not p.is_file():
            raise LinkError("No existe ese archivo.")
        if p.stat().st_size > MAX_FILE:
            raise LinkError(f"El archivo pesa más de {MAX_FILE // 2**20} MB.")
        return self.send("file", to=to, fname=p.name, data=base64.b64encode(p.read_bytes()).decode())

    def status(self) -> str:
        c = conf()
        if not c["code"]:
            return "Sin vincular"
        lan = [p["n"] for p in self.peers.values() if p.get("ip") and time.time() - p.get("seen", 0) < FRESH_S]
        return (f"Vinculado · LAN: {', '.join(lan) if lan else 'sin equipos a la vista'} · relay: "
                + ("sin configurar" if not c["relay"] else "conectado" if self.relay_ok else "sin conexión")) + (f" · {self.error}" if self.error else "")


if __name__ == "__main__":
    code = new_code()
    b = '{"x":1}'
    assert sign(code, b) != sign(new_code(), b)
    assert len(room(code)) == 16 and code not in room(code)
    peers = {"a": {"n": "Pixel", "k": "phone"}}
    assert parse("dile al celular que abra Maps", peers) == ("Pixel", "abra Maps")
    assert parse("En el otro equipo, abre Chrome", peers) == ("", "abre Chrome")
    assert parse("abre Maps", peers) is None
    print("ok")
