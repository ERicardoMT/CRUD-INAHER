from django.contrib import messages
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)

from .catalogo import modelos_catalogo
from .forms import PartidaFormSet, PedidoForm, mensaje_numero_ocupado
from .models import Cliente, Pedido, porcentaje


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
}

FILTROS = {**{t["clave"]: t["titulo"] for t in TARJETAS}, **MOSTRAR}


def minutos_a_horas(minutos):
    return round(minutos / 60, 1)


class PedidoListView(ListView):
    model = Pedido
    template_name = "pedidos/pedido_list.html"
    context_object_name = "pedidos"

    def get_filtro(self):
        ver = self.request.GET.get("ver", "activos")
        return ver if ver in FILTROS else "activos"

    def get_queryset(self):
        return (
            Pedido.objects.por_filtro(self.get_filtro())
            .con_minutos()
            .select_related("cliente")
            .prefetch_related("partidas")
            .order_by(F("fecha_salida").asc(nulls_last=True), "numero")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pedidos = list(context["pedidos"])
        filtro = self.get_filtro()

        min_total = sum(p.min_total for p in pedidos)
        min_restante = sum(p.min_restante for p in pedidos)

        context.update({
            "pedidos": pedidos,
            "filtro": filtro,
            "filtro_nombre": FILTROS[filtro],
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


class PedidoDetailView(DetailView):
    model = Pedido
    template_name = "pedidos/pedido_detail.html"
    context_object_name = "pedido"

    def get_queryset(self):
        return Pedido.objects.select_related("cliente").prefetch_related("partidas")


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


class PedidoDeleteView(DeleteView):
    model = Pedido
    template_name = "pedidos/pedido_confirm_delete.html"
    context_object_name = "pedido"
    success_url = reverse_lazy("pedidos:lista")


@require_POST
def cambiar_estado(request, pk):
    """Cambia el estatus desde la lista del renglón (cualquier estatus se puede poner a mano)."""
    pedido = get_object_or_404(Pedido, pk=pk)
    nuevo = request.POST.get("estado", "")

    if nuevo not in Pedido.Estado.values:
        messages.error(request, "Estatus no válido.")
    elif nuevo != pedido.estado:
        anterior = pedido.get_estado_display()
        pedido.estado = nuevo
        pedido.save(update_fields=["estado", "fecha_actualizacion"])
        messages.success(request, f"Pedido {pedido.numero}: {anterior} → {pedido.get_estado_display()}.")

    siguiente = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}):
        return redirect(siguiente)
    return redirect("pedidos:lista")


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


@require_POST
def vaciar_pedidos_seleccionados(request):
    """Elimina en bloque los pedidos seleccionados."""
    pedido_ids = request.POST.getlist("pedido_ids")
    if pedido_ids:
        eliminados = Pedido.objects.filter(id__in=pedido_ids).count()
        Pedido.objects.filter(id__in=pedido_ids).delete()
        messages.success(request, f"Se eliminaron {eliminados} pedido(s) seleccionado(s).")
    else:
        messages.warning(request, "No seleccionaste ningún pedido.")
    return redirect("pedidos:lista")
