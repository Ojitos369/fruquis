"""Personajes: cada uno es una carpeta {character.json, hojas .png, brief.md}. Sin Qt (probable con `python -m fruquis check`)."""
import hashlib
import json
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import store

BUNDLED = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)) / "fruquis" / "characters"
USER = store.HOME / "characters"
DEFAULT_CELL = (192, 208)
LOOK = "look"  # 16 cuadros (22.5° c/u) en filas consecutivas de 8

# nombre: (obligatoria, para qué sirve, cuadros sugeridos, respaldo, acción para el prompt de generación)
WANTED = {
    "idle": (True, "de pie, respirando", 6, None, "Calm resting loop in the character's own natural resting posture: gentle breathing and a blink, using only the body parts it has."),
    "running-right": (True, "camina/corre a la derecha", 8, None, "Rightward locomotion cycle, facing right, in the way THIS character naturally moves (walking, slithering, gliding, hopping, floating...), using only the body parts it has."),
    "running-left": (True, "camina/corre a la izquierda", 8, None, "Leftward locomotion cycle, facing left, in the way THIS character naturally moves (walking, slithering, gliding, hopping, floating...), using only the body parts it has."),
    "jumping": (True, "salto de alegría / salto a una ventana", 5, None, "Joyful vertical jump in the character's own way: anticipation (crouch or coil), take-off, apex, descent and landing, using the body parts it really has."),
    "waving": (True, "saluda", 4, None, "Friendly greeting loop with whatever this character can greet with (an arm, a tail, a tentacle, a wing, or a head tilt if it has no limbs). No wave marks or symbols."),
    "failed": (True, "triste/error", 8, None, "Sad or dismayed reaction: slump, droop and partial recovery, expressed through the character's own posture and face."),
    "waiting": (True, "espera", 6, None, "Patient waiting: small head tilts and weight shifts typical of this character's body."),
    "review": (True, "pensando/trabajando", 6, None, "Focused thinking: concentrating pose with small head movements, using the character's own body language."),
    "talking": (False, "habla (mensajes y chat)", 4, "waving", "Speaking loop: the mouth (or its equivalent) opens and closes with small head bobs. No speech bubbles or text."),
    "sleeping": (False, "duerme", 4, "waiting", "Asleep in this character's natural resting pose (curled, coiled, lying, perched...): eyes closed, slow breathing cycle. No 'Zzz' text or symbols."),
    "sitting": (False, "sentada en un borde", 4, "idle", "Resting in this character's natural 'seated' pose on a ledge (legs dangling if it has legs; coiled tail, hovering or perched if it does not), small blinks and sways."),
    "dragged": (False, "colgada mientras la arrastras", 3, "waiting", "Hanging as if held from the top of the head: the body dangles naturally and sways gently."),
    "falling": (False, "cae", 3, "jumping", "Falling: surprised face, body parts trailing upward as they would on this character. Loop."),
    "climbing": (False, "trepa paredes (se dibuja de pie, la app la rota)", 6, "running-right", "Climbing cycle in this character's own way (limbs, coiling, clinging), drawn UPRIGHT like a locomotion cycle. The app rotates it onto walls and ceilings."),
    "poking": (False, "pica algo", 5, "jumping", "Reaches out with whatever the character has (an arm, a tail tip, a tentacle, its nose) to press something in front of it, then retracts."),
    "reading": (False, "lee / mira con atención (cuando analiza tu ventana)", 4, "review", "Reading attentively: head slightly lowered, eyes scanning left and right, small nods."),
    "typing": (False, "teclea", 4, "review", "Quickly taps forward with its own appendages as if typing on an invisible keyboard (no keyboard drawn)."),
    "pampered": (False, "la están mimando (feliz, se deja querer)", 5, "waving", "Being petted and pampered: eyes closed in bliss, leaning into the touch, small happy wiggle. No hearts or effects drawn."),
    "playing": (False, "juega", 6, "jumping", "Playful: bouncing, spinning or batting at an invisible toy, in this character's own way."),
    "eating": (False, "come", 6, "waving", "Eating: brings invisible food to the mouth with its own limbs (or lunges at it if it has none), cheeks or body puffing while chewing, happy. No food drawn."),
    "cleaning": (False, "se limpia", 6, "waving", "Cleaning itself in this character's own way (grooming with limbs, shaking, rubbing against itself). No bubbles or effects drawn."),
}
STYLE = ("Pet-safe sprite: compact full-body mascot, readable in a {w}x{h} cell, clear silhouette, simple face, stable palette/materials, "
         "and crisp edges for chroma-key extraction.")


@dataclass
class Character:
    id: str
    name: str
    description: str
    cell: tuple
    anims: dict  # nombre -> {sheet: Path, row, frames, fps, loop}
    dir: Path
    identity: str = ""    # descripción visual precisa (la escribe la IA al analizar las imágenes del personaje; editable)
    anatomy: str = ""     # partes del cuerpo que tiene y las que no, y su forma natural de moverse
    actions: dict = field(default_factory=dict)  # animación -> descripción del movimiento adaptada a su anatomía

    @property
    def source(self):
        """Imagen general de referencia (la carga el usuario); sirve de base para generar las vistas y las animaciones."""
        f = self.dir / "source.png"
        return f if f.exists() else None

    @property
    def neutral(self):
        """Hoja neutral: 4 vistas (frontal, trasera, lateral izquierda y derecha). Es solo de referencia: no sale en el catálogo de animaciones."""
        f = self.dir / "neutral.png"
        return f if f.exists() else None

    @property
    def brief(self) -> str:
        f = self.dir / "brief.md"
        base = f.read_text().strip() if f.exists() else self.description
        return (base + (" " if base else "") + f"Detailed visual description: {self.identity}").strip() if self.identity else base


def _load(d: Path) -> Character | None:
    try:
        j = json.loads((d / "character.json").read_text())
    except Exception:
        return None
    anims = {n: {**a, "sheet": d / a["sheet"]} for n, a in j["anims"].items()}
    return Character(d.name, j.get("name", d.name), j.get("description", ""), tuple(j.get("cell", DEFAULT_CELL)), anims, d,
                     j.get("identity", ""), j.get("anatomy", ""), j.get("actions", {}))


def list_all() -> dict:
    out = {}
    for base in (BUNDLED, USER):
        for d in sorted(base.glob("*")):
            if (c := _load(d)):
                out[c.id] = c
    return out


def get(cid: str) -> Character:
    """El personaje `cid`, o el primero que haya si no existe. SystemExit con instrucciones si no hay ninguno."""
    allc = list_all()
    if not allc:
        raise SystemExit("No hay personajes. Importa uno: ./run.sh import personaje.zip")
    return allc.get(cid) or next(iter(allc.values()))


def writable_dir(cid: str) -> Path:
    """Carpeta editable del personaje; un personaje incluido se copia primero a ~/.fruquis."""
    d = USER / cid
    if not d.exists():
        src = BUNDLED / cid
        if src.exists():
            shutil.copytree(src, d)
        else:
            d.mkdir(parents=True)
    return d


def _save(d: Path, name, description, cell, anims):
    try:
        j = json.loads((d / "character.json").read_text())  # se conservan los demás campos (identidad, anatomía, acciones…)
    except Exception:
        j = {}
    j.update({"name": name, "description": description, "cell": list(cell), "anims": {n: {**a, "sheet": Path(a["sheet"]).name} for n, a in anims.items()}})
    (d / "character.json").write_text(json.dumps(j, indent=1, ensure_ascii=False))


def set_profile(cid: str, identity=None, anatomy=None, actions=None):
    """Guarda la identidad visual, la anatomía y las acciones adaptadas del personaje (lo que no se pasa se conserva)."""
    d = writable_dir(cid)
    c = get(cid)
    _save(d, c.name, c.description, c.cell, c.anims)
    j = json.loads((d / "character.json").read_text())
    for k, v in (("identity", identity), ("anatomy", anatomy), ("actions", actions)):
        if v is not None:
            j[k] = v
    (d / "character.json").write_text(json.dumps(j, indent=1, ensure_ascii=False))


def create(name: str, description: str, cell=DEFAULT_CELL) -> Character:
    cid = "".join(ch for ch in name.lower().replace(" ", "-") if ch.isalnum() or ch == "-") or "personaje"
    d = writable_dir(cid)
    (d / "brief.md").write_text(description.strip() + "\n")
    _save(d, name, description, cell, {})
    return get(cid)


def plan(cid: str, path: str, ai: bool = True, model: str = "haiku") -> dict:
    """Analiza una hoja de cualquier tamaño: {rows: cuadros normalizados por fila, anims: [{name, fps, mode, note, rows}], ai: bool}.
    Con `ai`, claude (viendo la imagen) decide qué animaciones hay y si varias filas son una sola; sin ella, una animación por fila."""
    from . import importer
    c = get(cid)
    rows = importer.analyze(path, c.cell)
    anims = importer.describe(path, rows, {n: w[4] for n, w in WANTED.items()}, model) if ai else None
    if anims:
        for o in anims:
            o["rows"] = [r for r in o.get("rows", []) if 0 <= r < len(rows)] or [0]
    else:
        todo = [n for n in WANTED if n not in c.anims]
        anims = [{"name": todo[i] if i < len(todo) else f"anim{i}", "fps": 8, "mode": "loop", "note": "", "rows": [i]} for i in range(len(rows))]
    return {"rows": rows, "anims": anims, "ai": bool(ai and anims and anims[0].get("note") is not None and ai)}


def apply(cid: str, rows: list, anims: list) -> list:
    """Escribe una hoja con una fila por animación (los cuadros de sus filas, en orden) y las registra; reemplaza las de igual nombre."""
    c = get(cid)
    lists = [[f for r in o["rows"] for f in rows[r]] for o in anims]
    cols = max(len(x) for x in lists)
    sheet = Image.new("RGBA", (c.cell[0] * cols, c.cell[1] * len(lists)), (0, 0, 0, 0))
    for i, fr in enumerate(lists):
        for j, f in enumerate(fr):
            sheet.alpha_composite(f, (j * c.cell[0], i * c.cell[1]))
    d = writable_dir(cid)
    name = f"hoja-{hashlib.sha1(sheet.tobytes()).hexdigest()[:10]}.png"
    sheet.save(d / name)
    c = get(cid)
    out, log = dict(c.anims), []
    for i, (o, fr) in enumerate(zip(anims, lists)):
        mode = o.get("mode", "loop")
        out[o["name"]] = {"sheet": d / name, "row": i, "frames": len(fr), "fps": o.get("fps", 8), "loop": mode != "once", "pingpong": mode == "pingpong"}
        log.append(f"  {o['name']}: {len(fr)} cuadros, {o.get('fps', 8)} fps, {mode}" + (f" — {o['note']}" if o.get("note") else ""))
    _save(d, c.name, c.description, c.cell, out)
    _gc(d)
    return log


def add_sheet(cid: str, path: str, names: list | None = None, fps: int | None = None, ai: bool = True, model: str = "haiku") -> list:
    """Agrega una hoja de cualquier tamaño. Con `names` (uno por fila) no usa IA; sin ellos la IA propone todo."""
    p = plan(cid, path, ai=names is None and ai, model=model)
    if names:
        if len(names) > len(p["rows"]):
            raise SystemExit(f"{len(names)} nombres pero detecté {len(p['rows'])} fila(s) de cuadros.")
        p["anims"] = [{"name": n.strip(), "fps": fps or 8, "mode": "loop", "rows": [i]} for i, n in enumerate(names) if n.strip()]
    elif fps:
        for o in p["anims"]:
            o["fps"] = fps
    return apply(cid, p["rows"], p["anims"])


def replace(cid: str, name: str, path: str, row: int | None = None) -> list:
    """Cambia los cuadros de una animación por los de la hoja, conservando su fps y modo. Sin `row` toma TODAS las filas, en orden de lectura
    (una animación suele continuar en la fila siguiente); con `row`, solo esa."""
    from . import importer
    c = get(cid)
    rows = importer.analyze(path, c.cell)
    old = c.anims.get(name, {})
    mode = "pingpong" if old.get("pingpong") else ("loop" if old.get("loop", True) else "once")
    return apply(cid, rows, [{"name": name, "fps": old.get("fps", 8), "mode": mode, "rows": list(range(len(rows))) if row is None else [min(row, len(rows) - 1)]}])


def remove(cid: str, name: str):
    c = get(cid)
    d = writable_dir(cid)
    anims = {n: a for n, a in c.anims.items() if n != name}
    _save(d, c.name, c.description, c.cell, anims)
    _gc(d)


def set_meta(cid: str, name: str, fps: int, mode: str):
    c = get(cid)
    d = writable_dir(cid)
    anims = dict(get(cid).anims)
    anims[name] = {**anims[name], "fps": fps, "loop": mode != "once", "pingpong": mode == "pingpong"}
    _save(d, c.name, c.description, c.cell, anims)


def _gc(d: Path):  # noqa: D401
    """Borra las hojas de la carpeta del usuario que ya ninguna animación usa (nunca la referencia, la imagen general ni la hoja neutral)."""
    used = {a["sheet"] for a in (_load(d).anims.values() if _load(d) else [])}
    for f in d.glob("*.png"):
        if f.name not in ("reference.png", "source.png", "neutral.png") and f not in used:
            f.unlink()


MAX_ZIP, MAX_FILE, MAX_PX = 120 * 1024 * 1024, 40 * 1024 * 1024, 8192
SAFE_NAME = re.compile(r"^[\w .()\-]+\.(json|png|md)$")


def export_character(cid: str, dest: str) -> Path:
    """Empaqueta un personaje en un zip (character.json, sus hojas, brief.md y reference.png) para llevarlo a otro equipo."""
    c = get(cid)
    d = Path(dest)
    if d.is_dir():
        d = d / f"{c.id}.zip"
    d = d.with_suffix(".zip") if d.suffix.lower() != ".zip" else d
    sheets = {Path(a["sheet"]).name for a in c.anims.values()}
    with zipfile.ZipFile(d, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ["character.json", "brief.md", "reference.png", "source.png", "neutral.png", *sorted(sheets)]:
            if (c.dir / name).exists():
                z.write(c.dir / name, f"{c.id}/{name}")
    return d


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", text.lower().replace(" ", "-").replace("_", "-")).strip("-") or "personaje"


def import_character(path: str, overwrite: bool = False) -> Character:
    """Importa un zip hecho con export_character. Valida rutas, tamaños e imágenes antes de escribir; un id repetido recibe sufijo
    (-2, -3…) salvo con `overwrite`, que reemplaza al personaje del usuario."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise SystemExit(f"No es un zip válido: {e}")
    with z:
        files = {}
        total = 0
        for i in z.infolist():
            if i.is_dir():
                continue
            parts = Path(i.filename).parts
            if i.filename.startswith(("/", "\\")) or ".." in parts or len(parts) > 2 or not SAFE_NAME.match(parts[-1]):
                raise SystemExit(f"El zip trae un archivo no permitido: {i.filename}")
            total += i.file_size
            if i.file_size > MAX_FILE or total > MAX_ZIP:
                raise SystemExit("El zip es demasiado grande para ser un personaje.")
            files[parts[-1]] = i
        if "character.json" not in files:
            raise SystemExit("El zip no trae character.json: no parece un personaje de Fruquis.")
        try:
            j = json.loads(z.read(files["character.json"]))
            cw, ch = (int(v) for v in j["cell"])
            anims = j["anims"]
            assert 8 <= cw <= 2048 and 8 <= ch <= 2048 and isinstance(anims, dict) and len(anims) <= 200
            for n, a in anims.items():
                sheet = a["sheet"]
                if sheet not in files or "/" in sheet or "\\" in sheet:
                    raise SystemExit(f"La animación '{n}' usa la hoja '{sheet}', que no está en el zip.")
                assert int(a["frames"]) > 0 and int(a["row"]) >= 0 and float(a["fps"]) > 0
        except (KeyError, ValueError, TypeError, AssertionError):
            raise SystemExit("character.json está dañado o incompleto.")
        from io import BytesIO
        for name, i in files.items():  # las imágenes se abren de verdad (acotadas) y las filas deben caber en la hoja
            if name.endswith(".png"):
                try:
                    im = Image.open(BytesIO(z.read(i)))
                    im.verify()
                    w, h = Image.open(BytesIO(z.read(i))).size
                except Exception as e:  # noqa: BLE001
                    raise SystemExit(f"{name} no es una imagen válida: {e}")
                if max(w, h) > MAX_PX:
                    raise SystemExit(f"{name} es demasiado grande ({w}x{h}).")
                for n, a in anims.items():
                    if a["sheet"] == name and (a["row"] + -(-a["frames"] // max(1, w // cw))) * ch > h:
                        raise SystemExit(f"La animación '{n}' no cabe en su hoja ({name}).")
        root = Path(next(iter(z.namelist()))).parts[0] if "/" in next(iter(z.namelist())) else j.get("name", "personaje")
        cid = _slug(root)
        taken = set(list_all())
        if cid in taken and overwrite and (USER / cid).exists():
            shutil.rmtree(USER / cid)
        elif cid in taken:
            k = 2
            while f"{cid}-{k}" in taken:
                k += 1
            cid = f"{cid}-{k}"
        dest = USER / cid
        dest.mkdir(parents=True, exist_ok=True)
        for name, i in files.items():
            (dest / name).write_bytes(z.read(i))
    return get(cid)


def fallback(have: dict, name: str):
    while name not in have:
        name = WANTED.get(name, (0, 0, 0, None))[3]
        if name is None:
            return None
    return name


def report(c: Character) -> list:
    lines = [f"{c.name}: {', '.join(sorted(c.anims)) or 'sin animaciones'}", ""]
    for name, (req, why, n, fb, _) in WANTED.items():
        if name not in c.anims:
            use = f" (mientras tanto: '{fb}')" if fb else ""
            lines.append(f"{'FALTA' if req else 'opcional'}: {name} — {why}. ~{n} cuadros{use}")
    if LOOK not in c.anims:
        lines.append("opcional: look — 16 cuadros (22.5° c/u), 2 filas de 8: sigue el cursor con la mirada")
    lines += ["", f"Formato: celdas de {c.cell[0]}x{c.cell[1]} px, una animación por fila, fondo transparente o #FF00FF."]
    return lines


def reference(c: Character) -> Path | None:
    """Exporta el primer cuadro de 'idle' como referencia de identidad para el generador de imágenes."""
    a = c.anims.get("idle") or next(iter(c.anims.values()), None)
    if not a:
        f = c.dir / "reference.png"
        return c.source or (f if f.exists() else None)
    out = c.dir / "reference.png"
    Image.open(a["sheet"]).convert("RGBA").crop((0, a["row"] * c.cell[1], c.cell[0], (a["row"] + 1) * c.cell[1])).save(out)
    return out


def set_source(cid: str, path: str):
    """Carga la imagen general del personaje (cualquier formato de imagen; se guarda como PNG)."""
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"No pude leer la imagen: {e}")
    if max(im.size) > MAX_PX:
        raise SystemExit(f"La imagen es demasiado grande ({im.width}x{im.height}).")
    im.convert("RGBA").save(writable_dir(cid) / "source.png")


def set_neutral(cid: str, path: str) -> list:
    """Guarda la hoja neutral a partir de una imagen con las 4 vistas (en cualquier distribución): se detectan, se limpian y se ordenan
    como frontal, trasera, lateral izquierda y lateral derecha. Se conserva a mayor resolución que las animaciones, porque es referencia."""
    from . import importer
    c = get(cid)
    big = (c.cell[0] * 3, c.cell[1] * 3)
    frames = [f for r in importer.analyze(path, big) for f in r]
    if len(frames) != 4:
        raise SystemExit(f"Esperaba 4 vistas y detecté {len(frames)}. Ajusta la imagen: una vista por celda, bien separadas.")
    sheet = Image.new("RGBA", (big[0] * 4, big[1]), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        sheet.alpha_composite(f, (i * big[0], 0))
    sheet.save(writable_dir(cid) / "neutral.png")
    return ["  Hoja neutral guardada: 4 vistas (frontal, trasera, lateral izquierda, lateral derecha)."]


def clear_ref(cid: str, which: str):
    """Quita la imagen general ('source') o la hoja neutral ('neutral')."""
    f = writable_dir(cid) / f"{which}.png"
    if f.exists():
        f.unlink()


def neutral_prompt(c: Character, background: str = "#FF00FF", extra: str = "") -> str:
    """Prompt para la hoja neutral: las 4 vistas del personaje respetando todos sus detalles (base de consistencia de las animaciones)."""
    return TEMPLATE.format(
        animacion=("hoja de referencia NEUTRAL del personaje: la misma figura en 4 vistas, de pie, relajada y en pose neutra, sin acción ni expresión "
                   "exagerada. Orden de izquierda a derecha: 1) vista frontal, 2) vista trasera, 3) vista lateral izquierda, 4) vista lateral derecha. "
                   "Las 4 vistas con la misma escala, la misma altura y la misma línea del piso."),
        cuadros=4, distribucion="4 columnas × 1 fila", tamano=f"{c.cell[0]} × {c.cell[1]} px", fondo=background, ciclo="no aplica (no es una animación)",
        direccion="una vista por celda, exactamente las 4 pedidas", estilo="",
        detalles=((extra + " ") if extra else "") + (f"Anatomía de este personaje: {c.anatomy} " if c.anatomy else "") + ("Respeta TODOS los detalles de la imagen de referencia en cada vista: colores, formas, accesorios, marcas, texturas, ropa y proporciones; "
                  "en la vista trasera y las laterales deduce con coherencia lo que no se ve. " + f"Identidad del personaje: {c.brief}")).strip()


TEMPLATE = """# ===== VARIABLES EDITABLES =====
# Deja una variable vacía para usar su valor por defecto.

ANIMACION = "{animacion}"
# Por defecto: animación idle, con respiración suave y un parpadeo.

NUMERO_DE_CUADROS = "{cuadros}"
# Por defecto: 8.

DISTRIBUCION = "{distribucion}"
# Por defecto: 4 columnas × 2 filas.

TAMANO_DE_CADA_CUADRO = "{tamano}"
# Por defecto: 192 × 208 px.

FONDO = "{fondo}"
# Por defecto: transparente.

TIPO_DE_CICLO = "{ciclo}"
# Por defecto: loop fluido, con el último cuadro conectando con el primero.

DIRECCION = "{direccion}"
# Por defecto: conservar la orientación de la imagen de referencia.

ESTILO = "{estilo}"
# Por defecto: conservar el estilo de la imagen de referencia.

DETALLES_ADICIONALES = "{detalles}"
# Por defecto: ninguno.

# ===== INSTRUCCIONES =====

Genera un spritesheet a partir de la imagen adjunta y de las variables anteriores.

Primero, revisa las variables. Si alguna está vacía, usa exactamente el valor por defecto indicado en el comentario. No me preguntes por las variables vacías. Si la imagen no está adjunta o la descripción de la animación resulta incompatible con ella, indícalo antes de generar.

Usa la imagen adjunta como referencia de identidad y diseño. Conserva el mismo personaje u objeto en todos los cuadros: silueta, proporciones, colores, cara, ropa, accesorios, marcas, materiales, perspectiva e iluminación. Mantén el estilo visual indicado. No añadas personajes, objetos ni detalles que no aparezcan en la referencia, salvo que se soliciten en los detalles adicionales.

Crea una sola imagen con el spritesheet completo. Organiza los cuadros en la distribución especificada, en orden de izquierda a derecha y de arriba abajo. Cada cuadro debe mostrar una pose completa dentro de su propia celda. Mantén la escala y el punto de apoyo del personaje u objeto consistentes; permite que cambien solo cuando la acción lo requiera, por ejemplo durante un salto.

Haz que cada cuadro avance la animación de forma clara y natural. Evita poses duplicadas, cambios bruscos, deformaciones, variaciones de estilo, recortes, cuadros vacíos y elementos que invadan celdas vecinas. Si la animación es un loop, haz que la transición entre el último y el primer cuadro se vea fluida.

Usa el fondo indicado. Si es transparente, entrega transparencia real. Si es de color sólido, mantén exactamente el mismo color en todas las celdas y evita que ese color aparezca en el personaje u objeto.

No incluyas texto, números, títulos, etiquetas, guías, bordes de celda, marcas de agua, sombras sueltas ni decoración fuera de la animación.

Antes de entregar, comprueba que el spritesheet tenga el número de cuadros solicitado, respete la distribución, conserve la identidad visual de la referencia y represente la animación indicada. Entrega únicamente la imagen final.
"""


NEUTRAL_NOTE = ("La imagen adjunta principal es la HOJA NEUTRAL del personaje con 4 vistas (frontal, trasera, lateral izquierda y lateral derecha): "
                "respeta todos sus detalles y úsala para dibujar cada pose desde el ángulo que corresponda.")


MARK = "# ===== INSTRUCCIONES ====="
TEMPLATE_VARS, TEMPLATE_INSTR = TEMPLATE.split(MARK)[0], MARK + TEMPLATE.split(MARK)[1]


def layout_cols(n: int) -> int:
    """Columnas de la distribución sin celdas vacías: una fila hasta 7 cuadros; si no, el divisor más cercano a 4 (8 → 4×2, 12 → 4×3)."""
    if n <= 7:
        return n
    divs = [d for d in (4, 5, 3, 6, 2) if n % d == 0]
    return divs[0] if divs else n


ANATOMY_NOTE = ("Adapta el movimiento a la anatomía única de este personaje: usa solo las partes del cuerpo que realmente tiene (no le inventes piernas, "
                "brazos, alas, manos ni nada que no aparezca en la referencia) y reinterpreta la acción con sus propias partes y su manera natural de moverse.")


def _vars(c: Character, anim: str, frames=None, action=None, background="", distribution="", direction="", cycle="", extra="", note=True) -> dict:
    w = WANTED.get(anim)
    n = frames or (w[2] if w else 8)
    cols = layout_cols(n)
    rows_ = -(-n // cols)
    dist = distribution or f"{cols} columna{'s' if cols > 1 else ''} × {rows_} fila{'s' if rows_ > 1 else ''}"
    act = action or c.actions.get(anim) or (w[4] if w else "")
    dir_ = direction or {"running-right": "mirando y avanzando hacia la derecha", "running-left": "mirando y avanzando hacia la izquierda"}.get(anim, "")
    return dict(animacion=f"{anim}" + (f" ({w[1]})" if w else "") + (f": {act}" if act else ""), cuadros=n, distribucion=dist,
                tamano=f"{c.cell[0]} × {c.cell[1]} px", fondo=background, ciclo=cycle or ("una sola vez, sin repetir" if anim == "jumping" else ""),
                direccion=dir_, estilo="",
                detalles=((extra + " ") if extra else "") + (NEUTRAL_NOTE + " " if (note and c.neutral) else "") + ANATOMY_NOTE + " "
                + (f"Anatomía de este personaje: {c.anatomy} " if c.anatomy else "") + f"Identidad del personaje: {c.brief}")


def prompt(c: Character, anim: str, frames: int | None = None, action: str | None = None, background: str = "",
           distribution: str = "", direction: str = "", cycle: str = "", extra: str = "") -> str:
    """Prompt para generar una animación (plantilla del usuario). Imagen adjunta: `reference(c)`. Luego: `./run.sh add hoja.png`."""
    return TEMPLATE.format(**_vars(c, anim, frames, action, background, distribution, direction, cycle, extra)).strip()


def general_prompt(c: Character, anims: list, background: str = "#FF00FF") -> str:
    """UN prompt para pedir varias animaciones, cada una como imagen separada, respetando las variables individuales de cada una."""
    n = len(anims)
    head = (f"# PROMPT GENERAL: {n} ANIMACIONES, CADA UNA POR SEPARADO\n\n"
            f"Genera {n} spritesheets INDEPENDIENTES, uno por cada animación de la lista, en el mismo orden. Reglas:\n"
            "- Cada animación va en su PROPIA imagen: no combines varias animaciones en una sola imagen ni compartas filas o celdas entre ellas.\n"
            "- Cada animación tiene sus propias variables (bloque «ANIMACIÓN k de N»). Respeta EXACTAMENTE los detalles individuales de cada bloque: "
            "número de cuadros, distribución, tamaño de cada cuadro, fondo, tipo de ciclo, dirección, movimiento y detalles adicionales. "
            "Lo indicado en un bloque NO aplica a los demás.\n"
            "- Mantén exactamente la misma identidad del personaje en todas las imágenes (misma referencia adjunta).\n"
            f"- Entrega las {n} imágenes una por una, en el orden de la lista. Indica en tu respuesta (nunca dentro de las imágenes) a qué animación "
            "corresponde cada una.\n"
            + (f"- {NEUTRAL_NOTE}\n" if c.neutral else "") +
            "- Las instrucciones comunes al final aplican a CADA imagen por separado.\n\n")
    blocks = []
    for k, a in enumerate(anims, 1):
        name = a if isinstance(a, str) else a["name"]
        opts = {} if isinstance(a, str) else {key: v for key, v in a.items() if key != "name"}
        blocks.append(f"## ANIMACIÓN {k} de {n}: {name}\n\n" + TEMPLATE_VARS.format(**_vars(c, name, background=background, note=False, **opts)).strip())
    return (head + "\n\n---\n\n".join(blocks) + "\n\n---\n\n" + TEMPLATE_INSTR.replace("# ===== INSTRUCCIONES =====",
            "# ===== INSTRUCCIONES COMUNES (aplican a cada animación por separado) =====").strip())
