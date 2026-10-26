from django.http import Http404
from django.shortcuts import render

from pedidos.models import Pedido


MODULOS = [
    {
        "slug": "designacion-diaria",
        "titulo": "Designación diaria",
        "descripcion": (
            "Organiza las tareas, personas, operaciones "
            "y máquinas de cada jornada."
        ),
        "icono": "bi-calendar2-check",
    },
    {
        "slug": "eficiencia",
        "titulo": "Eficiencia",
        "descripcion": (
            "Consulta la captura de producción y "
            "los indicadores de desempeño."
        ),
        "icono": "bi-speedometer2",
    },
    {
        "slug": "estudio-de-tiempos",
        "titulo": "Estudio de tiempos",
        "descripcion": (
            "Organiza las mediciones y los tiempos "
            "estándar de las operaciones."
        ),
        "icono": "bi-stopwatch",
    },
    {
        "slug": "catalogos",
        "titulo": "Catálogos",
        "descripcion": (
            "Administra personas, máquinas y operaciones."
        ),
        "icono": "bi-sliders",
    },
    {
        "slug": "historico-reportes",
        "titulo": "Histórico y reportes",
        "descripcion": (
            "Consulta los registros y prepara reportes "
            "de producción."
        ),
        "icono": "bi-clock-history",
    },
]


def inicio(request):
    contexto = {
        "total_pedidos": Pedido.objects.count(),

        "pedidos_en_proceso": Pedido.objects.filter(
            estado=Pedido.Estado.EN_PROCESO
        ).count(),

        "pedidos_terminados": Pedido.objects.filter(
            estado=Pedido.Estado.TERMINADO
        ).count(),

        "modulos": MODULOS,
    }

    return render(request, "core/inicio.html", contexto)


def modulo_pendiente(request, slug):
    modulo = next(
        (item for item in MODULOS if item["slug"] == slug),
        None,
    )

    if modulo is None:
        raise Http404("El módulo solicitado no existe.")

    return render(
        request,
        "core/modulo_pendiente.html",
        {"modulo": modulo},
    )