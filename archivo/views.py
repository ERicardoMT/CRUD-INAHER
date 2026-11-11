from datetime import date, timedelta

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, DateField, F, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods, require_POST

from designaciones.models import ItemDesignacion, Maquina, OperacionMadre, Operario
from pedidos.catalogo import modelos_catalogo
from pedidos.models import Cliente, MovimientoPedido, Pago, PartidaPedido, Pedido, normalizar
from pedidos.views import quien_hace

from .excel import respuesta_excel
from .forms import FacturaForm, PagoForm

POR_PAGINA = 50

SEGUIMIENTO = {
    "sin_facturar": "Sin facturar",
    "sin_pagar": "Sin pagar",
    "no_pidio": "No pidió factura",
    "completos": "Completos",
}

TARJETAS_NOMBRE = {
    "sin_facturar": "Sin facturar (todos los entregados)",
    "sin_pagar": "Sin pagar (todos los entregados)",
    "sin_terminar": "Archivados sin terminar",
}

AGRUPAR = {
    "persona": ("quien__nombre", "Persona"),
    "operacion": ("operacion_madre__nombre", "Operación madre"),
    "pedido": ("pedido__numero", "Pedido"),
    "dia": ("fecha_cierre", "Día"),
}


# ---------------------------------------------------------------- utilidades

def con_parametros(request, quitar=(), **poner):
    """Liga a esta misma página cambiando parámetros: búsqueda, filtros y página viajan en la dirección."""
    consulta = request.GET.copy()
    for clave in ("page", *quitar, *poner):
        consulta.pop(clave, None)
    for clave, valor in poner.items():
        if valor:
            consulta[clave] = valor
    return f"?{consulta.urlencode()}"


def _fecha(texto):
    try:
        return parse_date(texto or "")
    except ValueError:
        return None


def _texto_rango(desde, hasta):
    if not (desde or hasta):
        return "todas las fechas"
    return f"{desde:%d/%m/%Y}" if desde else "…" + " – " + (f"{hasta:%d/%m/%Y}" if hasta else "…")


def leer_rango(request, hoy):
    """Botones 90 días · mes · año · año anterior · todo, o Desde/Hasta a mano. Abre en 90 días."""
    clave = request.GET.get("rango")
    if clave is None and not (request.GET.get("desde") or request.GET.get("hasta")):
        clave = "90"
    rangos = {
        "90": (hoy - timedelta(days=90), hoy),
        "mes": (hoy.replace(day=1), hoy),
        "anio": (hoy.replace(month=1, day=1), hoy),
        "anterior": (date(hoy.year - 1, 1, 1), date(hoy.year - 1, 12, 31)),
        "todo": (None, None),
    }
    if clave in rangos:
        return (clave, *rangos[clave])
    return "", _fecha(request.GET.get("desde")), _fecha(request.GET.get("hasta"))


def botones_rango(request, hoy, activo):
    nombres = [("90", "90 días"), ("mes", "Este mes"), ("anio", "Este año"),
               ("anterior", str(hoy.year - 1)), ("todo", "Todo")]
    return [
        {"nombre": nombre, "activo": clave == activo,
         "url": con_parametros(request, quitar=("desde", "hasta", "tarjeta", "q"), rango=clave)}
        for clave, nombre in nombres
    ]


def _pagina(request, consulta):
    paginador = Paginator(consulta, POR_PAGINA)
    pagina = paginador.get_page(request.GET.get("page"))
    return pagina, paginador.get_elided_page_range(pagina.number, on_each_side=1, on_ends=1)


# ---------------------------------------------------------------- pedidos archivados

def tarjetas_archivo(request, hoy, activa):
    """Archivados depende de 90 días; las otras tres no dependen del rango."""
    archivados = Pedido.objects.filter(archivado=True)
    sin_facturar = Pedido.objects.sin_facturar()
    sin_pagar = Pedido.objects.sin_pagar()
    viejo_factura = sin_facturar.order_by("fecha_entrega").first()
    viejo_pago = sin_pagar.annotate(desde=Coalesce("factura_fecha", "fecha_entrega")).order_by("desde").first()

    lista = [
        {"clave": "", "titulo": "Archivados", "tono": "blue", "icono": "bi-archive",
         "valor": archivados.filter(archivado_en__date__gte=hoy - timedelta(days=90)).count(),
         "texto": f"últimos 90 días · {archivados.count()} en total"},
        {"clave": "sin_facturar", "titulo": "Sin facturar", "tono": "amber", "icono": "bi-receipt",
         "valor": sin_facturar.count(), "viejo": viejo_factura,
         "dias": viejo_factura.dias_sin_facturar if viejo_factura else None,
         "alcance": "Todos los entregados"},
        {"clave": "sin_pagar", "titulo": "Sin pagar", "tono": "red", "icono": "bi-cash-coin",
         "valor": sin_pagar.count(), "viejo": viejo_pago,
         "dias": viejo_pago.dias_sin_pagar if viejo_pago else None,
         "alcance": "Todos los entregados"},
        {"clave": "sin_terminar", "titulo": "Archivados sin terminar", "tono": "gray", "icono": "bi-x-octagon",
         "valor": archivados.filter(archivado_sin_terminar=True).count(),
         "texto": "cancelados / incompletos", "alcance": "Todo el archivo"},
    ]
    for t in lista:
        t["activo"] = t["clave"] == activa
        t["url"] = con_parametros(request, quitar=("rango", "desde", "hasta", "q", "seguimiento"), tarjeta=t["clave"])
    return lista


def filtrar_pedidos(request, hoy):
    """Lo que se ve en pantalla. Lo comparten la lista, la impresión y el Excel para que siempre coincidan."""
    f = {
        "q": request.GET.get("q", "").strip()[:60],
        "tarjeta": request.GET.get("tarjeta", ""),
        "cliente": request.GET.get("cliente", "").strip()[:150],
        "modelo": request.GET.get("modelo", ""),
        "seguimiento": request.GET.get("seguimiento", ""),
    }
    if f["tarjeta"] not in TARJETAS_NOMBRE:
        f["tarjeta"] = ""
    f["rango"], f["desde"], f["hasta"] = leer_rango(request, hoy)
    if f["q"] or f["tarjeta"]:
        f["rango"], f["desde"], f["hasta"] = "", None, None  # buscador y tarjetas no dependen del rango

    # Rango por fecha de entrega (de archivado si no se entregó)
    pedidos = Pedido.objects.annotate(
        fecha_ref=Coalesce("fecha_entrega", TruncDate("archivado_en"), output_field=DateField())
    )
    if f["q"]:
        pedidos = pedidos.buscar(f["q"])  # todo el sistema: archivo y activos
    elif f["tarjeta"] == "sin_facturar":
        pedidos = pedidos.sin_facturar()
    elif f["tarjeta"] == "sin_pagar":
        pedidos = pedidos.sin_pagar()
    elif f["tarjeta"] == "sin_terminar":
        pedidos = pedidos.filter(archivado=True, archivado_sin_terminar=True)
    else:
        pedidos = pedidos.filter(archivado=True)
        if f["desde"]:
            pedidos = pedidos.filter(fecha_ref__gte=f["desde"])
        if f["hasta"]:
            pedidos = pedidos.filter(fecha_ref__lte=f["hasta"])

    if f["cliente"]:
        pedidos = pedidos.filter(cliente__nombre__icontains=f["cliente"])
    if f["modelo"]:
        pedidos = pedidos.filter(pk__in=PartidaPedido.objects.filter(modelo=f["modelo"]).values("pedido"))
    if f["seguimiento"] == "sin_facturar":
        pedidos = pedidos.filter(pk__in=Pedido.objects.sin_facturar().values("pk"))
    elif f["seguimiento"] == "sin_pagar":
        pedidos = pedidos.filter(pk__in=Pedido.objects.sin_pagar().values("pk"))
    elif f["seguimiento"] == "no_pidio":
        pedidos = pedidos.filter(factura_estado=Pedido.Factura.NO_PIDIO)
    elif f["seguimiento"] == "completos":
        pedidos = pedidos.exclude(factura_estado=Pedido.Factura.PENDIENTE).filter(
            pk__in=Pago.objects.filter(tipo=Pago.Tipo.LIQUIDACION).values("pedido")
        )

    pedidos = (
        pedidos.select_related("cliente")
        .prefetch_related("partidas", "entregas", "pagos")
        .order_by(F("fecha_ref").desc(nulls_last=True), "-pk")
    )
    return pedidos, f


def describir_filtros(f):
    """Texto del filtro para la impresión y el Excel."""
    if f["q"]:
        partes = [f"búsqueda “{f['q']}” en todo el sistema"]
    elif f["tarjeta"]:
        partes = [TARJETAS_NOMBRE[f["tarjeta"]]]
    else:
        partes = [f"archivados · {_texto_rango(f['desde'], f['hasta'])}"]
    if f["cliente"]:
        partes.append(f"cliente: {f['cliente']}")
    if f["modelo"]:
        partes.append(f"modelo: {f['modelo']}")
    if f["seguimiento"] in SEGUIMIENTO:
        partes.append(f"seguimiento: {SEGUIMIENTO[f['seguimiento']]}")
    return " · ".join(partes)


def pedidos_archivados(request):
    hoy = timezone.localdate()
    pedidos, f = filtrar_pedidos(request, hoy)
    pagina, paginas = _pagina(request, pedidos)
    return render(request, "archivo/pedidos.html", {
        **f,
        "pagina": pagina,
        "paginas": paginas,
        "tarjetas": tarjetas_archivo(request, hoy, None if f["q"] else f["tarjeta"]),
        "rangos": botones_rango(request, hoy, f["rango"]),
        "seguimientos": SEGUIMIENTO,
        "modelos": modelos_catalogo(),
        "clientes": Cliente.objects.values_list("nombre", flat=True),
        "consulta": con_parametros(request),
    })


def imprimir_pedidos(request):
    pedidos, f = filtrar_pedidos(request, timezone.localdate())
    return render(request, "archivo/imprimir.html", {
        "pedidos": pedidos,
        "filtro": describir_filtros(f),
        "ahora": timezone.localtime(),
    })


def exportar_pedidos(request):
    """Todo lo filtrado (todas las páginas), un renglón por partida para sumar por modelo o cliente."""
    pedidos, f = filtrar_pedidos(request, timezone.localdate())
    filas = []
    for p in pedidos.iterator(chunk_size=500):
        inicio = [p.numero, p.cotizacion, p.oc_cliente, str(p.cliente or "")]
        final = [
            p.fecha_captura,
            p.fecha_entrega,
            timezone.localdate(p.archivado_en) if p.archivado_en else None,
            p.situacion_archivo,
            " · ".join(f"{e.paqueteria_nombre} {e.guia}".strip() for e in p.entregas.all()),
            p.factura_texto,
            p.factura_fecha,
            " · ".join(f"{x.get_tipo_display()} {x.fecha:%d/%m/%Y} ({x.get_forma_display()})" for x in p.pagos.all()),
            p.notas,
        ]
        for partida in p.partidas.all() or [None]:
            medio = [partida.modelo, partida.cantidad, partida.descripcion] if partida else ["", p.cantidad, p.descripcion]
            filas.append(inicio + medio + final)

    return respuesta_excel(
        nombre="archivo_pedidos",
        titulo="Archivo de pedidos",
        subtitulo=describir_filtros(f),
        encabezados=["# Pedido", "Cotización", "OC", "Cliente", "Modelo", "Cant", "Descripción",
                     "Captura", "Entregado", "Archivado", "Situación", "Guías", "Factura",
                     "Fecha factura", "Pagos", "Notas"],
        filas=filas,
        anchos=[11, 12, 12, 22, 12, 7, 38, 12, 12, 12, 24, 30, 16, 13, 40, 30],
        columnas_fecha=(7, 8, 9, 13),
    )


def buscar(request):
    """Buscador en vivo: contesta dónde está cada pedido (ARCHIVADO o ACTIVO EN PEDIDOS)."""
    q = request.GET.get("q", "").strip()[:60]
    pedidos = Pedido.objects.none()
    if len(normalizar(q)) >= 2:
        pedidos = (
            Pedido.objects.buscar(q).select_related("cliente")
            .prefetch_related("partidas", "entregas", "pagos")
            .order_by("-fecha_captura", "-pk")
        )
    return render(request, "archivo/_busqueda.html", {"pedidos": pedidos[:8], "total": pedidos.count(), "q": q})


# ---------------------------------------------------------------- seguimiento (ventanas)

@require_http_methods(["GET", "POST"])
def facturado(request, pk):
    """FACTURADO: con factura o no pidió factura. Al cambiar el folio, el anterior queda en bitácora."""
    pedido = get_object_or_404(Pedido, pk=pk)
    folio_anterior = pedido.factura_folio

    if request.method == "GET":
        return render(request, "archivo/ventana_facturado.html", {"pedido": pedido, "form": FacturaForm(instance=pedido)})

    if request.POST.get("accion") == "quitar":
        pedido.factura_estado = Pedido.Factura.PENDIENTE
        pedido.factura_fecha, pedido.factura_folio, pedido.factura_nota = None, "", ""
    else:
        form = FacturaForm(request.POST, instance=pedido)
        if not form.is_valid():
            return render(request, "archivo/ventana_facturado.html", {"pedido": pedido, "form": form}, status=400)
        pedido = form.save(commit=False)

    quien = quien_hace(request)
    with transaction.atomic():
        pedido.factura_por = quien
        pedido.save(update_fields=["factura_estado", "factura_fecha", "factura_folio",
                                   "factura_nota", "factura_por", "fecha_actualizacion"])
        pedido.actualizar_busqueda()
        if folio_anterior and folio_anterior != pedido.factura_folio:
            MovimientoPedido.objects.create(
                accion=MovimientoPedido.Accion.FOLIO_CAMBIADO,
                pedido_numero=pedido.numero,
                detalle=f"{folio_anterior} → {pedido.factura_folio or 'sin folio'}",
                usuario=quien or "Sin nombre",
            )
    return HttpResponse(status=204)


@require_http_methods(["GET", "POST"])
def pagado(request, pk):
    """PAGADO: varios pagos (anticipo · abono · liquidación). Queda parcial hasta la liquidación."""
    pedido = get_object_or_404(Pedido.objects.prefetch_related("pagos"), pk=pk)
    form = PagoForm(request.POST or None, pedido=pedido)
    if request.method == "POST" and form.is_valid():
        pago = form.save(commit=False)
        pago.pedido = pedido
        pago.registrado_por = quien_hace(request)
        pago.save()
        return HttpResponse(status=204)
    estado = 400 if request.method == "POST" else 200
    return render(request, "archivo/ventana_pagado.html", {"pedido": pedido, "form": form}, status=estado)


@require_POST
def quitar_pago(request, pk):
    get_object_or_404(Pago, pk=pk).delete()
    return HttpResponse(status=204)


# ---------------------------------------------------------------- tareas cerradas

def filtrar_tareas(request, hoy):
    """Tareas cerradas (Nuevo día o al archivar). Lo comparten la lista y el Excel."""
    f = {
        "q": request.GET.get("q", "").strip()[:60],
        "quien": request.GET.get("quien", ""),
        "madre": request.GET.get("madre", ""),
        "maquina": request.GET.get("maquina", ""),
        "modelo": request.GET.get("modelo", ""),
        "num_pedido": request.GET.get("pedido", "").strip()[:30],
        "agrupar": request.GET.get("agrupar", ""),
    }
    f["rango"], f["desde"], f["hasta"] = leer_rango(request, hoy)

    tareas = ItemDesignacion.objects.filter(fecha_cierre__isnull=False)
    if f["desde"]:
        tareas = tareas.filter(fecha_cierre__gte=f["desde"])
    if f["hasta"]:
        tareas = tareas.filter(fecha_cierre__lte=f["hasta"])
    if f["q"]:
        tareas = tareas.filter(
            Q(pedido__numero__icontains=f["q"]) | Q(quien__nombre__icontains=f["q"])
            | Q(operacion_madre__nombre__icontains=f["q"]) | Q(operacion_detallada__nombre__icontains=f["q"])
        )
    for campo, clave in (("quien_id", "quien"), ("operacion_madre_id", "madre"), ("maquina_id", "maquina")):
        if f[clave].isdigit():
            tareas = tareas.filter(**{campo: f[clave]})
    if f["modelo"]:
        tareas = tareas.filter(partida__modelo=f["modelo"])
    if f["num_pedido"]:
        tareas = tareas.filter(pedido__numero__icontains=f["num_pedido"])

    tareas = tareas.select_related(
        "quien", "pedido", "partida", "operacion_madre", "operacion_detallada", "maquina"
    ).order_by("-fecha_cierre", "quien__nombre", "paso", "pk")
    return tareas, f


def tareas_cerradas(request):
    hoy = timezone.localdate()
    tareas, f = filtrar_tareas(request, hoy)

    # Totales de todo lo filtrado (todas las páginas), calculados en la base de datos
    totales = tareas.aggregate(
        tareas=Count("pk"),
        minutos=Coalesce(Sum("minutos"), 0),
        pedidos=Count("pedido", distinct=True),
        al_archivar=Count("pk", filter=Q(cerrada_al_archivar=True)),
    )
    totales["horas"] = round(totales["minutos"] / 60, 1)
    totales["operador"] = totales["tareas"] - totales["al_archivar"]

    agrupar_titulo = ""
    filas = tareas
    if f["agrupar"] in AGRUPAR:
        campo, agrupar_titulo = AGRUPAR[f["agrupar"]]
        filas = (
            tareas.values(grupo=F(campo))
            .annotate(n=Count("pk"), cantidad=Sum("cantidad"), minutos=Sum("minutos"))
            .order_by("-grupo" if f["agrupar"] == "dia" else "grupo")
        )
    pagina, paginas = _pagina(request, filas)

    opciones_agrupar = [("", "ninguno"), ("persona", "persona"), ("operacion", "operación"),
                        ("pedido", "pedido"), ("dia", "día")]
    return render(request, "archivo/tareas.html", {
        **f,
        "pagina": pagina,
        "paginas": paginas,
        "totales": totales,
        "agrupar_titulo": agrupar_titulo,
        "agrupaciones": [
            {"nombre": nombre, "activo": clave == f["agrupar"], "url": con_parametros(request, agrupar=clave)}
            for clave, nombre in opciones_agrupar
        ],
        "tarjetas": [
            {"titulo": "Tareas cerradas", "valor": totales["tareas"], "tono": "blue", "icono": "bi-check2-square",
             "texto": _texto_rango(f["desde"], f["hasta"]), "activo": True},
            {"titulo": "Min estándar", "valor": totales["minutos"], "tono": "blue", "icono": "bi-stopwatch",
             "texto": f"{totales['horas']} h"},
            {"titulo": "Pedidos", "valor": totales["pedidos"], "tono": "gray", "icono": "bi-box-seam",
             "texto": "con tareas en el periodo"},
            {"titulo": "Cerradas al archivar", "valor": totales["al_archivar"], "tono": "amber", "icono": "bi-archive",
             "texto": "sin ✓ del operador"},
        ],
        "rangos": botones_rango(request, hoy, f["rango"]),
        "operarios": Operario.objects.order_by("-activo", "nombre"),
        "madres": OperacionMadre.objects.order_by("-activa", "nombre"),
        "maquinas": Maquina.objects.order_by("-activa", "nombre"),
        "modelos": modelos_catalogo(),
        "consulta": con_parametros(request),
    })


def exportar_tareas(request):
    """Tareas cerradas con sus columnas tal como se ven, de todo lo filtrado."""
    tareas, f = filtrar_tareas(request, timezone.localdate())
    filas = [
        [t.fecha_cierre, t.quien.nombre, t.pedido.numero if t.pedido else "", t.paso, t.producto_cerrado,
         t.operacion_madre.nombre, t.operacion_detallada.nombre, t.maquina.nombre if t.maquina else "",
         t.cantidad, t.minutos, "✓ al archivar" if t.cerrada_al_archivar else "✓ operador"]
        for t in tareas.iterator(chunk_size=1000)
    ]
    return respuesta_excel(
        nombre="archivo_tareas",
        titulo="Tareas cerradas",
        subtitulo=f"cerradas: {_texto_rango(f['desde'], f['hasta'])} · {len(filas)} tarea(s)",
        encabezados=["Fecha", "Quién", "# P", "Paso", "Producto", "Operación madre", "Operación detallada",
                     "Máquina", "Cant", "Min est", "Cerrada"],
        filas=filas,
        anchos=[12, 16, 10, 7, 32, 28, 34, 22, 8, 9, 15],
        columnas_fecha=(0,),
    )
