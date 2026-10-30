"""Generación de imágenes con la suscripción de ChatGPT a través del CLI oficial de Codex (`codex login`), como en Video Studio:
`codex exec` con las imágenes de referencia y se recoge el PNG que Codex deja en ~/.codex/generated_images. Sin Qt."""
import glob
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from PIL import Image

from . import anatomy, binaries, importer, provider, sprites, store

WIN = os.name == "nt"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KEY = (255, 0, 255)  # fondo de croma: la IA no entrega transparencia real; el importador lo vuelve transparente
_proc = None


def find_codex() -> str | None:
    return binaries.resolve("codex")


def argv(exe: str) -> list:
    return binaries.argv(exe)


def status() -> tuple:
    """(listo, texto) para mostrar en la interfaz."""
    if provider.api_on("image"):
        return provider.test("image")
    exe = find_codex()
    if not exe:
        return False, "No encontré Codex CLI. Instálalo (npm i -g @openai/codex) e inicia sesión con `codex login`."
    try:
        r = subprocess.run([*argv(exe), "login", "status"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20, creationflags=NOWIN)
        out = (r.stdout + r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return False, f"No pude consultar Codex: {e}"
    ok = r.returncode == 0 and "not logged" not in out.lower()
    return ok, ("Codex listo · " + out.splitlines()[0]) if ok else "Codex sin sesión: ejecuta `codex login` y elige ChatGPT."


_procs, _cancelled, _claimed = {}, set(), set()
_lock = threading.Lock()


def cancel(key=None):
    """Cancela una generación (por su clave) o todas las que estén corriendo."""
    with _lock:
        for k, p in list(_procs.items()):
            if key is None or k == key:
                _cancelled.add(k)
                if p.poll() is None:
                    p.kill()
        if isinstance(key, int) and key not in _procs:  # trabajo entre dos procesos: no arrancará el siguiente
            _cancelled.add(key)


def generate(prompt: str, refs: list, timeout: int = 900, key=None, labels: list | None = None) -> bytes:
    """Pide UNA imagen a ChatGPT (Codex) con imágenes de referencia; devuelve los bytes del PNG generado. Seguro en paralelo: la imagen de cada
    ejecución se identifica por el «session id» que imprime Codex (cada sesión guarda las suyas en su propia carpeta)."""
    if key in _cancelled:
        _cancelled.discard(key)
        raise SystemExit("Generación cancelada.")
    if provider.api_on("image"):
        head =("Imágenes de referencia adjuntas, en este orden:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(labels, 1)) + "\n\n") if labels else ""
        try:
            return provider.api_image(head + prompt, refs, timeout)
        except provider.AIError as e:
            raise SystemExit(f"La API de imágenes falló: {e}")
    exe = find_codex()
    if not exe:
        raise SystemExit(status()[1])
    key = key if key is not None else object()
    root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "generated_images"
    before = set(glob.glob(str(root / "**" / "*.*"), recursive=True))
    t0 = time.time()
    head = ("Imágenes de referencia adjuntas, en este orden:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(labels, 1)) + "\n\n") if labels else ""
    msg = ("Usa tu herramienta de generación de imágenes para crear UNA imagen siguiendo exactamente estas instrucciones, usando las imágenes "
           f"adjuntas como referencia:\n\n{head}{prompt}\n\nNo escribas código ni archivos; solo genera la imagen y responde 'listo'.")
    cmd = [*argv(exe), "exec", "-m", os.environ.get("CODEX_IMAGE_MODEL", "gpt-6-luna"), "--skip-git-repo-check", "--ephemeral", "-s", "read-only"]  # Luna 6; alternativa: gpt-5.6-luna
    for r in refs:
        cmd += ["-i", str(r)]
    cmd += ["--", "-"]  # el mensaje va por la entrada estándar: sin comillas ni saltos de línea en los argumentos (cmd.exe de Windows los rompe)
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.Popen(cmd, cwd=tmp, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", creationflags=NOWIN)
        with _lock:
            _procs[key] = p
        try:
            out, err = p.communicate(msg, timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            raise SystemExit("Codex tardó demasiado en generar la imagen.")
        finally:
            with _lock:
                _procs.pop(key, None)
    if key in _cancelled:
        _cancelled.discard(key)
        raise SystemExit("Generación cancelada.")
    sid = re.search(r"session id:\s*([0-9a-fA-F-]{20,})", out + err)
    files = glob.glob(str(root / sid.group(1) / "**" / "*.*"), recursive=True) if sid else []
    if not files:  # sin session id: la imagen nueva que nadie más haya reclamado
        with _lock:
            files = [f for f in glob.glob(str(root / "**" / "*.*"), recursive=True) if f not in before and f not in _claimed and os.path.getmtime(f) >= t0 - 1]
    if not files:
        raise SystemExit("Codex no generó ninguna imagen" + (f": {err[-400:]}" if p.returncode else " (revisa `codex login status`)."))
    best = max(files, key=os.path.getmtime)
    with _lock:
        _claimed.add(best)
    return Path(best).read_bytes()


def neutral_ref(c: sprites.Character) -> Path:
    """La hoja neutral sobre fondo de croma, en un archivo temporal, lista para adjuntarla al generador."""
    sheet = Image.open(c.neutral).convert("RGBA")
    bg = Image.new("RGBA", sheet.size, (*KEY, 255))
    bg.alpha_composite(sheet)
    out = Path(tempfile.mkdtemp()) / "neutral-ref.png"
    bg.convert("RGB").save(out)
    return out


def _flat(rows: list) -> list:
    return [f for r in rows for f in r]


LABEL_NEUTRAL = ("HOJA NEUTRAL del personaje (4 vistas: frontal, trasera, lateral izquierda y lateral derecha). Es la referencia de identidad: el personaje "
                 "generado debe ser EXACTAMENTE este (mismo diseño, colores, rasgos, accesorios y proporciones), no uno parecido.")
LABEL_SOURCE = "IMAGEN GENERAL original del personaje: referencia de identidad; respeta todos sus detalles."


def identity_check(ref_path, result_path, model: str | None = None) -> tuple:
    """La IA (visión) compara la referencia con lo generado: ¿es el MISMO personaje? Devuelve (mismo, motivo). Sin IA disponible, se da por bueno."""
    if not provider.chat_ready() or not store.get("verify_identity", True):
        return True, ""
    a, b = Image.open(ref_path).convert("RGB"), Image.open(result_path).convert("RGB")
    h = 420
    a, b = (im.resize((max(1, int(im.width * h / im.height)), h)) for im in (a, b))
    sheet = Image.new("RGB", (a.width + b.width + 30, h + 20), (90, 90, 96))
    sheet.paste(a, (10, 10))
    sheet.paste(b, (a.width + 20, 10))
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "comparacion.png"
        sheet.save(img)
        prompt = (f"Mira la imagen {img}: a la IZQUIERDA está la referencia del personaje y a la DERECHA una imagen generada. ¿La derecha muestra al MISMO "
                  "personaje que la izquierda (mismo diseño, especie, colores, rasgos distintivos, accesorios y proporciones)? Sé estricto: otro personaje, "
                  'otra criatura o cambios importantes de diseño cuentan como NO. Responde SOLO JSON: {"same": true|false, "reason": "qué difiere"}')
        out = provider.vision(prompt, [img], model or store.get("chat_opts", {}).get("model", "haiku"), timeout=120)
    if out is None:
        return True, ""
    m = re.search(r"\{.*\}", out, re.S)
    try:
        d = json.loads(m.group())
    except (AttributeError, ValueError):
        return True, ""  # sin veredicto claro no se bloquea
    return bool(d.get("same", True)), str(d.get("reason", ""))[:240]


def _save_raw(cid: str, name: str, data: bytes) -> Path:
    d = sprites.writable_dir(cid) / "gen"
    d.mkdir(exist_ok=True)
    out = d / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}-{len(list(d.glob('*.png')))}.png"
    out.write_bytes(data)
    return out


def make_neutral(cid: str, progress=lambda s: None, key=None) -> list:
    """Genera la hoja neutral (4 vistas) a partir de la imagen general (o del primer cuadro de reposo), verifica que sea el mismo personaje (un
    reintento si no) y la guarda."""
    c = sprites.get(cid)
    ref = c.source or sprites.reference(c)
    if not ref:
        raise SystemExit("Carga primero una imagen general del personaje: sirve de referencia para generar sus vistas.")
    anatomy.ensure(cid, progress)
    c = sprites.get(cid)
    text, note = sprites.neutral_prompt(c), ""
    for attempt in (1, 2):
        progress("Generando la hoja neutral (4 vistas) con ChatGPT…" + (" (segundo intento)" if attempt == 2 else ""))
        data = generate(text + note, [ref], key=key, labels=[LABEL_SOURCE])
        raw = _save_raw(cid, "neutral", data)
        same, why = identity_check(ref, raw)
        if same or attempt == 2:
            break
        note = (f"\n\nIMPORTANTE: el intento anterior NO se parecía al personaje de la imagen de referencia ({why}). Copia con exactitud el diseño, "
                "la especie, los colores y los rasgos de la imagen adjunta; no inventes ni cambies nada.")
    out = sprites.set_neutral(cid, str(raw))
    return out + ([f"  ⚠ Puede no parecerse al original: {why}"] if not same else [])


def ensure_neutral(cid: str, progress=lambda s: None, key=None):
    if not sprites.get(cid).neutral:
        progress("No hay hoja neutral: generándola primero…")
        make_neutral(cid, progress, key)


def make_animation(cid: str, anim: str, prompt_text: str, progress=lambda s: None, key=None) -> dict:
    """Genera una animación con ChatGPT. SIEMPRE se adjunta la hoja neutral (si no existe, se genera primero) y la imagen general; la IA verifica
    que el resultado sea el mismo personaje y, si no, se reintenta una vez. Devuelve un plan listo para revisar (ver sprites.plan)."""
    anatomy.ensure(cid, progress)
    ensure_neutral(cid, progress, key)
    c = sprites.get(cid)
    refs = [neutral_ref(c)] + ([c.source] if c.source else [])
    labels = [LABEL_NEUTRAL] + ([LABEL_SOURCE] if c.source else [])
    text, note = prompt_text, ""
    why = ""
    for attempt in (1, 2):
        progress(f"Generando «{anim}» con ChatGPT…" + (" (segundo intento: el primero no se parecía al personaje)" if attempt == 2 else ""))
        data = generate(text + note, refs, key=key, labels=labels)
        raw = _save_raw(cid, anim, data)
        same, why = identity_check(refs[0], raw)
        if same or attempt == 2:
            break
        note = (f"\n\nIMPORTANTE: el intento anterior NO se parecía al personaje de referencia ({why}). Dibuja EXACTAMENTE el personaje de la hoja "
                "neutral adjunta: mismo diseño, especie, colores, rasgos y accesorios; solo cambia la pose según la animación.")
    plan = plan_from_image(cid, anim, str(raw))
    if not same:
        plan["warning"] = f"No parece el mismo personaje: {why}"
    return plan


def animation_ref(c: sprites.Character, anim: str) -> Path:
    """Los cuadros actuales de una animación en una tira sobre fondo de croma, listos para adjuntarlos al generador (para mejorarla)."""
    a = c.anims[anim]
    sheet = Image.open(a["sheet"]).convert("RGBA")
    cw, ch = c.cell
    cols = max(1, sheet.width // cw)
    n = a["frames"]
    strip = Image.new("RGBA", (cw * n, ch), (*KEY, 255))
    for i in range(n):
        cut = sheet.crop(((i % cols) * cw, (a["row"] + i // cols) * ch, (i % cols + 1) * cw, (a["row"] + i // cols + 1) * ch))
        strip.alpha_composite(cut, (i * cw, 0))
    out = Path(tempfile.mkdtemp()) / f"{anim}-actual.png"
    strip.convert("RGB").save(out)
    return out


def plan_from_image(cid: str, anim: str, path: str) -> dict:
    """Plan de revisión (ver sprites.plan) a partir de una imagen ya generada."""
    c = sprites.get(cid)
    rows = importer.analyze(path, c.cell)
    w = sprites.WANTED.get(anim)
    return {"rows": rows, "ai": False, "raw": str(path), "expected": (w[2] if w else None),
            "anims": [{"name": anim, "fps": 8, "mode": "loop", "note": "", "rows": list(range(len(rows)))}]}


def refine_prompt(c: sprites.Character, target: str, instruction: str, background: str = "#FF00FF") -> str:
    """Prompt de corrección: la imagen actual va adjunta y se pide cambiar SOLO lo indicado."""
    if target == "neutral":
        what = ("La imagen es la hoja neutral de 4 vistas del personaje, en este orden de izquierda a derecha: frontal, trasera, lateral izquierda y "
                "lateral derecha. Cada vista debe distinguirse con claridad de las demás: en la trasera se ve la espalda y la parte de atrás de la ropa "
                "y los accesorios (no la cara); en las laterales, el perfil.")
    else:
        w = sprites.WANTED.get(target)
        what = f"La imagen es la animación «{target}»" + (f" ({w[1]})" if w else "") + ": una tira de cuadros que se leen de izquierda a derecha."
    return (f"Corrige y mejora la imagen: la PRIMERA imagen adjunta es la versión actual.\n\nIndicación del usuario: {instruction}\n\n{what}\n\n"
            "Reglas: cambia solo lo que pide la indicación y mantén exactamente igual todo lo demás (personaje, estilo, colores, proporciones, escala, "
            f"el fondo sólido {background or 'liso'}, la distribución y el número y orden de vistas o cuadros). Respeta todos los detalles del personaje: "
            f"{c.brief} Las demás imágenes adjuntas (imagen general u hoja neutral) son solo referencia de identidad. No añadas texto, números, guías, "
            "bordes ni sombras sueltas. Entrega UNA sola imagen final.")


def refine(cid: str, current: str, instruction: str, target: str, progress=lambda s: None, key=None, background: str = "#FF00FF", extra: list = ()) -> str:
    """Una iteración de mejora: manda la versión `current` y la indicación a ChatGPT (Codex) junto con la hoja neutral y la imagen general
    (si no hay hoja neutral se genera antes) y las imágenes `extra` que adjuntó el usuario; guarda y devuelve la ruta de la nueva versión."""
    anatomy.ensure(cid, progress)
    if target != "neutral":
        ensure_neutral(cid, progress, key)
    c = sprites.get(cid)
    refs, labels = [current], ["VERSIÓN ACTUAL que hay que corregir (la imagen a modificar)."]
    if target != "neutral":
        refs.append(neutral_ref(c))
        labels.append(LABEL_NEUTRAL)
    if c.source:
        refs.append(c.source)
        labels.append(LABEL_SOURCE)
    for e in extra:
        refs.append(e)
        labels.append("REFERENCIA ADICIONAL que adjuntó el usuario para esta corrección: úsala como guía de lo que pide la indicación.")
    progress("Generando la nueva versión con ChatGPT…")
    data = generate(refine_prompt(c, target, instruction, background), refs, key=key, labels=labels)
    return str(_save_raw(cid, "neutral" if target == "neutral" else target, data))
