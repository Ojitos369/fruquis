"""Persistencia del usuario en ~/.fruquis (migra ~/.mutama de versiones anteriores). Escrituras atómicas: un cierre brusco no corrompe nada."""
import json
import os
from pathlib import Path

HOME = Path.home() / ".fruquis"
if not HOME.exists() and (Path.home() / ".mutama").exists():
    (Path.home() / ".mutama").rename(HOME)
_F = HOME / "config.json"


def read_text(path: Path) -> str:
    """Lee UTF-8; si el archivo lo guardó una versión anterior con la codificación de Windows (cp1252), lo lee así."""
    b = path.read_bytes()
    try:
        return b.decode("utf-8-sig")
    except UnicodeDecodeError:
        return b.decode("cp1252", errors="replace")


def write_text(path: Path, text: str):
    """Siempre UTF-8: con la predeterminada de Windows (cp1252) un emoji o una letra rara hacía fallar el guardado."""
    path.write_bytes(text.encode("utf-8"))


def read(path: Path, default=None):
    try:
        return json.loads(read_text(path))
    except Exception:
        return default


def write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    write_text(tmp, json.dumps(data, ensure_ascii=False))
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
