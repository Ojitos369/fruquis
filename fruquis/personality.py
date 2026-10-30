"""Personalidad de un personaje para el chat: la busca la IA en internet (si es conocido) o la deduce de una historia que da el usuario.
Mismos textos que `Persona` en Ai.kt (Android)."""
from . import provider, sprites, store

ASK = ("describe su PERSONALIDAD para que una IA lo interprete en un chat: temperamento, forma de hablar (tono, muletillas, frases típicas), "
       "gustos y manías, y cómo trata a los demás. Responde SOLO con ese texto en español, en segunda persona («Eres…»), máximo 90 palabras, "
       "sin fuentes ni enlaces.")
UNKNOWN = "DESCONOCIDO"


def prompt(name: str, desc: str, story: str = "") -> str:
    if story:
        return f"Esta es la historia del personaje «{name}» ({desc}):\n\n{story.strip()}\n\nA partir de ella " + ASK
    return (f"Busca en internet quién es «{name}» ({desc}): personaje de ficción, persona o mascota conocida. Luego " + ASK
            + f" Si no encuentras a nadie conocido con ese nombre, responde solo: {UNKNOWN}")


def clean(out: str | None, name: str) -> str:
    """Texto de la IA → personalidad. SystemExit si no respondió o no conoce al personaje."""
    text = (out or "").strip().strip('"')
    if not text:
        raise SystemExit("La IA no respondió. Inténtalo de nuevo.")
    if text.upper().startswith(UNKNOWN):
        raise SystemExit(f"No encontré a «{name}» en la red. Escribe su historia y usa «Sacar de la historia».")
    return text


def generate(cid: str, story: str = "") -> str:
    """Busca (sin `story`) o deduce (con `story`) la personalidad y la guarda en el personaje."""
    c = sprites.get(cid)
    if not provider.chat_ready():
        raise SystemExit("No hay IA configurada (elige el CLI `claude` o una API en Ajustes).")
    out = provider.vision(prompt(c.name, c.description, story), [], store.get("chat_opts", {}).get("model", "haiku"), timeout=240,
                          tools=() if story else ("WebSearch", "WebFetch"))
    text = clean(out, c.name)
    sprites.set_profile(cid, personality=text, story=story.strip() if story else None)
    return text
