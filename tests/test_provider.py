"""Prueba de provider.py contra un servidor falso (formatos OpenAI y Anthropic, chat, visión e imágenes). Uso: python tests/test_provider.py"""
import base64
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp())
from fruquis import store  # noqa: E402
store.HOME, store._F = tmp, tmp / "config.json"
from fruquis import provider  # noqa: E402

PNG = base64.b64encode(b"\x89PNG-fake").decode()
seen = []


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        if self.path == "/v1/messages":
            out = {"content": [{"type": "text", "text": "hola anthropic"}]}
        elif self.path == "/chat/completions":
            out = {"choices": [{"message": {"content": "hola openai"}}]}
        else:
            out = {"data": [{"b64_json": PNG}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_port}"
img = tmp / "a.png"
img.write_bytes(b"\x89PNG-x")

assert not provider.api_on("chat") and not provider.api_on("image")  # por defecto: binarios
store.put("ai", {"chat": {"mode": "api", "kind": "openai", "url": url, "key": "k1"}, "image": {"mode": "api", "url": url}})
assert provider.api_text("hola", "sistema") == "hola openai"
assert seen[-1][1]["authorization"] == "Bearer k1" and json.loads(seen[-1][2])["messages"][0]["role"] == "system"
assert provider.api_text("mira", images=[img]) == "hola openai" and "image_url" in seen[-1][2].decode()
assert provider.vision("mira", [img]) == "hola openai"
store.put("ai", {"chat": {"mode": "api", "kind": "anthropic", "url": url, "key": "k2"}})
assert provider.api_text("hola", "sistema", [img]) == "hola anthropic"
assert seen[-1][1]["x-api-key"] == "k2" and json.loads(seen[-1][2])["messages"][0]["content"][0]["type"] == "image"
store.put("ai", {"image": {"mode": "api", "url": url}})
assert provider.api_image("un pulpo") == b"\x89PNG-fake" and seen[-1][0] == "/images/generations"
assert provider.api_image("edita", [img]) == b"\x89PNG-fake" and seen[-1][0] == "/images/edits" and b'name="image[]"' in seen[-1][2]
store.put("ai", {"chat": {"mode": "api"}})  # oficial sin clave: error claro, sin tocar la red
try:
    provider.api_text("hola")
    raise SystemExit("debía fallar")
except provider.AIError as e:
    assert "clave" in str(e)
print("provider ok")
