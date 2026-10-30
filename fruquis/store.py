"""Persistencia del usuario en ~/.fruquis (migra ~/.mutama de versiones anteriores). Escrituras atómicas: un cierre brusco no corrompe nada."""
import json
import os
from pathlib import Path

HOME = Path.home() / ".fruquis"
if not HOME.exists() and (Path.home() / ".mutama").exists():
    (Path.home() / ".mutama").rename(HOME)
_F = HOME / "config.json"


def read(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    os.replace(tmp, path)  # atómico


def get(key, default=None):
    v = (read(_F, {}) or {}).get(key)
    return default if v is None else v


def put(key, value):
    d = read(_F, {}) or {}
    d[key] = value
    write(_F, d)


def chat_path(cid: str) -> Path:
    return HOME / "chats" / f"{cid}.json"
