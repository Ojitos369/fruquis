"""Iconos de línea (24×24, estilo Lucide) dibujados desde SVG con el color del tema: una sola fuente para todos los botones de la interfaz."""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "play": '<path d="M7 4.5 19 12 7 19.5Z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "checks": '<path d="M17 6 8 17l-5-5M22 6l-9 11"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6"/>',
    "edit": '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "download": '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    "upload": '<path d="M12 15V3M7 8l5-5 5 5M5 21h14"/>',
    "sparkles": '<path d="M11 3l1.9 5.1L18 10l-5.1 1.9L11 17l-1.9-5.1L4 10l5.1-1.9Z"/><path d="M19 15v6M16 18h6"/>',
    "layers": '<path d="M12 3 2 8l10 5 10-5Z"/><path d="M2 13l10 5 10-5"/>',
    "wand": '<path d="M4 20 15 9M15 3l1 2.5L18.5 6.5 16 7.5 15 10l-1-2.5L11.5 6.5 14 5.5Z"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8ZM14 3v5h5M9 13h6M9 17h6"/>',
    "back": '<path d="M19 12H5M12 5l-7 7 7 7"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/>',
    "chat": '<path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-5.4A8 8 0 1 1 21 12Z"/>',
    "heart": '<path d="M12 20s-8-4.9-8-11a4.5 4.5 0 0 1 8-2.7A4.5 4.5 0 0 1 20 9c0 6.1-8 11-8 11Z"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "activity": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.5"/><path d="M21 16l-5-5-9 9"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "book": '<path d="M4 4h6a3 3 0 0 1 2 1 3 3 0 0 1 2-1h6v15h-6a3 3 0 0 0-2 1 3 3 0 0 0-2-1H4ZM12 5v15"/>',
    "clip": '<path d="m21 11-9 9a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8"/>',
    "send": '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4Z"/>',
    "save": '<path d="M5 3h11l3 3v15H5ZM8 3v6h7V3M8 21v-7h8v7"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "folder": '<path d="M3 6a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "reset": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    "broom": '<path d="M19 3 11 11M9 13l-5 7 7-5M9 13l2 2"/>',
    "external": '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 21h8M12 16v5"/>',
}

IDLE, ON, OFF = "#a4a4b8", "#ffffff", "#55556a"  # reposo, activo (marcado / botón principal) y desactivado


@lru_cache(maxsize=None)
def pixmap(name: str, color: str, size: int) -> QPixmap:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" '
           f'stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>')
    px = QPixmap(QSize(size, size) * 2)  # el doble de resolución: nítido en pantallas HiDPI
    px.fill(Qt.transparent)
    p = QPainter(px)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    px.setDevicePixelRatio(2)
    return px


@lru_cache(maxsize=None)
def icon(name: str, color: str = IDLE, on: str = ON, size: int = 20) -> QIcon:
    """`color` en reposo, `on` cuando el botón está marcado; gris cuando está desactivado."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, on, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(pixmap(name, OFF, size), QIcon.Disabled, QIcon.Off)
    return ic
