"""aipi: API HTTP (solo stdlib) que expone `claude` y `codex` del servidor a las apps Fruquis (Android y escritorio). Clave en `?key=`.
  POST /api/chat/?key=K   {prompt, system?, model?, effort?, images?: [b64|{data,mime}]}  ->  {text}
  POST /api/image/?key=K  {prompt, images?: [b64|{data,mime}]}                           ->  {image: <png b64>, mime}
  GET  /api/health/?key=K
Las imágenes llegan en base64, se dejan en una carpeta temporal para que el CLI las lea y se borran al terminar. Config por entorno:
AIPI_KEY_FILE (def. ~/aipi/key), AIPI_PORT (8377), AIPI_JOBS (3 trabajos a la vez). `python3 aipi.py` en el servidor."""
import base64
import glob
import hmac
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path.home()
KEY = Path(os.environ.get("AIPI_KEY_FILE", HOME / "aipi" / "key")).read_text().strip()
PORT = int(os.environ.get("AIPI_PORT", 8377))
JOBS = threading.Semaphore(int(os.environ.get("AIPI_JOBS", 3)))
MAX_BODY = 60 * 1024 * 1024
CLAUDE = shutil.which("claude") or str(HOME / ".local/bin/claude")
CODEX = shutil.which("codex") or str(HOME / ".local/bin/codex")
CODEX_MODEL = os.environ.get("CODEX_IMAGE_MODEL", "gpt-6-luna")
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


class Bad(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def save_images(items, tmp: Path) -> list:
    """base64 (o {data, mime}) -> archivos en tmp; devuelve sus rutas."""
    out = []
    for i, it in enumerate(items or [], 1):
        mime, data = (it.get("mime", "image/png"), it.get("data", "")) if isinstance(it, dict) else ("image/png", it)
        if data.startswith("data:"):  # data URL
            head, data = data.split(",", 1)
            mime = head[5:].split(";")[0] or mime
        try:
            raw = base64.b64decode(data, validate=False)
        except ValueError:
            raise Bad(f"imagen {i}: base64 inválido")
        if raw[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        p = tmp / f"adjunto-{i}{EXT.get(mime, '.png')}"
        p.write_bytes(raw)
        out.append(p)
    return out


def chat(b: dict) -> dict:
    prompt = b.get("prompt") or ""
    if not prompt:
        raise Bad("falta prompt")
    with tempfile.TemporaryDirectory(prefix="aipi-") as t:
        tmp = Path(t)
        imgs = save_images(b.get("images"), tmp)
        if imgs:
            prompt = "[Imágenes adjuntas (léelas con la herramienta Read):\n" + "\n".join(map(str, imgs)) + "]\n" + prompt
        (tmp / "system.txt").write_text(b.get("system") or "Responde en español, breve.", encoding="utf-8")
        tools = (["Read"] if imgs else []) + ["WebSearch", "WebFetch"]
        cmd = [CLAUDE, "-p", "--model", b.get("model") or "haiku", "--effort", b.get("effort") or "medium", "--no-session-persistence",
               "--output-format", "json", "--system-prompt-file", str(tmp / "system.txt"), "--setting-sources", "project", "--disable-slash-commands",
               "--strict-mcp-config", "--tools", ",".join(tools), "--allowedTools", ",".join(tools), "--add-dir", str(tmp)]
        try:
            p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=tmp, timeout=int(b.get("timeout") or 180))
        except subprocess.TimeoutExpired:
            raise Bad("claude tardó demasiado", 408)
    try:
        text = json.loads(p.stdout).get("result") or ""
    except ValueError:
        text = ""
    if not text.strip():
        raise Bad("claude no respondió: " + (p.stderr or p.stdout)[-300:], 500)
    return {"text": text.strip()}


def image(b: dict) -> dict:
    prompt = b.get("prompt") or ""
    if not prompt:
        raise Bad("falta prompt")
    root = Path(os.environ.get("CODEX_HOME") or HOME / ".codex") / "generated_images"
    with tempfile.TemporaryDirectory(prefix="aipi-") as t:
        tmp = Path(t)
        cmd = [CODEX, "exec", "-m", CODEX_MODEL, "--skip-git-repo-check", "--ephemeral", "-s", "read-only"]
        for r in save_images(b.get("images"), tmp):
            cmd += ["-i", str(r)]
        msg = ("Usa tu herramienta de generación de imágenes para crear UNA imagen siguiendo exactamente estas instrucciones, usando las imágenes "
               f"adjuntas como referencia:\n\n{prompt}\n\nNo escribas código ni archivos; solo genera la imagen y responde 'listo'.")
        try:
            p = subprocess.run(cmd + ["--", "-"], input=msg, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=tmp,
                               timeout=int(b.get("timeout") or 900))
        except subprocess.TimeoutExpired:
            raise Bad("codex tardó demasiado", 408)
    sid = re.search(r"session id:\s*([0-9a-fA-F-]{20,})", p.stdout + p.stderr)  # cada sesión guarda sus imágenes en su carpeta: seguro en paralelo
    files = glob.glob(str(root / sid.group(1) / "**" / "*.*"), recursive=True) if sid else []
    if not files:
        raise Bad("codex no generó ninguna imagen: " + p.stderr[-300:], 500)
    best = Path(max(files, key=os.path.getmtime))
    return {"image": base64.b64encode(best.read_bytes()).decode(), "mime": "image/png"}


ROUTES = {"/api/chat": chat, "/api/image": image}


class H(BaseHTTPRequestHandler):
    def reply(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_req(self, post):
        u = urlparse(self.path)
        key = (parse_qs(u.query).get("key") or [""])[0]
        if not hmac.compare_digest(key.encode(), KEY.encode()):
            return self.reply(401, {"error": "clave inválida"})
        path = u.path.rstrip("/")
        if path == "/api/health":
            return self.reply(200, {"ok": True, "claude": os.path.exists(CLAUDE), "codex": os.path.exists(CODEX)})
        fn = ROUTES.get(path)
        if not fn or not post:
            return self.reply(404, {"error": "ruta desconocida"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise Bad("cuerpo demasiado grande", 413)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                raise Bad("JSON inválido")
            with JOBS:
                self.reply(200, fn(body))
        except Bad as e:
            self.reply(e.code, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 - nunca tumbar el servidor por una petición
            self.reply(500, {"error": f"{type(e).__name__}: {e}"})

    do_GET = lambda self: self.handle_req(False)  # noqa: E731
    do_POST = lambda self: self.handle_req(True)  # noqa: E731

    def log_message(self, fmt, *a):  # sin la clave en los registros
        print(self.address_string(), self.command, urlparse(self.path).path, flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
