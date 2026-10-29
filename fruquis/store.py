"""Preferencias del usuario en ~/.fruquis/config.json (migra ~/.mutama de versiones anteriores)."""
import json
from pathlib import Path

HOME = Path.home() / ".fruquis"
if not HOME.exists() and (Path.home() / ".mutama").exists():
    (Path.home() / ".mutama").rename(HOME)
_F = HOME / "config.json"


def get(key, default=None):
    try:
        return json.loads(_F.read_text()).get(key, default)
    except Exception:
        return default


def put(key, value):
    try:
        d = json.loads(_F.read_text())
    except Exception:
        d = {}
    d[key] = value
    HOME.mkdir(parents=True, exist_ok=True)
    _F.write_text(json.dumps(d))
