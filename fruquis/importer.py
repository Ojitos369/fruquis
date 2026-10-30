"""Importa hojas de sprites de cualquier tamaño: detecta los cuadros por su contenido, los limpia y los normaliza a la celda
del personaje; la IA (claude, con visión) propone nombre, velocidad y modo de cada fila. Sin Qt."""
import json
import re
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from . import provider, store


def _alpha(im: Image.Image) -> Image.Image:
    """RGBA; si no hay transparencia, vuelve transparente el color plano de la esquina (magenta, blanco, negro...)."""
    im = im.convert("RGBA")
    a = np.asarray(im)
    if a[..., 3].min() < 250:
        return im
    corner = a[0, 0, :3].astype(int)
    rgb = a[..., :3].astype(int)
    near = (np.abs(rgb - corner).sum(-1) < 60)
    if corner.max() - corner.min() < 30 and corner.min() > 90:  # «cuadrícula de transparencia» dibujada por la IA: casillas blancas y grises alternas
        near |= (rgb.max(-1) - rgb.min(-1) < 30) & (rgb.min(-1) > 90)
    # solo el fondo conectado con el borde: un color parecido dentro del personaje (capucha oscura sobre fondo oscuro) se conserva
    lab, _ = ndimage.label(near)
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    near = np.isin(lab, edge[edge > 0])
    pink = (rgb[..., 0] > 190) & (rgb[..., 2] > 190) & (rgb[..., 1] < 120)
    # croma magenta: también el borde mezclado (rosa/violeta casi puro) pasa a transparente; aunque la esquina sea de otro color (márgenes blancos)
    if (corner[0] > 200 and corner[2] > 200 and corner[1] < 90) or pink.mean() > 0.1:
        near |= pink
    # shortcut: huecos de fondo cerrados (entre tentáculos) de un fondo no magenta quedan opacos; mejor que borrar el personaje
    a = a.copy()
    a[near, 3] = 0
    return Image.fromarray(a)


def _runs(flags: np.ndarray, gap: int) -> list:
    """Tramos [i0, i1) de True, uniendo los separados por menos de `gap`."""
    idx = np.flatnonzero(flags)
    if idx.size == 0:
        return []
    out, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > gap:
            out.append((int(start), int(prev) + 1))
            start = i
        prev = i
    return out + [(int(start), int(prev) + 1)]


def _split_run(band: np.ndarray, want: int = 0) -> list:
    """Parte un tramo ancho en cuadros cuando sus poses se tocan: busca el mayor número de cortes iguales cuyos valles de la silueta
    (las columnas con menos píxeles) son claramente más bajos que el resto. Con `want` (cuántas poses caben, por el ancho de sus vecinas)
    corta en ese número aunque el tramo no sea tan ancho. Devuelve [(x0, x1)] relativos al tramo."""
    h, w = band.shape
    if w < h * 1.45 and want < 2:
        return [(0, w)]
    prof = np.convolve(band.sum(0).astype(float), np.ones(max(3, h // 40)) / max(3, h // 40), mode="same")
    ref = np.median(prof[prof > 0]) or 1.0
    for n in ([want] if want > 1 else range(min(12, int(w / (h * 0.35))), 1, -1)):
        fw = w / n
        if not want and not 0.35 * h <= fw <= 2.0 * h:
            continue
        cuts = []
        for k in range(1, n):
            lo, hi = int(k * fw - fw * 0.18), int(k * fw + fw * 0.18)
            cuts.append(lo + int(np.argmin(prof[lo:hi])))
        if want or np.mean([prof[c] for c in cuts]) / ref < 0.35:
            edges = [0, *cuts, w]
            return [(a, b) for a, b in zip(edges, edges[1:])]
    return [(0, w)]


def ai_review(sheet: Image.Image, cands: list, model: str = "haiku"):
    """Pide a claude (viendo una hoja de contacto con cada pieza dudosa numerada) que decida, pieza por pieza, si es parte legítima del cuadro
    (gota, chispa, accesorio, punta de cola) o suciedad / un fragmento de otro cuadro. {id: True} = quitar. None si no hay respuesta útil."""
    if not provider.chat_ready():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "cuadros.png"
        sheet.convert("RGB").save(img)
        prompt = (
            f"Mira la imagen {img}: es una hoja de contacto con los cuadros de una animación de sprites sobre fondo gris. Dentro de cada cuadro hay "
            "recuadros de colores con un número alrededor de piezas pequeñas que quedaron sueltas o separadas del cuerpo principal. Para CADA número "
            "decide con cuidado, mirando la pieza y su entorno: \"keep\" si es parte legítima del personaje o de su efecto (gota, chispa, accesorio, "
            "cabello, punta de cola, partícula de diseño) o \"remove\" si es un fragmento recortado de OTRO cuadro (forma cortada en seco en el borde, "
            "pedazo de otra pose), suciedad, ruido o un resto que no pertenece a este cuadro. Responde SOLO un objeto JSON, sin texto extra, con todos los "
            'números: {"1": "remove", "2": "keep"}')
        out = provider.vision(prompt, [img], model, timeout=150)
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        d = json.loads(m.group()) if m else None
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    return {int(k): str(v).lower().startswith("rem") for k, v in d.items() if str(k).isdigit()}


def _compose(a, lab, owner, items, rid_pad=0):
    """Pega en un lienzo RGBA las piezas de un cuadro. Una pieza entera conserva todos sus píxeles (aunque cruce la frontera del cuadro);
    una compartida entre cuadros solo aporta los de su lado."""
    ys0, xs0 = min(it["sl"][0].start for it in items), min(it["sl"][1].start for it in items)
    ys1, xs1 = max(it["sl"][0].stop for it in items), max(it["sl"][1].stop for it in items)
    canvas = np.zeros((ys1 - ys0, xs1 - xs0, 4), np.uint8)
    for it in items:
        sl = it["sl"]
        sub = lab[sl] == it["L"]
        if it["cut"]:
            sub &= owner[sl] == it["cut"]
        dst = (slice(sl[0].start - ys0, sl[0].stop - ys0), slice(sl[1].start - xs0, sl[1].stop - xs0))
        canvas[dst][sub] = a[sl][sub]
    return canvas, (xs0, ys0)


def _build_crops(a, mask, lab, frames, review) -> list:
    """Un recorte por cuadro asignando cada pieza conectada de la imagen a UN solo cuadro (el que contiene la mayor parte de ella) en lugar de
    cortar con líneas rectas: así un pedazo de la cola de un cuadro no se cuela en el siguiente. Las piezas pequeñas dudosas se quitan con
    reglas simples o, si hay IA, tras revisarlas una por una."""
    H, W = mask.shape
    regs = [(r, box) for r, row in enumerate(frames) for box in row]
    owner = np.zeros((H, W), np.int32)
    for i, (_, (x0, y0, x1, y1)) in enumerate(regs, 1):
        owner[y0:y1, x0:x1] = i
    pieces = {i: [] for i in range(1, len(regs) + 1)}
    for L, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None:
            continue
        counts = np.bincount(owner[sl][lab[sl] == L], minlength=len(regs) + 1)
        counts[0] = 0
        tot = int(counts.sum())
        if not tot:  # fuera de todo cuadro: pasa al más cercano como pieza dudosa (se descarta si está lejos de su cuerpo)
            cx, cy = (sl[1].start + sl[1].stop) / 2, (sl[0].start + sl[0].stop) / 2
            near = min(range(1, len(regs) + 1), key=lambda i: ((regs[i - 1][1][0] + regs[i - 1][1][2]) / 2 - cx) ** 2 + ((regs[i - 1][1][1] + regs[i - 1][1][3]) / 2 - cy) ** 2)
            pieces[near].append({"sl": sl, "L": L, "cut": 0, "area": int((lab[sl] == L).sum())})
            continue
        best = int(counts.argmax())
        if counts[best] >= 0.7 * tot:  # pieza entera de un solo cuadro
            pieces[best].append({"sl": sl, "L": L, "cut": 0, "area": tot})
        else:  # poses que se tocan: cada cuadro se queda con su lado
            for rid in range(1, len(regs) + 1):
                if counts[rid] > 0.05 * tot:
                    pieces[rid].append({"sl": sl, "L": L, "cut": rid, "area": int(counts[rid])})
    cands = []
    for rid, items in pieces.items():
        if not items:
            continue
        main = max(items, key=lambda it: it["area"])
        (my0, my1), (mx0, mx1) = (main["sl"][0].start, main["sl"][0].stop), (main["sl"][1].start, main["sl"][1].stop)
        mw, mh = mx1 - mx0, my1 - my0
        for it in items:
            if it is main or it["area"] >= 0.5 * main["area"]:
                continue
            gx = max(0, mx0 - it["sl"][1].stop, it["sl"][1].start - mx1)  # separación entre la pieza y el cuerpo principal
            gy = max(0, my0 - it["sl"][0].stop, it["sl"][0].start - my1)
            far = (gx * gx + gy * gy) ** 0.5 > 0.12 * max(mw, mh)
            it["guess"] = bool(far or it["cut"])  # lejos del cuerpo o recortada por una frontera: sospechosa de ser de otro cuadro
            it["rid"] = rid
            cands.append(it)
    if cands and review:
        decided = review_pieces(a, lab, owner, pieces, cands, review)
        if decided is not None:
            for k, it in enumerate(cands, 1):
                it["guess"] = decided.get(k, it["guess"])
    drop = {id(it) for it in cands if it["guess"]}
    crops = [[] for _ in frames]
    for rid, (r, _) in enumerate(regs, 1):
        items = [it for it in pieces[rid] if id(it) not in drop]
        if items:
            canvas, _ = _compose(a, lab, owner, items)
            crops[r].append(Image.fromarray(canvas))
    return crops


def review_pieces(a, lab, owner, pieces, cands, review):
    """Hoja de contacto de los cuadros con piezas dudosas (recuadros numerados) para que la IA decida pieza por pieza."""
    from PIL import ImageDraw
    palette = [(255, 80, 80), (80, 200, 255), (255, 210, 60), (120, 255, 120), (255, 120, 255), (255, 150, 60)]
    by_frame = {}
    for k, it in enumerate(cands, 1):
        by_frame.setdefault(it["rid"], []).append((k, it))
    tiles = []
    for rid, lst in by_frame.items():
        canvas, (ox, oy) = _compose(a, lab, owner, pieces[rid])
        tile = Image.new("RGBA", (canvas.shape[1], canvas.shape[0]), (110, 110, 118, 255))
        tile.alpha_composite(Image.fromarray(canvas))
        dr = ImageDraw.Draw(tile)
        for k, it in lst:
            sl = it["sl"]
            box = (sl[1].start - ox, sl[0].start - oy, sl[1].stop - ox, sl[0].stop - oy)
            col = palette[k % len(palette)]
            dr.rectangle((box[0] - 3, box[1] - 3, box[2] + 3, box[3] + 3), outline=col, width=3)
            dr.text((box[0] - 3, max(0, box[1] - 18)), str(k), fill=col)
        sc = min(1.0, 320 / tile.height)
        tiles.append(tile.resize((max(1, int(tile.width * sc)), max(1, int(tile.height * sc))), Image.LANCZOS))
    cols = min(3, len(tiles))
    rows_ = -(-len(tiles) // cols)
    cw, ch = max(t.width for t in tiles), max(t.height for t in tiles)
    sheet = Image.new("RGBA", (cols * (cw + 8) + 8, rows_ * (ch + 8) + 8), (60, 60, 66, 255))
    for i, t in enumerate(tiles):
        sheet.alpha_composite(t, (8 + (i % cols) * (cw + 8), 8 + (i // cols) * (ch + 8)))
    return review(sheet, cands)


def analyze(path: str, cell: tuple, pad: int = 6, ai: bool | None = None) -> list:
    """Filas de cuadros (imágenes del tamaño de la celda), sin importar el tamaño de la hoja ni dónde estén los cuadros. Cada pieza de la
    imagen se asigna a un solo cuadro; las piezas dudosas las revisa la IA (`ai`, por defecto el ajuste «Revisar cuadros con IA»)."""
    if ai is None:
        ai = bool(store.get("ai_clean", True))
    im = _alpha(Image.open(path))
    a = np.asarray(im)
    mask = a[..., 3] > 24
    d = max(3, min(im.size) // 120)
    lab, n = ndimage.label(ndimage.binary_dilation(mask, iterations=d))
    if n == 0:
        raise SystemExit("La imagen no tiene nada visible (todo transparente).")
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    keep = np.isin(lab, [i + 1 for i, s in enumerate(sizes) if s >= sizes.max() * 0.003])  # fuera motas diminutas; las pequeñas dudosas se evalúan pieza por pieza
    mask &= keep
    a = a.copy()
    a[~mask, 3] = 0
    lab = np.where(mask, lab, 0)
    gap = max(2, d)  # con d*2 dos poses a ~17 px (orejas anchas) se fundían en una sola
    dens = lambda m, ax: m.sum(ax) > 0.012 * m.sum(ax).max()  # ignora los hilos de motas entre filas
    rows = _runs(dens(mask, 1), 2)
    frames = []
    for y0, y1 in rows:
        runs = _runs(dens(mask[y0:y1], 0), gap)
        ws = [x1 - x0 for x0, x1 in runs]
        mw = float(min(w for w in ws if w >= 0.5 * np.median(ws))) if len(ws) >= 2 else 0  # ancho de una pose suelta (la más angosta que no es un resto)
        # un tramo ~2× más ancho que el más angosto de su fila son varias poses pegadas: se parte en ese número
        cols = [(x0 + a_, x0 + b_) for x0, x1 in runs
                for a_, b_ in _split_run(mask[y0:y1, x0:x1], round((x1 - x0) / mw) if mw and (x1 - x0) > 1.8 * mw else 0)]  # poses de frente/perfil difieren ~1.5×: solo es «pegada» si mide casi el doble
        frames.append([(x0, y0, x1, y1) for x0, x1 in cols])
    # fila con menos cuadros que el resto y mucho más ancha que uno: se parte en partes iguales
    most = max(len(r) for r in frames)
    w1 = np.median([b[2] - b[0] for r in frames for b in r])
    for k, r in enumerate(frames):
        if len(r) < most and (r[-1][2] - r[0][0]) > w1 * 1.6 * len(r) and len(r) == 1:
            x0, x1, y0, y1 = r[0][0], r[0][2], r[0][1], r[0][3]
            step = (x1 - x0) / most
            frames[k] = [(round(x0 + i * step), y0, round(x0 + (i + 1) * step), y1) for i in range(most)]
    # una «región» muy pequeña (un fragmento suelto entre cuadros) no es un cuadro: se descarta y sus píxeles pasan a ser piezas dudosas
    areas = [int(mask[y0:y1, x0:x1].sum()) for r in frames for x0, y0, x1, y1 in r]
    med = float(np.median(areas))
    frames = [[b for b in r if mask[b[1]:b[3], b[0]:b[2]].sum() >= 0.1 * med] for r in frames]
    frames = [r for r in frames if r]
    crops = _build_crops(a, mask, lab, frames, ai_review if ai else None)
    crops = [[c for c in r if c.getchannel("A").getbbox()] for r in crops]
    crops = [r for r in crops if r]
    crops = [[c.crop(c.getchannel("A").getbbox()) for c in r] for r in crops]
    big_w, big_h = max(c.width for r in crops for c in r), max(c.height for r in crops for c in r)
    s = min((cell[0] - 2 * pad) / big_w, (cell[1] - 2 * pad) / big_h)  # una sola escala para toda la hoja: conserva proporciones
    out = []
    for r in crops:
        row = []
        for c in r:
            c = c.resize((max(1, round(c.width * s)), max(1, round(c.height * s))), Image.LANCZOS)
            al = np.asarray(c.getchannel("A")).astype(float)
            cx = (al.sum(0) * np.arange(c.width)).sum() / max(al.sum(), 1)  # centro de masa: el cuerpo no baila al animarse
            x = int(round(cell[0] / 2 - cx))
            x = max(0, min(x, cell[0] - c.width))
            frame = Image.new("RGBA", cell, (0, 0, 0, 0))
            frame.alpha_composite(c, (x, cell[1] - pad - c.height))  # pies sobre la misma línea base
            row.append(frame)
        out.append(row)
    return out


def describe(path: str, rows: list, known: dict, model: str = "haiku") -> list | None:
    """Pide a claude (viendo la imagen) un {name, fps, mode, note} por fila. None si no hay CLI o no responde algo útil."""
    with tempfile.TemporaryDirectory() as tmp:
        prev = Path(tmp) / "sheet.png"
        im = Image.open(path).convert("RGBA")
        im.thumbnail((1400, 1400))
        bg = Image.new("RGBA", im.size, (128, 128, 128, 255))
        bg.alpha_composite(im)
        bg.convert("RGB").save(prev)
        listing = "\n".join(f"- {k}: {v}" for k, v in known.items())
        prompt = (
            f"Mira la imagen {prev}: es una hoja de sprites de una mascota de escritorio. Detecté {len(rows)} fila(s) con "
            f"{[len(r) for r in rows]} cuadros cada una. Dime qué animaciones hay. Una animación puede ocupar varias filas seguidas (se lee de izquierda a derecha y de arriba abajo) "
            "o cada fila ser una animación distinta; decide mirando si los cuadros son continuación unos de otros.\n"
            f"Nombres conocidos (usa uno si encaja; si no, inventa un nombre corto en inglés, minúsculas y guiones):\n{listing}\n"
            "Elige también fps (4-12) y mode: 'loop' (vuelve al primer cuadro), 'pingpong' (los cuadros van y vienen, típico de "
            "respirar o mecerse) o 'once'. Responde SOLO un arreglo JSON, sin texto extra, con un objeto por fila: "
            '[{"name":"sleeping","fps":6,"mode":"pingpong","rows":[0,1],"note":"qué se ve"}]. "rows" son los índices de fila (desde 0) que forman esa animación.')
        out = provider.vision(prompt, [prev], model, timeout=150)
    m = re.search(r"\[.*\]", out or "", re.S)
    try:
        arr = json.loads(m.group()) if m else None
    except ValueError:
        return None
    if not isinstance(arr, list) or not arr:
        return None
    clean = []
    for o in arr:
        name = re.sub(r"[^a-z0-9-]", "", str(o.get("name", "")).lower().replace("_", "-").replace(" ", "-"))
        if not name:
            return None
        mode = o.get("mode") if o.get("mode") in ("loop", "pingpong", "once") else "loop"
        clean.append({"name": name, "fps": max(2, min(24, int(o.get("fps", 8) or 8))), "mode": mode, "note": str(o.get("note", ""))[:120],
                      "rows": [int(r) for r in o.get("rows", []) if str(r).isdigit() and int(r) < len(rows)] or [len(clean) % len(rows)]})
    return clean
