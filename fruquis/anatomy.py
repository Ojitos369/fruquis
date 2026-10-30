"""Identidad visual y anatomía de un personaje, analizadas por la IA (visión) a partir de sus imágenes de referencia. Con eso los prompts
describen al personaje con precisión y adaptan cada animación a su cuerpo (una serpiente repta, no camina; sin brazos, saluda con la cola)."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

from . import binaries, chat, sprites, store


def reference_image(c: sprites.Character):
    """La mejor imagen disponible del personaje para que la IA la mire: hoja neutral (sobre fondo gris), imagen general o cuadro de reposo."""
    from PIL import Image
    if c.neutral:
        im = Image.open(c.neutral).convert("RGBA")
        bg = Image.new("RGBA", im.size, (118, 118, 126, 255))
        bg.alpha_composite(im)
        out = Path(tempfile.mkdtemp()) / "neutral.png"
        bg.convert("RGB").save(out)
        return out
    return c.source or sprites.reference(c)


def analyze(cid: str, model: str | None = None) -> dict:
    """Pide a claude (viendo las imágenes) {identity, anatomy, actions} y lo guarda en el personaje. SystemExit si no se puede."""
    c = sprites.get(cid)
    img = reference_image(c)
    exe = chat.claude_bin()
    if not exe:
        raise SystemExit("No encuentro el CLI `claude` (elige su ruta en Ajustes).")
    if not img:
        raise SystemExit("El personaje no tiene ninguna imagen: carga primero la imagen general.")
    model = model or store.get("chat_opts", {}).get("model", "haiku")
    base = "\n".join(f"- {n}: {w[4]}" for n, w in sprites.WANTED.items())
    with tempfile.TemporaryDirectory() as tmp:
        cp = Path(tmp) / img.name
        cp.write_bytes(Path(img).read_bytes())
        prompt = (
            f"Mira con atención la imagen {cp}: es el personaje «{c.name}» de una mascota de escritorio. Analízalo y responde SOLO un objeto JSON "
            "(sin texto extra) con estas claves, todas en inglés porque se usarán en prompts de generación de imágenes:\n"
            '- "identity": descripción visual precisa y compacta (máximo 80 palabras): tipo de criatura, colores exactos, rasgos distintivos '
            "(ojos, cabello, escamas, accesorios, joyas, marcas), proporciones y estilo.\n"
            '- "anatomy": qué partes del cuerpo SÍ tiene y cuáles NO (por ejemplo «serpentine lower body, no legs; two small arms; tail ending in an '
            'ice-crystal star») y su forma natural de moverse (máximo 60 palabras).\n'
            '- "actions": un objeto con una entrada por CADA animación de la lista, con la descripción del movimiento reescrita para ESTA anatomía '
            "(máximo 35 palabras cada una): usa solo las partes que tiene; si la acción base pide algo que no tiene (piernas, manos), sustitúyelo por lo "
            "equivalente en su cuerpo; conserva el espíritu de la acción.\n\nAnimaciones y descripción base:\n" + base)
        r = subprocess.run([*binaries.argv(exe), "-p", "--model", model, "--effort", "medium", "--no-session-persistence", "--tools", "Read",
                            "--allowedTools", "Read", "--add-dir", tmp], input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=240, cwd=tmp, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    m = re.search(r"\{.*\}", r.stdout, re.S)
    try:
        d = json.loads(m.group()) if m else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not d.get("identity"):
        raise SystemExit("La IA no devolvió un análisis utilizable. Inténtalo de nuevo.")
    actions = {k: str(v).strip() for k, v in (d.get("actions") or {}).items() if k in sprites.WANTED and str(v).strip()}
    sprites.set_profile(cid, identity=str(d["identity"]).strip(), anatomy=str(d.get("anatomy", "")).strip(), actions=actions)
    return {"identity": d["identity"], "anatomy": d.get("anatomy", ""), "actions": actions}


_tried = set()


def ensure(cid: str, progress=lambda s: None):
    """Si el personaje aún no tiene identidad/anatomía, la analiza ahora (hace falta antes de generar para que no se invente el diseño).
    Se intenta una sola vez por sesión: si falla, se genera igual con las imágenes de referencia."""
    c = sprites.get(cid)
    if (c.identity and c.anatomy) or cid in _tried:
        return
    _tried.add(cid)
    progress("Analizando al personaje (identidad y anatomía)…")
    try:
        analyze(cid)
    except SystemExit:
        pass  # sin análisis se genera igual con la imagen de referencia; no bloquea
