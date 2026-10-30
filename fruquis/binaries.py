"""Binarios externos: el chat usa `claude` y el generador de imágenes usa `codex`. Se resuelven en este orden: ruta elegida en Ajustes,
variable de entorno (CLAUDE_BIN / CODEX_BIN), PATH, lugares habituales de instalación por usuario y, al final, el PATH del shell de login
(las apps lanzadas con doble clic en macOS/Linux no heredan el PATH de la terminal). Linux, macOS y Windows. Sin Qt."""
import functools
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import store

WIN = os.name == "nt"
MAC = sys.platform == "darwin"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SETTING = {"claude": "bin_claude", "codex": "bin_codex"}


def candidates(tool: str, win: bool | None = None, mac: bool | None = None) -> list:
    """Lugares habituales de instalación por usuario (parámetros `win`/`mac` para poder probar cada sistema desde otro)."""
    win, mac = WIN if win is None else win, MAC if mac is None else mac
    home = Path.home()
    if win:
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        roam = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        out = [home / ".local" / "bin" / f"{tool}.exe", local / "Programs" / tool / f"{tool}.exe", home / f".{tool}" / "local" / f"{tool}.exe",
               roam / "npm" / f"{tool}.cmd", roam / "npm" / f"{tool}.exe", local / "pnpm" / f"{tool}.cmd", local / "Microsoft" / "WinGet" / "Links" / f"{tool}.exe",
               home / "scoop" / "shims" / f"{tool}.exe", home / ".bun" / "bin" / f"{tool}.exe"]
        if os.environ.get("NVM_SYMLINK"):
            out.append(Path(os.environ["NVM_SYMLINK"]) / f"{tool}.cmd")
        return out
    out = [home / ".local" / "bin" / tool, home / f".{tool}" / "local" / tool, home / f".{tool}" / "local" / "node_modules" / ".bin" / tool,
           Path("/usr/local/bin") / tool, Path("/usr/bin") / tool, home / ".npm-global" / "bin" / tool, home / ".bun" / "bin" / tool,
           home / ".volta" / "bin" / tool, home / ".asdf" / "shims" / tool, home / ".local" / "share" / "pnpm" / tool,
           home / ".local" / "share" / "mise" / "shims" / tool]
    if mac:
        out += [Path("/opt/homebrew/bin") / tool, Path("/opt/homebrew/opt/node/bin") / tool, home / "Library" / "pnpm" / tool]
    else:
        out += [Path("/home/linuxbrew/.linuxbrew/bin") / tool, Path("/snap/bin") / tool]
    out += sorted(home.glob(f".nvm/versions/node/*/bin/{tool}"), reverse=True)
    out += sorted(home.glob(f".local/share/fnm/node-versions/*/installation/bin/{tool}"), reverse=True)
    return out


@functools.lru_cache(maxsize=8)
def _npm_prefix() -> str | None:
    npm = shutil.which("npm.cmd" if WIN else "npm") or shutil.which("npm")
    if not npm:
        return None
    try:
        return subprocess.run([npm, "prefix", "-g"], capture_output=True, text=True, timeout=20, creationflags=NOWIN).stdout.strip() or None
    except Exception:
        return None


@functools.lru_cache(maxsize=8)
def _login_shell(tool: str) -> str | None:
    """PATH del shell de login (macOS/Linux): ahí suelen estar nvm, volta, homebrew… aunque la app se haya abierto con doble clic."""
    if WIN:
        return None
    sh = os.environ.get("SHELL") or "/bin/sh"
    try:
        out = subprocess.run([sh, "-lc", f"command -v {tool}"], capture_output=True, text=True, timeout=8).stdout.strip().splitlines()
    except Exception:
        return None
    return out[-1] if out and os.path.isfile(out[-1]) else None


def detect(tool: str) -> str | None:
    """Búsqueda automática (ignora lo elegido en Ajustes)."""
    pref = os.environ.get(f"{tool.upper()}_BIN")
    if pref and (shutil.which(pref) or os.path.isfile(pref)):
        return shutil.which(pref) or pref
    for name in ([f"{tool}.exe", f"{tool}.cmd", tool] if WIN else [tool]):
        if hit := shutil.which(name):
            return hit
    for p in candidates(tool):
        if p.is_file() and (WIN or os.access(p, os.X_OK)):
            return str(p)
    prefix = _npm_prefix()
    if prefix:
        for p in ([Path(prefix) / f"{tool}.cmd", Path(prefix) / f"{tool}.exe"] if WIN else [Path(prefix) / "bin" / tool]):
            if p.is_file():
                return str(p)
    return _login_shell(tool)


def resolve(tool: str) -> str | None:
    """La ruta elegida en Ajustes si existe; si no, la detectada."""
    chosen = store.get(SETTING[tool], "")
    if chosen and (shutil.which(chosen) or os.path.isfile(chosen)):
        return shutil.which(chosen) or chosen
    return detect(tool)


def shim_target(text: str, shim_dir: Path, which=shutil.which) -> list | None:
    """Un `.cmd` de npm solo lanza `node <script>.js`: devuelve [node, script] para ejecutarlo directo, sin cmd.exe (que rompe comillas,
    saltos de línea y símbolos en los argumentos)."""
    m = re.search(r'"%dp0%\\([^"]+?\.m?js)"', text) or re.search(r'"%~dp0\\([^"]+?\.m?js)"', text)
    if not m:
        return None
    script = shim_dir / m.group(1).replace("\\", os.sep)
    node = shim_dir / "node.exe"
    node = str(node) if node.is_file() else which("node")
    return [node, str(script)] if node else None


def argv(exe: str, win: bool | None = None) -> list:
    """Comando para ejecutar el binario. En Windows, un .cmd/.bat de npm se convierte en `node script.js`; si no se puede, va por cmd.exe."""
    if (WIN if win is None else win) and exe.lower().endswith((".cmd", ".bat")):
        try:
            direct = shim_target(Path(exe).read_text(errors="replace"), Path(exe).parent)
        except OSError:
            direct = None
        return direct or ["cmd.exe", "/d", "/s", "/c", exe]
    return [exe]


def check(path: str) -> tuple:
    """(funciona, texto): ejecuta `--version` para comprobar que la ruta es un binario usable."""
    if not path or not (shutil.which(path) or os.path.isfile(path)):
        return False, "No existe esa ruta."
    try:
        r = subprocess.run([*argv(shutil.which(path) or path), "--version"], capture_output=True, text=True, timeout=25, creationflags=NOWIN)
    except Exception as e:  # noqa: BLE001
        return False, f"No se pudo ejecutar: {e}"
    out = (r.stdout or r.stderr).strip().splitlines()
    return r.returncode == 0, (out[0] if out else f"código {r.returncode}")
