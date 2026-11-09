import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings

RUTAS_JSON = Path(settings.BASE_DIR) / "static/designaciones/data/datos_rutas_inaher.json"


@lru_cache(maxsize=1)
def modelos_catalogo():
    """
    Modelos de producto (MT-1, MT-2, REBO 400…) tomados de las familias del motor de rutas.
    Se omiten los prefijos terminados en "-" (ETH-), que el motor usa solo para reconocer.
    """
    try:
        datos = json.loads(RUTAS_JSON.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return ()

    modelos = {
        modelo.strip()
        for familia in datos.get("familias", [])
        for modelo in familia.get("modelos", "").split(",")
        if modelo.strip() and not modelo.strip().endswith("-")
    }
    return tuple(sorted(modelos))
