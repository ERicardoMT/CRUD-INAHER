from django.shortcuts import render
from django.utils import timezone

from archivo.excel import libro_excel
from eficiencia.views import leer_filtros, selects_filtros

from . import calculos


def _consulta(request):
    """Filtros de quien consulta: no cambian nada en Designación diaria."""
    elegidos, filtros = leer_filtros(request)
    mostrar = request.GET.get("mostrar", "todas")
    orden = request.GET.get("orden", "operacion")
    return (
        elegidos,
        filtros,
        mostrar if mostrar in calculos.MOSTRAR else "todas",
        orden if orden in calculos.ORDENES else "operacion",
    )


def lista(request):
    hoy = timezone.localdate()
    elegidos, filtros, mostrar, orden = _consulta(request)
    filas, totales = calculos.lista_del_dia(filtros, mostrar, orden)
    return render(request, "lista_trabajo/lista.html", {
        "hoy": hoy,
        "filas": filas,
        "tarjetas": calculos.tarjetas(totales),
        "selects": selects_filtros(elegidos),
        "mostrar": mostrar,
        "orden": orden,
        "opciones_mostrar": calculos.MOSTRAR,
        "opciones_orden": calculos.ORDENES,
    })


def imprimir(request):
    """Hoja horizontal con lo filtrado: fecha, filtros usados, totales y una hoja por máquina."""
    hoy = timezone.localdate()
    elegidos, filtros, mostrar, orden = _consulta(request)
    filas, totales = calculos.lista_del_dia(filtros, mostrar, orden)
    usados = [
        f"{s['etiqueta']}: {dict(s['opciones']).get(int(s['elegido']), '')}"
        for s in selects_filtros(elegidos) if s["elegido"].isdigit()
    ]
    return render(request, "lista_trabajo/imprimir.html", {
        "hoy": hoy,
        "maquinas": calculos.por_maquina(filas),
        "totales": totales,
        "filtros_usados": " · ".join(usados) or "sin filtros",
        "mostrar_nombre": calculos.MOSTRAR[mostrar],
        "orden_nombre": calculos.ORDENES[orden],
        "ahora": timezone.localtime(),
    })


def exportar(request):
    """Lista completa de hoy, sin los filtros de pantalla (misma regla que Eficiencia)."""
    hoy = timezone.localdate()
    filas, _ = calculos.lista_del_dia()
    return libro_excel("por_operacion", [calculos.hoja_excel(filas, hoy)])
