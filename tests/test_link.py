"""Vínculo entre equipos: firma, repetidos, destinatario, archivos y la frase «dile al celular que…». Uso: python tests/test_link.py"""
import base64
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fruquis import link  # noqa: E402


class Mem:  # config en memoria: la prueba no toca ~/.fruquis
    d: dict = {}
    get = staticmethod(lambda k, default=None: Mem.d.get(k) if Mem.d.get(k) is not None else default)
    put = staticmethod(lambda k, v: Mem.d.__setitem__(k, v))


link.store = Mem
link.DOWNLOADS = Path(tempfile.mkdtemp())
CODE = link.new_code()
link.save(code=CODE, name="PC", id="aaaa")
got, ev = [], threading.Event()
lk = link.Link(lambda m: (got.append(m), ev.set()))


def env(code=CODE, **kw):
    body = json.dumps({"id": "m1", "from": "bbbb", "n": "Pixel", "k": "phone", "to": "", "ts": int(time.time() * 1000), "type": "task", "text": "abre Maps", **kw})
    return {"b": body, "s": link.sign(code, body)}


assert lk.receive(env()) and ev.wait(2) and got[0]["text"] == "abre Maps"              # válido
assert lk.receive(env()) and len(got) == 1                                              # mismo id: no se ejecuta dos veces
assert not lk.receive(env(code=link.new_code(), id="m2"))                               # firma de otro código
e = env(id="m3"); e["b"] = e["b"].replace("Maps", "Chrome")
assert not lk.receive(e)                                                                # alterado
assert not lk.receive(env(id="m4", ts=int(time.time() * 1000) - 3_600_000))             # viejo
assert not lk.receive(env(id="m5", **{"from": "aaaa"}))                                 # el propio
assert lk.receive(env(id="m6", to="Otro")) and len(got) == 1                            # firmado pero para otro equipo
assert not lk.receive({"b": "x"}) and not lk.receive({"b": 1, "s": 2})                  # basura

ev.clear()
data = base64.b64encode(b"hola").decode()
assert lk.receive(env(id="m7", type="file", fname="../../x.txt", data=data)) and ev.wait(2)
p = Path(got[-1]["path"])
assert p.parent == link.DOWNLOADS and p.name == "x.txt" and p.read_bytes() == b"hola" and "data" not in got[-1]  # sin escapar de la carpeta

peers = {"b": {"n": "Pixel", "k": "phone"}}
assert link.parse("dile al celular que abra Maps", peers) == ("Pixel", "abra Maps")
assert link.parse("En el otro equipo, abre Chrome", peers) == ("", "abre Chrome")
assert link.parse("en Pixel: pon una alarma", peers) == ("Pixel", "pon una alarma")
assert link.parse("abre Maps", peers) is None and link.parse("en el celular", peers) is None
assert link.parse("en la compu abre X", peers) is None                                  # el otro es un celular, no una PC
assert link.clean_code("abcd-efgh jkmn") == "ABCDEFGHJKMN" and len(link.new_code()) == 12
print("ok")
