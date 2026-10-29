import argparse
import os
import sys


def main():
    p = argparse.ArgumentParser(prog="fruquis", description="Mascota de escritorio estilo shimeji.")
    sub = p.add_subparsers(dest="cmd")
    run = sub.add_parser("run", help="iniciar la mascota (por defecto)")
    run.add_argument("--scale", type=float, default=0.6)
    sub.add_parser("list", help="listar personajes")
    ex = sub.add_parser("export", help="exportar un personaje a un zip")
    ex.add_argument("character", nargs="?", default=None)
    ex.add_argument("--out", default=".", help="archivo .zip o carpeta de destino")
    im = sub.add_parser("import", help="importar un personaje desde un zip")
    im.add_argument("zip")
    im.add_argument("--overwrite", action="store_true", help="reemplaza al personaje del usuario con el mismo id")
    for n, h in (("check", "ver qué animaciones faltan"), ("prompt", "prompt para generar una animación")):
        s = sub.add_parser(n, help=h)
        s.add_argument("--character", default=None)
        if n == "prompt":
            s.add_argument("anim")
            s.add_argument("--frames", type=int)
            s.add_argument("--action")
            s.add_argument("--background", default="", help='por ejemplo "#FF00FF"; vacío = transparente')
            s.add_argument("--distribution", default="")
    add = sub.add_parser("add", help="agregar una hoja de sprites (una animación por fila)")
    add.add_argument("sheet")
    add.add_argument("--names", default=None, help="nombre por fila, separados por coma; si no lo das, la IA decide")
    add.add_argument("--character", default=None)
    add.add_argument("--fps", type=int)
    add.add_argument("--no-ai", action="store_true", help="sin IA: una animación por fila")
    add.add_argument("--model", default="haiku")
    a = p.parse_args()
    from . import sprites, store
    cid = getattr(a, "character", None) or store.get("active", "")
    if a.cmd == "list":
        for c in sprites.list_all().values():
            print(f"{c.id}\t{c.name}\t{len(c.anims)} animaciones")
        if not sprites.list_all():
            print("Sin personajes. Importa uno: ./run.sh import personaje.zip")
    elif a.cmd == "export":
        print(f"Exportado: {sprites.export_character(sprites.get(cid).id, a.out)}")
    elif a.cmd == "import":
        c = sprites.import_character(a.zip, a.overwrite)
        print(f"Importado: {c.id} ({c.name}, {len(c.anims)} animaciones)")
    elif a.cmd == "check":
        print("\n".join(sprites.report(sprites.get(cid))))
    elif a.cmd == "prompt":
        print(sprites.prompt(sprites.get(cid), a.anim, a.frames, a.action, a.background, a.distribution))
    elif a.cmd == "add":
        log = sprites.add_sheet(cid, a.sheet, a.names.split(",") if a.names else None, a.fps, not a.no_ai, a.model)
        print("\n".join(["Agregado:"] + log + [""] + sprites.report(sprites.get(cid))))
    else:
        if sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland":
            os.environ.setdefault("QT_QPA_PLATFORM", "xcb")  # posicionar ventanas libremente
        from . import app
        app.run(getattr(a, "scale", 0.6))


if __name__ == "__main__":
    main()
