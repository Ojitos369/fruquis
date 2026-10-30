"""Personalidad y animaciones pedidas por la IA ([[anim:…]]) en el chat. Uso: python tests/test_persona.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fruquis import chat, personality, sprites  # noqa: E402

have = {"idle": {}, "cleaning": {}, "running-left": {}}
assert chat.split_anim("¡Voy a bañarme! [[anim:cleaning]]", have) == ("¡Voy a bañarme!", "cleaning")
assert chat.split_anim("Hola [[ anim : dancing ]]", have) == ("Hola", None)          # no la tiene
assert chat.split_anim("Corro [[anim:running-left]]", have) == ("Corro", None)       # de locomoción: no
assert chat.split_anim("Sin marca", have) == ("Sin marca", None)

p = chat.persona_prompt(("Alastor", "demonio", "Eres un locutor teatral.", list(have)))
assert "locutor teatral" in p and "Tierna" not in p and "cleaning (se limpia)" in p and "running-left" not in p
assert "Tierna" in chat.persona_prompt(("Fruquis", "criatura"))

assert "historia" in personality.prompt("A", "b", "Era un niño…") and personality.UNKNOWN in personality.prompt("A", "b")
assert personality.clean("Eres alegre.", "A") == "Eres alegre."
for bad in ("", "DESCONOCIDO"):
    try:
        personality.clean(bad, "A")
        raise AssertionError(bad)
    except SystemExit:
        pass

d = Path(tempfile.mkdtemp()) / "x"
d.mkdir()
(d / "character.json").write_text(json.dumps({"name": "X", "anims": {}, "personality": "Eres gruñón.", "story": "Nació…"}))
c = sprites._load(d)
assert (c.personality, c.story) == ("Eres gruñón.", "Nació…")
print("ok")
