"""Ubicación aproximada del usuario (por IP, sin permisos) para que la IA sepa dónde está (clima, hora, cosas cercanas).
Paridad con Place en android/.../Ai.kt (mismo servicio y mismo texto)."""
import json
import urllib.request

_text = ""  # solo se guarda si se obtuvo; si falla, se reintenta en el siguiente mensaje


def hint() -> str:
    """Frase para añadir al prompt de sistema; vacía si no se pudo averiguar la ubicación."""
    global _text
    if not _text:
        try:
            with urllib.request.urlopen("https://ipwho.is/", timeout=4) as r:
                d = json.load(r)
            if d.get("success"):
                _text = (f" El usuario está (ubicación aproximada por IP) en {d['city']}, {d['region']}, {d['country']}, "
                         f"zona horaria {d.get('timezone', {}).get('id', '?')}. Úsalo para el clima, la hora y lo cercano sin preguntarle la ciudad, "
                         "salvo que él mencione otro lugar.")
        except Exception:  # noqa: BLE001 - sin red o servicio caído: se responde sin ubicación
            pass
    return _text
