from django.urls import reverse_lazy
from datetime import timedelta

from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)

from .models import Pedido
from .forms import PedidoForm
from django.utils import timezone

from designaciones.models import ItemDesignacion

# Al archivar un día, las tareas pendientes se copian a la jornada siguiente y la
# original queda sin ✓ en la jornada cerrada. Para no contarlas doble, solo son
# "vigentes" las tareas hechas o las que están en jornadas abiertas.
Q_ITEM_VIGENTE = Q(hecho=True) | Q(designacion__cerrada=False)
Q_ITEM_VIGENTE_REL = Q(items_designacion__hecho=True) | Q(items_designacion__designacion__cerrada=False)

JORNADA_MINUTOS = 480  # 8 h por día para estimar la terminación


TABS_PEDIDOS = {
    "abiertos": "Abiertos",
    "detenidos": "Detenidos",
    "terminados": "Terminados",
    "entregados": "Entregados",
}


class PedidoListView(ListView):
    model = Pedido
    template_name = "pedidos/pedido_list.html"
    context_object_name = "pedidos"

    def get_tab(self):
        tab = self.request.GET.get("tab", "abiertos")
        return tab if tab in TABS_PEDIDOS else "abiertos"

    @staticmethod
    def filtrar_tab(qs, tab):
        if tab == "detenidos":
            return qs.filter(estado=Pedido.Estado.DETENIDO)
        if tab == "terminados":
            return qs.filter(estado=Pedido.Estado.TERMINADO)
        if tab == "entregados":
            return qs.filter(estado=Pedido.Estado.ENTREGADO)
        return qs.exclude(estado__in=Pedido.ESTADOS_CERRADOS)

    def get_queryset(self):
        qs = self.filtrar_tab(super().get_queryset(), self.get_tab())

        estatus = self.request.GET.get("estatus", "")
        if estatus in (Pedido.Estado.EN_PROCESO, Pedido.Estado.DETENIDO):
            qs = qs.filter(estado=estatus)

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(numero__icontains=q.lstrip("#"))
                | Q(descripcion__icontains=q)
                | Q(notas__icontains=q)
                | Q(detenido_por__icontains=q)
            )

        # Minutos de la ruta cargada en designación (total y sin ✓)
        return qs.annotate(
            min_total=Coalesce(Sum("items_designacion__minutos", filter=Q_ITEM_VIGENTE_REL), 0),
            min_restante=Coalesce(
                Sum(
                    "items_designacion__minutos",
                    filter=Q(items_designacion__hecho=False, items_designacion__designacion__cerrada=False),
                ),
                0,
            ),
        ).order_by(F("fecha_salida").asc(nulls_last=True), "numero")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hoy = timezone.localdate()

        pedidos = list(context["pedidos"])
        for p in pedidos:
            p.avance = (
                round((p.min_total - p.min_restante) * 100 / p.min_total) if p.min_total else None
            )
        context["pedidos"] = pedidos

        todos = Pedido.objects.all()
        context["tabs"] = [
            {"key": key, "label": label, "count": self.filtrar_tab(todos, key).count()}
            for key, label in TABS_PEDIDOS.items()
        ]
        context["tab"] = self.get_tab()
        context["estatus"] = self.request.GET.get("estatus", "")
        context["estatus_opciones"] = [
            ("", "todos"),
            (Pedido.Estado.EN_PROCESO, "en proceso"),
            (Pedido.Estado.DETENIDO, "detenido"),
        ]
        context["q"] = self.request.GET.get("q", "").strip()

        abiertos = Pedido.objects.exclude(estado__in=Pedido.ESTADOS_CERRADOS)
        atrasados = abiertos.filter(fecha_salida__lt=hoy).order_by("fecha_salida")
        detenidos = abiertos.filter(estado=Pedido.Estado.DETENIDO)

        # Horas de trabajo a partir de las tareas de designación ligadas a pedidos abiertos
        items = ItemDesignacion.objects.filter(Q_ITEM_VIGENTE, pedido__in=abiertos)
        min_totales = items.aggregate(t=Sum("minutos"))["t"] or 0
        min_restantes = items.filter(hecho=False).aggregate(t=Sum("minutos"))["t"] or 0
        min_detenidos = (
            items.filter(hecho=False, pedido__estado=Pedido.Estado.DETENIDO)
            .aggregate(t=Sum("minutos"))["t"] or 0
        )
        avance = round((min_totales - min_restantes) * 100 / min_totales) if min_totales else 0

        context["kpis"] = {
            "abiertos": abiertos.count(),
            "piezas": abiertos.aggregate(t=Sum("cantidad"))["t"] or 0,
            "atrasados": atrasados.count(),
            "atrasados_numeros": list(atrasados.values_list("numero", flat=True)[:3]),
            "atrasados_extra": max(atrasados.count() - 3, 0),
            "sale_hoy": abiertos.filter(fecha_salida=hoy).count(),
            "sale_2_dias": abiertos.filter(
                fecha_salida__gt=hoy, fecha_salida__lte=hoy + timedelta(days=2)
            ).count(),
            "horas_restantes": round(min_restantes / 60, 1),
            "horas_totales": round(min_totales / 60, 1),
            "avance": avance,
            "detenidos": detenidos.count(),
            "horas_detenidas": round(min_detenidos / 60, 1),
        }
        return context

def sumar_dias_habiles(desde, dias):
    """Suma días de trabajo saltando domingos (igual que 'nuevo día' en designación)."""
    fecha = desde
    while dias > 0:
        fecha += timedelta(days=1)
        if fecha.weekday() != 6:
            dias -= 1
    return fecha


class PedidoDetailView(DetailView):
    model = Pedido
    template_name = "pedidos/pedido_detail.html"
    context_object_name = "pedido"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pedido = self.object
        hoy = timezone.localdate()
        detenido = pedido.estado == Pedido.Estado.DETENIDO

        items = list(
            pedido.items_designacion.filter(Q_ITEM_VIGENTE)
            .select_related("designacion", "quien", "operacion_madre", "operacion_detallada", "maquina")
            .order_by("paso", "designacion__fecha", "orden", "id")
        )

        # ----- Ruta: un renglón por paso -----
        pasos = {}
        for it in items:
            paso = pasos.setdefault(it.paso, {
                "numero": it.paso,
                "madre": it.operacion_madre.nombre,
                "detallada": it.operacion_detallada.nombre,
                "maquina": it.maquina.nombre if it.maquina else "—",
                "detalle": it.detalle,
                "registros": [],
                "minutos": 0,
                "min_hechos": 0,
                "pzas_hechas": 0,
                "pendiente_hoy": False,
            })
            paso["registros"].append(it)
            paso["minutos"] += it.minutos
            if it.hecho:
                paso["min_hechos"] += it.minutos
                paso["pzas_hechas"] += it.cantidad
            elif it.designacion.fecha == hoy:
                paso["pendiente_hoy"] = True

        ruta = list(pasos.values())
        for paso in ruta:
            if paso["min_hechos"] == paso["minutos"]:
                paso["estado"], paso["clase"] = "Lista", "lista"
            elif detenido:
                paso["estado"], paso["clase"] = "Detenido", "detenido"
            elif paso["pendiente_hoy"]:
                paso["estado"], paso["clase"] = "En curso", "curso"
            else:
                paso["estado"], paso["clase"] = "Pendiente", "pendiente"

        # ----- Indicadores -----
        min_total = sum(i.minutos for i in items)
        min_hecho = sum(i.minutos for i in items if i.hecho)
        min_pend = min_total - min_hecho
        pend_hoy = [i for i in items if not i.hecho and i.designacion.fecha == hoy]
        min_hoy = 0 if detenido else sum(i.minutos for i in pend_hoy)
        pasos_listos = sum(1 for p in ruta if p["clase"] == "lista")

        terminacion = None
        if not detenido and min_pend:
            dias = -(-min_pend // JORNADA_MINUTOS)  # redondeo hacia arriba
            terminacion = sumar_dias_habiles(hoy, dias - 1) if dias > 1 else hoy
        elif not detenido and min_total and not min_pend:
            terminacion = hoy

        dif_dias = None
        if terminacion and pedido.fecha_salida:
            dif_dias = (terminacion - pedido.fecha_salida).days

        context.update({
            "hoy": hoy,
            "ruta": ruta,
            "registros": items,
            "jornada_horas": JORNADA_MINUTOS // 60,
            "kpi": {
                "min_total": min_total,
                "horas_total": round(min_total / 60, 1),
                "pasos": len(ruta),
                "min_hecho": min_hecho,
                "pct_hecho": round(min_hecho * 100 / min_total) if min_total else 0,
                "pasos_listos": pasos_listos,
                "min_hoy": min_hoy,
                "tareas_hoy": 0 if detenido else len(pend_hoy),
                "min_pend": min_pend,
                "pasos_pend": len(ruta) - pasos_listos,
                "terminacion": terminacion,
                "dif_dias": dif_dias,
                "dif_dias_abs": abs(dif_dias) if dif_dias is not None else None,
            },
        })
        return context


# Cambios de estatus permitidos desde los botones rápidos del detalle
TRANSICIONES = {
    Pedido.Estado.EN_PROCESO: [Pedido.Estado.DETENIDO, Pedido.Estado.TERMINADO, Pedido.Estado.ENTREGADO],
    Pedido.Estado.DETENIDO: [Pedido.Estado.EN_PROCESO, Pedido.Estado.TERMINADO, Pedido.Estado.ENTREGADO],
    Pedido.Estado.TERMINADO: [Pedido.Estado.EN_PROCESO, Pedido.Estado.ENTREGADO],
    Pedido.Estado.ENTREGADO: [Pedido.Estado.EN_PROCESO],
}


@require_POST
def cambiar_estado(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    nuevo = request.POST.get("estado", "")

    if nuevo not in TRANSICIONES.get(pedido.estado, []):
        messages.error(request, "Ese cambio de estatus no está permitido.")
        return redirect("pedidos:detalle", pk=pedido.pk)

    if nuevo == Pedido.Estado.DETENIDO:
        motivo = request.POST.get("detenido_por", "").strip()
        if not motivo:
            messages.error(request, "Escribe el motivo por el que se detiene el pedido.")
            return redirect("pedidos:detalle", pk=pedido.pk)
        pedido.detenido_por = motivo[:150]
    else:
        # Al salir de "Detenido" el motivo ya no aplica
        pedido.detenido_por = ""

    anterior = pedido.get_estado_display()
    pedido.estado = nuevo
    pedido.save(update_fields=["estado", "detenido_por", "fecha_actualizacion"])
    messages.success(
        request,
        f"Pedido {pedido.numero}: {anterior} → {pedido.get_estado_display()}.",
    )
    return redirect("pedidos:detalle", pk=pedido.pk)


class PedidoCreateView(CreateView):
    model = Pedido
    form_class = PedidoForm
    template_name = "pedidos/pedido_form.html"
    success_url = reverse_lazy("pedidos:lista")

    extra_context = {
        "titulo": "Registrar pedido",
        "subtitulo": "Ingresa la información del pedido.",
        "texto_boton": "Guardar pedido",
    }


class PedidoUpdateView(UpdateView):
    model = Pedido
    form_class = PedidoForm
    template_name = "pedidos/pedido_form.html"
    success_url = reverse_lazy("pedidos:lista")

    extra_context = {
        "titulo": "Editar pedido",
        "subtitulo": "Actualiza los datos del pedido.",
        "texto_boton": "Guardar cambios",
    }


class PedidoDeleteView(DeleteView):
    model = Pedido
    template_name = "pedidos/pedido_confirm_delete.html"
    context_object_name = "pedido"
    success_url = reverse_lazy("pedidos:lista")

@require_POST
def vaciar_pedidos_seleccionados(request):
    """Elimina en bloque los pedidos seleccionados."""
    pedido_ids = request.POST.getlist("pedido_ids")
    if pedido_ids:
        eliminados, _ = Pedido.objects.filter(id__in=pedido_ids).delete()
        messages.success(request, f"Se vaciaron {eliminados} pedido(s) seleccionado(s).")
    else:
        messages.warning(request, "No seleccionaste ningún pedido para vaciar.")
    return redirect("pedidos:lista")    