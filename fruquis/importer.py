"""Importa hojas de sprites de cualquier tamaño: detecta los cuadros por su contenido, los limpia y los normaliza a la celda
del personaje; la IA (claude, con visión) propone nombre, velocidad y modo de cada fila. Sin Qt."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from . import chat


def _alpha(im: Image.Image) -> Image.Image:
    """RGBA; si no hay transparencia, vuelve transparente el color plano de la esquina (magenta, blanco, negro...)."""
    im = im.convert("RGBA")
    a = np.asarray(im)
    if a[..., 3].min() < 250:
        return im
    corner = a[0, 0, :3].astype(int)
    near = (np.abs(a[..., :3].astype(int) - corner).sum(-1) < 60)
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


def _split_run(band: np.ndarray) -> list:
    """Parte un tramo ancho en cuadros cuando sus poses se tocan: busca el mayor número de cortes iguales cuyos valles de la silueta
    (las columnas con menos píxeles) son claramente más bajos que el resto. Devuelve [(x0, x1)] relativos al tramo."""
    h, w = band.shape
    if w < h * 1.45:
        return [(0, w)]
    prof = np.convolve(band.sum(0).astype(float), np.ones(max(3, h // 40)) / max(3, h // 40), mode="same")
    ref = np.median(prof[prof > 0]) or 1.0
    for n in range(min(12, int(w / (h * 0.35))), 1, -1):
        fw = w / n
        if not 0.35 * h <= fw <= 2.0 * h:
            continue
        cuts = []
        for k in range(1, n):
            lo, hi = int(k * fw - fw * 0.18), int(k * fw + fw * 0.18)
            cuts.append(lo + int(np.argmin(prof[lo:hi])))
        if np.mean([prof[c] for c in cuts]) / ref < 0.35:
            edges = [0, *cuts, w]
            return [(a, b) for a, b in zip(edges, edges[1:])]
    return [(0, w)]


def analyze(path: str, cell: tuple, pad: int = 6) -> list:
    """Filas de cuadros (imágenes del tamaño de la celda), sin importar el tamaño de la hoja ni dónde estén los cuadros."""
    im = _alpha(Image.open(path))
    a = np.asarray(im)
    mask = a[..., 3] > 24
    d = max(3, min(im.size) // 120)
    lab, n = ndimage.label(ndimage.binary_dilation(mask, iterations=d))
    if n == 0:
        raise SystemExit("La imagen no tiene nada visible (todo transparente).")
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    keep = np.isin(lab, [i + 1 for i, s in enumerate(sizes) if s >= sizes.max() * 0.02])  # fuera motas sueltas
    mask &= keep
    a = a.copy()
    a[~mask, 3] = 0
    gap = max(2, d * 2)
    dens = lambda m, ax: m.sum(ax) > 0.012 * m.sum(ax).max()  # ignora los hilos de motas entre filas
    rows = _runs(dens(mask, 1), 2)
    frames = []
    for y0, y1 in rows:
        cols = [(x0 + a, x0 + b) for x0, x1 in _runs(dens(mask[y0:y1], 0), gap) for a, b in _split_run(mask[y0:y1, x0:x1])]
        frames.append([(x0, y0, x1, y1) for x0, x1 in cols])
    # fila con menos cuadros que el resto y mucho más ancha que uno: se parte en partes iguales
    most = max(len(r) for r in frames)
    w1 = np.median([b[2] - b[0] for r in frames for b in r])
    for k, r in enumerate(frames):
        if len(r) < most and (r[-1][2] - r[0][0]) > w1 * 1.6 * len(r) and len(r) == 1:
            x0, x1, y0, y1 = r[0][0], r[0][2], r[0][1], r[0][3]
            step = (x1 - x0) / most
            frames[k] = [(round(x0 + i * step), y0, round(x0 + (i + 1) * step), y1) for i in range(most)]
    crops = [[Image.fromarray(a[y0:y1, x0:x1]) for x0, y0, x1, y1 in r] for r in frames]
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
        exe = chat.claude_bin()
        if not exe:
            return None
        try:
            r = subprocess.run([exe, "-p", "--model", model, "--effort", "medium", "--no-session-persistence", "--tools", "Read", "--allowedTools", "Read", "--add-dir", tmp],
                               input=prompt, capture_output=True, text=True, timeout=150, cwd=tmp,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return None
    m = re.search(r"\[.*\]", r.stdout, re.S)
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
