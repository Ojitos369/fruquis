"""Chat con Claude Code CLI (`claude -p`). Ideas sin herramientas; el chat puede usar Bash."""
import shutil
import subprocess
from pathlib import Path

PERSONA = ("Eres {name}, una mascota de escritorio ({desc}). Tierna, breve, "
           "responde siempre en español, máximo 3 frases. No pegues código largo.")
ACT = " Tienes la herramienta Bash: si el usuario pide abrir, ejecutar o revisar algo, hazlo tú y cuéntalo en una frase. Corrige typos evidentes en rutas."


def claude_bin() -> str | None:
    return shutil.which("claude") or next(
        (str(p) for p in (Path.home() / ".local/bin/claude", Path.home() / ".claude/local/claude", Path.home() / ".npm-global/bin/claude") if p.exists()), None)


ERRORS = ("No encuentro el CLI", "Tardé demasiado", "No pude responder")
_proc = None


def is_error(text: str) -> bool:
    return text.startswith(ERRORS)


def cancel():
    """Detiene la respuesta en curso (el chat la usa para el botón de parar)."""
    if _proc and _proc.poll() is None:
        _proc.kill()


def ask(prompt: str, model: str = "haiku", timeout: int = 120, tools: bool = False, effort: str = "medium", track: bool = False, persona: tuple = ("Fruquis", "una criatura simpática")) -> str:
    """`claude -p`; con `tools` puede usar Bash. `track` permite cancelarla con cancel() (devuelve "")."""
    global _proc
    exe = claude_bin()
    if not exe:
        return "No encuentro el CLI `claude`. Instálalo o ponlo en PATH."
    cmd = [exe, "-p", "--model", model, "--effort", effort, "--no-session-persistence", "--system-prompt", PERSONA.format(name=persona[0], desc=persona[1]) + (ACT if tools else ""),
           *(["--tools", "Bash", "--allowedTools", "Bash"] if tools else ["--tools", ""])]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=Path.home(),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # en Windows no abre consola
    if track:
        _proc = p
    try:
        out, err = p.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        return "Tardé demasiado en pensar…"
    if p.returncode < 0:  # cancelada
        return ""
    return out.strip() or f"No pude responder ({err.strip()[:120]})"
