"""Cruce entre monitores: qué borde tiene otro monitor al lado. Uso: python tests/test_screens.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QRect  # noqa: E402

from fruquis.app import neighbor  # noqa: E402

LEFT, RIGHT = QRect(0, 0, 1920, 1080), QRect(1920, 0, 1920, 1080)


def test_vecinos_lado_a_lado():
    assert neighbor(LEFT, [LEFT, RIGHT], 1) == RIGHT
    assert neighbor(RIGHT, [LEFT, RIGHT], -1) == LEFT
    assert neighbor(LEFT, [LEFT, RIGHT], -1) is None  # borde exterior: pared


def test_monitor_apagado_es_pared():
    assert neighbor(LEFT, [LEFT], 1) is None


def test_panel_lateral_deja_hueco():
    assert neighbor(LEFT, [LEFT, QRect(1968, 0, 1872, 1080)], 1) is not None
    assert neighbor(LEFT, [LEFT, QRect(1920, 1080, 1920, 1080)], 1) is None  # está abajo, no al lado


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
