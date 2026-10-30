"""Chat con Claude Code CLI (`claude -p`). Por defecto sin herramientas; opcionalmente puede ejecutar comandos (Bash), ver la ventana activa
(captura + Read) y controlar el escritorio (comandos `ctl`). Lee la salida en streaming para saber qué está haciendo (pensando, leyendo,
trabajando, escribiendo) y avisarlo a la mascota."""
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from . import binaries, control, provider

PERSONA = ("Eres {name}, una mascota de escritorio ({desc}). Tierna, breve, "
           "responde siempre en español, máximo 3 frases. No pegues código largo.")
ACT = " Tienes la herramienta Bash: si el usuario pide abrir, ejecutar o revisar algo, hazlo tú y cuéntalo en una frase. Corrige typos evidentes en rutas."
SEE = (" Se te adjunta una captura de la ventana activa del usuario: léela con la herramienta Read (es una imagen) y úsala para responder sobre "
       "su contenido.")
CTL = (" Puedes ver y controlar el escritorio con estos comandos de Bash (úsalos tal cual):\n"
       "  {p} screenshot [--screen]   → guarda una captura y dice su ruta y origen; léela con Read\n"
       "  {p} windows                 → lista las ventanas abiertas\n"
       "  {p} focus \"<parte del título>\"  → pone una ventana al frente\n"
       "  {p} click X Y [--right|--double] | {p} move X Y | {p} type \"texto\" | {p} key ctrl+l | {p} scroll down 3\n"
       "Los clics usan coordenadas (píxeles) de la ÚLTIMA captura. Tras actuar toma otra captura para comprobar el resultado. Haz como máximo 15 "
       "acciones por respuesta. ANTES de algo destructivo o irreversible (borrar, enviar, pagar, publicar, cerrar sin guardar) no lo hagas: "
       "pide confirmación al usuario en tu respuesta.")

ERRORS = ("No encuentro el CLI", "Tardé demasiado", "No pude responder")
_proc = None
_cancelled = False  # la petición por API no se puede abortar: se descarta su respuesta


def claude_bin() -> str | None:
    return binaries.resolve("claude")


def is_error(text: str) -> bool:
    return text.startswith(ERRORS)


def cancel():
    """Detiene la respuesta en curso (el chat la usa para el botón de parar)."""
    global _cancelled
    _cancelled = True
    if _proc and _proc.poll() is None:
        _proc.kill()


def _phase(block: dict):
    t = block.get("type")
    if t == "thinking":
        return "thinking"
    if t == "tool_use":
        return "reading" if block.get("name") == "Read" else "working"
    if t == "text":
        return "writing"
    return None


def ask(prompt: str, model: str = "haiku", timeout: int = 120, tools: bool = False, effort: str = "medium", track: bool = False,
        persona: tuple = ("Fruquis", "una criatura simpática"), image: str | None = None, desktop: bool = False, on_phase=None) -> str:
    """`claude -p`. `tools`: Bash; `image`: captura que puede leer; `desktop`: ver y controlar el escritorio. `on_phase(str)` se llama con
    thinking / reading / working / writing. `track` permite cancelarla con cancel() (devuelve "")."""
    global _proc
    if provider.api_on("chat"):  # por API: solo texto y visión (sin Bash ni control del escritorio, que son del CLI)
        global _cancelled
        _cancelled = False
        (on_phase or (lambda p: None))("thinking")
        try:
            out = provider.api_text(prompt, PERSONA.format(name=persona[0], desc=persona[1]), [image] if image else [], timeout=timeout)
        except provider.AIError as e:
            return f"No pude responder ({e})"
        return "" if _cancelled else (out or "No pude responder (respuesta vacía)")
    exe = claude_bin()
    if not exe:
        return "No encuentro el CLI `claude`. Instálalo o elige su ruta en Ajustes."
    emit = on_phase or (lambda p: None)
    system = (PERSONA.format(name=persona[0], desc=persona[1]) + (ACT if (tools or desktop) else "") + (SEE if (image or desktop) else "")
              + (CTL.format(p=control.prefix()) if desktop else ""))
    names = ([] + (["Bash"] if (tools or desktop) else []) + (["Read"] if (image or desktop) else []))
    if image:
        prompt = f"[Captura de la ventana activa del usuario: {image} — léela con la herramienta Read.]\n{prompt}"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    with tempfile.TemporaryDirectory() as tmp:
        sysfile = Path(tmp) / "system.txt"  # el prompt de sistema va en un archivo: sin comillas ni saltos de línea en los argumentos (Windows)
        sysfile.write_text(system, encoding="utf-8")
        cmd = [*binaries.argv(exe), "-p", "--model", model, "--effort", effort, "--no-session-persistence", "--output-format", "stream-json",
               "--verbose", "--system-prompt-file", str(sysfile)]
        cmd += ["--tools", ",".join(names), "--allowedTools", ",".join(names), "--add-dir", str(control.SHOTS)] if names else ["--tools", ""]
        if names:
            control.SHOTS.mkdir(parents=True, exist_ok=True)
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                             cwd=Path.home(), env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # en Windows no abre consola
        if track:
            _proc = p
        timed_out = []
        timer = threading.Timer(timeout * (3 if desktop else 1), lambda: (timed_out.append(1), p.kill()))
        timer.start()
        emit("thinking")
        final, texts, tail = None, [], []
        try:
            p.stdin.write(prompt)
            p.stdin.close()
        except OSError:
            pass
        for line in p.stdout:
            line = line.strip()
            if not line.startswith("{"):
                tail.append(line)
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "assistant":
                for b in d.get("message", {}).get("content", []):
                    if ph := _phase(b):
                        emit(ph)
                    if b.get("type") == "text":
                        texts.append(b.get("text", ""))
            elif d.get("type") == "result":
                final = d.get("result")
        p.wait()
        timer.cancel()
    if timed_out:
        return "Tardé demasiado en pensar…"
    if p.returncode is not None and p.returncode < 0:  # cancelada
        return ""
    return (final if final is not None else "\n".join(texts)).strip() or f"No pude responder ({' '.join(tail)[-160:]})"
