"""Índice local del equipo (apps, binarios, carpetas) para que el chat identifique de qué se habla y Whisper escriba bien los nombres.
Se construye en segundo plano al iniciar y vive solo en ~/.fruquis/machine.json (nunca en el repo). Solo escritorio: en Android no aplica."""
import difflib
import getpass
import json
import os
import platform
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path

from . import store

FILE = store.HOME / "machine.json"
STALE = 24 * 3600  # se reindexa si el índice tiene más de un día
SKIP = {"node_modules", "__pycache__", "venv", ".venv", "site-packages", "build", "dist", "target", "snap", "proc", "cache", "caches", "trash"}
_idx: dict = {}
_lock = threading.Lock()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()).strip()


def apps() -> list[str]:
    """Nombres de las apps instaladas (menú de aplicaciones de cada sistema)."""
    names: set[str] = set()
    if sys.platform == "win32":
        roots = [Path(os.environ.get(k, "")) / "Microsoft/Windows/Start Menu/Programs" for k in ("ProgramData", "APPDATA")]
        names = {p.stem for r in roots if r.is_dir() for p in r.rglob("*.lnk")}
    elif sys.platform == "darwin":
        names = {p.stem for r in (Path("/Applications"), Path.home() / "Applications") if r.is_dir() for p in r.glob("*.app")}
    else:
        for r in (Path("/usr/share/applications"), Path.home() / ".local/share/applications", Path("/var/lib/flatpak/exports/share/applications")):
            for p in r.glob("*.desktop") if r.is_dir() else ():
                try:
                    t = p.read_text(errors="ignore")
                except OSError:
                    continue
                n = next((l[5:].strip() for l in t.splitlines() if l.startswith("Name=")), "")
                if n and "NoDisplay=true" not in t:
                    names.add(n)
    return sorted(names, key=str.lower)


def bins() -> list[str]:
    """Ejecutables del PATH (sin extensión en Windows)."""
    out: set[str] = set()
    for d in os.environ.get("PATH", "").split(os.pathsep):
        try:
            for p in Path(d).iterdir():
                if os.access(p, os.X_OK) and p.is_file():
                    out.add(p.stem if sys.platform == "win32" else p.name)
        except OSError:
            continue
    return sorted(out, key=str.lower)[:4000]


ROOTS = (".git", "package.json", "pyproject.toml", "requirements.txt", "setup.py", "manage.py", "pom.xml", "Cargo.toml", "go.mod", "build.gradle", "pubspec.yaml", "composer.json")


def _subdirs(d: Path) -> list[Path]:
    try:
        return sorted((s for s in d.iterdir() if s.is_dir() and not s.is_symlink() and not s.name.startswith(".") and s.name.lower() not in SKIP),
                      key=lambda p: p.name.lower())
    except OSError:
        return []


def _is_project(d: Path) -> bool:
    return any((d / m).exists() for m in ROOTS)


def _classify(ask: dict) -> dict:
    """Una consulta a la IA: {ruta: ejemplos de contenido} -> {ruta: deep|base|skip}."""
    try:
        from . import chat  # perezoso: chat importa este módulo
        out = chat.ask("Clasifica carpetas del equipo de un usuario para un índice local que ayuda a un asistente a saber de qué habla («abre el proyecto X»). "
                       "Para cada ruta (con ejemplos de lo que contiene) responde «deep» si contiene proyectos, código, documentos o archivos personales del usuario "
                       "y conviene recorrer por dentro; «base» si solo importa la carpeta en sí (SDKs, herramientas o software instalado, runtimes, bibliotecas, "
                       "dependencias, repositorios clonados ajenos); «skip» SOLO para cachés, temporales y basura evidentes; ante la duda usa «base», y nunca «skip» para carpetas que parezcan del usuario (docs, scripts, juegos, ideas, configuraciones). "
                       "Responde SOLO un objeto JSON {ruta: clasificación} con todas las rutas.\n" + json.dumps(ask, ensure_ascii=False), model="haiku", timeout=90)
        got = json.loads(out[out.index("{"):out.rindex("}") + 1])
        return {k: v for k, v in got.items() if k in ask and v in ("deep", "base", "skip")}
    except Exception:  # noqa: BLE001 - sin IA: reglas por nombre
        return {k: ("base" if re.search(r"sdk|cache|conda|flutter|android|snap|\bgo\b|cargo|node", k.lower()) else "deep") for k in ask}


def triage(rules: dict) -> dict:
    """La IA decide qué carpetas contenedoras se recorren por dentro: «deep» = proyectos/archivos del usuario, «base» = indexar solo la carpeta
    (SDKs, software instalado, dependencias), «skip» = ignorarla. Dos rondas (home y luego dentro de las «deep»); solo pregunta por lo que aún no tiene regla."""
    home = Path.home()
    for lvl in (1, 2):
        ask = {}
        for d in _subdirs(home):
            if lvl == 1:
                parents = [home]
            elif rules.get(str(d.relative_to(home))) == "deep" and not _is_project(d):
                parents = [d]
            else:
                continue
            for c in (_subdirs(parents[0]) if lvl == 2 else [d]):
                rel = str(c.relative_to(home))
                if rel not in rules and not _is_project(c) and len(ask) < 150:
                    ask[rel] = [x.name for x in _subdirs(c)[:6]]
        if ask:
            rules = {**rules, **_classify(ask)}
    return rules


def folders(rules: dict, depth: int = 4, cap: int = 6000) -> list[str]:
    """Carpetas del home (rutas relativas) según las reglas de la IA; al llegar a la raíz de un proyecto no se baja más."""
    home, out = Path.home(), []

    def walk(d: Path, lvl: int):
        for s in _subdirs(d):
            rel = str(s.relative_to(home))
            if len(out) >= cap or rules.get(rel) == "skip":
                continue
            out.append(rel)
            if lvl < depth and rules.get(rel) != "base" and not _is_project(s):
                walk(s, lvl + 1)

    walk(home, 1)
    return out


def build() -> dict:
    rules = triage(_idx.get("rules", {}) if _idx else {})
    data = {"rules": rules, "t": time.time(), "os": f"{platform.system()} {platform.release()}", "user": getpass.getuser(), "home": str(Path.home()),
            "apps": apps(), "bins": bins(), "folders": folders(rules)}
    store.write(FILE, data)
    return data


def _run():
    global _idx
    try:
        data = build()
        with _lock:
            _idx = data
    except Exception:  # noqa: BLE001 - sin índice se funciona igual
        pass


def start():
    """Al iniciar: carga el índice guardado al momento y lo reconstruye en segundo plano si falta o está viejo."""
    global _idx
    old = store.read(FILE, {}) if FILE.exists() else {}
    with _lock:
        _idx = old
    if time.time() - old.get("t", 0) > STALE:
        threading.Thread(target=_run, daemon=True, name="machine-index").start()


def hint() -> str:
    """Contexto fijo para el prompt de sistema: sistema, apps y carpetas de primer/segundo nivel; vacío si aún no hay índice."""
    with _lock:
        d = _idx
    if not d:
        return ""
    top = [f for f in d["folders"] if f.count("/") < 2][:120]
    return (f" Equipo del usuario: {d['os']}, usuario {d['user']}, home {d['home']}. Apps instaladas: {', '.join(d['apps'][:150])}. "
            f"Carpetas (relativas al home): {', '.join(top)}. Con esto resuelve nombres dictados y mal transcritos y ábrelos directamente; "
            "pregunta solo si hay varias candidatas igual de probables.")


def match(text: str, limit: int = 8) -> str:
    """Lo local que parece nombrar `text` (apps, binarios, carpetas), aun mal transcrito; vacío si nada se parece."""
    with _lock:
        d = _idx
    words = [w for w in _norm(text).split() if len(w) >= 4]
    if not d or not words:
        return ""
    cands: dict[str, str] = {}  # nombre normalizado -> descripción
    for a in d["apps"]:
        cands.setdefault(_norm(a), f"app «{a}»")
    for b in d["bins"]:
        cands.setdefault(_norm(b), f"comando `{b}`")
    for f in d["folders"]:
        cands.setdefault(_norm(Path(f).name), f"carpeta ~/{f}")
    found: list[str] = []
    for w in words:
        for m in difflib.get_close_matches(w, [k for k in cands if k], n=3, cutoff=0.8):
            if cands[m] not in found:
                found.append(cands[m])
    return (" Posibles coincidencias locales con lo dictado: " + "; ".join(found[:limit]) + ".") if found else ""


def vocab() -> list[str]:
    """Nombres de proyectos que Whisper debe saber escribir (pocos: solo lee ~224 tokens del prompt)."""
    with _lock:
        d = _idx
    return [Path(f).name for f in d.get("folders", []) if f.count("/") > 1][:25]


if __name__ == "__main__":
    d = build()
    print(d["rules"]);print(len(d["apps"]), len(d["bins"]), len(d["folders"]))
    _idx.update(d)
    assert "fruquis" in match("abre el proyecto fruquis")
    print(match("abre el proyecto fruquis y el navegador brave"))
