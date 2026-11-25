"""Datos de rutas para el motor, conservando el formato JSON original."""

import json
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import FamiliaRuta, PasoRuta


@require_GET
def catalogo_rutas(request):
    """
    Entrega al motor las rutas administrables.

    Conserva madres, máquinas, operaciones y demás configuración
    del JSON original. Las familias y sus pasos se leen de SQLite.
    """

    archivo = (
        Path(settings.BASE_DIR)
        / "static/designaciones/data/datos_rutas_inaher.json"
    )

    try:
        datos = json.loads(
            archivo.read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError):
        return JsonResponse(
            {"error": "No se pudo leer el catálogo de rutas."},
            status=500,
        )

    # En una instalación nueva, antes de importar a SQLite,
    # se mantiene disponible el JSON original.
    #
    # Si ya existen rutas administrables, la base de datos
    # tiene prioridad. Desactivar todas las familias no debe
    # reactivar accidentalmente el catálogo estático.

    if FamiliaRuta.objects.exists() or PasoRuta.objects.exists():

        familias = FamiliaRuta.objects.filter(
            activa=True
        ).order_by(
            "orden",
            "nombre",
        )

        pasos = PasoRuta.objects.filter(
            activo=True,
            familia__activa=True,
        ).select_related(
            "familia",
            "madre",
        ).order_by(
            "familia__orden",
            "familia__nombre",
            "orden",
            "pk",
        )

        datos["familias"] = [
            {
                "familia": familia.nombre,
                "modelos": familia.modelos,
                "descripcion": familia.descripcion,
            }
            for familia in familias
        ]

        datos["rutas"] = [
            {
                "familia": paso.familia.nombre,
                "madre": paso.madre.nombre,
                "detallada": paso.detallada,
                "condicion": paso.condicion,
                "nota": paso.nota,
            }
            for paso in pasos
        ]

    respuesta = JsonResponse(
        datos,
        json_dumps_params={"ensure_ascii": False},
    )

    # Las modificaciones del administrador deben aparecer
    # sin depender de una versión anterior almacenada en caché.
    respuesta["Cache-Control"] = "no-store, max-age=0"

    return respuesta
