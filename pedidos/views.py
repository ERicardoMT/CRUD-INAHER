from datetime import date

from django.contrib import messages
from django.db import transaction
from django.db.models import F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from urllib.parse import quote

from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
)
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .catalogo import modelos_catalogo
from .forms import EntregaForm, PartidaFormSet, PedidoForm, mensaje_numero_ocupado
from .models import Cliente, Entrega, EntregaPartida, MovimientoPedido, Pedido, porcentaje


# Tarjetas de arriba del listado: al hacer clic filtran la tabla.
TARJETAS = [
    {"clave": "activos", "titulo": "Activos", "emoji": "📋", "icono": "bi-clipboard-check",
     "tono": "blue", "texto": "Sin entregar"},
    {"clave": "atrasados", "titulo": "Atrasados", "emoji": "🔴", "icono": "bi-exclamation-circle",
     "tono": "red", "texto": "Fecha vencida"},
    {"clave": "sale_hoy", "titulo": "Salen hoy", "emoji": "🟠", "icono": "bi-calendar-event",
     "tono": "amber", "texto": "Compromiso del día"},
    {"clave": "detenidos", "titulo": "Detenidos", "emoji": "⛔", "icono": "bi-pause-circle",
     "tono": "gray", "texto": "Requieren atención"},
]

# Selector "Mostrar" del listado
MOSTRAR = {
    "activos": "Activos",
    "terminados": "Terminados",
    "entregados": "Entregados",
    "todos": "Todos",
    "historico": "Histórico (archivados)",
}

# "⋮ Opciones" → Ordenar por
ORDENES = {
    "fecha_salida": "fecha de salida",
    "fecha_captura": "fecha de captura",
    "estado": "estado",
    "estatus": "estatus",
}

# Orden de urgencia para "Ordenar por estado"
RANGO_ESTADO = {"ATRASADO": 0, "SALE HOY": 1, "URGENTE": 2, "EN TIEMPO": 3, "SIN FECHA": 4, "LISTO": 5, "ENTREGADO": 6}
RANGO_ESTATUS = {valor: i for i, valor in enumerate(Pedido.Estado.values)}

FILTROS = {**{t["clave"]: t["titulo"] for t in TARJETAS}, **MOSTRAR}


def _fecha_orden(fecha):
    return fecha or date.max


def listado_pedidos(request):
    """
    Lo que se ve en pantalla (filtro + orden). Lo comparten el listado,
    la impresión y la exportación a Excel para que siempre coincidan.
    """
    filtro = request.GET.get("ver", "activos")
    filtro = filtro if filtro in FILTROS else "activos"
    orden = request.GET.get("orden", "fecha_salida")
    orden = orden if orden in ORDENES else "fecha_salida"

    pedidos = list(
        Pedido.objects.por_filtro(filtro)
        .con_minutos()
        .select_related("cliente")
        .prefetch_related("partidas", "entregas")
    )
    for p in pedidos:
        p.avance_por_partida = p.avance_partidas() if len(p.partidas.all()) > 1 else []

    if orden == "fecha_captura":
        pedidos.sort(key=lambda p: (p.fecha_captura, p.pk), reverse=True)
    elif orden == "estado":
        pedidos.sort(key=lambda p: (RANGO_ESTADO.get(p.alerta_estado["texto"], 9), _fecha_orden(p.fecha_salida), p.numero))
    elif orden == "estatus":
        pedidos.sort(key=lambda p: (RANGO_ESTATUS.get(p.estado, 9), _fecha_orden(p.fecha_salida), p.numero))
    else:
        pedidos.sort(key=lambda p: (_fecha_orden(p.fecha_salida), p.numero))

    return pedidos, filtro, orden


def quien_hace(request):
    """Nombre para la bitácora: el usuario con sesión o el que escribieron en el formulario."""
    if request.user.is_authenticated:
        return request.user.get_full_name() or request.user.get_username()
    return request.POST.get("quien", "").strip()[:150]


def volver(request, por_defecto="pedidos:lista"):
    siguiente = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}):
        return redirect(siguiente)
    return redirect(por_defecto)


def minutos_a_horas(minutos):
    return round(minutos / 60, 1)


class PedidoListView(ListView):
    model = Pedido
    template_name = "pedidos/pedido_list.html"
    context_object_name = "pedidos"

    def get_queryset(self):
        self.pedidos, self.filtro, self.orden = listado_pedidos(self.request)
        return self.pedidos

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pedidos = self.pedidos
        filtro = self.filtro

        min_total = sum(p.min_total for p in pedidos)
        min_restante = sum(p.min_restante for p in pedidos)

        consulta = self.request.GET.copy()
        consulta.pop("orden", None)

        context.update({
            "pedidos": pedidos,
            "filtro": filtro,
            "filtro_nombre": FILTROS[filtro],
            "es_historico": filtro == "historico",
            "orden": self.orden,
            "orden_nombre": ORDENES[self.orden],
            "ordenes": ORDENES,
            "consulta_sin_orden": consulta.urlencode(),
            "consulta": self.request.GET.urlencode(),
            "mostrar": MOSTRAR,
            "estados": Pedido.Estado.choices,
            "tarjetas": [
                {**t, "valor": Pedido.objects.por_filtro(t["clave"]).count()}
                for t in TARJETAS
            ],
            "avance": {
                "min_total": min_total,
                "min_hechos": min_total - min_restante,
                "min_restante": min_restante,
                "horas_total": minutos_a_horas(min_total),
                "horas_restante": minutos_a_horas(min_restante),
                "pct": porcentaje(min_total - min_restante, min_total),
                "sin_ruta": [p.numero for p in pedidos if not p.min_total],
            },
        })
        return context


def imprimir_listado(request):
    pedidos, filtro, orden = listado_pedidos(request)
    return render(request, "pedidos/imprimir_listado.html", {
        "pedidos": pedidos,
        "filtro_nombre": FILTROS[filtro],
        "orden_nombre": ORDENES[orden],
        "titulo": "Histórico de pedidos" if filtro == "historico" else f"Pedidos {FILTROS[filtro].lower()}",
        "ahora": timezone.localtime(),
    })


def imprimir_ficha(request, pk):
    pedido = get_object_or_404(
        Pedido.objects.con_minutos().select_related("cliente").prefetch_related("partidas", "entregas"), pk=pk
    )
    return render(request, "pedidos/imprimir_ficha.html", {
        "pedido": pedido,
        "ahora": timezone.localtime(),
    })


def exportar_excel(request):
    """Exporta lo que se ve en pantalla (mismo filtro y orden)."""
    pedidos, filtro, orden = listado_pedidos(request)
    ahora = timezone.localtime()

    wb = Workbook()
    ws = wb.active
    ws.title = "Pedidos"
    negrita = Font(bold=True)

    ws.append([f"INAHER · Pedidos · {FILTROS[filtro]}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Exportado: {ahora:%d/%m/%Y %H:%M} · orden: {ORDENES[orden]} · {len(pedidos)} pedido(s)"])
    ws.append(["Días y Estado calculados con la fecha de exportación"])
    ws.append([])

    encabezados = [
        "# Pedido", "Cliente", "Cant", "Descripción", "Fecha captura", "Fecha salida",
        "Días", "Estado", "Estatus", "Entregado", "Detenido por", "Min total", "Min restante", "% avance", "Notas",
    ]
    ws.append(encabezados)
    fila_encabezado = ws.max_row
    relleno = PatternFill("solid", fgColor="E8EEF6")
    for celda in ws[fila_encabezado]:
        celda.font = negrita
        celda.fill = relleno

    for p in pedidos:
        partidas = list(p.partidas.all())
        estatus = p.get_estado_display()
        if p.archivado:
            estatus += " · archivado" + (" sin terminar" if p.archivado_sin_terminar else "")
        ws.append([
            p.numero,
            str(p.cliente or ""),
            p.cantidad,
            "\n".join(f"{x.cantidad} {x.descripcion}" for x in partidas) or p.descripcion,
            p.fecha_captura,
            p.fecha_salida,
            p.dias_restantes,
            p.alerta_estado["texto"],
            estatus,
            f"{p.cantidad_entregada} de {p.cantidad}" if p.cantidad_entregada else "",
            p.detenido_por if p.detenido else "",
            p.min_total,
            p.min_restante,
            p.pct_avance / 100,
        ] + [p.notas])

    for fila in ws.iter_rows(min_row=fila_encabezado + 1):
        fila[3].alignment = Alignment(wrap_text=True, vertical="top")
        fila[4].number_format = fila[5].number_format = "DD/MM/YYYY"
        fila[13].number_format = "0%"

    anchos = [11, 22, 7, 42, 13, 13, 7, 12, 22, 12, 28, 10, 12, 10, 40]
    for i, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = ancho
    ws.freeze_panes = ws.cell(row=fila_encabezado + 1, column=1)
    ws.auto_filter.ref = f"A{fila_encabezado}:{get_column_letter(len(encabezados))}{ws.max_row}"

    respuesta = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    respuesta["Content-Disposition"] = f'attachment; filename="pedidos_{filtro}_{ahora:%Y%m%d_%H%M}.xlsx"'
    wb.save(respuesta)
    return respuesta


class PedidoDetailView(DetailView):
    model = Pedido
    template_name = "pedidos/pedido_detail.html"
    context_object_name = "pedido"

    def get_queryset(self):
        return (
            Pedido.objects.con_minutos()
            .select_related("cliente")
            .prefetch_related("partidas__entregas", "entregas")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pedido = self.object

        context["avance_partidas"] = pedido.avance_partidas()
        context["estados"] = Pedido.Estado.choices

        # Consulta de tareas vigentes. No se modifican desde esta ficha.
        context["tareas_designacion"] = (
            pedido.items_designacion
            .filter(
                Q(hecho=True) |
                Q(designacion__cerrada=False)
            )
            .select_related(
                "designacion",
                "partida",
                "quien",
                "operacion_madre",
                "operacion_detallada",
                "maquina",
            )
            .order_by(
                "designacion__fecha",
                "paso",
                "orden",
                "id",
            )
        )

        # Movimientos disponibles en la bitácora actual.
        context["movimientos"] = (
            MovimientoPedido.objects
            .filter(pedido_numero=pedido.numero)
            .order_by("-fecha", "-id")[:8]
        )

        return context

class PedidoFormMixin:
    """Formulario del pedido + sus partidas (lo comparten Registrar y Editar)."""
    model = Pedido
    form_class = PedidoForm
    template_name = "pedidos/pedido_form.html"
    success_url = reverse_lazy("pedidos:lista")

    def get_partidas(self):
        datos = self.request.POST if self.request.method == "POST" else None
        return PartidaFormSet(datos, instance=self.object, prefix="partidas")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        partidas = kwargs.get("partidas") or self.get_partidas()
        form = context["form"]

        errores = 0
        if form.is_bound:
            errores = (
                len(form.errors)
                + sum(1 for e in partidas.errors if e)
                + (1 if partidas.non_form_errors() else 0)
            )

        context.update({
            "partidas": partidas,
            "errores": errores,
            "clientes": Cliente.objects.values_list("nombre", flat=True),
            "modelos": modelos_catalogo(),
        })
        return context

    def form_valid(self, form):
        partidas = self.get_partidas()
        if not partidas.is_valid():
            return self.render_to_response(self.get_context_data(form=form, partidas=partidas))

        with transaction.atomic():
            self.object = form.save()
            partidas.instance = self.object
            partidas.save()
            self.object.actualizar_resumen()
            if "estado" in form.changed_data:
                self.object.establecer_estado(self.object.estado)
            self.object.sincronizar_detenido()

        messages.success(self.request, f"Pedido {self.object.numero} guardado.")
        return redirect(self.get_success_url())


class PedidoCreateView(PedidoFormMixin, CreateView):
    extra_context = {
        "titulo": "Registrar pedido",
        "subtitulo": "Ingresa la información del pedido.",
        "texto_boton": "Guardar pedido",
    }


class PedidoUpdateView(PedidoFormMixin, UpdateView):
    extra_context = {
        "titulo": "Editar pedido",
        "subtitulo": "Actualiza los datos del pedido.",
        "texto_boton": "Guardar cambios",
    }


def _ids_seleccionados(request):
    return [i for i in request.POST.getlist("pedido_ids") if str(i).isdigit()]


def eliminar_pedidos(request, pk=None):
    """
    Eliminar = borrar por completo (no queda en Histórico).
    Regla: solo si no tiene ninguna ✓ en la designación; si ya tiene avance se ofrece Archivar.
    Pide confirmar y deja en la bitácora quién lo eliminó.
    """
    ids = [pk] if pk else _ids_seleccionados(request)
    pedidos = list(Pedido.objects.filter(pk__in=ids).select_related("cliente").prefetch_related("partidas"))
    if not pedidos:
        messages.warning(request, "No seleccionaste ningún pedido.")
        return volver(request)

    con_avance = [p for p in pedidos if p.tiene_avance()]
    eliminables = [p for p in pedidos if p not in con_avance]

    if request.method == "POST" and request.POST.get("confirmar") == "1":
        quien = quien_hace(request)
        if not quien:
            messages.error(request, "Escribe quién elimina el pedido (queda en la bitácora).")
        elif eliminables:
            with transaction.atomic():
                for p in eliminables:
                    MovimientoPedido.objects.create(
                        accion=MovimientoPedido.Accion.ELIMINADO,
                        pedido_numero=p.numero,
                        detalle=f"{p.cliente or 'Sin cliente'} · {p.descripcion}"[:255],
                        usuario=quien,
                    )
                    # Sus tareas no tienen ✓ (regla), así que salen también de la designación
                    p.items_designacion.all().delete()
                    p.delete()
            numeros = ", ".join(p.numero for p in eliminables)
            messages.success(request, f"Se eliminó {len(eliminables)} pedido(s): {numeros}.")
            if con_avance:
                messages.warning(
                    request,
                    "No se eliminaron por tener avance: " + ", ".join(p.numero for p in con_avance) + ". Archívalos en su lugar.",
                )
            return redirect("pedidos:lista")

    return render(request, "pedidos/pedido_confirm_delete.html", {
        "eliminables": eliminables,
        "con_avance": con_avance,
        "total": len(pedidos),
        "next": request.POST.get("next") or request.GET.get("next") or "",
        "quien_sesion": quien_hace(request) if request.user.is_authenticated else "",
    })


@require_POST
def archivar_pedidos(request):
    """
    Archivar = mandar al Histórico (sale de Activos y de la carga de planta).
    Normal: TERMINADO o ENTREGADO. Si tiene tareas sin ✓ (o no está terminado)
    pide confirmar y se marca "archivado sin terminar".
    """
    pedidos = list(Pedido.objects.filter(pk__in=_ids_seleccionados(request), archivado=False))
    if not pedidos:
        messages.warning(request, "No seleccionaste ningún pedido para archivar.")
        return volver(request)

    sin_terminar = [p for p in pedidos if p.archivar_es_sin_terminar()]
    quien = quien_hace(request)

    if sin_terminar and (request.POST.get("confirmar") != "1" or not quien):
        if request.POST.get("confirmar") == "1":
            messages.error(request, "Escribe quién archiva (queda en la bitácora).")
        for p in sin_terminar:
            p.pendientes = p.tareas_sin_palomear()
        return render(request, "pedidos/pedido_confirm_archivar.html", {
            "pedidos": pedidos,
            "sin_terminar": sin_terminar,
            "normales": len(pedidos) - len(sin_terminar),
            "next": request.POST.get("next", ""),
        })

    ahora = timezone.now()
    with transaction.atomic():
        for p in pedidos:
            es_sin_terminar = p in sin_terminar
            p.archivado = True
            p.archivado_en = ahora
            p.archivado_sin_terminar = es_sin_terminar
            p.save(update_fields=["archivado", "archivado_en", "archivado_sin_terminar", "fecha_actualizacion"])
            MovimientoPedido.objects.create(
                accion=(MovimientoPedido.Accion.ARCHIVADO_SIN_TERMINAR if es_sin_terminar
                        else MovimientoPedido.Accion.ARCHIVADO),
                pedido_numero=p.numero,
                detalle=f"Estatus: {p.get_estado_display()}",
                usuario=quien or "Sin nombre",
            )

    messages.success(
        request,
        f"Se mandó {len(pedidos)} pedido(s) al Histórico: {', '.join(p.numero for p in pedidos)}.",
    )
    return volver(request)


@require_POST
def desarchivar_pedidos(request):
    pedidos = list(Pedido.objects.filter(pk__in=_ids_seleccionados(request), archivado=True))
    if not pedidos:
        messages.warning(request, "No seleccionaste ningún pedido del Histórico.")
        return volver(request)

    with transaction.atomic():
        for p in pedidos:
            p.archivado = False
            p.archivado_en = None
            p.archivado_sin_terminar = False
            p.save(update_fields=["archivado", "archivado_en", "archivado_sin_terminar", "fecha_actualizacion"])
            MovimientoPedido.objects.create(
                accion=MovimientoPedido.Accion.DESARCHIVADO,
                pedido_numero=p.numero,
                usuario=quien_hace(request) or "Sin nombre",
            )

    messages.success(request, f"Regresó a pedidos: {', '.join(p.numero for p in pedidos)}.")
    return volver(request)


def bitacora(request):
    return render(request, "pedidos/bitacora.html", {
        "movimientos": MovimientoPedido.objects.all()[:300],
    })


@require_POST
def cambiar_estado(request, pk):
    """
    Cambia el estatus a mano desde la lista (el sistema lo respeta).
    ENTREGADO es la excepción: se registra con fecha y cantidad.
    """
    pedido = get_object_or_404(Pedido, pk=pk)
    nuevo = request.POST.get("estado", "")

    if nuevo == Pedido.Estado.ENTREGADO and pedido.estado != nuevo:
        url = reverse("pedidos:registrar_entrega", args=[pedido.pk])
        siguiente = request.POST.get("next", "")
        return redirect(f"{url}?next={quote(siguiente)}" if siguiente else url)

    if nuevo not in Pedido.Estado.values:
        messages.error(request, "Estatus no válido.")
    elif nuevo != pedido.estado:
        anterior = pedido.get_estado_display()
        pedido.establecer_estado(nuevo)
        messages.success(request, f"Pedido {pedido.numero}: {anterior} → {pedido.get_estado_display()}.")

    return volver(request)


def registrar_entrega(request, pk):
    """ENTREGADO: solo a mano, con fecha y cantidad. Admite entregas parciales."""
    pedido = get_object_or_404(
        Pedido.objects.prefetch_related("entregas__partidas__partida", "partidas__entregas"), pk=pk
    )
    siguiente = request.POST.get("next") or request.GET.get("next") or ""

    if request.method == "POST":
        form = EntregaForm(request.POST, request.FILES, pedido=pedido)
        if form.is_valid():
            with transaction.atomic():
                entrega = form.save(commit=False)
                entrega.pedido = pedido
                entrega.registrada_por = quien_hace(request)
                entrega.save()
                EntregaPartida.objects.bulk_create(
                    EntregaPartida(entrega=entrega, partida=p, cantidad=c)
                    for p, c in form.cantidades.items() if c
                )

                pedido.actualizar_por_entregas()

            pedido = Pedido.objects.prefetch_related("entregas").get(pk=pedido.pk)
            if pedido.estado == Pedido.Estado.ENTREGADO:
                messages.success(request, f"Pedido {pedido.numero} entregado completo ({pedido.cantidad} pzas). Sale de Activos.")
            else:
                messages.success(
                    request,
                    f"Entrega parcial del pedido {pedido.numero}: entregado {pedido.cantidad_entregada} de {pedido.cantidad}.",
                )
            return volver(request, por_defecto=reverse("pedidos:detalle", args=[pedido.pk]))
    else:
        form = EntregaForm(pedido=pedido)

    return render(request, "pedidos/registrar_entrega.html", {
        "pedido": pedido,
        "form": form,
        "next": siguiente,
    })


@require_POST
def eliminar_entrega(request, pk):
    """Corrige una entrega capturada por error."""
    entrega = get_object_or_404(Entrega.objects.select_related("pedido"), pk=pk)
    pedido = entrega.pedido
    with transaction.atomic():
        entrega.acuse.delete(save=False)
        entrega.delete()
        pedido.actualizar_por_entregas()
    messages.info(request, f"Se quitó la entrega de {entrega.cantidad} pzas del pedido {pedido.numero}.")
    return redirect("pedidos:registrar_entrega", pk=pedido.pk)


@require_GET
def numero_disponible(request):
    """Verificación en vivo del # de pedido en el formulario."""
    pedidos = Pedido.objects.numero(request.GET.get("numero")).select_related("cliente")
    excluir = request.GET.get("excluir", "")
    if excluir.isdigit():
        pedidos = pedidos.exclude(pk=excluir)
    existente = pedidos.first()
    if existente:
        return JsonResponse({"disponible": False, "mensaje": mensaje_numero_ocupado(existente)})
    return JsonResponse({"disponible": True})
