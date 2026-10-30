"""Chat con Claude Code CLI (`claude -p`). Por defecto sin herramientas; opcionalmente puede ejecutar comandos (Bash), ver la ventana activa
(captura + Read) y controlar el escritorio (comandos `ctl`). Lee la salida en streaming para saber qué está haciendo (pensando, leyendo,
trabajando, escribiendo) y avisarlo a la mascota."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from . import binaries, control, machine, place, provider, store

PERSONA = ("Eres {name}, una mascota de escritorio ({desc}). Tierna, breve, "
           "responde siempre en español, máximo 3 frases. No pegues código largo.")
SHELL = "PowerShell" if sys.platform == "win32" else "Bash"  # la terminal de cada sistema: PowerShell en Windows, Bash (terminal) en Linux y macOS
ACT = (" Eres además un asistente completo del equipo del usuario y tienes la herramienta " + SHELL + ": para lo que pida (abrir apps, ajustes o archivos, "
       "buscar, instalar, revisar el sistema, git, scripts…) ejecuta tú los comandos de " + SHELL + " y cuéntalo en una o dos frases, sin decirle que lo haga él. "
       + ("En Windows abre Ajustes con `Start-Process ms-settings:` y apps con `Start-Process`. " if sys.platform == "win32"
          else "En macOS usa `open`; en Linux `xdg-open`. " if sys.platform == "darwin" else "Para abrir cosas usa `xdg-open`. ")
       + ("Para el volumen exacto en Windows usa Add-Type con la interfaz COM IAudioEndpointVolume (SetMasterVolumeLevelScalar / GetMasterVolumeLevelScalar), "
          "no las teclas multimedia. " if sys.platform == "win32" else "")
       + "VERIFICA cada acción: tras ejecutarla comprueba que el resultado sea el pedido (lee el valor, lista el proceso, mira que exista el archivo) y, si no "
         "coincide, corrígelo; no digas «listo» sin comprobarlo y, si no pudiste, dilo con el motivo. "
       + "Las órdenes llegan dictadas por voz y pueden traer errores de transcripción: interpreta la intención («porciento» = por ciento). "
       + "PREFIERE SIEMPRE la terminal a la interfaz gráfica: el ratón es el último recurso porque es lento y falla. Para bajar o guardar algo de internet "
         "(imagen, archivo, PDF) encuentra la URL directa con WebSearch/WebFetch y descárgala con Invoke-WebRequest (o curl) a la carpeta pedida (Descargas = "
         "$env:USERPROFILE\\Downloads), comprueba con Get-Item que existe y su tamaño, y di el nombre del archivo; nunca dejes la descarga «a medias» pidiéndole al usuario "
         "que haga clic: si una URL falla, prueba otra. "
       + "Corrige typos evidentes en rutas. ANTES de algo destructivo o irreversible (borrar, formatear, desinstalar, enviar, pagar) pide confirmación.")
SEE = (" Se te adjunta una captura de la ventana activa del usuario: léela con la herramienta Read (es una imagen) y úsala para responder sobre "
       "su contenido.")
CTL = (" Puedes ver y controlar el escritorio con estos comandos de la terminal (úsalos tal cual):\n"
       "  {p} screenshot [--screen]   → guarda una captura y dice su ruta y origen; léela con Read\n"
       "  {p} screenshot --window \"<parte del título>\"  → captura OTRA ventana aunque no esté enfocada o esté tapada (para mirar sin moverle el foco al usuario)\n"
       "  {p} windows                 → lista las ventanas abiertas\n"
       "  {p} audio                   → ventanas abiertas y qué apps están sonando ahora (para «qué se escucha»)\n"
       "  {p} focus \"<parte del título>\"  → pone una ventana al frente\n"
       "  {p} volume [0-100|+N|-N]    → fija o mueve el volumen del sistema y dice el valor REAL que quedó (úsalo para el volumen)\n"
       "  {p} click X Y [--right|--double] | {p} move X Y | {p} type \"texto\" | {p} key ctrl+l | {p} scroll down 3\n"
       "Cualquiera de esos cinco admite --window \"<parte del título>\": enfoca esa ventana y entonces X Y son de la imagen de `screenshot --window` de ella "
       "(así controlas otra aplicación aunque no esté al frente: captura con --window, actúa con --window y vuelve a capturar para comprobar).\n"
       "Para lo demás (archivos, apps, procesos, sistema) usa directamente la herramienta de terminal con sus propios comandos; nunca digas que no puedes "
       "porque «fruquis no tiene ese comando». Los clics usan coordenadas (píxeles) de la ÚLTIMA captura. Tras actuar toma otra captura para comprobar el resultado. Haz como máximo 15 "
       "acciones por respuesta. ANTES de algo destructivo o irreversible (borrar, enviar, pagar, publicar, cerrar sin guardar) no lo hagas: "
       "pide confirmación al usuario en tu respuesta.")

WEB = (" Puedes buscar en internet con WebSearch y leer páginas con WebFetch: úsalas SIEMPRE para datos que cambian o que no sabes (clima, noticias, "
       "precios, horarios, resultados, información reciente) en vez de adivinar, y responde con el dato concreto, sin listas de fuentes ni enlaces.")

BROWSER = (" Controlas el navegador del usuario (su Chrome/Brave con la extensión Claude in Chrome) con las herramientas mcp__claude-in-chrome__*: empieza SIEMPRE con "
           "tabs_context_mcp, abre tus propias pestañas con tabs_create_mcp, y usa read_page / get_page_text para leer, navigate, find, form_input y computer para actuar, "
           "y comprueba el resultado. Con sus sesiones ya iniciadas puedes trabajar en sus cuentas. Antes de enviar, comprar, publicar o borrar algo, pide confirmación. "
           "Si las herramientas no responden, dile que abra el navegador con la extensión instalada y conectada.")
ERRORS =("No encuentro el CLI", "Tardé demasiado", "No pude responder")
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
        try:  # también los comandos que lanzó (PowerShell, bash…), no solo el CLI
            import psutil
            for c in psutil.Process(_proc.pid).children(recursive=True):
                c.kill()
        except Exception:  # noqa: BLE001 - sin psutil o proceso ya terminado: basta con matar el CLI
            pass
        _proc.kill()


def _phase(block: dict):
    t = block.get("type")
    if t == "thinking":
        return "thinking"
    if t == "tool_use":
        n = block.get("name")
        return "reading" if n == "Read" else "searching" if n in ("WebSearch", "WebFetch") else "working"
    if t == "text":
        return "writing"
    return None


def ask(prompt: str, model: str = "haiku", timeout: int = 120, tools: bool = False, effort: str = "medium", track: bool = False,
        persona: tuple = ("Fruquis", "una criatura simpática"), image: str | None = None, desktop: bool = False, on_phase=None,
        refs: list = ()) -> str:
    """`claude -p`. `tools`: Bash; `image`: captura que puede leer; `refs`: imágenes que adjunta el usuario; `desktop`: ver y controlar el escritorio. `on_phase(str)` se llama con
    thinking / reading / working / writing. `track` permite cancelarla con cancel() (devuelve "")."""
    global _proc
    if provider.api_on("chat"):  # por API: solo texto y visión (sin Bash ni control del escritorio, que son del CLI)
        global _cancelled
        _cancelled = False
        (on_phase or (lambda p: None))("thinking")
        try:
            out = provider.api_text(prompt, PERSONA.format(name=persona[0], desc=persona[1]) + place.hint(), ([image] if image else []) + list(refs), timeout=timeout)
        except provider.AIError as e:
            return f"No pude responder ({e})"
        return "" if _cancelled else (out or "No pude responder (respuesta vacía)")
    exe = claude_bin()
    if not exe:
        return "No encuentro el CLI `claude`. Instálalo o elige su ruta en Ajustes."
    emit = on_phase or (lambda p: None)
    see = bool(image or refs or desktop)
    system = (PERSONA.format(name=persona[0], desc=persona[1]) + (ACT if (tools or desktop) else "") + (SEE if see else "")
              + (CTL.format(p=control.prefix()) if desktop else "")
              + (" Escritorios virtuales de Windows: `key win+ctrl+right` / `key win+ctrl+left` (para ir al primero, varias veces a la izquierda y luego avanza; «el segundo "
                 "escritorio» casi siempre es un escritorio virtual, no un monitor). Las órdenes llegan dictadas y pueden venir mal transcritas: si no tienen sentido, "
                 "pide que las repita en vez de adivinar." if desktop and sys.platform == "win32" else ""))
    system += WEB + place.hint() + (machine.hint() + machine.match(prompt) if (tools or desktop) else "")  # el contexto del equipo solo sirve si puede ejecutar comandos
    names = ([SHELL] if (tools or desktop) else []) + (["Read"] if see else []) + ["WebSearch", "WebFetch"]
    browser = bool(store.get("chat_opts", {}).get("browser"))  # casilla «Navegador» del chat: extensión Claude in Chrome
    if browser:
        system += BROWSER
    if see:  # el usuario dejó ver: además de la captura, qué hay abierto y qué suena (no depende de que la ventana activa sea la que pregunta)
        prompt = control.overview() + "\n" + prompt
    if image:
        prompt = f"[Captura de la ventana activa del usuario: {image} — léela con la herramienta Read.]\n{prompt}"
    if refs:  # se copian a la carpeta de capturas (ya permitida con --add-dir) para que Read pueda abrirlas
        control.SHOTS.mkdir(parents=True, exist_ok=True)
        copies = [shutil.copy(r, control.SHOTS / f"adjunto-{i}{Path(r).suffix}") for i, r in enumerate(refs, 1)]
        prompt = "[Imágenes que adjuntó el usuario como referencia (léelas con la herramienta Read):\n" + "\n".join(copies) + "]\n" + prompt
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    with tempfile.TemporaryDirectory() as tmp:
        sysfile = Path(tmp) / "system.txt"  # el prompt de sistema va en un archivo: sin comillas ni saltos de línea en los argumentos (Windows)
        sysfile.write_text(system, encoding="utf-8")
        cmd = [*binaries.argv(exe), "-p", "--model", model, "--effort", effort, "--no-session-persistence", "--output-format", "stream-json",
               "--verbose", "--system-prompt-file", str(sysfile),
               # sin tus MCP, skills ni ajustes de usuario (hooks, plugins): cada petición arrancaba cargando ~90 herramientas ajenas y tardaba el doble
               "--setting-sources", "project", "--disable-slash-commands"]
        # --strict-mcp-config también bloquea la extensión de Chrome, así que solo se usa sin navegador; con él se prohíben los conectores ajenos
        cmd += ["--disallowedTools", "mcp__claude_ai_*", "--chrome"] if browser else ["--strict-mcp-config"]
        allowed = names + (["mcp__claude-in-chrome__*"] if browser else [])
        cmd += ["--tools", ",".join(names), "--allowedTools", ",".join(allowed), "--add-dir", str(control.SHOTS)] if names else ["--tools", ""]
        if names:
            control.SHOTS.mkdir(parents=True, exist_ok=True)
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                             cwd=Path.home(), env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # en Windows no abre consola
        if track:
            _proc = p
        timed_out = []
        timer = threading.Timer(timeout * (5 if desktop or browser else 1), lambda: (timed_out.append(1), p.kill()))
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
