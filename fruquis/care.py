"""Tamagotchi: hambre, limpieza, diversión y energía (0-100) por personaje. Sin Qt. `python -m fruquis.care` = autocomprobación."""
import json
import time
from pathlib import Path

DECAY = {"hambre": 6, "limpieza": 4, "diversion": 5, "energia": 2}  # puntos por hora
FLOOR = 15  # al reabrir tras días fuera, nada baja de aquí por el tiempo ausente
ACTIONS = {  # acción: (efectos, texto)
    "comer": ({"hambre": +35, "limpieza": -5}, "🍙 ¡Ñam!"),
    "limpiar": ({"limpieza": +50}, "🫧 ¡Qué fresquito!"),
    "jugar": ({"diversion": +30, "energia": -8, "hambre": -5}, "🎾 ¡Otra vez!"),
    "mimar": ({"diversion": +25, "energia": +3}, "💜 ¡Mimos!"),
    "dormir": ({"energia": +40, "hambre": -3}, "💤 Zzz…"),
}


class Care:
    def __init__(self, path: Path):
        self.path = path
        self.s = {k: 80.0 for k in DECAY}
        self.at = time.time()
        try:
            d = json.loads(path.read_text())
            self.s.update(d["s"])
            self.at = d["at"]
        except Exception:
            pass
        self.advance(time.time() - self.at, offline=True)

    def advance(self, seconds: float, offline: bool = False):
        for k, per_hour in DECAY.items():
            v = self.s[k] - per_hour * seconds / 3600
            self.s[k] = max(min(self.s[k], FLOOR), v) if offline else max(0, v)
        self.at = time.time()

    def act(self, name: str) -> str:
        fx, text = ACTIONS[name]
        for k, d in fx.items():
            self.s[k] = min(100, max(0, self.s[k] + d))
        self.save()
        return text

    def worst(self):
        k = min(self.s, key=self.s.get)
        return (k, self.s[k]) if self.s[k] < 25 else None

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"s": self.s, "at": self.at}))


if __name__ == "__main__":
    import tempfile
    c = Care(Path(tempfile.mkdtemp()) / "care.json")
    c.advance(10 * 3600 * 24, offline=True)  # 10 días fuera
    assert all(v >= 0 for v in c.s.values()) and c.s["hambre"] >= FLOOR - 1e-9 and c.s["hambre"] <= 80, c.s
    c.act("comer"); c.act("comer"); c.act("comer")
    assert c.s["hambre"] <= 100 and c.worst() is None or c.worst()[0] != "hambre"
    print("care ok", {k: round(v) for k, v in c.s.items()})
