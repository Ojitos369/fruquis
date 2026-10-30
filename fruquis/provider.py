"""Proveedores de IA: cada función (chat, imagen) usa un binario local (`claude`, `codex`) o una API. La API puede ser la oficial (OpenAI,
Anthropic) o un servidor propio con el mismo formato: basta cambiar la URL. Sin Qt ni dependencias (urllib). Ajustes en store["ai"]:
{"chat": {mode: binary|api, kind: openai|anthropic|server, url, key, model}, "image": {mode, kind: openai|server, url, key, model}}. kind «server» = servidor
propio aipi (server/aipi.py: claude y codex de un servidor, POST {url}/api/chat/?key= y /api/image/?key=, imágenes en base64). Formato compartido con la app Android
(android/.../Ai.java). `python tests/test_provider.py` = prueba contra un servidor falso."""
import base64
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import binaries, store

OFFICIAL = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com"}
MODELS = {"chat": {"openai": "gpt-4o-mini", "anthropic": "claude-haiku-5-5"}, "image": {"openai": "gpt-image-1"}}
ENV_KEY = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


class AIError(Exception):
    pass


def cfg(what: str) -> dict:
    """Configuración efectiva de `chat` o `image`, con los valores por defecto aplicados."""
    c = dict((store.get("ai", {}) or {}).get(what) or {})
    kind = c.get("kind") if c.get("kind") in (("openai", "server") if what == "image" else (*OFFICIAL, "server")) else "openai"  # imágenes: sin formato Anthropic
    url = (c.get("url") or OFFICIAL.get(kind, "")).rstrip("/")
    key = c.get("key") or os.environ.get("FRUQUIS_API_KEY") or (os.environ.get(ENV_KEY[kind]) if url == OFFICIAL.get(kind) else "") or ""
    return {"mode": "api" if c.get("mode") == "api" else "binary", "kind": kind, "url": url, "key": key,
            "model": c.get("model") or MODELS[what].get(kind, ""), "official": url == OFFICIAL.get(kind)}


def api_on(what: str) -> bool:
    c = cfg(what)
    if c["mode"] != "api":
        return False
    # API oficial sin clave y con el binario instalado: se usa el binario en vez de fallar con «Falta la clave»
    return not (c["official"] and not c["key"] and binaries.resolve("claude" if what == "chat" else "codex"))


def chat_ready() -> bool:
    return api_on("chat") or bool(binaries.resolve("claude"))


def image_ready() -> bool:
    return api_on("image") or bool(binaries.resolve("codex"))


def _post(c: dict, path: str, body: bytes, headers: dict, timeout: int) -> dict:
    full = c["url"] + path
    if c["kind"] == "server":  # la URL de Ajustes es el enlace personal (con ?key=); también vale la base + clave aparte
        full = c["url"] if "/api/" in c["url"] else c["url"] + path
        if "key=" not in full and c["key"]:
            full += ("&" if "?" in full else "?") + "key=" + urllib.parse.quote(c["key"])
        if not c["url"] or "key=" not in full:
            raise AIError("Falta el enlace del servidor con su clave (Ajustes → IA).")
    elif c["official"] and not c["key"]:
        raise AIError("Falta la clave de la API (Ajustes → IA).")
    h = {"User-Agent": "fruquis", **headers,  # Cloudflare rechaza el User-Agent por defecto de urllib
         **({"Authorization": f"Bearer {c['key']}"} if c["kind"] == "openai" and c["key"] else {}),
         **({"x-api-key": c["key"], "anthropic-version": "2023-06-01"} if c["kind"] == "anthropic" and c["key"] else {})}
    req = urllib.request.Request(full, body, h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise AIError(f"HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AIError(f"No pude conectar con {c['url']}: {e}")


def _b64(p) -> tuple:
    return ("image/jpeg" if str(p).lower().endswith((".jpg", ".jpeg")) else "image/png"), base64.b64encode(Path(p).read_bytes()).decode()


def api_text(prompt: str, system: str = "", images: list = (), model: str | None = None, timeout: int = 120) -> str:
    """Una respuesta de texto (con imágenes opcionales para visión) por la API de chat configurada."""
    c = cfg("chat")
    model = model or c["model"]
    if c["kind"] == "server":
        d = _post(c, "/api/chat/", json.dumps({"prompt": prompt, "system": system, "model": model, "images": [x for _, x in map(_b64, images)]}).encode(),
                  {"content-type": "application/json"}, timeout)
        return (d.get("text") or "").strip()
    if c["kind"] == "anthropic":
        parts = [{"type": "image", "source": {"type": "base64", "media_type": m, "data": d}} for m, d in map(_b64, images)] + [{"type": "text", "text": prompt}]
        d = _post(c, "/v1/messages", json.dumps({"model": model, "max_tokens": 2048, "system": system, "messages": [{"role": "user", "content": parts}]}).encode(),
                  {"content-type": "application/json"}, timeout)
        return "".join(b.get("text", "") for b in d.get("content", [])).strip()
    parts = [{"type": "image_url", "image_url": {"url": f"data:{m};base64,{d}"}} for m, d in map(_b64, images)] + [{"type": "text", "text": prompt}]
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": parts if images else prompt}]
    d = _post(c, "/chat/completions", json.dumps({"model": model, "messages": msgs}).encode(), {"content-type": "application/json"}, timeout)
    try:
        return (d["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise AIError("Respuesta inesperada de la API.")


def api_image(prompt: str, refs: list = (), timeout: int = 600) -> bytes:
    """Una imagen (PNG) por la API de imágenes configurada: /images/generations, o /images/edits si hay imágenes de referencia."""
    c = cfg("image")
    if c["kind"] == "server":
        d = _post(c, "/api/image/", json.dumps({"prompt": prompt, "images": [x for _, x in map(_b64, refs)]}).encode(), {"content-type": "application/json"}, timeout)
        try:
            return base64.b64decode(d["image"])
        except (KeyError, ValueError):
            raise AIError("La API no devolvió ninguna imagen.")
    if not refs:
        d = _post(c, "/images/generations", json.dumps({"model": c["model"], "prompt": prompt, "size": "1024x1024", "n": 1}).encode(),
                  {"content-type": "application/json"}, timeout)
    else:
        bd = uuid.uuid4().hex
        body = b"".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in (("model", c["model"]), ("prompt", prompt)))
        for r in refs:
            body += (f'--{bd}\r\nContent-Disposition: form-data; name="image[]"; filename="{Path(r).name}"\r\nContent-Type: {_b64(r)[0]}\r\n\r\n').encode() + Path(r).read_bytes() + b"\r\n"
        d = _post(c, "/images/edits", body + f"--{bd}--\r\n".encode(), {"content-type": f"multipart/form-data; boundary={bd}"}, timeout)
    try:
        item = d["data"][0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        with urllib.request.urlopen(item["url"], timeout=timeout) as r:  # algunos servidores devuelven una URL en vez de base64
            return r.read()
    except (KeyError, IndexError, TypeError, OSError):
        raise AIError("La API no devolvió ninguna imagen.")


def vision(prompt: str, images: list = (), model: str = "haiku", effort: str = "medium", timeout: int = 150) -> str | None:
    """Pregunta de un solo turno que mira imágenes y devuelve texto: por API si está activada o con `claude -p` (herramienta Read). None si no
    hay IA disponible o falla. Lo usan el análisis de personajes, la verificación de identidad y la detección de animaciones."""
    epoch = _epoch
    if api_on("chat"):
        try:
            out = api_text(prompt, images=images, timeout=timeout)
        except AIError:
            return None
        return None if epoch != _epoch else out  # la API no se puede abortar: si se canceló, se descarta la respuesta
    exe = binaries.resolve("claude")
    if not exe:
        return None
    dirs = sorted({str(Path(p).resolve().parent) for p in images}) or [tempfile.gettempdir()]
    cmd = [*binaries.argv(exe), "-p", "--model", model, "--effort", effort, "--no-session-persistence", "--tools", "Read", "--allowedTools", "Read"]
    for d in dirs:
        cmd += ["--add-dir", d]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                         cwd=dirs[0], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _procs.add(p)
    try:
        out, _ = p.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        return None
    finally:
        _procs.discard(p)
    return None if epoch != _epoch else out


_procs, _epoch = set(), 0


def cancel():
    """Aborta los análisis con IA en curso (`vision`): mata el proceso `claude` y descarta lo que devuelva la API."""
    global _epoch
    _epoch += 1
    for p in list(_procs):
        if p.poll() is None:
            p.kill()


def test(what: str) -> tuple:
    """(funciona, texto) para el botón «Probar» de Ajustes."""
    try:
        if what == "chat":
            return True, "✓ " + (api_text("Responde solo: ok", timeout=40)[:60] or "(vacío)") + f"  ·  {cfg('chat')['model']}"
        c = cfg("image")
        return (True, f"Listo · {c['url']} · {c['model']}") if c["key"] or not c["official"] else (False, "Falta la clave de la API.")
    except AIError as e:
        return False, str(e)


if __name__ == "__main__":
    print(json.dumps({k: {**cfg(k), "key": "…" if cfg(k)["key"] else ""} for k in ("chat", "image")}, indent=1))
