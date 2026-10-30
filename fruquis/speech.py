"""Respuestas en voz alta con voz masculina o femenina según el género del personaje (`gender` en character.json: "masculino", "femenino"
o vacío = voz del sistema). Se apaga con el ajuste «Responder con voz» (store "speak"). Paridad con Speech en android/.../VoiceService.kt.
Usa lo que trae cada sistema: spd-say/espeak-ng (Linux), say (macOS), System.Speech por PowerShell (Windows)."""
import re
import shutil
import subprocess
import sys

from . import store

_proc = None
# macOS no da el género de sus voces: nombres de voces en español conocidas
MAC = {"masculino": "Juan", "femenino": "Paulina"}


def clean(text: str) -> str:
    """Sin emojis ni marcas de markdown: el sintetizador los leería en voz alta."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.,;:¿?¡!'\"()%-]", " ", text)).strip()


def command(text: str, gender: str) -> tuple[list, str | None]:
    """(comando, texto por stdin) para decir `text` en este sistema; ([], None) si no hay sintetizador."""
    if sys.platform == "win32":
        g = {"masculino": "Male", "femenino": "Female"}.get(gender)
        hint = f"$s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::{g}, [System.Speech.Synthesis.VoiceAge]::Adult, 0, [Globalization.CultureInfo]'es-ES');" if g else ""
        return (["powershell", "-NoProfile", "-Command", "[Console]::InputEncoding = [Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                 + hint + " $s.Speak([Console]::In.ReadToEnd())"], text)
    if sys.platform == "darwin":
        return (["say", *(["-v", MAC[gender]] if gender in MAC else []), text], None)
    if shutil.which("spd-say"):
        return (["spd-say", "-w", "-l", "es", *(["-t", "male1" if gender == "masculino" else "female1"] if gender in MAC else []), "--", text], None)
    if exe := shutil.which("espeak-ng") or shutil.which("espeak"):
        return ([exe, "-v", "es" + {"masculino": "+m3", "femenino": "+f3"}.get(gender, ""), text], None)
    return ([], None)


def speaking() -> bool:
    """Está diciendo algo (el proceso vive hasta terminar de hablar): la escucha ignora lo que oye para no tomar su propia voz como orden."""
    return _proc is not None and _proc.poll() is None


def stop():
    global _proc
    if _proc and _proc.poll() is None:
        _proc.kill()
        if sys.platform.startswith("linux") and shutil.which("spd-say"):
            subprocess.run(["spd-say", "-C"], capture_output=True)  # speech-dispatcher sigue hablando aunque muera el cliente
    _proc = None


def say(text: str, gender: str = ""):
    """Dice `text` (cortando lo que se estuviera diciendo) si el ajuste «Responder con voz» está activo."""
    global _proc
    text = clean(text)
    if not store.get("speak", True) or not text:
        return
    cmd, stdin = command(text, gender)
    if not cmd:
        return
    stop()
    try:
        _proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if stdin else subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if stdin:
            _proc.stdin.write(stdin)
            _proc.stdin.close()
    except OSError:  # sintetizador roto o sin permisos: se responde solo con texto
        _proc = None


if __name__ == "__main__":
    assert clean("¡Hola! 😄 **listo**") == "¡Hola! listo"
    say("Hola, soy Fruquis", "femenino")
